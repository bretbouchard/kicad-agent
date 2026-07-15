"""Tests for training pipeline modules: chains, dataset, evaluator."""

import pytest


class TestChainsModule:
    """Tests for training chains."""

    def test_import(self):
        """Training chains module is importable."""
        from volta.training.chains import MazeReasoningChain
        assert MazeReasoningChain is not None


class TestDatasetModule:
    """Tests for training dataset."""

    def test_import(self):
        """Dataset module is importable."""
        from volta.training.dataset import MazeDataset
        assert MazeDataset is not None


class TestEvaluatorModule:
    """Tests for training evaluator."""

    def test_import(self):
        """Evaluator module is importable."""
        from volta.training.evaluation import EvaluationHarness
        assert EvaluationHarness is not None


class TestGeneratorModule:
    """Tests for training generator."""

    def test_import(self):
        """Generator module is importable."""
        from volta.training import generator
        assert generator is not None


class TestPipelineModule:
    """Tests for training pipeline."""

    def test_import(self):
        """Pipeline module is importable."""
        from volta.training.pipeline import TrainingPipelineConfig
        assert TrainingPipelineConfig is not None


class TestGrpoModule:
    """Tests for GRPO training module."""

    def test_import(self):
        """GRPO module is importable."""
        from volta.training.grpo import AdvantageWeightedTrainer
        assert AdvantageWeightedTrainer is not None


class TestGrpoConfig:
    """Tests for GRPO config."""

    def test_import(self):
        """GRPOTrainingConfig is importable."""
        from volta.training.grpo_config import GRPOTrainingConfig
        assert GRPOTrainingConfig is not None


class TestRewardModel:
    """Tests for reward model."""

    def test_import(self):
        """RewardModel is importable."""
        from volta.training.reward_model import RewardModel
        assert RewardModel is not None
