#!/usr/bin/env python3
"""SFT fine-tuning for Gemma 4 12B on PCB spatial reasoning data.

Trains a LoRA adapter on Gemma ChatML training data using mlx-lm.
Designed for Apple Silicon (8GB model fits in 16GB unified memory).

Output: training_output/gemma_sft/adapters.safetensors + adapter_config.json

Usage:
    python3 scripts/train_gemma_sft_mlx.py
    python3 scripts/train_gemma_sft_mlx.py --data-dir training_output/gemma_sft_data
    python3 scripts/train_gemma_sft_mlx.py --iters 1000 --lr 1e-5  # quick test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_GEMMA_MODEL_ID = "ggml-org/gemma-4-12B-it-Q4_K_M"

# LoRA layers to target in Gemma 4 12B.
_LORA_TARGET_MODULES = [
    "self_attn.q_proj",
    "self_attn.k_proj",
    "self_attn.v_proj",
    "self_attn.o_proj",
    "mlp.gate_proj",
    "mlp.up_proj",
    "mlp.down_proj",
]


def load_gemma_training_data(data_dir: Path) -> list[dict]:
    """Load training data from train.jsonl in Gemma ChatML format.

    Args:
        data_dir: Directory containing train.jsonl.

    Returns:
        List of training examples with 'messages' key.
    """
    train_path = data_dir / "train.jsonl"
    if not train_path.exists():
        raise FileNotFoundError(
            f"Training data not found at {train_path}. "
            f"Run generate_gap_training_data.py first."
        )

    examples = []
    with open(train_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if "messages" in record:
                examples.append(record)

    print(f"Loaded {len(examples)} training examples from {train_path}")
    return examples


def train_gemma_sft(
    data_dir: Path,
    output_dir: Path,
    model_id: str = _GEMMA_MODEL_ID,
    lora_rank: int = 32,
    lora_scale: float = 16.0,
    lora_layers: int = 16,
    batch_size: int = 1,
    lr: float = 5e-6,
    iters: int = 2000,
    max_seq_length: int = 1024,
    seed: int = 42,
) -> Path:
    """Run SFT fine-tuning on Gemma 4 12B.

    Args:
        data_dir: Directory with train.jsonl / val.jsonl.
        output_dir: Output directory for adapter files.
        model_id: HuggingFace model ID.
        lora_rank: LoRA rank.
        lora_scale: LoRA alpha scaling factor.
        lora_layers: Number of layers to apply LoRA.
        batch_size: Training batch size.
        lr: Learning rate.
        iters: Number of training iterations.
        max_seq_length: Maximum sequence length.
        seed: Random seed.

    Returns:
        Path to the output adapter directory.
    """
    import mlx.core as mx
    from mlx_lm import load
    from mlx_lm.tuner import datasets as mlx_datasets
    from mlx_lm.tuner import train as tuner_train
    from mlx_lm.tuner.trainer import TrainingArgs
    from mlx_lm.tuner.utils import linear_to_lora_layers

    # Load training data.
    examples = load_gemma_training_data(data_dir)

    # Load model.
    print(f"Loading model: {model_id}")
    model, tokenizer = load(model_id)

    # Apply LoRA.
    print(f"Applying LoRA: rank={lora_rank}, scale={lora_scale}, layers={lora_layers}")
    model = linear_to_lora_layers(
        model,
        _LORA_TARGET_MODULES,
        lora_rank,
        lora_scale,
    )

    # Freeze non-LoRA parameters.
    total_params = sum(v.size for v in model.trainable_parameters())
    print(f"Trainable parameters: {total_params:,}")

    # Create training dataset.
    # mlx-lm's ChatDataset expects list of {"messages": [...]}.
    train_dataset = mlx_datasets.ChatDataset(
        messages=[ex["messages"] for ex in examples],
        tokenizer=tokenizer,
        max_length=max_seq_length,
    )

    # Training arguments.
    output_dir.mkdir(parents=True, exist_ok=True)
    training_args = TrainingArgs(
        batch_size=batch_size,
        iters=iters,
        lr=lr,
        max_seq_length=max_seq_length,
        output_dir=str(output_dir),
        adapter_file=str(output_dir / "adapters.safetensors"),
    )

    # Configure optimizer.
    optimizer = None  # mlx-lm creates default AdamW

    start_time = time.time()

    # Train.
    print(f"\nStarting SFT training...")
    print(f"  Examples: {len(examples)}")
    print(f"  Batch size: {batch_size}")
    print(f"  Iterations: {iters}")
    print(f"  Learning rate: {lr}")
    print(f"  Max seq length: {max_seq_length}")

    tuner_train(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        dataset=train_dataset,
    )

    elapsed = time.time() - start_time
    print(f"\nTraining complete in {elapsed:.1f}s")
    print(f"Adapter saved to: {output_dir}")

    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SFT fine-tuning for Gemma 4 12B on PCB spatial reasoning.",
    )
    parser.add_argument("--model", default=_GEMMA_MODEL_ID)
    parser.add_argument("--data-dir", type=Path, default=Path("training_output/gemma_sft_data"))
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/gemma_sft"))
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--lora-scale", type=float, default=16.0)
    parser.add_argument("--lora-layers", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("Gemma 4 12B SFT Fine-Tuning")
    print(f"  Model: {args.model}")
    print(f"  Data:  {args.data_dir}")
    print(f"  Output: {args.output_dir}")

    try:
        train_gemma_sft(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            model_id=args.model,
            lora_rank=args.lora_rank,
            lora_scale=args.lora_scale,
            lora_layers=args.lora_layers,
            batch_size=args.batch_size,
            lr=args.lr,
            iters=args.iters,
            max_seq_length=args.max_seq_length,
            seed=args.seed,
        )
    except FileNotFoundError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        print("Run generate_gap_training_data.py first.", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        print("Install mlx-lm: pip install mlx-lm", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
