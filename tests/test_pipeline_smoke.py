"""Tests for training pipeline smoke tests (TRAIN-03).

Covers: SFT smoke test convergence, GRPO smoke test completion, timing, skip guard.
"""

import time

import pytest

from volta.training.smoke_test import run_sft_smoke_test, run_grpo_smoke_test


def _torch_available() -> bool:
    try:
        import torch
        return True
    except ImportError:
        return False


# Skip all tests if PyTorch not installed
pytestmark = pytest.mark.skipif(
    not _torch_available(),
    reason="PyTorch not installed",
)


@pytest.mark.slow
class TestSftSmoke:
    """SFT smoke test: train RewardModel on 10 synthetic samples, 2 epochs."""

    def test_sft_smoke_completes(self) -> None:
        """SFT smoke test runs and returns completed=True."""
        result = run_sft_smoke_test()
        assert result["completed"] is True
        assert result["n_samples"] == 10
        assert result["n_epochs"] == 2

    def test_sft_smoke_loss_decreases(self) -> None:
        """SFT smoke test verifies loss decreases (convergence signal)."""
        result = run_sft_smoke_test()
        assert result["initial_loss"] > 0
        assert result["final_loss"] < result["initial_loss"], (
            f"Loss did not decrease: initial={result['initial_loss']:.4f}, "
            f"final={result['final_loss']:.4f}"
        )

    def test_sft_smoke_under_60s(self) -> None:
        """SFT smoke test completes in under 60 seconds on CPU."""
        start = time.time()
        run_sft_smoke_test()
        elapsed = time.time() - start
        assert elapsed < 60, f"SFT smoke test took {elapsed:.1f}s (limit: 60s)"


@pytest.mark.slow
class TestGrpoSmoke:
    """GRPO smoke test: run training loop end-to-end without error."""

    def test_grpo_smoke_completes(self) -> None:
        """GRPO smoke test runs and returns completed=True."""
        result = run_grpo_smoke_test()
        assert result["completed"] is True
        assert result["n_samples"] == 10
        assert result["n_epochs"] == 1

    def test_grpo_smoke_under_60s(self) -> None:
        """GRPO smoke test completes in under 60 seconds on CPU."""
        start = time.time()
        run_grpo_smoke_test()
        elapsed = time.time() - start
        assert elapsed < 60, f"GRPO smoke test took {elapsed:.1f}s (limit: 60s)"
