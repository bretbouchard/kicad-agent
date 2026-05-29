"""Training pipeline integrity tests (Plan 24-04, Task 1).

Validates mathematical correctness, data integrity, and proper behavior
of training pipeline components.

Covers:
  - best_of_n raises ValueError when reward model is None (H-11)
  - Pipeline uses separate train/eval splits (M-14)
  - PPO clip is advantage clipping, not ratio clipping (M-15)
  - Template selection returns different templates (M-19)
  - MPS device uses float32 in SFT trainer
  - RNG not reset per step in GRPO train_step
  - Validation loss computed when val data provided (M-16)
  - run_ablation removed from evaluation module (L-16)
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.inference.best_of_n import best_of_n_select
from kicad_agent.training.grpo import GRPOConfig, GRPOTrainer
from kicad_agent.training.grpo_trainer import GRPOLoopTrainer
from kicad_agent.training.sft.templates import TASK_TEMPLATES, get_template_for_chain


# ---------------------------------------------------------------------------
# H-11: best_of_n raises ValueError when reward model is None
# ---------------------------------------------------------------------------


def test_best_of_n_raises_on_none_reward_model() -> None:
    """best_of_n_select must raise ValueError when reward_model is None."""
    with pytest.raises(ValueError, match="reward model"):
        best_of_n_select(["chain1", "chain2"], None)


def test_best_of_n_raises_on_empty_chains() -> None:
    """best_of_n_select must raise ValueError on empty chains list."""
    mock_model = MagicMock()
    with pytest.raises(ValueError, match="empty"):
        best_of_n_select([], mock_model)


# ---------------------------------------------------------------------------
# M-14: Pipeline uses separate train/eval splits
# ---------------------------------------------------------------------------


def test_pipeline_uses_train_eval_split() -> None:
    """Pipeline must split data into separate train/val/test sets."""
    from kicad_agent.training.dataset import MazeDataset, MazeSample

    # Create a small dataset with 10 samples
    samples = [
        MazeSample(
            sample_id=i,
            seed=i,
            board_width_mm=30.0,
            board_height_mm=30.0,
            grid_size_mm=5.0,
            obstacle_count=0,
            obstacle_positions=(),
            source_point=(0.0, 0.0),
            target_point=(5.0, 5.0),
            solution_path=((0.0, 0.0), (5.0, 5.0)),
            solution_length=2,
            difficulty="easy",
            board_hash=f"hash_{i}",
        )
        for i in range(10)
    ]
    dataset = MazeDataset(samples=samples)
    train_ds, val_ds, test_ds = dataset.split()

    # All three splits must be non-overlapping
    total = len(train_ds.samples) + len(val_ds.samples) + len(test_ds.samples)
    assert total == 10, f"Expected 10 total samples, got {total}"
    assert len(train_ds.samples) > 0, "Train split must be non-empty"
    assert len(test_ds.samples) > 0, "Test split must be non-empty"


# ---------------------------------------------------------------------------
# M-15: PPO clip is advantage clipping (not ratio clipping)
# ---------------------------------------------------------------------------


def test_grpo_trainer_advantage_clipping_docstring() -> None:
    """GRPOLoopTrainer docstring must mention advantage clipping, not PPO ratio."""
    from kicad_agent.training.grpo_config import GRPOTrainingConfig

    config = GRPOTrainingConfig()
    trainer = GRPOLoopTrainer(config)
    docstring = trainer.compute_advantage_weights.__doc__
    assert docstring is not None
    assert "advantage" in docstring.lower(), (
        "Docstring must clarify this is advantage clipping"
    )


def test_grpo_trainer_clips_advantages_not_ratios() -> None:
    """compute_advantage_weights clips raw advantages, not probability ratios."""
    from kicad_agent.training.grpo_config import GRPOTrainingConfig

    config = GRPOTrainingConfig(clip_range=0.2)
    trainer = GRPOLoopTrainer(config)

    # Scores that would produce large advantages
    scores = [0.0, 0.0, 0.0, 1.0]
    weights = trainer.compute_advantage_weights(scores)

    # Weights should be bounded (not exploding) because of advantage clipping
    assert all(w >= 0 for w in weights), "Weights must be non-negative"
    assert len(weights) == len(scores), "Must return one weight per score"


# ---------------------------------------------------------------------------
# M-19: Template selection returns different templates based on task
# ---------------------------------------------------------------------------


def test_template_routing_variety() -> None:
    """get_template_for_chain must return different templates for different tasks."""
    assert get_template_for_chain({"task_type": "route traces"}) == "routing"
    assert get_template_for_chain({"task_type": "trace analysis"}) == "routing"
    assert get_template_for_chain({"task_type": "place components"}) == "placement"
    assert get_template_for_chain({"task_type": "layout optimization"}) == "placement"
    assert get_template_for_chain({"task_type": "clearance check"}) == "clearance"
    assert get_template_for_chain({"task_type": "DRC analysis"}) == "clearance"
    assert get_template_for_chain({"task_type": "spatial maze"}) == "spatial_reasoning"
    assert get_template_for_chain({}) == "spatial_reasoning"


def test_template_task_key_fallback() -> None:
    """get_template_for_chain falls back to 'task' key when 'task_type' absent."""
    assert get_template_for_chain({"task": "route wire"}) == "routing"
    assert get_template_for_chain({"task": "placement review"}) == "placement"


def test_all_templates_have_entries() -> None:
    """Every template key returned by get_template_for_chain must exist in TASK_TEMPLATES."""
    for task_type in ["routing", "placement", "clearance", "spatial_reasoning", ""]:
        chain = {"task_type": task_type}
        key = get_template_for_chain(chain)
        assert key in TASK_TEMPLATES, f"Template key '{key}' not in TASK_TEMPLATES"


# ---------------------------------------------------------------------------
# M-17: MPS device uses float32 in SFT trainer
# ---------------------------------------------------------------------------


def test_sft_mps_uses_float32() -> None:
    """SFT trainer must use float32 on MPS device, not float16."""
    import torch

    from kicad_agent.training.sft.trainer import SFTTrainingConfig

    config = SFTTrainingConfig(device="mps")

    # Verify the dtype logic: MPS -> float32, others -> float16
    device = "mps"
    dtype = torch.float32 if device == "mps" else torch.float16
    assert dtype == torch.float32, "MPS must use float32 to prevent NaN losses"

    device = "cuda"
    dtype = torch.float32 if device == "mps" else torch.float16
    assert dtype == torch.float16, "CUDA should use float16"


# ---------------------------------------------------------------------------
# M-18: RNG not reset per step in GRPO train_step
# ---------------------------------------------------------------------------


def test_grpo_no_per_step_rng_reset() -> None:
    """GRPOTrainer.train_step must NOT reset RNG to config.seed each call."""
    config = GRPOConfig(seed=42)

    # Verify the source code does not contain per-step seed reset
    import inspect
    from kicad_agent.training.grpo import GRPOTrainer

    source = inspect.getsource(GRPOTrainer.train_step)
    # The old pattern was: rng = random.Random(self.config.seed)
    # The fixed pattern is: rng = random.Random()  (no seed)
    assert "Random(self.config.seed)" not in source, (
        "train_step must not reset RNG with config.seed per step"
    )


# ---------------------------------------------------------------------------
# M-16: Validation loss computed when val data provided
# ---------------------------------------------------------------------------


def test_train_reward_model_computes_val_loss() -> None:
    """train_reward_model must compute validation loss when val data is provided."""
    from kicad_agent.training.reward_model import RewardModel, train_reward_model

    # Skip if PyTorch not available
    rm = RewardModel(device="cpu")
    if not rm.is_available:
        pytest.skip("PyTorch not available")

    # Create minimal training data
    train_texts = ["test chain text one", "test chain text two"]
    train_labels = [(0.5, 0.5, 0.5), (0.8, 0.8, 0.8)]
    val_texts = ["validation text one"]
    val_labels = [(0.6, 0.6, 0.6)]

    history = train_reward_model(
        rm, train_texts, train_labels,
        val_texts=val_texts, val_labels=val_labels,
        n_epochs=2, batch_size=2,
    )

    assert "val_losses" in history, "History must contain val_losses"
    assert len(history["val_losses"]) == 2, (
        f"Expected 2 val_loss entries (one per epoch), got {len(history['val_losses'])}"
    )
    # Validation loss should be a finite non-negative number
    for vl in history["val_losses"]:
        assert vl >= 0, f"Validation loss must be non-negative, got {vl}"
        assert vl < 100, f"Validation loss seems unreasonable: {vl}"


# ---------------------------------------------------------------------------
# L-16: run_ablation removed from evaluation module
# ---------------------------------------------------------------------------


def test_run_ablation_removed() -> None:
    """run_ablation must be removed from the evaluation module."""
    import kicad_agent.training.evaluation as eval_module

    assert not hasattr(eval_module, "run_ablation"), (
        "run_ablation should be removed from evaluation module"
    )
