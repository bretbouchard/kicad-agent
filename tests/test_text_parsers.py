"""Tests for TextIntentParser, TextErrorFixer, TextCritiqueParser."""

from __future__ import annotations

import json

import pytest

from volta.llm.text_parsers import (
    TextCritiqueParser,
    TextErrorFixer,
    TextIntentParser,
)
from volta.llm.error_fixer import FixResult
from volta.llm.design_critic import CritiqueReport


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


class MockClient:
    """Mock LLM client returning a fixed text response."""

    def __init__(self, text: str = "ok"):
        self._text = text

    def create_message(self, **kwargs):
        class Content:
            type = "text"
            text = self._text

        class Msg:
            content = [Content()]

        return Msg()


class FailingClient:
    """Mock client that always raises."""

    def create_message(self, **kwargs):
        raise RuntimeError("LLM unavailable")


# ---------------------------------------------------------------------------
# Shared valid intent JSON
# ---------------------------------------------------------------------------

_VALID_INTENT_JSON = json.dumps(
    {
        "name": "test",
        "description": "test circuit",
        "board": {"width_mm": 100, "height_mm": 80, "layer_count": 2},
        "components": [],
        "nets": [],
        "power": {"nets": ["GND"]},
        "design_rules": {},
    }
)


# ---------------------------------------------------------------------------
# TextIntentParser
# ---------------------------------------------------------------------------


class TestTextIntentParser:
    def test_text_intent_parser_valid_json(self):
        client = MockClient(text=_VALID_INTENT_JSON)
        parser = TextIntentParser(client)
        intent = parser.parse("Design a test circuit")

        assert intent.name == "test"
        assert intent.description == "test circuit"
        assert intent.board.width_mm == 100
        assert intent.board.height_mm == 80

    def test_text_intent_parser_no_json(self):
        client = MockClient(text="I cannot help with that.")
        parser = TextIntentParser(client)

        with pytest.raises(ValueError, match="could not extract JSON"):
            parser.parse("Design something")


# ---------------------------------------------------------------------------
# TextErrorFixer
# ---------------------------------------------------------------------------


class TestTextErrorFixer:
    def test_text_error_fixer_valid(self):
        fix_json = json.dumps(
            {
                "operations": [{"op": "move", "ref": "R1", "x": 10, "y": 20}],
                "fix_description": "Moved R1 to clear clearance violation",
            }
        )
        client = MockClient(text=fix_json)
        fixer = TextErrorFixer(client)

        result = fixer.fix(
            violations=[{"description": "Clearance violation", "severity": "error", "type": "DRC"}]
        )

        assert isinstance(result, FixResult)
        assert result.success is True
        assert len(result.operations) == 1
        assert result.operations[0]["op"] == "move"

    def test_text_error_fixer_no_json(self):
        client = MockClient(text="No fix available")
        fixer = TextErrorFixer(client)

        result = fixer.fix(
            violations=[{"description": "Some error", "severity": "error", "type": "ERC"}]
        )

        assert isinstance(result, FixResult)
        assert result.success is False
        assert result.operations == ()

    def test_text_error_fixer_exception(self):
        client = FailingClient()
        fixer = TextErrorFixer(client)

        result = fixer.fix(
            violations=[{"description": "Broken", "severity": "error", "type": "DRC"}]
        )

        assert isinstance(result, FixResult)
        assert result.success is False
        assert "LLM call failed" in result.fix_description


# ---------------------------------------------------------------------------
# TextCritiqueParser
# ---------------------------------------------------------------------------


class TestTextCritiqueParser:
    def test_text_critique_parser_valid(self):
        critique_json = json.dumps(
            {
                "findings": [
                    {
                        "severity": "warning",
                        "category": "clearance",
                        "description": "Trace too close to pad",
                        "coordinates": [[1.0, 2.0]],
                    },
                    {
                        "severity": "info",
                        "category": "placement",
                        "description": "Consider better grouping",
                        "coordinates": [],
                    },
                ],
                "summary": "Minor clearance and placement issues",
                "overall_quality_score": 0.75,
            }
        )

        parser = TextCritiqueParser()
        report = parser.parse(critique_json)

        assert isinstance(report, CritiqueReport)
        assert len(report.findings) == 2
        assert report.findings[0].category == "clearance"
        assert report.findings[0].coordinates == ((1.0, 2.0),)
        assert report.overall_quality_score == 0.75
        assert "clearance" in report.summary

    def test_text_critique_parser_no_json(self):
        parser = TextCritiqueParser()
        report = parser.parse("This is not JSON")

        assert isinstance(report, CritiqueReport)
        assert report.findings == ()
        assert report.overall_quality_score == 1.0
