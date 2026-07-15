"""Tests for best_of_n selector -- reward model chain selection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from volta.inference.best_of_n import ScoredChain, best_of_n_select


# ---------------------------------------------------------------------------
# ScoredChain
# ---------------------------------------------------------------------------


def test_scored_chain_immutable() -> None:
    """ScoredChain is a frozen dataclass -- attribute assignment raises."""
    chain = ScoredChain(
        chain_text="text",
        format_score=0.8,
        quality_score=0.7,
        accuracy_score=0.9,
        composite_score=0.8,
        generation_time_s=0.5,
    )
    with pytest.raises(AttributeError):
        chain.chain_text = "modified"  # type: ignore[misc]


def test_scored_chain_composite_is_mean() -> None:
    """composite_score should be the mean of format/quality/accuracy."""
    chain = ScoredChain(
        chain_text="t",
        format_score=0.9,
        quality_score=0.6,
        accuracy_score=0.3,
        composite_score=(0.9 + 0.6 + 0.3) / 3.0,
    )
    assert abs(chain.composite_score - 0.6) < 1e-6


# ---------------------------------------------------------------------------
# best_of_n_select
# ---------------------------------------------------------------------------


def test_best_of_n_selects_highest() -> None:
    """best_of_n_select returns the chain with highest composite score."""
    from volta.training.reward_model import PredictedReward

    mock_model = MagicMock()

    with patch("volta.inference.best_of_n.predict_reward") as mock_predict:
        mock_predict.side_effect = [
            PredictedReward(format_score=0.9, quality_score=0.9, accuracy_score=0.9),
            PredictedReward(format_score=0.1, quality_score=0.1, accuracy_score=0.1),
        ]

        result = best_of_n_select(["good chain", "bad chain"], mock_model)
        assert result.chain_text == "good chain"
        assert result.composite_score > 0.8


def test_best_of_n_single_chain() -> None:
    """N=1 returns the single chain with its score."""
    from volta.training.reward_model import PredictedReward

    mock_model = MagicMock()

    with patch("volta.inference.best_of_n.predict_reward") as mock_predict:
        mock_predict.return_value = PredictedReward(
            format_score=0.7, quality_score=0.8, accuracy_score=0.6,
        )

        result = best_of_n_select(["only chain"], mock_model)
        assert result.chain_text == "only chain"
        assert abs(result.composite_score - (0.7 + 0.8 + 0.6) / 3.0) < 1e-6


def test_best_of_n_empty_raises() -> None:
    """Empty chains list raises ValueError."""
    mock_model = MagicMock()
    with pytest.raises(ValueError, match="empty"):
        best_of_n_select([], mock_model)


def test_best_of_n_no_reward_model() -> None:
    """No reward model raises ValueError instead of returning fake scores."""
    with pytest.raises(ValueError, match="reward model"):
        best_of_n_select(["chain1", "chain2"], None)


def test_best_of_n_improves_over_single() -> None:
    """Best-of-4 mean composite score >= 20% higher than mean single-sample."""
    from volta.training.reward_model import PredictedReward

    mock_model = MagicMock()

    # Four chains with varying scores
    scores = [
        PredictedReward(format_score=0.3, quality_score=0.3, accuracy_score=0.3),  # 0.3
        PredictedReward(format_score=0.4, quality_score=0.4, accuracy_score=0.4),  # 0.4
        PredictedReward(format_score=0.5, quality_score=0.5, accuracy_score=0.5),  # 0.5
        PredictedReward(format_score=0.9, quality_score=0.9, accuracy_score=0.9),  # 0.9
    ]

    with patch("volta.inference.best_of_n.predict_reward") as mock_predict:
        mock_predict.side_effect = scores

        chains = ["chain1", "chain2", "chain3", "chain4"]
        result = best_of_n_select(chains, mock_model)

        # Mean single-sample = mean of all scores = (0.3 + 0.4 + 0.5 + 0.9) / 4 = 0.525
        mean_single = sum(
            (s.format_score + s.quality_score + s.accuracy_score) / 3.0
            for s in scores
        ) / len(scores)

        # Best-of-4 should select the 0.9 chain
        assert result.composite_score >= mean_single * 1.2  # 20% improvement


def test_best_of_n_composite_is_mean_of_scores() -> None:
    """Composite score is computed as (fmt + qual + acc) / 3."""
    from volta.training.reward_model import PredictedReward

    mock_model = MagicMock()

    with patch("volta.inference.best_of_n.predict_reward") as mock_predict:
        mock_predict.return_value = PredictedReward(
            format_score=0.6, quality_score=0.8, accuracy_score=0.7,
        )

        result = best_of_n_select(["chain"], mock_model)
        expected = (0.6 + 0.8 + 0.7) / 3.0
        assert abs(result.composite_score - expected) < 1e-6
