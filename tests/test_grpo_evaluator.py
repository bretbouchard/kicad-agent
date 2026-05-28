"""Tests for GRPO evaluation metrics.

Tests cover:
  - Discrimination rate range and boundaries
  - Perfect discrimination (all correct > corrupted)
  - SFT vs GRPO comparison returns delta keys
  - Model evaluation returns all three reward dimensions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.training.grpo_evaluator import (
    compare_sft_vs_grpo,
    evaluate_grpo_model,
    run_discrimination_test,
)


def _mock_reward_model():
    """Create a mock RewardModel that doesn't touch disk."""
    mock_rm = MagicMock()
    mock_rm.is_available = True
    return mock_rm


class TestDiscriminationRateRange:
    """Test discrimination_rate is between 0 and 1."""

    @patch("kicad_agent.training.grpo_evaluator.RewardModel")
    @patch("kicad_agent.training.grpo_evaluator.predict_reward")
    @patch("kicad_agent.training.grpo_evaluator._generate_text_with_adapter")
    @patch("kicad_agent.training.grpo_evaluator._load_chatml_prompts")
    def test_rate_in_range(
        self, mock_load, mock_generate, mock_predict, mock_rm_cls,
    ):
        """discrimination_rate is between 0 and 1 with fixed scores."""
        mock_rm_cls.load_trained.return_value = _mock_reward_model()
        mock_load.return_value = [
            {"prompt": "test prompt 1", "messages": [{"role": "user", "content": "hello"}]},
            {"prompt": "test prompt 2", "messages": [{"role": "user", "content": "world"}]},
        ]
        mock_generate.return_value = "Generated completion text"
        # Correct scores slightly higher than corrupted
        mock_predict.side_effect = [
            # Sample 1: correct
            MagicMock(format_score=0.6, quality_score=0.6, accuracy_score=0.6),
            # Sample 1: corrupted
            MagicMock(format_score=0.4, quality_score=0.4, accuracy_score=0.4),
            # Sample 2: correct
            MagicMock(format_score=0.5, quality_score=0.5, accuracy_score=0.5),
            # Sample 2: corrupted
            MagicMock(format_score=0.5, quality_score=0.5, accuracy_score=0.5),
        ]
        result = run_discrimination_test(
            adapter_path="/fake/adapter",
            reward_model_dir="/fake/reward",
            test_data_path="/fake/test.jsonl",
            n_samples=2,
        )
        assert 0.0 <= result["discrimination_rate"] <= 1.0
        assert result["n_tested"] == 2


class TestDiscriminationPerfect:
    """Test perfect discrimination when correct always scores higher."""

    @patch("kicad_agent.training.grpo_evaluator.RewardModel")
    @patch("kicad_agent.training.grpo_evaluator.predict_reward")
    @patch("kicad_agent.training.grpo_evaluator._generate_text_with_adapter")
    @patch("kicad_agent.training.grpo_evaluator._load_chatml_prompts")
    def test_perfect_discrimination(
        self, mock_load, mock_generate, mock_predict, mock_rm_cls,
    ):
        """discrimination_rate is 1.0 when correct always scores higher."""
        mock_rm_cls.load_trained.return_value = _mock_reward_model()
        mock_load.return_value = [
            {"prompt": "test 1", "messages": [{"role": "user", "content": "hello"}]},
            {"prompt": "test 2", "messages": [{"role": "user", "content": "world"}]},
            {"prompt": "test 3", "messages": [{"role": "user", "content": "foo"}]},
        ]
        mock_generate.return_value = "Generated text"
        # Correct always scores 0.9, corrupted always 0.1
        mock_predict.side_effect = [
            MagicMock(format_score=0.9, quality_score=0.9, accuracy_score=0.9),
            MagicMock(format_score=0.1, quality_score=0.1, accuracy_score=0.1),
            MagicMock(format_score=0.9, quality_score=0.9, accuracy_score=0.9),
            MagicMock(format_score=0.1, quality_score=0.1, accuracy_score=0.1),
            MagicMock(format_score=0.9, quality_score=0.9, accuracy_score=0.9),
            MagicMock(format_score=0.1, quality_score=0.1, accuracy_score=0.1),
        ]
        result = run_discrimination_test(
            adapter_path="/fake/adapter",
            reward_model_dir="/fake/reward",
            test_data_path="/fake/test.jsonl",
            n_samples=3,
        )
        assert result["discrimination_rate"] == 1.0


class TestCompareReturnsDeltas:
    """Test compare_sft_vs_grpo returns delta keys for each dimension."""

    @patch("kicad_agent.training.grpo_evaluator.run_discrimination_test")
    @patch("kicad_agent.training.grpo_evaluator.evaluate_grpo_model")
    def test_compare_deltas(self, mock_evaluate, mock_discrimination):
        """compare_sft_vs_grpo returns delta_reward, delta_format, delta_quality, delta_accuracy."""
        mock_evaluate.side_effect = [
            {  # SFT results
                "avg_reward": 0.5,
                "avg_format": 0.5,
                "avg_quality": 0.5,
                "avg_accuracy": 0.5,
                "n_samples": 10,
                "sample_outputs": [],
            },
            {  # GRPO results
                "avg_reward": 0.7,
                "avg_format": 0.7,
                "avg_quality": 0.7,
                "avg_accuracy": 0.7,
                "n_samples": 10,
                "sample_outputs": [],
            },
        ]
        mock_discrimination.return_value = {
            "discrimination_rate": 0.9,
            "n_tested": 10,
        }
        result = compare_sft_vs_grpo(
            sft_adapter_path="/fake/sft",
            grpo_adapter_path="/fake/grpo",
            test_data_path="/fake/test.jsonl",
            reward_model_dir="/fake/reward",
            n_samples=10,
        )
        assert "delta_reward" in result
        assert "delta_format" in result
        assert "delta_quality" in result
        assert "delta_accuracy" in result
        assert "grpo_wins_all_dimensions" in result
        # GRPO is higher on all, so deltas should be positive
        assert result["delta_reward"] > 0
        assert result["grpo_wins_all_dimensions"] is True


class TestEvaluateReturnsDimensions:
    """Test evaluate_grpo_model returns all three reward dimensions."""

    @patch("kicad_agent.training.grpo_evaluator.RewardModel")
    @patch("kicad_agent.training.grpo_evaluator.predict_reward")
    @patch("kicad_agent.training.grpo_evaluator._generate_text_with_adapter")
    @patch("kicad_agent.training.grpo_evaluator._load_chatml_prompts")
    def test_evaluate_dimensions(
        self, mock_load, mock_generate, mock_predict, mock_rm_cls,
    ):
        """evaluate_grpo_model returns avg_format, avg_quality, avg_accuracy."""
        mock_rm_cls.load_trained.return_value = _mock_reward_model()
        mock_load.return_value = [
            {"prompt": "test 1", "messages": [{"role": "user", "content": "hello"}]},
        ]
        mock_generate.return_value = "Generated completion text"
        mock_predict.return_value = MagicMock(
            format_score=0.8, quality_score=0.7, accuracy_score=0.6,
        )
        result = evaluate_grpo_model(
            adapter_path="/fake/adapter",
            test_data_path="/fake/test.jsonl",
            reward_model_dir="/fake/reward",
            n_samples=1,
        )
        assert "avg_format" in result
        assert "avg_quality" in result
        assert "avg_accuracy" in result
        assert "avg_reward" in result
        assert "n_samples" in result
        assert result["avg_format"] == pytest.approx(0.8, abs=0.01)
        assert result["avg_quality"] == pytest.approx(0.7, abs=0.01)
        assert result["avg_accuracy"] == pytest.approx(0.6, abs=0.01)
        assert result["avg_reward"] == pytest.approx(0.7, abs=0.01)
