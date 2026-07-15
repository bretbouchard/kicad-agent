"""Unit tests for LegibilityRewardAdapter (Plan 04 Task 1).

CR-110-01: CritiqueResult is SHIPPED, consumed directly.
CR-110-04: Caps consume CapInputs value object.
HI-110-05: completeness_source explicit ("none" default folds weight into correctness).
LO-110-11: malformed critique -> 0.0 with warning, no crash.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest

from volta.training.legibility_reward_adapter import (
    LegibilityRewardAdapter,
    RewardWeights,
)
from volta.training.rewards import (
    CapInputs,
    CompactnessCap,
    CrossingsFloorCap,
    LegibilityReward,
)


def _make_critique(factors: dict, model_used: str = "gemma4") -> MagicMock:
    """Build a CritiqueResult-like mock exposing factors_view()."""
    critique = MagicMock()
    critique.factors_view.return_value = MappingProxyType(dict(factors))
    critique.model_used = model_used
    return critique


def _make_cap_inputs(bbox: float, footprint: float, crossings: int) -> CapInputs:
    return CapInputs(
        bounding_box_mm2=bbox,
        component_footprint_area_mm2=footprint,
        crossing_count=crossings,
    )


# ---------------------------------------------------------------------------
# RewardWeights
# ---------------------------------------------------------------------------


def test_reward_weights_default_sums_to_one() -> None:
    """RewardWeights default = 0.40/0.40/0.20 (D-03)."""
    w = RewardWeights()
    assert w.correctness == 0.40
    assert w.completeness == 0.40
    assert w.legibility == 0.20
    assert w.correctness + w.completeness + w.legibility == pytest.approx(1.0)


def test_reward_weights_invalid_sum_raises() -> None:
    """Test 8: weights not summing to 1.0 raise ValueError."""
    with pytest.raises(ValueError, match="reward_weights must sum to 1.0"):
        RewardWeights(correctness=0.5, completeness=0.5, legibility=0.5)


# ---------------------------------------------------------------------------
# compute_legibility
# ---------------------------------------------------------------------------


def test_compute_legibility_perfect_factors_no_caps_returns_one() -> None:
    """Test 1 & 2: perfect factors + ratio=1.0 + crossings=5 -> 1.0."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(threshold_ratio=2.0),
        crossings_floor_cap=CrossingsFloorCap(min_crossings=1),
    )
    critique = _make_critique({"density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0})
    cap_inputs = _make_cap_inputs(bbox=100.0, footprint=100.0, crossings=5)
    score = adapter.compute_legibility(critique, cap_inputs)
    assert score == pytest.approx(1.0)


def test_compute_legibility_compactness_cap_fires() -> None:
    """Test 3: ratio=3.0 -> CompactnessCap fires, score < 1.0."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(threshold_ratio=2.0),
        crossings_floor_cap=CrossingsFloorCap(min_crossings=1),
    )
    critique = _make_critique({"density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0})
    cap_inputs = _make_cap_inputs(bbox=300.0, footprint=100.0, crossings=5)
    score = adapter.compute_legibility(critique, cap_inputs)
    assert score < 1.0


def test_compute_legibility_crossings_floor_cap_fires() -> None:
    """Test 4: crossings=0 -> CrossingsFloorCap fires, score = 0.3 * base."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(threshold_ratio=2.0),
        crossings_floor_cap=CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3),
    )
    critique = _make_critique({"density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0})
    cap_inputs = _make_cap_inputs(bbox=100.0, footprint=100.0, crossings=0)
    score = adapter.compute_legibility(critique, cap_inputs)
    assert score == pytest.approx(0.3)


def test_compute_legibility_both_caps_compose_multiplicatively() -> None:
    """Test 5: both caps fire -> multipliers compose."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(threshold_ratio=2.0),
        crossings_floor_cap=CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3),
    )
    critique = _make_critique({"density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0})
    cap_inputs = _make_cap_inputs(bbox=300.0, footprint=100.0, crossings=0)
    score = adapter.compute_legibility(critique, cap_inputs)
    # base=1.0, compactness < 1.0, crossings=0.3 -> score < 0.3
    assert score < 0.3


# ---------------------------------------------------------------------------
# combine (D-03 multi-objective)
# ---------------------------------------------------------------------------


def test_combine_with_all_three_terms() -> None:
    """Test 6: 0.4*0.8 + 0.4*0.7 + 0.2*0.6 = 0.72."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
        weights=RewardWeights(),
        completeness_source="layout_result",
    )
    score = adapter.combine(correctness=0.8, completeness=0.7, legibility=0.6)
    assert score == pytest.approx(0.72)


def test_combine_completeness_source_none_folds_into_correctness() -> None:
    """Test 9: HI-110-05 — completeness_source='none' -> 0.8*correctness + 0.2*legibility."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
        weights=RewardWeights(),
        completeness_source="none",
    )
    # completeness=None ignored, weight folded into correctness (0.4+0.4=0.8)
    score = adapter.combine(correctness=0.5, completeness=None, legibility=1.0)
    expected = 0.8 * 0.5 + 0.2 * 1.0
    assert score == pytest.approx(expected)


def test_combine_completeness_source_layout_result_uses_value() -> None:
    """Test 10: completeness_source='layout_result' uses provided completeness value."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
        weights=RewardWeights(),
        completeness_source="layout_result",
    )
    score = adapter.combine(correctness=0.8, completeness=0.9, legibility=0.6)
    expected = 0.4 * 0.8 + 0.4 * 0.9 + 0.2 * 0.6
    assert score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_parses_d03_defaults() -> None:
    """Test 7 / Test 6: from_config parses config.json shape with D-03 defaults."""
    config = {
        "training": {
            "reward_weights": {"correctness": 0.4, "completeness": 0.4, "legibility": 0.2},
            "completeness_source": "none",
            "legibility_factor_weights": {
                "density": 0.25, "clarity": 0.25, "spacing": 0.25, "organization": 0.25,
            },
            "anti_hack": {
                "compactness_threshold_ratio": 2.0,
                "crossings_floor_min": 1,
                "crossings_floor_multiplier": 0.3,
            },
        }
    }
    adapter = LegibilityRewardAdapter.from_config(config)
    assert adapter.weights.correctness == 0.4
    assert adapter.weights.completeness == 0.4
    assert adapter.weights.legibility == 0.2
    assert adapter.completeness_source == "none"


# ---------------------------------------------------------------------------
# CR-110-01: CritiqueResult consumed directly
# ---------------------------------------------------------------------------


def test_compute_legibility_accepts_critique_result_directly() -> None:
    """Test 11: CR-110-01 — passes critique.factors_view() to LegibilityReward.score()."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
    )
    # Build a real-ish CritiqueResult mock — compute_legibility calls .factors_view()
    critique = MagicMock()
    critique.factors_view.return_value = MappingProxyType({
        "density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5,
    })
    critique.model_used = "gemma4"
    cap_inputs = _make_cap_inputs(bbox=100.0, footprint=100.0, crossings=5)
    score = adapter.compute_legibility(critique, cap_inputs)
    assert score == pytest.approx(0.5)
    critique.factors_view.assert_called_once()


# ---------------------------------------------------------------------------
# LO-110-11: malformed critique robustness
# ---------------------------------------------------------------------------


def test_compute_legibility_missing_factor_returns_zero_with_warning(caplog) -> None:
    """Test 12 / LO-110-11: missing factor -> KeyError caught -> 0.0, no crash."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
    )
    # Malformed: missing "spacing" key
    critique = MagicMock()
    critique.factors_view.return_value = MappingProxyType({
        "density": 0.5, "clarity": 0.5, "organization": 0.5,
    })
    critique.model_used = "gemma4"
    cap_inputs = _make_cap_inputs(bbox=100.0, footprint=100.0, crossings=5)

    score = adapter.compute_legibility(critique, cap_inputs)
    assert score == 0.0


def test_compute_legibility_out_of_range_factor_returns_zero() -> None:
    """LO-110-11 extension: factor > 1.0 -> ValueError caught -> 0.0."""
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
    )
    critique = MagicMock()
    critique.factors_view.return_value = MappingProxyType({
        "density": 1.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5,
    })
    critique.model_used = "claude"
    cap_inputs = _make_cap_inputs(bbox=100.0, footprint=100.0, crossings=5)

    score = adapter.compute_legibility(critique, cap_inputs)
    assert score == 0.0


# ---------------------------------------------------------------------------
# Phase 100 CR-01: adapter frozen
# ---------------------------------------------------------------------------


def test_legibility_reward_adapter_is_frozen() -> None:
    """Phase 100 CR-01: LegibilityRewardAdapter is frozen."""
    assert is_dataclass(LegibilityRewardAdapter)
    adapter = LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(),
        crossings_floor_cap=CrossingsFloorCap(),
    )
    with pytest.raises(Exception):
        adapter.completeness_source = "fixed_value"  # type: ignore[misc]
