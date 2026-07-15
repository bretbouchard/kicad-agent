"""Tests for the AI legibility critic (Phase 109).

Tests 1-12 cover Task 1: CritiqueResult + Suggestion schemas, CritiqueSchOp,
LegibilityCritic Protocol, build_legibility_prompt, parse_legibility_json,
GemmaLegibilityCritic with R-6 fallback.

Tests 13-22 cover Task 2: ClaudeLegibilityCritic + HybridLegibilityCritic dispatcher.

All tests use FakePipeline / FakeClaudeClient test doubles. Real model
invocation is opt-in via @pytest.mark.integration + importorskip.

Integration Testing
-------------------
Real Gemma 4 12B V2 (23.8 GB) and real Claude API invocation are deferred to
the Phase 110 eval harness. To run real-model integration tests::

    @pytest.mark.integration
    def test_real_gemma():
        importorskip("mlx_vlm")
        pytest.importorskip("anthropic")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("requires ANTHROPIC_API_KEY")
        # ... real invocation here
"""
from __future__ import annotations

import dataclasses
import io
import json
from typing import Any

from PIL import Image

import pytest
from pydantic import ValidationError

from volta.analysis.legibility_critic import (
    ClaudeLegibilityCritic,
    CritiqueResult,
    GemmaLegibilityCritic,
    HybridLegibilityCritic,
    LegibilityCritic,
    Suggestion,
    build_legibility_prompt,
    parse_legibility_json,
    validate_factors,
    validate_no_coordinates,
    validate_score_range,
)
from volta.ops._schema_critique import CritiqueSchOp


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakePipeline:
    """Test double for KiCadVisionPipeline — never loads the real 23.8 GB model."""

    def __init__(self, response: str | Exception) -> None:
        self._response = response
        self.call_count = 0

    def generate_from_image(self, image: Any, prompt: str) -> str:
        self.call_count += 1
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeClaudeClient:
    """Test double for LLMClient — never makes real network calls.

    Mirrors LLMClient.create_message(**kwargs) interface (per Council MED-01
    Option A — reuse existing LLMClient wrapper, not raw anthropic).
    """

    def __init__(self, response_json: str | Exception, model: str = "claude-test") -> None:
        self._response = response_json
        self._model = model
        self.call_count = 0

    def create_message(self, **kwargs: Any) -> Any:
        self.call_count += 1
        if isinstance(self._response, Exception):
            raise self._response
        # Mirror anthropic Message shape: response.content[0].text
        return type(
            "Resp",
            (),
            {
                "content": [
                    type("Block", (), {"text": self._response})()
                ]
            },
        )

    @property
    def model(self) -> str:
        return self._model


def _valid_response_json(confidence: float = 0.9, srs: float = 0.75) -> str:
    """Build a valid Gemma-style JSON response string."""
    return json.dumps({
        "overall_srs": srs,
        "factors": {
            "density": 0.7,
            "clarity": 0.8,
            "spacing": 0.75,
            "organization": 0.7,
        },
        "suggestions": [
            {"text": "reduce density near U3", "severity": "warning", "category": "density"},
        ],
        "confidence": confidence,
    })


def _fake_pil_image() -> Image.Image:
    """Build a tiny real PIL image — _encode_image_for_claude needs .save()."""
    return Image.new("RGB", (4, 4), color="white")


# ---------------------------------------------------------------------------
# Test 1 — CritiqueResult is frozen and JSON-serializable
# ---------------------------------------------------------------------------


class TestCritiqueResultFrozen:
    def test_json_round_trip(self) -> None:
        r = CritiqueResult(
            overall_srs=0.7,
            factors={"density": 0.6, "clarity": 0.8, "spacing": 0.7, "organization": 0.7},
            suggestions=(
                Suggestion(text="reduce density near U1", severity="warning", category="density"),
            ),
            model_used="gemma4",
            confidence=0.85,
            latency_ms=1200,
        )
        dumped = json.dumps(dataclasses.asdict(r))
        loaded = json.loads(dumped)
        assert loaded["overall_srs"] == 0.7
        assert loaded["model_used"] == "gemma4"
        assert loaded["factors"]["density"] == 0.6

    def test_replace_succeeds(self) -> None:
        r = CritiqueResult(
            overall_srs=0.7,
            factors={"density": 0.6, "clarity": 0.8, "spacing": 0.7, "organization": 0.7},
            suggestions=(),
            model_used="gemma4",
            confidence=0.85,
            latency_ms=1200,
        )
        r2 = dataclasses.replace(r, overall_srs=0.8)
        assert r2.overall_srs == 0.8
        assert r.overall_srs == 0.7  # original unchanged

    def test_attribute_assignment_raises_frozen(self) -> None:
        r = CritiqueResult(
            overall_srs=0.7,
            factors={"density": 0.6, "clarity": 0.8, "spacing": 0.7, "organization": 0.7},
            suggestions=(),
            model_used="gemma4",
            confidence=0.85,
            latency_ms=1200,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.overall_srs = 0.8  # type: ignore[misc]

    def test_factors_view_is_immutable(self) -> None:
        """MED-02 Option B: factors_view returns MappingProxy that raises on mutation."""
        r = CritiqueResult(
            overall_srs=0.7,
            factors={"density": 0.6, "clarity": 0.8, "spacing": 0.7, "organization": 0.7},
            suggestions=(),
            model_used="gemma4",
            confidence=0.85,
            latency_ms=1200,
        )
        view = r.factors_view()
        with pytest.raises(TypeError):
            view["density"] = 0.99  # type: ignore[index]


# ---------------------------------------------------------------------------
# Test 2 — LO-04 hardening (no coordinates)
# ---------------------------------------------------------------------------


class TestSuggestionLO04:
    def test_valid_suggestion(self) -> None:
        s = Suggestion(text="move C5 closer to U1", severity="warning", category="spacing")
        assert s.text == "move C5 closer to U1"

    def test_rejects_x_field_at_construction(self) -> None:
        """Dataclass rejects unknown kwargs — Python TypeError fires before __post_init__.

        This is the constructor-layer LO-04 defense: callers cannot inject
        x/y/position/coord fields into a Suggestion via the public constructor.
        """
        with pytest.raises(TypeError):
            Suggestion(text="move", severity="warning", category="spacing", x=50.0)  # type: ignore[call-arg]

    def test_rejects_y_field_at_construction(self) -> None:
        with pytest.raises(TypeError):
            Suggestion(text="move", severity="warning", category="spacing", y=30.0)  # type: ignore[call-arg]

    def test_rejects_position_field_at_construction(self) -> None:
        with pytest.raises(TypeError):
            Suggestion(text="move", severity="warning", category="spacing", position=(50, 30))  # type: ignore[call-arg]

    def test_rejects_coord_field_at_construction(self) -> None:
        with pytest.raises(TypeError):
            Suggestion(text="move", severity="warning", category="spacing", coord=(50, 30))  # type: ignore[call-arg]

    def test_validate_no_coordinates_rejects_x(self) -> None:
        with pytest.raises(ValueError):
            validate_no_coordinates({"text": "ok", "x": 50})

    def test_validate_no_coordinates_rejects_nested(self) -> None:
        with pytest.raises(ValueError):
            validate_no_coordinates({
                "suggestions": [{"text": "leak", "y": 30}]
            })

    def test_validate_no_coordinates_accepts_clean(self) -> None:
        validate_no_coordinates({"text": "reduce density near U3"})  # no exception


# ---------------------------------------------------------------------------
# Test 3 — Per-factor schema (D-02)
# ---------------------------------------------------------------------------


class TestFactorValidation:
    def test_valid_four_factors(self) -> None:
        validate_factors({
            "density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5
        })

    def test_missing_factor_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_factors({"density": 0.5, "clarity": 0.5, "spacing": 0.5})

    def test_extra_factor_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_factors({
                "density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5,
                "bogus": 0.5,
            })


# ---------------------------------------------------------------------------
# Test 4 — Score range validation
# ---------------------------------------------------------------------------


class TestScoreRange:
    def test_zero_ok(self) -> None:
        validate_score_range(0.0)

    def test_one_ok(self) -> None:
        validate_score_range(1.0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_score_range(-0.01)

    def test_over_one_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_score_range(1.01)


# ---------------------------------------------------------------------------
# Test 5 — CritiqueSchOp Pydantic schema (D-04)
# ---------------------------------------------------------------------------


class TestCritiqueSchOp:
    def test_defaults(self) -> None:
        op = CritiqueSchOp(target_file="board.kicad_sch")
        assert op.op_type == "critique_sch"
        assert op.gemma_only is False
        assert op.claude_only is False
        assert op.include_suggestions is True

    def test_claude_only_flag(self) -> None:
        op = CritiqueSchOp(target_file="board.kicad_sch", claude_only=True)
        assert op.claude_only is True

    def test_rejects_non_kicad_sch(self) -> None:
        with pytest.raises(ValidationError):
            CritiqueSchOp(target_file="board.txt")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValidationError):
            CritiqueSchOp(target_file="../../../etc/passwd")


# ---------------------------------------------------------------------------
# Test 6 — build_legibility_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_contains_factor_names(self) -> None:
        prompt = build_legibility_prompt()
        assert "density" in prompt.lower()
        assert "clarity" in prompt.lower()
        assert "spacing" in prompt.lower()
        assert "organization" in prompt.lower()

    def test_contains_json_instruction(self) -> None:
        prompt = build_legibility_prompt()
        assert "json" in prompt.lower()

    def test_does_not_contain_coordinate_language(self) -> None:
        """LO-04 prompt hardening — no coordinate-language phrases."""
        prompt = build_legibility_prompt().lower()
        assert "x coordinate" not in prompt
        assert "y coordinate" not in prompt
        assert "absolute position" not in prompt


# ---------------------------------------------------------------------------
# Test 7 — parse_legibility_json never raises (Phase 98 R-2 pattern)
# ---------------------------------------------------------------------------


class TestParseLegibilityJson:
    def test_bare_json(self) -> None:
        parsed = parse_legibility_json('{"overall_srs": 0.7, "factors": {}}')
        assert parsed["overall_srs"] == 0.7

    def test_markdown_fence(self) -> None:
        parsed = parse_legibility_json('```json\n{"overall_srs": 0.7}\n```')
        assert parsed["overall_srs"] == 0.7

    def test_prose_prefix(self) -> None:
        parsed = parse_legibility_json('Sorry, I cannot help.{}')
        # {} is empty — should either parse to {} or fall back to {}
        assert parsed == {}

    def test_empty_string(self) -> None:
        assert parse_legibility_json("") == {}

    def test_none(self) -> None:
        assert parse_legibility_json(None) == {}

    def test_picks_largest_dict(self) -> None:
        raw = '{"a": 1} {"overall_srs": 0.7, "factors": {"density": 0.5}}'
        parsed = parse_legibility_json(raw)
        assert "overall_srs" in parsed


# ---------------------------------------------------------------------------
# Test 8 — parse_legibility_json rejects coordinates (LO-04)
# ---------------------------------------------------------------------------


class TestParseRejectsCoordinates:
    def test_rejects_coordinates_in_suggestions(self) -> None:
        raw = json.dumps({
            "suggestions": [{"text": "move C5 to (50, 30)", "x": 50, "y": 30}]
        })
        assert parse_legibility_json(raw) == {}

    def test_accepts_clean_suggestions(self) -> None:
        raw = json.dumps({
            "suggestions": [{"text": "reduce density near U3", "severity": "warning", "category": "density"}]
        })
        parsed = parse_legibility_json(raw)
        assert "suggestions" in parsed


# ---------------------------------------------------------------------------
# Test 9 — GemmaLegibilityCritic returns valid CritiqueResult on success
# ---------------------------------------------------------------------------


class TestGemmaCriticSuccess:
    def test_returns_valid_result(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.9, srs=0.75))
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object(), file_path="board.kicad_sch")
        assert result.model_used == "gemma4"
        assert result.confidence == pytest.approx(0.9, abs=0.01)
        assert result.latency_ms >= 0
        assert set(result.factors.keys()) == {"density", "clarity", "spacing", "organization"}

    def test_records_suggestions(self) -> None:
        pipeline = FakePipeline(_valid_response_json())
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        assert len(result.suggestions) >= 1


# ---------------------------------------------------------------------------
# Test 10 — GemmaLegibilityCritic R-6 fallback on synthetic exception
# ---------------------------------------------------------------------------


class TestGemmaCriticR6Exception:
    def test_exception_returns_fallback(self) -> None:
        pipeline = FakePipeline(RuntimeError("model crashed"))
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        assert result.model_used == "none"
        assert result.confidence == 0.0
        assert result.overall_srs == 0.0
        assert result.suggestions == ()
        assert set(result.factors.keys()) == {"density", "clarity", "spacing", "organization"}
        for v in result.factors.values():
            assert v == 0.0


# ---------------------------------------------------------------------------
# Test 10b — GemmaLegibilityCritic R-6 fallback on empty string
# (MED-03: real pipeline returns "" on failure, doesn't raise)
# ---------------------------------------------------------------------------


class TestGemmaCriticR6EmptyString:
    def test_empty_string_returns_fallback(self) -> None:
        pipeline = FakePipeline("")
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        assert result.model_used == "none"
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Test 11 — R-6 fallback on parse failure AND on LO-04 violation
# ---------------------------------------------------------------------------


class TestGemmaCriticR6ParseFailure:
    def test_unparseable_response(self) -> None:
        pipeline = FakePipeline("I cannot analyze this image")
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        assert result.model_used == "none"

    def test_coordinate_violation_triggers_fallback(self) -> None:
        raw = '{"suggestions": [{"text": "move to 50,30", "x": 50, "y": 30}]}'
        pipeline = FakePipeline(raw)
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        assert result.model_used == "none"


# ---------------------------------------------------------------------------
# Test 12 — Suggestion count cap (D-04 / CONTEXT Claude's Discretion)
# ---------------------------------------------------------------------------


class TestSuggestionCap:
    def test_caps_at_ten(self) -> None:
        suggestions = [
            {"text": f"suggestion {i}", "severity": "warning", "category": "density"}
            for i in range(20)
        ]
        raw = json.dumps({
            "overall_srs": 0.5,
            "factors": {"density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5},
            "suggestions": suggestions,
            "confidence": 0.8,
        })
        pipeline = FakePipeline(raw)
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        assert len(result.suggestions) <= 10

    def test_severity_sort_priority(self) -> None:
        suggestions = [
            {"text": "sug", "severity": "suggestion", "category": "density"},
            {"text": "crit", "severity": "critical", "category": "density"},
            {"text": "warn", "severity": "warning", "category": "density"},
        ]
        raw = json.dumps({
            "overall_srs": 0.5,
            "factors": {"density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5},
            "suggestions": suggestions,
            "confidence": 0.8,
        })
        pipeline = FakePipeline(raw)
        critic = GemmaLegibilityCritic(pipeline)
        result = critic.critique(image=object())
        # Critical should come first
        assert result.suggestions[0].severity == "critical"


# ---------------------------------------------------------------------------
# Task 2 Tests — Claude + Hybrid (Tests 13-22)
# ---------------------------------------------------------------------------


# Test 13 — ClaudeLegibilityCritic returns valid result on success
class TestClaudeCriticSuccess:
    def test_returns_valid_result(self) -> None:
        client = FakeClaudeClient(_valid_response_json(confidence=0.85))
        critic = ClaudeLegibilityCritic(client)
        result = critic.critique(image=_fake_pil_image(), file_path="board.kicad_sch")
        assert result.model_used == "claude"
        assert result.confidence > 0.0
        assert set(result.factors.keys()) == {"density", "clarity", "spacing", "organization"}


# Test 14 — Claude R-6 fallback on exception
class TestClaudeCriticR6:
    def test_exception_returns_fallback(self) -> None:
        class FakeAPIError(Exception):
            pass
        client = FakeClaudeClient(FakeAPIError("API error"))
        critic = ClaudeLegibilityCritic(client)
        result = critic.critique(image=_fake_pil_image())
        assert result.model_used == "none"
        assert result.confidence == 0.0


# Test 15 — Claude reuses parse_legibility_json (LO-04 enforcement)
class TestClaudeLO04Reuse:
    def test_coordinate_violation_triggers_fallback(self) -> None:
        raw = '{"suggestions": [{"text": "x=50", "x": 50}]}'
        client = FakeClaudeClient(raw)
        critic = ClaudeLegibilityCritic(client)
        result = critic.critique(image=_fake_pil_image())
        assert result.model_used == "none"


# Test 16 — Hybrid dispatches to Gemma first
class TestHybridGemmaFirst:
    def test_uses_gemma_when_high_confidence(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.95, srs=0.85))
        client = FakeClaudeClient(_valid_response_json(confidence=0.9))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
        )
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "gemma4"
        assert client.call_count == 0


# Test 17 — R-4 gate triggers Claude when Gemma confidence < 0.7
class TestR4LowConfidence:
    def test_low_confidence_triggers_claude(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.5, srs=0.85))
        client = FakeClaudeClient(_valid_response_json(confidence=0.95))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
        )
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "claude"
        assert client.call_count == 1


# Test 18 — R-4 gate triggers Claude when SRS in uncertain band [0.4, 0.7]
class TestR4UncertainBand:
    def test_uncertain_band_triggers_claude(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.95, srs=0.55))
        client = FakeClaudeClient(_valid_response_json(confidence=0.9, srs=0.8))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
        )
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "claude"


# Test 19 — claude_only=True bypasses Gemma
class TestClaudeOnly:
    def test_skips_gemma(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.95))
        client = FakeClaudeClient(_valid_response_json(confidence=0.9))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
            claude_only=True,
        )
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "claude"
        assert pipeline.call_count == 0


# Test 20 — gemma_only=True bypasses Claude
class TestGemmaOnly:
    def test_skips_claude_on_low_confidence(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.3, srs=0.3))
        client = FakeClaudeClient(_valid_response_json(confidence=0.95))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
            gemma_only=True,
        )
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "gemma4"
        assert client.call_count == 0


# Test 21 — Double R-6 fallback
class TestDoubleR6Fallback:
    def test_both_fail_returns_none(self) -> None:
        pipeline = FakePipeline(RuntimeError("gemma crash"))
        client = FakeClaudeClient(RuntimeError("claude crash"))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
        )
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "none"
        assert result.confidence == 0.0


# Test 22 — R-4 threshold + uncertain band are tunable
class TestTunableThresholds:
    def test_custom_thresholds(self) -> None:
        pipeline = FakePipeline(_valid_response_json(confidence=0.8, srs=0.65))
        client = FakeClaudeClient(_valid_response_json(confidence=0.9, srs=0.85))
        hybrid = HybridLegibilityCritic(
            gemma=GemmaLegibilityCritic(pipeline),
            claude=ClaudeLegibilityCritic(client),
            confidence_threshold=0.85,
            uncertain_band=(0.3, 0.6),
        )
        # confidence 0.8 < 0.85 → triggers Claude
        result = hybrid.critique(image=_fake_pil_image())
        assert result.model_used == "claude"

    def test_defaults_match_context(self) -> None:
        from dataclasses import fields
        hybrid_fields = {f.name: f.default for f in fields(HybridLegibilityCritic)}
        assert hybrid_fields["confidence_threshold"] == 0.7
        assert hybrid_fields["uncertain_band"] == (0.4, 0.7)


# ---------------------------------------------------------------------------
# Protocol structural subtyping
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_gemma_satisfies_protocol(self) -> None:
        pipeline = FakePipeline(_valid_response_json())
        critic: LegibilityCritic = GemmaLegibilityCritic(pipeline)
        # Should not raise — structural subtyping
        assert hasattr(critic, "critique")

    def test_claude_satisfies_protocol(self) -> None:
        client = FakeClaudeClient(_valid_response_json())
        critic: LegibilityCritic = ClaudeLegibilityCritic(client)
        assert hasattr(critic, "critique")
