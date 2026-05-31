"""Tests for evaluation regression detection (TRAIN-02).

Covers:
  - detect_regression flags reward/accuracy/pass_rate drops below thresholds
  - detect_regression returns is_regression=False for improvements
  - detect_regression returns is_regression=False for within-threshold changes
  - BaselineStore save/load round-trip
  - BaselineStore.compare_or_update saves improvement, keeps on regression
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_agent.training.evaluation import EvalResult
from kicad_agent.training.regression import (
    BaselineStore,
    RegressionResult,
    RegressionThresholds,
    detect_regression,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    reward: float = 0.5,
    accuracy: float = 0.6,
    pass_rate: float = 0.7,
) -> EvalResult:
    """Create a minimal EvalResult for testing."""
    return EvalResult(
        model_name="test_model",
        n_samples=100,
        avg_reward=reward,
        avg_accuracy=accuracy,
        coordinate_coverage=0.8,
        chain_length_mean=10.0,
        chain_length_std=2.0,
        pass_rate=pass_rate,
        discrimination_gap=0.0,
    )


# ---------------------------------------------------------------------------
# detect_regression tests
# ---------------------------------------------------------------------------


class TestDetectRegression:
    """Regression detection against configurable thresholds."""

    def test_regression_reward_drop(self) -> None:
        """Reward drop > 0.05 flags regression."""
        baseline = _make_result(reward=0.80)
        current = _make_result(reward=0.70)
        result = detect_regression(baseline, current)
        assert result.is_regression is True
        assert any("reward" in r.lower() for r in result.regressions)

    def test_regression_accuracy_drop(self) -> None:
        """Accuracy drop > 0.10 flags regression."""
        baseline = _make_result(accuracy=0.80)
        current = _make_result(accuracy=0.60)
        result = detect_regression(baseline, current)
        assert result.is_regression is True
        assert any("accuracy" in r.lower() for r in result.regressions)

    def test_regression_pass_rate_drop(self) -> None:
        """Pass rate drop > 0.05 flags regression."""
        baseline = _make_result(pass_rate=0.80)
        current = _make_result(pass_rate=0.60)
        result = detect_regression(baseline, current)
        assert result.is_regression is True
        assert any("pass rate" in r.lower() for r in result.regressions)

    def test_no_regression_on_improvement(self) -> None:
        """Improved metrics do not flag regression."""
        baseline = _make_result(reward=0.50, accuracy=0.50, pass_rate=0.50)
        current = _make_result(reward=0.70, accuracy=0.70, pass_rate=0.70)
        result = detect_regression(baseline, current)
        assert result.is_regression is False
        assert result.regressions == []

    def test_no_regression_within_threshold(self) -> None:
        """Small changes within thresholds do not flag regression."""
        baseline = _make_result(reward=0.50, accuracy=0.50, pass_rate=0.50)
        current = _make_result(reward=0.48, accuracy=0.47, pass_rate=0.48)
        result = detect_regression(baseline, current)
        assert result.is_regression is False
        assert result.regressions == []

    def test_deltas_computed(self) -> None:
        """Deltas are computed and included in result."""
        baseline = _make_result(reward=0.80, accuracy=0.80, pass_rate=0.80)
        current = _make_result(reward=0.60, accuracy=0.60, pass_rate=0.60)
        result = detect_regression(baseline, current)
        assert abs(result.deltas["reward"] - (-0.20)) < 0.001
        assert abs(result.deltas["accuracy"] - (-0.20)) < 0.001
        assert abs(result.deltas["pass_rate"] - (-0.20)) < 0.001

    def test_custom_thresholds(self) -> None:
        """Custom thresholds are respected."""
        baseline = _make_result(reward=0.50)
        current = _make_result(reward=0.44)
        # Drop of 0.06 exceeds default 0.05
        result_default = detect_regression(baseline, current)
        assert result_default.is_regression is True
        # But with threshold 0.10, it's within range
        thresholds = RegressionThresholds(max_reward_drop=0.10)
        result_loose = detect_regression(baseline, current, thresholds=thresholds)
        assert result_loose.is_regression is False

    def test_result_contains_baseline_and_current(self) -> None:
        """Result references the original baseline and current."""
        baseline = _make_result()
        current = _make_result()
        result = detect_regression(baseline, current)
        assert result.baseline is baseline
        assert result.current is current


# ---------------------------------------------------------------------------
# BaselineStore tests
# ---------------------------------------------------------------------------


class TestBaselineStore:
    """Baseline persistence and comparison."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Round-trip save/load preserves EvalResult."""
        store = BaselineStore(store_dir=tmp_path)
        result = _make_result(reward=0.75, accuracy=0.65, pass_rate=0.85)
        store.save_baseline("v1", result)

        loaded = store.load_baseline("v1")
        assert loaded is not None
        assert loaded.avg_reward == result.avg_reward
        assert loaded.avg_accuracy == result.avg_accuracy
        assert loaded.pass_rate == result.pass_rate

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        """Loading a nonexistent baseline returns None."""
        store = BaselineStore(store_dir=tmp_path)
        assert store.load_baseline("nonexistent") is None

    def test_compare_or_update_saves_improvement(self, tmp_path: Path) -> None:
        """Improved metrics save current as new baseline."""
        store = BaselineStore(store_dir=tmp_path)
        baseline = _make_result(reward=0.50, accuracy=0.50, pass_rate=0.50)
        store.save_baseline("model_a", baseline)

        improved = _make_result(reward=0.70, accuracy=0.60, pass_rate=0.60)
        result = store.compare_or_update("model_a", improved)

        assert result.is_regression is False
        # Current should now be saved as new baseline
        loaded = store.load_baseline("model_a")
        assert loaded is not None
        assert loaded.avg_reward == 0.70

    def test_compare_or_update_keeps_on_regression(self, tmp_path: Path) -> None:
        """Regressed metrics keep old baseline unchanged."""
        store = BaselineStore(store_dir=tmp_path)
        baseline = _make_result(reward=0.80, accuracy=0.80, pass_rate=0.80)
        store.save_baseline("model_b", baseline)

        worse = _make_result(reward=0.50, accuracy=0.50, pass_rate=0.50)
        result = store.compare_or_update("model_b", worse)

        assert result.is_regression is True
        # Baseline should remain unchanged
        loaded = store.load_baseline("model_b")
        assert loaded is not None
        assert loaded.avg_reward == 0.80

    def test_compare_or_update_no_existing_baseline(self, tmp_path: Path) -> None:
        """First run with no existing baseline saves current."""
        store = BaselineStore(store_dir=tmp_path)
        current = _make_result(reward=0.60)
        result = store.compare_or_update("new_model", current)

        assert result.is_regression is False
        loaded = store.load_baseline("new_model")
        assert loaded is not None
        assert loaded.avg_reward == 0.60
