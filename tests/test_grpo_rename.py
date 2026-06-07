"""Tests for GRPO -> AdvantageWeighted rename (Plan 78-02).

Verifies:
1. New class names exist and import correctly
2. Old names are backward-compatible aliases (identity check)
3. kl_coefficient removed from new config
4. clip_range does not exist on new config
5. AdvantageWeightedTrainer accepts AdvantageWeightedConfig
6. grpo_trainer.py (GRPOLoopTrainer) unchanged
7. All consumer imports still work via aliases
8. Config has expected fields after rename
"""

from __future__ import annotations

import importlib


def test_advantage_weighted_config_import():
    """New name AdvantageWeightedConfig must be importable."""
    from kicad_agent.training.grpo import AdvantageWeightedConfig
    assert AdvantageWeightedConfig is not None


def test_advantage_weighted_trainer_import():
    """New name AdvantageWeightedTrainer must be importable."""
    from kicad_agent.training.grpo import AdvantageWeightedTrainer
    assert AdvantageWeightedTrainer is not None


def test_grpo_config_is_alias():
    """Old GRPOConfig must be an alias (same identity) as AdvantageWeightedConfig."""
    from kicad_agent.training.grpo import GRPOConfig, AdvantageWeightedConfig
    assert GRPOConfig is AdvantageWeightedConfig


def test_grpo_trainer_is_alias():
    """Old GRPOTrainer must be an alias (same identity) as AdvantageWeightedTrainer."""
    from kicad_agent.training.grpo import GRPOTrainer, AdvantageWeightedTrainer
    assert GRPOTrainer is AdvantageWeightedTrainer


def test_no_kl_coefficient():
    """AdvantageWeightedConfig must not have kl_coefficient attribute."""
    from kicad_agent.training.grpo import AdvantageWeightedConfig
    cfg = AdvantageWeightedConfig()
    assert not hasattr(cfg, "kl_coefficient"), (
        "kl_coefficient should be removed from AdvantageWeightedConfig"
    )


def test_no_clip_range():
    """AdvantageWeightedConfig must not have clip_range attribute."""
    from kicad_agent.training.grpo import AdvantageWeightedConfig
    cfg = AdvantageWeightedConfig()
    assert not hasattr(cfg, "clip_range"), (
        "clip_range should not exist on AdvantageWeightedConfig"
    )


def test_trainer_accepts_new_config():
    """AdvantageWeightedTrainer.__init__ accepts AdvantageWeightedConfig."""
    from kicad_agent.training.grpo import AdvantageWeightedConfig, AdvantageWeightedTrainer

    cfg = AdvantageWeightedConfig(seed=123)
    trainer = AdvantageWeightedTrainer(None, None, None, config=cfg)
    assert trainer.config is cfg
    assert trainer.config.seed == 123


def test_grpo_trainer_module_unchanged():
    """grpo_trainer.py GRPOLoopTrainer must still be importable and unchanged."""
    from kicad_agent.training.grpo_trainer import GRPOLoopTrainer
    assert GRPOLoopTrainer is not None
    # Verify it still has the expected method
    assert hasattr(GRPOLoopTrainer, "compute_advantage_weights")


def test_config_has_expected_fields():
    """AdvantageWeightedConfig must have all expected fields except removed ones."""
    from kicad_agent.training.grpo import AdvantageWeightedConfig
    cfg = AdvantageWeightedConfig()
    # Fields that should exist
    assert hasattr(cfg, "learning_rate")
    assert hasattr(cfg, "group_size")
    assert hasattr(cfg, "max_generation_length")
    assert hasattr(cfg, "temperature")
    assert hasattr(cfg, "seed")
    assert hasattr(cfg, "checkpoint_every")
    assert hasattr(cfg, "output_dir")
    assert hasattr(cfg, "lr_schedule")
    assert hasattr(cfg, "warmup_steps")
    assert hasattr(cfg, "total_steps")
    # Check default values
    assert cfg.learning_rate == 1e-5
    assert cfg.group_size == 8
    assert cfg.seed == 42


def test_consumer_import_grpo_trainer():
    """Consumer import of GRPOTrainer via alias must work (placement/training/train.py)."""
    from kicad_agent.training.grpo import GRPOTrainer
    # Just importing is enough -- the alias is what consumers use
    assert GRPOTrainer is not None


def test_consumer_import_grpo_config():
    """Consumer import of GRPOConfig via alias must work (smoke_test.py)."""
    from kicad_agent.training.grpo import GRPOConfig
    assert GRPOConfig is not None


def test_trainer_defaults_to_new_config():
    """AdvantageWeightedTrainer without config arg defaults to AdvantageWeightedConfig."""
    from kicad_agent.training.grpo import AdvantageWeightedTrainer, AdvantageWeightedConfig
    trainer = AdvantageWeightedTrainer(None, None, None)
    assert isinstance(trainer.config, AdvantageWeightedConfig)
