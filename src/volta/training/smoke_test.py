"""Smoke tests for training pipeline (SFT + GRPO).

TRAIN-03: Minimal end-to-end tests that verify the training loop
completes without error on tiny synthetic data. Uses CPU-only with
the 4-layer RewardModel (d_model=256).

Usage:
    from volta.training.smoke_test import run_sft_smoke_test, run_grpo_smoke_test

    result = run_sft_smoke_test()
    assert result["completed"]
    assert result["final_loss"] < result["initial_loss"]
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _torch_available() -> bool:
    """Check if PyTorch is installed."""
    try:
        import torch
        return True
    except ImportError:
        return False


def run_sft_smoke_test(output_dir: Path | None = None) -> dict:
    """Run SFT smoke test: train RewardModel on 10 synthetic samples, 2 epochs.

    Generates a tiny MazeDataset, scores chains, trains the RewardModel
    with supervised MSE loss, and verifies loss decreases.

    Args:
        output_dir: Optional directory for outputs. Uses tempdir if None.

    Returns:
        Dict with completed, initial_loss, final_loss, n_samples, n_epochs.

    Raises:
        ImportError: If PyTorch is not installed.
    """
    if not _torch_available():
        raise ImportError("PyTorch is required for smoke tests")

    from volta.training.chains import synthesize_maze_chain
    from volta.training.dataset import generate_dataset
    from volta.training.reward import RewardConfig, score_chain
    from volta.training.reward_model import RewardModel, train_reward_model
    from volta.training.tokenizer import ChainTokenizer

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="smoke_sft_"))

    n_samples = 10
    n_epochs = 2

    # Generate tiny dataset with one small board config
    dataset = generate_dataset(
        n_samples=n_samples,
        seed_base=42,
        board_configs=[{"width_mm": 30.0, "height_mm": 30.0, "grid_size_mm": 5.0}],
    )

    # Split
    train_ds, val_ds, _ = dataset.split(train=0.8, val=0.1, test=0.1)

    # Score training samples
    reward_config = RewardConfig()
    train_texts: list[str] = []
    train_labels: list[tuple[float, float, float]] = []

    for sample in train_ds.samples:
        chain = synthesize_maze_chain(sample)
        chain_reward = score_chain(chain, sample, reward_config)
        train_texts.append(chain.chain_text)
        fmt_avg = sum(sr.format_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        qual_avg = sum(sr.quality_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        acc_avg = sum(sr.accuracy_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        train_labels.append((fmt_avg, qual_avg, acc_avg))

    # Score validation samples
    val_texts: list[str] = []
    val_labels: list[tuple[float, float, float]] = []
    for sample in val_ds.samples:
        chain = synthesize_maze_chain(sample)
        chain_reward = score_chain(chain, sample, reward_config)
        val_texts.append(chain.chain_text)
        fmt_avg = sum(sr.format_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        qual_avg = sum(sr.quality_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        acc_avg = sum(sr.accuracy_score for sr in chain_reward.step_rewards) / max(len(chain_reward.step_rewards), 1)
        val_labels.append((fmt_avg, qual_avg, acc_avg))

    # Train tokenizer
    tokenizer = ChainTokenizer(vocab_size=500)
    tokenizer.train(train_texts)

    # Create and train model
    model = RewardModel(device="cpu")
    model.set_tokenizer(tokenizer)

    history = train_reward_model(
        model,
        train_texts,
        train_labels,
        val_texts=val_texts if val_texts else None,
        val_labels=val_labels if val_labels else None,
        n_epochs=n_epochs,
        learning_rate=1e-3,
        batch_size=5,
    )

    losses = history.get("losses", [])
    initial_loss = losses[0] if losses else 0.0
    final_loss = losses[-1] if losses else 0.0

    logger.info(
        "SFT smoke test complete: initial_loss=%.4f, final_loss=%.4f, n_samples=%d",
        initial_loss, final_loss, n_samples,
    )

    return {
        "completed": True,
        "initial_loss": initial_loss,
        "final_loss": final_loss,
        "n_samples": n_samples,
        "n_epochs": n_epochs,
    }


def run_grpo_smoke_test(output_dir: Path | None = None) -> dict:
    """Run GRPO smoke test: train loop on 10 synthetic samples, 1 epoch.

    Generates a tiny dataset, creates GRPOTrainer with minimal settings,
    and runs the training loop for 1 epoch. Validates the loop runs
    without error (tiny data is insufficient for meaningful improvement).

    Args:
        output_dir: Optional directory for outputs. Uses tempdir if None.

    Returns:
        Dict with completed, n_samples, n_epochs.

    Raises:
        ImportError: If PyTorch is not installed.
    """
    if not _torch_available():
        raise ImportError("PyTorch is required for smoke tests")

    from volta.training.dataset import generate_dataset
    from volta.training.grpo import GRPOConfig, GRPOTrainer
    from volta.training.reward_model import RewardModel
    from volta.training.tokenizer import ChainTokenizer

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="smoke_grpo_"))

    n_samples = 10
    n_epochs = 1

    # Generate tiny dataset
    dataset = generate_dataset(
        n_samples=n_samples,
        seed_base=42,
        board_configs=[{"width_mm": 30.0, "height_mm": 30.0, "grid_size_mm": 5.0}],
    )

    # Create models
    policy_model = RewardModel(device="cpu")
    reward_model = RewardModel(device="cpu")
    ref_model = RewardModel(device="cpu")

    # Configure GRPO with minimal settings
    config = GRPOConfig(
        group_size=2,
        seed=42,
        learning_rate=1e-3,
        output_dir=str(output_dir),
    )

    trainer = GRPOTrainer(
        policy_model=policy_model,
        reward_model=reward_model,
        ref_model=ref_model,
        config=config,
    )

    # Run training for 1 epoch
    history = trainer.train(dataset, n_epochs=n_epochs, batch_size=5)

    logger.info(
        "GRPO smoke test complete: n_samples=%d, n_epochs=%d, steps=%d",
        n_samples, n_epochs, len(history.get("losses", [])),
    )

    return {
        "completed": True,
        "n_samples": n_samples,
        "n_epochs": n_epochs,
    }
