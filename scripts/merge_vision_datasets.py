#!/usr/bin/env python3
"""Merge maze vision and PCB vision datasets into unified HuggingFace dataset.

Combines two HuggingFace datasets (maze vision + PCB vision) created by
the maze vision converter and PCB vision data builder into a single
unified dataset suitable for LoRA fine-tuning.

Usage:
    python scripts/merge_vision_datasets.py \\
        --maze-dir training_output/maze_vision_data/train \\
        --pcb-dir training_output/vision_data/train \\
        --output-dir training_output/unified_vision_data/train

    # Smoke test with small subsets
    python scripts/merge_vision_datasets.py \\
        --maze-dir training_output/maze_vision_data/train \\
        --pcb-dir training_output/vision_data/train \\
        --maze-max 10 --pcb-max 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge maze + PCB vision datasets into unified HuggingFace dataset.",
    )
    parser.add_argument(
        "--maze-dir",
        type=Path,
        required=True,
        help="Path to maze vision dataset (HuggingFace save_to_disk format)",
    )
    parser.add_argument(
        "--pcb-dir",
        type=Path,
        required=True,
        help="Path to PCB vision dataset (HuggingFace save_to_disk format)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/unified_vision_data/train"),
        help="Output path for unified dataset",
    )
    # Council HIGH-2: smoke test flags for quick pipeline validation
    parser.add_argument(
        "--maze-max",
        type=int,
        default=None,
        help="Max maze samples to include (smoke test: 10)",
    )
    parser.add_argument(
        "--pcb-max",
        type=int,
        default=None,
        help="Max PCB samples to include (smoke test: 10)",
    )
    args = parser.parse_args()

    if not args.maze_dir.exists():
        print(f"Error: maze dataset not found: {args.maze_dir}", file=sys.stderr)
        return 1
    if not args.pcb_dir.exists():
        print(f"Error: PCB dataset not found: {args.pcb_dir}", file=sys.stderr)
        return 1

    try:
        from datasets import concatenate_datasets, load_from_disk
    except ImportError:
        print(
            "Error: datasets library not installed. Install with: pip install datasets",
            file=sys.stderr,
        )
        return 1

    print(f"Loading maze dataset from {args.maze_dir}...")
    maze_ds = load_from_disk(str(args.maze_dir))
    if args.maze_max and args.maze_max < len(maze_ds):
        maze_ds = maze_ds.select(range(args.maze_max))
        print(f"  Maze samples (subset): {len(maze_ds)}")
    else:
        print(f"  Maze samples: {len(maze_ds)}")

    print(f"Loading PCB dataset from {args.pcb_dir}...")
    pcb_ds = load_from_disk(str(args.pcb_dir))
    if args.pcb_max and args.pcb_max < len(pcb_ds):
        pcb_ds = pcb_ds.select(range(args.pcb_max))
        print(f"  PCB samples (subset): {len(pcb_ds)}")
    else:
        print(f"  PCB samples: {len(pcb_ds)}")

    print("Concatenating datasets...")
    unified_ds = concatenate_datasets([pcb_ds, maze_ds])
    print(f"  Unified total: {len(unified_ds)}")

    print(f"Saving unified dataset to {args.output_dir}...")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    unified_ds.save_to_disk(str(args.output_dir))

    print(f"\nMerge complete: {len(unified_ds)} samples")
    print(f"  ({len(pcb_ds)} PCB + {len(maze_ds)} maze)")
    print(f"Saved to: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
