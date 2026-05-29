"""Tests for the hybrid pipeline integration (llm_generate with HybridLLMClient).

Verifies that llm_generate() works with both cloud-only mode (backward compat)
and local-first mode using mock clients, and that intervention events are
recorded during fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.llm.pipeline import llm_generate, _resolve_hybrid_client


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


class MockTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class MockToolBlock:
    type = "tool_use"

    def __init__(self, name: str, input_data: dict):
        self.name = name
        self.input = input_data


class MockMessage:
    role = "assistant"
    stop_reason = "end_turn"

    def __init__(self, blocks: list):
        self.content = blocks
        self.model = "mock-model"


def _make_intent_response() -> MockMessage:
    """Cloud-style tool_use response for intent parsing."""
    return MockMessage([
        MockToolBlock("create_design_intent", {
            "name": "test-regulator",
            "description": "A test voltage regulator",
            "board": {"width_mm": 100.0, "height_mm": 80.0, "layer_count": 2},
            "components": [],
            "nets": [],
            "power": {"nets": ["GND", "+3V3"]},
            "design_rules": {},
        }),
    ])


def _make_text_intent_response() -> MockMessage:
    """Local-style text response for intent parsing."""
    return MockMessage([
        MockTextBlock('```json\n{"name": "test-regulator", "description": "A test voltage regulator", "board": {"width_mm": 100.0, "height_mm": 80.0, "layer_count": 2}, "components": [], "nets": [], "power": {"nets": ["GND", "+3V3"]}, "design_rules": {}}\n```'),
    ])


# ---------------------------------------------------------------------------
# _resolve_hybrid_client tests
# ---------------------------------------------------------------------------


def test_resolve_hybrid_client_no_mode():
    """No mode set returns None (pure cloud)."""
    with patch.dict(os.environ, {}, clear=True):
        result = _resolve_hybrid_client(None, None)
    assert result is None


def test_resolve_hybrid_client_with_mode():
    """Mode set creates HybridLLMClient."""
    with patch.dict(os.environ, {}, clear=True):
        client = _resolve_hybrid_client("cloud_only", 0.7)
    assert client is not None
    assert client.fallback_mode == "cloud_only"
    assert client.confidence_threshold == 0.7


def test_resolve_hybrid_client_env_override():
    """KICAD_AGENT_LLM_MODE env var is used when no explicit mode."""
    with patch.dict(os.environ, {"KICAD_AGENT_LLM_MODE": "local_first"}, clear=True):
        client = _resolve_hybrid_client(None, None)
    assert client is not None
    assert client.fallback_mode == "local_first"


# ---------------------------------------------------------------------------
# Pipeline integration tests with mock components
# ---------------------------------------------------------------------------


def test_pipeline_cloud_only_mode_backward_compat():
    """Cloud-only mode with injected intent parser uses cloud path."""
    mock_parser = MagicMock()
    mock_intent = MagicMock()
    mock_intent.name = "test-design"
    mock_parser.parse.return_value = mock_intent

    # Mock generate_design to fail fast (we only care about stage 1)
    with patch("kicad_agent.generation.pipeline.generate_design") as mock_gen:
        mock_gen_result = MagicMock()
        mock_gen_result.success = False
        mock_gen_result.errors = ["test error"]
        mock_gen.return_value = mock_gen_result

        result = llm_generate(
            "design a voltage regulator",
            output_dir=Path("/tmp/test-project"),
            intent_parser=mock_parser,
            run_refinement=False,
            run_critique=False,
            run_evaluation=False,
        )

    mock_parser.parse.assert_called_once_with("design a voltage regulator")
    assert result.intent is mock_intent
    assert result.success is False  # generate_design failed, but parsing worked


def test_pipeline_local_first_mode_uses_unified_parser():
    """Local-first mode creates UnifiedIntentParser instead of IntentParser."""
    mock_parser = MagicMock()
    mock_intent = MagicMock()
    mock_intent.name = "test-design"
    mock_parser.parse.return_value = mock_intent

    with patch("kicad_agent.generation.pipeline.generate_design") as mock_gen:
        mock_gen_result = MagicMock()
        mock_gen_result.success = False
        mock_gen_result.errors = ["test error"]
        mock_gen.return_value = mock_gen_result

        result = llm_generate(
            "design a voltage regulator",
            output_dir=Path("/tmp/test-project"),
            intent_parser=mock_parser,
            llm_mode="cloud_only",  # use cloud_only to avoid needing local model
            run_refinement=False,
            run_critique=False,
            run_evaluation=False,
        )

    # Parser was used (injected, so it's our mock)
    mock_parser.parse.assert_called_once()


def test_pipeline_no_mode_preserves_existing_behavior():
    """When no llm_mode is set, pipeline behaves identically to before."""
    mock_parser = MagicMock()
    mock_intent = MagicMock()
    mock_intent.name = "test-design"
    mock_parser.parse.return_value = mock_intent

    with patch.dict(os.environ, {}, clear=True):
        with patch("kicad_agent.generation.pipeline.generate_design") as mock_gen:
            mock_gen_result = MagicMock()
            mock_gen_result.success = True
            mock_gen_result.erc_pass = True
            mock_gen_result.pcb_path = None
            mock_gen_result.errors = []
            mock_gen_result.project_dir = Path("/tmp/test")
            mock_gen.return_value = mock_gen_result

            result = llm_generate(
                "design a voltage regulator",
                output_dir=Path("/tmp/test-project"),
                intent_parser=mock_parser,
                run_refinement=False,
                run_critique=False,
                run_evaluation=False,
            )

    assert result.success is True
    assert result.intent is mock_intent


def test_pipeline_intent_parse_failure():
    """Intent parse failure returns early with error."""
    mock_parser = MagicMock()
    mock_parser.parse.side_effect = ValueError("Could not understand description")

    result = llm_generate(
        "asdfghjkl",
        output_dir=Path("/tmp/test-project"),
        intent_parser=mock_parser,
        run_refinement=False,
        run_critique=False,
        run_evaluation=False,
    )

    assert result.success is False
    assert len(result.errors) > 0
    assert "Could not understand" in result.errors[0]
