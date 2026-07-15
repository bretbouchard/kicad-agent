"""Unit tests for LegibilityReward weighted-sum reward (Plan 01 Task 1, D-01)."""
from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock

import pytest

from volta.training.rewards.legibility import LegibilityReward


def test_perfect_factors_returns_one() -> None:
    """Test 1: all factors 1.0 -> reward 1.0."""
    reward = LegibilityReward().score({"density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0})
    assert reward == pytest.approx(1.0)


def test_zero_factors_returns_zero() -> None:
    """Test 2: all factors 0.0 -> reward 0.0."""
    reward = LegibilityReward().score({"density": 0.0, "clarity": 0.0, "spacing": 0.0, "organization": 0.0})
    assert reward == pytest.approx(0.0)


def test_mixed_factors_returns_weighted_sum() -> None:
    """Test 3: 0.8/0.6/0.4/0.2 -> 0.5 exactly."""
    reward = LegibilityReward().score({
        "density": 0.8, "clarity": 0.6, "spacing": 0.4, "organization": 0.2,
    })
    assert reward == pytest.approx(0.5)


def test_missing_factor_raises_keyerror_naming_factor() -> None:
    """Test 4: missing density key raises KeyError naming the factor."""
    with pytest.raises(KeyError) as exc_info:
        LegibilityReward().score({"clarity": 0.5, "spacing": 0.5, "organization": 0.5})
    assert "density" in str(exc_info.value)


def test_weights_configurable_and_recompute_correctly() -> None:
    """Test 5: custom weights change the result correctly."""
    reward = LegibilityReward(weights={"density": 0.4, "clarity": 0.2, "spacing": 0.2, "organization": 0.2})
    score = reward.score({"density": 1.0, "clarity": 0.0, "spacing": 0.0, "organization": 0.0})
    assert score == pytest.approx(0.4)


def test_weights_not_summing_to_one_raises_valueerror() -> None:
    """Test 5b: weights must sum to 1.0 (training stability guard)."""
    with pytest.raises(ValueError, match="weights must sum to 1.0"):
        LegibilityReward(weights={"density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5})


def test_default_weights_are_uniform_quarter() -> None:
    """Test 6: default weights are exactly 0.25 each per D-01."""
    reward = LegibilityReward()
    assert reward.weights == {"density": 0.25, "clarity": 0.25, "spacing": 0.25, "organization": 0.25}


def test_factor_above_one_raises_valueerror() -> None:
    """Test 7a: factor > 1.0 raises ValueError (input contract)."""
    with pytest.raises(ValueError, match="must be in \\[0.0, 1.0\\]"):
        LegibilityReward().score({"density": 1.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5})


def test_factor_below_zero_raises_valueerror() -> None:
    """Test 7b: factor < 0.0 raises ValueError (input contract)."""
    with pytest.raises(ValueError, match="must be in \\[0.0, 1.0\\]"):
        LegibilityReward().score({"density": -0.1, "clarity": 0.5, "spacing": 0.5, "organization": 0.5})


def test_accepts_critique_result_factors_view_mappingproxytype() -> None:
    """Test 8: LegibilityReward accepts CritiqueResult.factors_view() (MappingProxyType)."""
    # Build a fake CritiqueResult-like object exposing factors_view()
    fake_critique = MagicMock()
    fake_critique.factors_view.return_value = MappingProxyType({
        "density": 0.7, "clarity": 0.6, "spacing": 0.8, "organization": 0.5,
    })
    reward = LegibilityReward().score(fake_critique.factors_view())
    expected = 0.25 * (0.7 + 0.6 + 0.8 + 0.5)
    assert reward == pytest.approx(expected)


def test_legibility_reward_is_frozen_dataclass() -> None:
    """Phase 100 CR-01: LegibilityReward must be frozen."""
    reward = LegibilityReward()
    with pytest.raises(Exception):
        reward.weights = {"density": 0.1, "clarity": 0.1, "spacing": 0.1, "organization": 0.7}  # type: ignore[misc]
