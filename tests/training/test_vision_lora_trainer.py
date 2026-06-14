"""Tests for Vision LoRA Trainer (Plan 03)."""

from __future__ import annotations

import argparse
import pytest
import pydantic
from pathlib import Path

from kicad_agent.training.vision_lora_trainer import (
    KiCadVisionSFTConfig,
    _build_lora_args,
)


class TestKiCadVisionSFTConfig:
    """Vision SFT config validation tests."""

    def test_default_config(self):
        config = KiCadVisionSFTConfig()
        assert config.model == "mlx-community/gemma-4-12B-it-8bit"
        assert config.lora_layers == 16
        assert config.batch_size == 1
        assert config.learning_rate == 1e-5
        assert config.max_steps == 500
        assert config.chunk_size == 50
        assert config.grad_checkpoint is True

    def test_custom_config(self):
        config = KiCadVisionSFTConfig(
            model="custom-model",
            lora_layers=8,
            max_steps=1000,
        )
        assert config.model == "custom-model"
        assert config.lora_layers == 8
        assert config.max_steps == 1000

    def test_frozen(self):
        config = KiCadVisionSFTConfig()
        with pytest.raises(pydantic.ValidationError):
            config.model = "other"

    def test_extra_forbid(self):
        with pytest.raises(pydantic.ValidationError):
            KiCadVisionSFTConfig(nonexistent="bad")


class TestBuildLoraArgs:
    """mlx-vlm argument namespace construction tests."""

    def test_basic_args(self):
        config = KiCadVisionSFTConfig()
        args = _build_lora_args(config, chunk_steps=50, adapter_path=None, output_path="/tmp/out")

        assert isinstance(args, argparse.Namespace)
        assert args.model_path == config.model
        assert args.batch_size == 1
        assert args.iters == 50
        assert args.lora_rank == 16
        assert args.grad_checkpoint is True
        assert args.adapter_path is None
        assert args.output_path == "/tmp/out"

    def test_resume_args(self):
        config = KiCadVisionSFTConfig()
        args = _build_lora_args(
            config,
            chunk_steps=25,
            adapter_path="/tmp/chunk-0",
            output_path="/tmp/chunk-1",
        )
        assert args.adapter_path == "/tmp/chunk-0"
        assert args.iters == 25

    def test_chunk_steps_less_than_max(self):
        config = KiCadVisionSFTConfig(max_steps=100, chunk_size=50)
        args = _build_lora_args(config, chunk_steps=50, adapter_path=None, output_path="/out")
        assert args.iters == 50
