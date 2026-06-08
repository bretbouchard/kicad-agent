#!/usr/bin/env python3
"""Train Gemma 4 vision adapter for KiCad PCB analysis.

Converts existing text training data to vision format (PCB images + reasoning chains)
and runs LoRA fine-tuning via mlx-vlm with chunked restart.

Usage:
    # Convert training data to vision format
    python3 scripts/train_kicad_vision.py --convert --input training_output/gemma_sft_data/train.jsonl --pcb-dir qa/data/pcbnew

    # Run training (requires mlx-vlm)
    python3 scripts/train_kicad_vision.py --train --data training_output/vision_data

    # Full pipeline: convert + train
    python3 scripts/train_kicad_vision.py --convert --input data/train.jsonl --pcb-dir qa/data --train
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_DEFAULT_MODEL = "ggml-org/gemma-4-12B-it-Q4_K_M"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gemma 4 vision training for KiCad PCB analysis.",
    )

    # Convert mode
    parser.add_argument("--convert", action="store_true", help="Convert text JSONL to vision dataset")
    parser.add_argument("--input", type=Path, help="Input JSONL file (ChatML format)")
    parser.add_argument("--pcb-dir", type=Path, help="Directory of PCB files for rendering")
    parser.add_argument("--output-dir", type=Path, default=Path("training_output/vision_data"))
    parser.add_argument("--max-samples", type=int, default=None, help="Max samples to convert")

    # Train mode
    parser.add_argument("--train", action="store_true", help="Run LoRA training on vision data")
    parser.add_argument("--data", type=Path, default=Path("training_output/vision_data"))
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--chunk-size", type=int, default=50)

    args = parser.parse_args()

    if not args.convert and not args.train:
        parser.print_help()
        return 1

    if args.convert:
        if not args.input:
            print("Error: --input required for --convert", file=sys.stderr)
            return 1

        from kicad_agent.training.vision_data_builder import build_vision_dataset

        print(f"Converting {args.input} to vision dataset...")
        count = build_vision_dataset(
            input_jsonl=args.input,
            output_dir=args.output_dir,
            pcb_dir=args.pcb_dir,
            max_samples=args.max_samples,
        )
        print(f"Converted {count} samples to {args.output_dir}")

    if args.train:
        from kicad_agent.training.vision_lora_trainer import (
            KiCadVisionSFTConfig,
            run_kicad_vision_lora,
        )

        config = KiCadVisionSFTConfig(
            model=args.model,
            data=args.data,
            lora_layers=args.lora_rank,
            batch_size=args.batch_size,
            learning_rate=args.lr,
            max_steps=args.max_steps,
            chunk_size=args.chunk_size,
        )

        print(f"Training Gemma 4 vision adapter...")
        print(f"  Model: {config.model}")
        print(f"  Data:  {config.data}")
        print(f"  Steps: {config.max_steps}")
        print(f"  Chunks: {config.chunk_size} steps each")

        try:
            result = run_kicad_vision_lora(config)
            print(f"\nTraining complete:")
            print(f"  Total steps: {result['total_steps']}")
            print(f"  Chunks: {result['chunks_completed']}")
            print(f"  Checkpoint: {result['checkpoint_path']}")
        except FileNotFoundError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            return 1
        except ImportError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            print("Install mlx-vlm: pip install mlx-vlm==0.6.2", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
