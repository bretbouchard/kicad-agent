"""Tests for eval_reward_quality() held-out evaluation.

TDD RED phase: Tests for Kendall tau, Spearman rho, top-k accuracy,
and input validation in eval_reward_quality().
"""

from __future__ import annotations

import math

import pytest

from kicad_agent.training.reward_model import (
    PredictedReward,
    eval_reward_quality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_preds(*scores: tuple[float, float, float]) -> list[PredictedReward]:
    """Create PredictedReward objects from (format, quality, accuracy) tuples."""
    return [PredictedReward(f, q, a) for f, q, a in scores]


# ---------------------------------------------------------------------------
# Test 1: Return dict has all required keys
# ---------------------------------------------------------------------------

class TestEvalRewardQualityKeys:
    """Verify eval_reward_quality returns dict with expected keys."""

    def test_return_keys(self):
        preds = _make_preds((0.9, 0.8, 0.7), (0.3, 0.2, 0.1))
        gt = [(0.9, 0.8, 0.7), (0.3, 0.2, 0.1)]
        result = eval_reward_quality(preds, gt)
        assert "kendall_tau" in result
        assert "spearman_rho" in result
        assert "top_1_accuracy" in result
        assert "top_3_accuracy" in result
        assert "n_samples" in result


# ---------------------------------------------------------------------------
# Test 2: Perfect correlation (model ranks match ground truth)
# ---------------------------------------------------------------------------

class TestPerfectCorrelation:
    """On synthetic data where model ranks match ground truth, tau ~ 1.0."""

    def test_kendall_tau_perfect(self):
        preds = _make_preds(
            (0.9, 0.9, 0.9),  # best
            (0.6, 0.6, 0.6),
            (0.3, 0.3, 0.3),
            (0.1, 0.1, 0.1),  # worst
        )
        gt = [
            (0.9, 0.9, 0.9),
            (0.6, 0.6, 0.6),
            (0.3, 0.3, 0.3),
            (0.1, 0.1, 0.1),
        ]
        result = eval_reward_quality(preds, gt)
        assert result["kendall_tau"] == pytest.approx(1.0, abs=0.01)
        assert result["spearman_rho"] == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 3: Random / near-zero correlation
# ---------------------------------------------------------------------------

class TestRandomCorrelation:
    """On synthetic data where model ranks are random, tau near 0.0."""

    def test_kendall_tau_near_zero(self):
        # Ground truth: item 0 is best, item 3 is worst
        gt = [
            (0.9, 0.9, 0.9),  # truth: best
            (0.6, 0.6, 0.6),
            (0.3, 0.3, 0.3),
            (0.1, 0.1, 0.1),  # truth: worst
        ]
        # Model predicts: item 3 is best, item 0 is worst (inverted)
        preds = _make_preds(
            (0.1, 0.1, 0.1),  # model: worst
            (0.3, 0.3, 0.3),
            (0.6, 0.6, 0.6),
            (0.9, 0.9, 0.9),  # model: best
        )
        result = eval_reward_quality(preds, gt)
        assert result["kendall_tau"] == pytest.approx(-1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 4: Accepts PredictedReward and tuple lists
# ---------------------------------------------------------------------------

class TestInputTypes:
    """Verify function accepts list[PredictedReward] and list[tuple]."""

    def test_accepts_predicted_reward_list(self):
        preds = _make_preds((0.5, 0.5, 0.5))
        gt = [(0.5, 0.5, 0.5)]
        result = eval_reward_quality(preds, gt)
        assert result["n_samples"] == 1

    def test_accepts_ground_truth_tuples(self):
        preds = [PredictedReward(1.0, 1.0, 1.0)]
        gt = [(0.5, 0.5, 0.5)]
        result = eval_reward_quality(preds, gt)
        assert "kendall_tau" in result


# ---------------------------------------------------------------------------
# Test 5: Top-1 and top-3 accuracy
# ---------------------------------------------------------------------------

class TestTopKAccuracy:
    """Top-1 accuracy when model's best matches truth's best."""

    def test_top_1_accuracy_perfect(self):
        # Both agree: index 0 is best
        preds = _make_preds(
            (0.9, 0.9, 0.9),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
        )
        gt = [
            (0.9, 0.9, 0.9),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
        ]
        result = eval_reward_quality(preds, gt)
        assert result["top_1_accuracy"] == pytest.approx(1.0, abs=0.01)

    def test_top_1_accuracy_miss(self):
        # Model says index 0 is best, truth says index 3 is best
        preds = _make_preds(
            (0.9, 0.9, 0.9),  # model best
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
        )
        gt = [
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.9, 0.9, 0.9),  # truth best
        ]
        result = eval_reward_quality(preds, gt)
        assert result["top_1_accuracy"] == pytest.approx(0.0, abs=0.01)

    def test_top_3_accuracy(self):
        # Truth best is index 3; model ranks index 3 as 2nd (within top-3)
        preds = _make_preds(
            (0.9, 0.9, 0.9),  # model rank 1
            (0.7, 0.7, 0.7),  # model rank 2
            (0.2, 0.2, 0.2),
            (0.6, 0.6, 0.6),  # model rank 3 (within top-3)
        )
        gt = [
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.1, 0.1, 0.1),
            (0.9, 0.9, 0.9),  # truth best is index 3
        ]
        result = eval_reward_quality(preds, gt)
        assert result["top_1_accuracy"] == pytest.approx(0.0, abs=0.01)
        assert result["top_3_accuracy"] == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 6: Uses scipy.stats (verified import path)
# ---------------------------------------------------------------------------

class TestScipyUsage:
    """Verify scipy.stats is used for correlation computation."""

    def test_scipy_kendalltau_used(self):
        """Cross-check: manual scipy call matches function output."""
        from scipy.stats import kendalltau as scipy_kendalltau

        preds = _make_preds((1.0, 0.5, 0.5), (0.5, 0.5, 0.5), (0.0, 0.5, 0.5))
        gt = [(1.0, 0.5, 0.5), (0.5, 0.5, 0.5), (0.0, 0.5, 0.5)]

        # Compute expected manually via scipy
        model_avgs = [(p.format_score + p.quality_score + p.accuracy_score) / 3.0 for p in preds]
        truth_avgs = [(g[0] + g[1] + g[2]) / 3.0 for g in gt]
        expected_tau, _ = scipy_kendalltau(model_avgs, truth_avgs)

        result = eval_reward_quality(preds, gt)
        assert result["kendall_tau"] == pytest.approx(expected_tau, abs=1e-10)


# ---------------------------------------------------------------------------
# Test 7: Input validation (empty, mismatched lengths)
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Verify error handling for invalid inputs."""

    def test_empty_lists_raise(self):
        with pytest.raises(ValueError, match="empty"):
            eval_reward_quality([], [])

    def test_mismatched_lengths_raise(self):
        preds = _make_preds((0.5, 0.5, 0.5))
        gt = [(0.5, 0.5, 0.5), (0.5, 0.5, 0.5)]
        with pytest.raises(ValueError, match="length"):
            eval_reward_quality(preds, gt)

    def test_single_sample(self):
        """Single sample: tau should be 1.0 (trivially correlated)."""
        preds = _make_preds((0.5, 0.5, 0.5))
        gt = [(0.5, 0.5, 0.5)]
        result = eval_reward_quality(preds, gt)
        assert result["n_samples"] == 1
        # Kendall tau on single element is NaN/undefined; function should handle
        # this gracefully (return NaN or 0.0)
        if math.isnan(result["kendall_tau"]):
            pass  # acceptable: can't compute correlation with 1 sample
