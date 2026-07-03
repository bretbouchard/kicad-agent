"""Phase 106: BlockerDiagnosticianModel unit tests.

Tests parsing and fallback logic without loading the 24GB model.
Uses a mock pipeline that returns canned responses.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.diagnostician import BlockerDiagnostician
from kicad_agent.routing.diagnostician_model import BlockerDiagnosticianModel
from kicad_agent.routing.pathfinder import RouteFailure
from kicad_agent.spatial.primitives import SpatialBox


def _make_failure() -> RouteFailure:
    return RouteFailure(
        net_name="NET_A",
        source_point=(10.0, 50.0),
        target_point=(90.0, 50.0),
        dead_end_point=(45.0, 50.0),
        reachable_count=500,
        failure_type="no_path",
    )


def _make_fallback() -> BlockerDiagnostician:
    return BlockerDiagnostician(
        board_bounds=(0, 0, 100, 100),
        obstacles=[],
        constraints=RoutingConstraints(grid_resolution_mm=1.0),
    )


# A canned model response matching the training format exactly.
_GOOD_RESPONSE = """Blocker diagnosis for net 'NET_A':
Dead-end point: (45.00, 50.00)
Target point: (90.00, 50.00)
Failure type: no_path

Blockers identified (ranked by removal benefit):
  1. footprint 'U3' (IC_UUID0...)
     Classification: HARD_COMPONENT
     Causal blocker: True
     Recommended action: nudge_component
     Removal benefit: 0.7
  2. track 'GND' (TRACK_UUID...)
     Classification: SOFT_OTHER
     Causal blocker: False
     Recommended action: rip_and_reroute
     Removal benefit: 0.3
"""


class TestParsing:
    """Test the model response parser."""

    def test_parses_multiple_blockers(self) -> None:
        model = BlockerDiagnosticianModel(
            pipeline=MagicMock(),
            pcb_path=Path("/dummy"),
            fallback=_make_fallback(),
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        blockers = model._parse_response(_GOOD_RESPONSE)
        assert len(blockers) == 2

        b1 = blockers[0]
        assert b1.entity_type == "footprint"
        assert b1.reference == "U3"
        assert b1.classification == "HARD_COMPONENT"
        assert b1.blocks_path is True
        assert b1.recommended_action == "nudge_component"
        assert b1.removal_benefit == 0.7

        b2 = blockers[1]
        assert b2.entity_type == "track"
        assert b2.reference == "GND"
        assert b2.classification == "SOFT_OTHER"
        assert b2.blocks_path is False
        assert b2.recommended_action == "rip_and_reroute"

    def test_empty_response_returns_no_blockers(self) -> None:
        model = BlockerDiagnosticianModel(
            pipeline=MagicMock(),
            pcb_path=Path("/dummy"),
            fallback=_make_fallback(),
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        blockers = model._parse_response("No blockers found.")
        assert blockers == []

    def test_invalid_classification_defaults_to_hard_fixed(self) -> None:
        model = BlockerDiagnosticianModel(
            pipeline=MagicMock(),
            pcb_path=Path("/dummy"),
            fallback=_make_fallback(),
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        response = """Blockers identified:
  1. footprint 'X1' (UUID1...)
     Classification: UNKNOWN_TYPE
     Causal blocker: True
     Recommended action: unknown_action
     Removal benefit: 0.5
"""
        blockers = model._parse_response(response)
        assert len(blockers) == 1
        # Invalid classification/action should default to safe values.
        assert blockers[0].classification == "HARD_FIXED"
        assert blockers[0].recommended_action == "escalate"


class TestDiagnose:
    """Test the full diagnose() flow with mock pipeline."""

    def test_model_diagnosis_success(self) -> None:
        """A good model response produces a valid BlockerDiagnosis."""
        mock_pipeline = MagicMock()
        mock_pipeline.generate_from_image.return_value = _GOOD_RESPONSE

        model = BlockerDiagnosticianModel(
            pipeline=mock_pipeline,
            pcb_path=Path("/dummy"),
            fallback=_make_fallback(),
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        result = model.diagnose(_make_failure())

        assert result.net_name == "NET_A"
        assert len(result.blockers) == 2
        assert result.failure_type == "no_path"

    def test_falls_back_on_empty_output(self) -> None:
        """Empty model output triggers deterministic fallback."""
        mock_pipeline = MagicMock()
        mock_pipeline.generate_from_image.return_value = ""

        fallback = _make_fallback()
        model = BlockerDiagnosticianModel(
            pipeline=mock_pipeline,
            pcb_path=Path("/dummy"),
            fallback=fallback,
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        # Should not raise — should delegate to fallback.
        result = model.diagnose(_make_failure())
        assert isinstance(result.net_name, str)

    def test_falls_back_on_model_exception(self) -> None:
        """Model crash triggers deterministic fallback (R-6)."""
        mock_pipeline = MagicMock()
        mock_pipeline.generate_from_image.side_effect = RuntimeError("OOM")

        fallback = _make_fallback()
        model = BlockerDiagnosticianModel(
            pipeline=mock_pipeline,
            pcb_path=Path("/dummy"),
            fallback=fallback,
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        result = model.diagnose(_make_failure())
        # Fallback returns a valid diagnosis (possibly with empty blockers).
        assert result.net_name == "NET_A"

    def test_falls_back_on_unparseable_output(self) -> None:
        """Garbage model output that can't be parsed triggers fallback."""
        mock_pipeline = MagicMock()
        mock_pipeline.generate_from_image.return_value = (
            "The quick brown fox jumps over the lazy dog."
        )

        fallback = _make_fallback()
        model = BlockerDiagnosticianModel(
            pipeline=mock_pipeline,
            pcb_path=Path("/dummy"),
            fallback=fallback,
            board_bounds=(0, 0, 100, 100),
            render_fn=lambda p: MagicMock(),
        )
        result = model.diagnose(_make_failure())
        assert result.net_name == "NET_A"


class TestPromptFormat:
    """Verify the prompt matches the training format exactly."""

    def test_prompt_contains_all_fields(self) -> None:
        from kicad_agent.routing.diagnostician_model_prompts import (
            build_diagnostician_prompt,
        )
        failure = _make_failure()
        bounds = (0.0, 0.0, 100.0, 100.0)
        prompt = build_diagnostician_prompt(failure, bounds)

        # Must contain all fields from the training format.
        assert "NET_A" in prompt
        assert "10.00" in prompt  # source x
        assert "90.00" in prompt  # target x
        assert "45.00" in prompt  # dead-end x
        assert "no_path" in prompt
        assert "500" in prompt  # reachable count
        assert "What is blocking" in prompt
