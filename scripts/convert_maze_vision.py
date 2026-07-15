#!/usr/bin/env python3
"""Convert maze routing chains to HuggingFace vision training dataset."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volta.training.maze_vision_converter import build_maze_vision_dataset


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert maze routing chains to HuggingFace vision training dataset.",
    )
    parser.add_argument(
        "--chains-file",
        type=Path,
        required=True,
        help="Path to chains_100k.jsonl",
    )
    parser.add_argument(
        "--maze-samples-file",
        type=Path,
        required=True,
        help="Path to maze_samples_100k.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/maze_vision_data"),
        help="Output directory for maze vision dataset",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Max samples to convert (None = all)",
    )
    args = parser.parse_args()

    if not args.chains_file.exists():
        print(f"Error: chains file not found: {args.chains_file}", file=sys.stderr)
        return 1
    if not args.maze_samples_file.exists():
        print(f"Error: maze samples file not found: {args.maze_samples_file}", file=sys.stderr)
        return 1

    print(f"Converting maze chains to vision format...")
    print(f"  Chains: {args.chains_file}")
    print(f"  Maze samples: {args.maze_samples_file}")
    print(f"  Output: {args.output_dir}")

    count = build_maze_vision_dataset(
        chains_file=args.chains_file,
        maze_samples_file=args.maze_samples_file,
        output_dir=args.output_dir,
        max_samples=args.max_samples,
    )

    print(f"\nConversion complete: {count} samples converted")
    print(f"Dataset saved to: {args.output_dir / 'train'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
