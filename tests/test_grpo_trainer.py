"""Tests for GRPO training loop (ReST-style with group-relative advantages).

Tests cover:
  - GRPOTrainingConfig defaults
  - compute_advantage_weights (uniform, ranked)
  - filter_by_advantages (top-K fraction)
  - build_chatml_prompt (ChatML format)
  - KL penalty non-negativity
"""

from __future__ import annotations

import math

import pytest

from kicad_agent.training.grpo_config import GRPOTrainingConfig
from kicad_agent.training.grpo_trainer import GRPOLoopTrainer


class TestGRPOTrainingConfig:
    """Test GRPOTrainingConfig default values."""

    def test_config_defaults(self):
        """GRPOTrainingConfig defaults match spec."""
        config = GRPOTrainingConfig()
        assert config.model_name == "Qwen/Qwen2.5-0.5B-Instruct"
        assert config.adapter_path == "training_output/sft"
        assert config.reward_model_dir == "training_output/unified"
        assert config.train_data_path == "training_output/sft_data/train.jsonl"
        assert config.output_dir == "training_output/grpo_v2"
        assert config.n_iterations == 3
        assert config.group_size == 4
        assert config.filter_top_k == 0.5
        assert config.max_prompts_per_iter == 200
        assert config.sft_iters_per_round == 500
        assert config.learning_rate == 5e-6
        assert config.max_gen_tokens == 512
        assert config.gen_temperature == 0.8
        assert config.kl_coefficient == 0.1
        assert config.clip_range == 0.2
        assert config.lora_rank == 16
        assert config.lora_scale == 32.0
        assert config.lora_layers == 16
        assert config.max_seq_length == 1024
        assert config.batch_size == 1
        assert config.seed == 42


class TestAdvantageWeights:
    """Test compute_advantage_weights."""

    def test_advantage_weights_uniform(self):
        """Uniform scores produce uniform weights (summing to group_size)."""
        config = GRPOTrainingConfig(group_size=4, clip_range=0.2, kl_coefficient=0.1)
        trainer = GRPOLoopTrainer(config)
        scores = [0.5, 0.5, 0.5, 0.5]
        weights = trainer.compute_advantage_weights(scores)
        # Uniform scores: all raw advantages = 0, clipped to 0, KL penalty = 0
        # shifted = eps for all, normalized to group_size
        assert len(weights) == 4
        assert abs(sum(weights) - len(weights)) < 0.01  # sums to group_size

    def test_advantage_weights_ranked(self):
        """Higher scores get higher weights."""
        config = GRPOTrainingConfig(group_size=4, clip_range=0.2, kl_coefficient=0.1)
        trainer = GRPOLoopTrainer(config)
        scores = [0.1, 0.3, 0.5, 0.9]
        weights = trainer.compute_advantage_weights(scores)
        assert len(weights) == 4
        # The highest score should have the highest weight
        assert weights[3] > weights[0]
        # Weights should sum to group_size
        assert abs(sum(weights) - len(scores)) < 0.01

    def test_advantage_weights_with_kl_penalty(self):
        """KL penalty reduces all weights proportionally."""
        config = GRPOTrainingConfig(group_size=4, clip_range=0.2, kl_coefficient=0.5)
        trainer = GRPOLoopTrainer(config)
        scores = [0.1, 0.3, 0.5, 0.9]
        weights_no_kl = trainer.compute_advantage_weights(scores, kl_penalty=0.0)
        weights_with_kl = trainer.compute_advantage_weights(scores, kl_penalty=1.0)
        # With KL penalty, relative ordering should still hold
        assert weights_with_kl[3] > weights_with_kl[0]
        # Weights should still sum to group_size
        assert abs(sum(weights_with_kl) - len(scores)) < 0.01


class TestFilterByAdvantages:
    """Test filter_by_advantages."""

    def test_filter_by_advantages(self):
        """filter_by_advantages keeps top fraction of samples by advantage."""
        config = GRPOTrainingConfig(group_size=4, filter_top_k=0.5)
        trainer = GRPOLoopTrainer(config)
        # 2 prompts, each with 4 completions
        prompt_completions = [
            {
                "prompt": "test prompt 1",
                "completions": [
                    {"text": "comp 1a", "score": 0.9},
                    {"text": "comp 1b", "score": 0.1},
                    {"text": "comp 1c", "score": 0.5},
                    {"text": "comp 1d", "score": 0.3},
                ],
            },
            {
                "prompt": "test prompt 2",
                "completions": [
                    {"text": "comp 2a", "score": 0.8},
                    {"text": "comp 2b", "score": 0.2},
                    {"text": "comp 2c", "score": 0.6},
                    {"text": "comp 2d", "score": 0.4},
                ],
            },
        ]
        filtered = trainer.filter_by_advantages(prompt_completions)
        # With filter_top_k=0.5 and group_size=4, should keep top 2 per prompt
        # Total: 2 prompts * 2 kept = 4 filtered samples
        assert len(filtered) == 4
        # Each filtered sample should have messages and advantage_weight
        for item in filtered:
            assert "messages" in item
            assert "advantage_weight" in item
            assert item["advantage_weight"] > 0


class TestBuildChatMLPrompt:
    """Test build_chatml_prompt."""

    def test_build_chatml_prompt(self):
        """build_chatml_prompt produces valid ChatML with im_start/im_end markers."""
        messages = [
            {"role": "system", "content": "You are a PCB expert."},
            {"role": "user", "content": "Analyze this board."},
            {"role": "assistant", "content": "Analysis follows."},
        ]
        prompt = GRPOLoopTrainer.build_chatml_prompt(messages)
        assert "<|im_start|>system\n" in prompt
        assert "<|im_end|>" in prompt
        assert "<|im_start|>user\n" in prompt
        assert "<|im_start|>assistant\n" in prompt
        assert "You are a PCB expert." in prompt
        assert "Analyze this board." in prompt

    def test_build_chatml_prompt_generation(self):
        """build_chatml_prompt for generation ends with assistant start."""
        messages = [
            {"role": "system", "content": "You are a PCB expert."},
            {"role": "user", "content": "Analyze this board."},
        ]
        prompt = GRPOLoopTrainer.build_chatml_prompt(messages)
        assert prompt.endswith("<|im_start|>assistant\n")


class TestKLPenalty:
    """Test KL divergence penalty properties."""

    def test_kl_penalty_non_negative(self):
        """KL penalty is non-negative and zero for identical distributions."""
        config = GRPOTrainingConfig()
        trainer = GRPOLoopTrainer(config)

        # Identical distributions -> KL should be zero
        logprobs = [-1.0, -2.0, -0.5, -3.0]
        kl_identical = trainer.compute_kl_penalty(logprobs, logprobs)
        assert kl_identical >= 0.0
        assert kl_identical == pytest.approx(0.0, abs=1e-6)

        # Different distributions -> KL should be non-negative
        policy_logprobs = [-1.0, -2.0, -0.5, -3.0]
        ref_logprobs = [-0.5, -1.5, -1.0, -2.5]
        kl_different = trainer.compute_kl_penalty(policy_logprobs, ref_logprobs)
        assert kl_different >= 0.0

        # Empty lists -> KL should be zero
        kl_empty = trainer.compute_kl_penalty([], [])
        assert kl_empty == 0.0
