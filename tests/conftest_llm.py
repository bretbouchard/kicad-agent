"""Shared fixtures for LLM module tests.

Provides mock Anthropic client and sample data for testing LLM integration
without requiring an actual API key or network access.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class FakeToolUseBlock:
    """Mimics an Anthropic ToolUseBlock for testing."""

    def __init__(self, name: str, tool_input: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = tool_input
        self.id = "toolu_test_123"


class FakeTextBlock:
    """Mimics an Anthropic TextBlock for testing."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeMessage:
    """Mimics an Anthropic Message response."""

    def __init__(self, blocks: list[Any], stop_reason: str = "end_turn") -> None:
        self.content = blocks
        self.stop_reason = stop_reason
        self.model = "claude-sonnet-4-20250514"
        self.usage = {"input_tokens": 100, "output_tokens": 200}


@pytest.fixture
def mock_anthropic_client():
    """Mock anthropic.Anthropic().messages.create() returning a configurable fake response.

    Usage in tests:
        mock_anthropic_client.return_value = FakeMessage([
            FakeToolUseBlock("create_design_intent", {...})
        ])
    """
    with patch("anthropic.Anthropic") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance.messages.create


@pytest.fixture
def sample_intent_dict() -> dict[str, Any]:
    """A valid GenerationIntent as a plain dict (LED circuit)."""
    return {
        "name": "LED Blinker",
        "description": "Simple LED blinker circuit with current-limiting resistor",
        "board": {
            "width_mm": 50.0,
            "height_mm": 50.0,
            "layer_count": 2,
            "thickness_mm": 1.6,
            "edge_connector": False,
        },
        "components": [
            {
                "library_id": "Device:R",
                "reference": "R1",
                "value": "330",
                "position": {"x": 25.0, "y": 20.0, "angle": 0.0},
                "footprint": "",
            },
            {
                "library_id": "Device:LED",
                "reference": "D1",
                "value": "Red",
                "position": {"x": 25.0, "y": 30.0, "angle": 0.0},
                "footprint": "",
            },
        ],
        "nets": [
            {"name": "VCC_R", "pins": ["R1.1", "D1.1"]},
        ],
        "power": {"nets": ["GND", "+3V3"]},
        "design_rules": {},
    }


@pytest.fixture
def sample_suggestions_dict() -> list[dict[str, str]]:
    """A list of valid component suggestion dicts."""
    return [
        {
            "library_id": "Device:R_Small_US",
            "value": "10k",
            "reference_prefix": "R",
            "rationale": "Standard pull-up resistor value",
        },
        {
            "library_id": "Device:C_Small",
            "value": "100nF",
            "reference_prefix": "C",
            "rationale": "Decoupling capacitor for noise filtering",
        },
    ]


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    """Set ANTHROPIC_API_KEY for all LLM tests."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-for-testing-only")
