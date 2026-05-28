"""SFT training wrapper for Qwen2.5-1.5B-Instruct with LoRA on Apple MPS.

Provides MPS-compatible training configuration and a run_sft_training()
function that handles the full SFT pipeline: model loading, LoRA setup,
dataset preparation, training, and saving.

Usage:
    from kicad_agent.training.sft.trainer import run_sft_training, SFTTrainingConfig

    config = SFTTrainingConfig()
    result = run_sft_training(config)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SFTTrainingConfig:
    """Configuration for SFT training on Apple MPS.

    Attributes:
        model_name: HuggingFace model identifier.
        output_dir: Directory to save trained adapter and tokenizer.
        train_data_path: Path to ChatML-formatted training JSONL.
        val_data_path: Path to ChatML-formatted validation JSONL.
        num_train_epochs: Number of training epochs.
        per_device_train_batch_size: Batch size per device.
        learning_rate: Peak learning rate.
        max_length: Maximum sequence length for packing.
        lora_r: LoRA rank.
        lora_alpha: LoRA alpha (scaling factor).
        lora_dropout: LoRA dropout rate.
        warmup_ratio: Fraction of steps for learning rate warmup.
        logging_steps: Log every N steps.
        seed: Random seed for reproducibility.
        device: Device override ("auto", "mps", "cuda", "cpu").
    """

    model_name: str = "Qwen/Qwen2.5-1.5B-Instruct"
    output_dir: str = "training_output/sft_final"
    train_data_path: str = "training_output/sft_prepared/train.jsonl"
    val_data_path: str = "training_output/sft_prepared/val.jsonl"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 4
    learning_rate: float = 2e-4
    max_length: int = 512
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    warmup_ratio: float = 0.1
    logging_steps: int = 10
    seed: int = 42
    device: str = "auto"


def _get_device(config: SFTTrainingConfig) -> str:
    """Detect best available device.

    Args:
        config: Training config with device field.

    Returns:
        Device string: "mps", "cuda", or "cpu".
    """
    if config.device != "auto":
        return config.device

    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _build_lora_config(config: SFTTrainingConfig):
    """Create LoRA configuration from training config.

    Args:
        config: Training config with LoRA parameters.

    Returns:
        LoraConfig instance.
    """
    from peft import LoraConfig, TaskType

    return LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )


def _build_sft_config(config: SFTTrainingConfig):
    """Create SFTConfig with MPS-safe settings.

    Key MPS constraints:
    - fp16=False and bf16=False (ValueError on MPS otherwise)
    - dataloader_pin_memory=False (MPS does not support pinned memory)
    - max_length (not max_seq_length, removed in trl 1.0+)

    Args:
        config: Training config with training parameters.

    Returns:
        SFTConfig instance.
    """
    from trl import SFTConfig

    return SFTConfig(
        output_dir=config.output_dir,
        num_train_epochs=config.num_train_epochs,
        per_device_train_batch_size=config.per_device_train_batch_size,
        learning_rate=config.learning_rate,
        max_length=config.max_length,
        fp16=False,
        bf16=False,
        dataloader_pin_memory=False,
        packing=False,
        warmup_ratio=config.warmup_ratio,
        logging_steps=config.logging_steps,
        seed=config.seed,
        save_strategy="epoch",
        eval_strategy="epoch",
        report_to="none",
    )


def _prepare_dataset(data_path: str, tokenizer) -> list[dict]:
    """Load JSONL and format messages into text field using chat template.

    Args:
        data_path: Path to JSONL file with "messages" field.
        tokenizer: HuggingFace tokenizer with apply_chat_template.

    Returns:
        List of dicts with "text" field containing ChatML-formatted text.
    """
    records: list[dict] = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            messages = record.get("messages", [])
            if not messages:
                continue
            text = tokenizer.apply_chat_template(messages, tokenize=False)
            records.append({"text": text})
    return records


def run_sft_training(config: SFTTrainingConfig | None = None) -> dict:
    """Run the full SFT training pipeline.

    Loads the base model, applies LoRA adapters, trains on ChatML data,
    and saves the adapter and tokenizer.

    Args:
        config: Training configuration. Uses defaults if None.

    Returns:
        Dict with training history (loss per epoch).
    """
    import torch
    from datasets import Dataset
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTTrainer

    if config is None:
        config = SFTTrainingConfig()

    # Resolve device
    device = _get_device(config)
    print(f"Using device: {device}")

    # Load model
    print(f"Loading model: {config.model_name}")
    model = AutoModelForCausalLM.from_pretrained(
        config.model_name,
        torch_dtype=torch.float16,
        device_map=device,
    )

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(config.model_name)
    tokenizer.pad_token = tokenizer.eos_token

    # Build configs
    lora_config = _build_lora_config(config)
    sft_config = _build_sft_config(config)

    # Prepare datasets
    print(f"Loading training data from {config.train_data_path}")
    train_records = _prepare_dataset(config.train_data_path, tokenizer)
    train_dataset = Dataset.from_list(train_records)

    print(f"Loading validation data from {config.val_data_path}")
    val_records = _prepare_dataset(config.val_data_path, tokenizer)
    eval_dataset = Dataset.from_list(val_records) if val_records else None

    print(f"Training: {len(train_records)} samples, {len(val_records)} validation samples")

    # Create trainer
    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        peft_config=lora_config,
        processing_class=tokenizer,
    )

    # Train
    print("Starting SFT training...")
    trainer.train()

    # Save
    print(f"Saving adapter to {config.output_dir}")
    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
    trainer.save_model(config.output_dir)
    tokenizer.save_pretrained(config.output_dir)

    # Extract history
    history = {}
    if hasattr(trainer.state, "log_history"):
        history["log_history"] = trainer.state.log_history

    return history
