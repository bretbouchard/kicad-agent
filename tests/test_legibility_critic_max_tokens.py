"""Unit tests for ClaudeLegibilityCritic max_tokens=2048 bound (LO-08 fix).

Phase 110 Plan 01 Task 0 — closes Phase 109 Gate 2 finding LO-08: without
max_tokens bound, a verbose Claude response could consume unbounded token
budget and trigger pathological brace-matching in parse_legibility_json.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from volta.analysis.legibility_critic import ClaudeLegibilityCritic


def _build_client_with_response(response: object) -> MagicMock:
    """Build a mock LLMClient whose create_message returns the given response."""
    client = MagicMock()
    client.create_message.return_value = response
    return client


class _FakeImage:
    """Minimal PIL-image stand-in: supports .save(buf, format=...)."""

    def save(self, buf, format: str = "PNG") -> None:  # noqa: A002
        buf.write(b"\x89PNG\r\n\x1a\nFAKEPNGBYTES")


def test_critique_passes_max_tokens_2048_to_create_message() -> None:
    """Test 1: ClaudeLegibilityCritic.critique() forwards max_tokens=2048."""
    client = _build_client_with_response(response=None)  # None -> R-6 fallback
    critic = ClaudeLegibilityCritic(client)

    critic.critique(image=_FakeImage(), file_path="test.kicad_sch")

    client.create_message.assert_called_once()
    kwargs = client.create_message.call_args.kwargs
    assert kwargs.get("max_tokens") == 2048, (
        f"LO-08: expected max_tokens=2048 in create_message call, got kwargs={kwargs}"
    )


def test_max_tokens_is_class_constant_2048() -> None:
    """Test 2: _MAX_TOKENS class-level constant documents the bound."""
    assert hasattr(ClaudeLegibilityCritic, "_MAX_TOKENS"), (
        "LO-08: ClaudeLegibilityCritic must expose _MAX_TOKENS class constant"
    )
    assert ClaudeLegibilityCritic._MAX_TOKENS == 2048


def test_critique_never_raises_on_api_error_r6_fallback_intact() -> None:
    """Test 3: R-6 fallback unchanged — critique never raises."""
    client = MagicMock()
    client.create_message.side_effect = RuntimeError("API down")
    critic = ClaudeLegibilityCritic(client)

    # Must NOT raise — R-6 broad-except returns fallback CritiqueResult
    result = critic.critique(image=_FakeImage(), file_path="test.kicad_sch")
    assert result.model_used == "none"
    assert result.overall_srs == 0.0
