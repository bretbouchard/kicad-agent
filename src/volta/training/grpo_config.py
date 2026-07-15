"""GRPO training configuration for RL fine-tuning.

Phase 21: Configuration dataclass for the GRPO ReST-style training loop.
Defines all hyperparameters for generation, scoring, filtering, and retraining.

Usage:
    from volta.training.grpo_config import GRPOTrainingConfig

    config = GRPOTrainingConfig(n_iterations=3, group_size=4)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GRPOTrainingConfig:
    """Configuration for GRPO RL fine-tuning.

    Attributes:
        model_name: Base model identifier for mlx-lm.
        adapter_path: Path to SFT-trained LoRA adapter directory.
        reward_model_dir: Path to trained reward model directory.
        train_data_path: Path to ChatML training data JSONL.
        output_dir: Directory for GRPO training outputs.
        n_iterations: Number of ReST iterations (generate-score-retrain cycles).
        group_size: Number of completions generated per prompt per iteration.
        filter_top_k: Fraction of top completions to keep (0.5 = top half).
        max_prompts_per_iter: Maximum prompts sampled per iteration.
        sft_iters_per_round: SFT training iterations per ReST round.
        learning_rate: Learning rate for SFT re-training.
        max_gen_tokens: Maximum tokens per generated completion.
        gen_temperature: Sampling temperature for generation.
        kl_coefficient: KL divergence penalty coefficient.
        clip_range: PPO-style clipping range for advantage weighting.
        lora_rank: LoRA adapter rank.
        lora_scale: LoRA adapter scale.
        lora_layers: Number of LoRA layers.
        max_seq_length: Maximum sequence length for training.
        batch_size: Training batch size.
        seed: Deterministic random seed.
    """

    model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"
    adapter_path: str = "training_output/sft"
    reward_model_dir: str = "training_output/unified"
    train_data_path: str = "training_output/sft_data/train.jsonl"
    output_dir: str = "training_output/grpo_v2"
    n_iterations: int = 3
    group_size: int = 4
    filter_top_k: float = 0.5
    max_prompts_per_iter: int = 200
    sft_iters_per_round: int = 500
    learning_rate: float = 5e-6
    max_gen_tokens: int = 512
    gen_temperature: float = 0.8
    kl_coefficient: float = 0.1
    clip_range: float = 0.2
    lora_rank: int = 16
    lora_scale: float = 32.0
    lora_layers: int = 16
    max_seq_length: int = 1024
    batch_size: int = 1
    seed: int = 42
