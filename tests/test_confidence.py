"""Tests for ConfidenceScorer, ConfidenceScore, and extract_json_from_text."""

import dataclasses
import json

import pytest

from volta.generation.intent import GenerationIntent
from volta.llm.confidence import (
    ConfidenceScore,
    ConfidenceScorer,
    extract_json_from_text as confidence_extract,
)
from volta.llm.text_prompts import extract_json_from_text as text_prompts_extract


# ---------------------------------------------------------------------------
# extract_json_from_text (from confidence module)
# ---------------------------------------------------------------------------


class TestExtractJsonConfidenceModule:
    """Tests for volta.llm.confidence.extract_json_from_text."""

    def test_extract_json_from_text_nested(self):
        text = '```json\n{"a": {"b": [1, 2]}, "c": 3}\n```'
        result = confidence_extract(text)
        assert result == {"a": {"b": [1, 2]}, "c": 3}

    def test_extract_json_from_text_array(self):
        text = "```json\n[1, 2, 3]\n```"
        result = confidence_extract(text)
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# extract_json_from_text (from text_prompts module)
# ---------------------------------------------------------------------------


class TestExtractJsonTextPrompts:
    """Tests for volta.llm.text_prompts.extract_json_from_text."""

    def test_extract_from_json_block(self):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = text_prompts_extract(text)
        assert result == {"key": "value"}

    def test_extract_from_generic_block(self):
        text = 'Here it is:\n```\n{"key": "value"}\n```\nDone'
        result = text_prompts_extract(text)
        assert result == {"key": "value"}

    def test_extract_raw_object(self):
        text = 'The result is {"a": 1, "b": 2} as expected.'
        result = text_prompts_extract(text)
        assert result == {"a": 1, "b": 2}

    def test_extract_returns_none_on_failure(self):
        result = text_prompts_extract("no json here at all")
        assert result is None


# ---------------------------------------------------------------------------
# ConfidenceScore dataclass
# ---------------------------------------------------------------------------


class TestConfidenceScore:
    def test_confidence_score_frozen(self):
        score = ConfidenceScore(
            overall=0.8,
            format_score=1.0,
            schema_score=1.0,
            reward_score=0.5,
            latency_s=0.01,
        )
        assert dataclasses.is_dataclass(score)
        with pytest.raises(dataclasses.FrozenInstanceError):
            score.overall = 0.0


# ---------------------------------------------------------------------------
# ConfidenceScorer — format_score
# ---------------------------------------------------------------------------


class TestFormatScore:
    def test_format_score_json_block(self):
        scorer = ConfidenceScorer()
        result = scorer.score('```json\n{"name": "test"}\n```')
        assert result.format_score == 1.0

    def test_format_score_no_json(self):
        scorer = ConfidenceScorer()
        result = scorer.score("plain text with no json whatsoever")
        assert result.format_score == 0.0

    def test_format_score_generic_block(self):
        scorer = ConfidenceScorer()
        result = scorer.score('```\n{"name": "test"}\n```')
        assert result.format_score == 1.0

    def test_format_score_raw_braces(self):
        scorer = ConfidenceScorer()
        result = scorer.score('here is {"name": "test"} in text')
        assert result.format_score == 1.0


# ---------------------------------------------------------------------------
# ConfidenceScorer — schema_score
# ---------------------------------------------------------------------------

_VALID_INTENT_JSON = json.dumps(
    {
        "name": "Amp",
        "description": "Simple amplifier",
        "board": {"width_mm": 50.0, "height_mm": 50.0},
        "components": [
            {
                "library_id": "Device:R",
                "reference": "R1",
                "value": "10k",
                "position": {"x": 10.0, "y": 20.0},
            }
        ],
        "nets": [{"name": "SDA", "pins": ["R1.1", "U1.3"]}],
        "power": {"nets": ["GND", "+3V3"]},
        "design_rules": {},
    }
)


class TestSchemaScore:
    def test_schema_score_valid_intent(self):
        scorer = ConfidenceScorer()
        text = f"```json\n{_VALID_INTENT_JSON}\n```"
        result = scorer.score(text, expected_schema=GenerationIntent)
        assert result.schema_score == 1.0

    def test_schema_score_invalid(self):
        scorer = ConfidenceScorer()
        result = scorer.score(
            '```json\n{"totally": "wrong"}\n```',
            expected_schema=GenerationIntent,
        )
        assert result.schema_score == 0.0


# ---------------------------------------------------------------------------
# ConfidenceScorer — overall composite
# ---------------------------------------------------------------------------


class TestOverallComposite:
    def test_overall_composite(self):
        scorer = ConfidenceScorer()
        # format=1, schema=1 (no schema passed → defaults 1), reward=0.5 (no model)
        result = scorer.score('```json\n{"a": 1}\n```')
        # 1*0.4 + 1*0.3 + 0.5*0.3 = 0.4 + 0.3 + 0.15 = 0.85
        assert abs(result.overall - 0.85) < 1e-6
