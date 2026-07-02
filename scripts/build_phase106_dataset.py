#!/usr/bin/env python3
"""Phase 106: Build merged HF vision dataset for repoint training.

Merges the diagnostic SFT data (from generate_diagnostic_training_data.py)
with the existing unified vision dataset (142K maze + PCB spatial rows).

The diagnostic data teaches the model a NEW task type ("blocker_diagnosis")
alongside its existing capabilities. The model already knows how to process
board images from the existing 142K rows; we're teaching it to reason about
routing failures and recommend actions.

For the diagnostic rows (text-only, no board render): the messages column
is populated with the ChatML text, images is an empty list. The model can
still learn the reasoning pattern; in production it will receive board
renders via the AiRoutingStrategy image pipeline.

Usage:
    python3 scripts/build_phase106_dataset.py \
        --diagnostic-jsonl training_output/diagnostic_sft_combined.jsonl \
        --base-dataset training_output/unified_vision_data/train \
        --output training_output/phase106_dataset/train
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from datasets import Dataset, load_from_disk, concatenate_datasets


def build_merged_dataset(
    diagnostic_jsonl: Path,
    base_dataset_path: Path,
    output_path: Path,
) -> int:
    """Merge diagnostic SFT data into the existing vision dataset.

    Args:
        diagnostic_jsonl: Path to the combined diagnostic SFT JSONL.
        base_dataset_path: Path to the existing HF dataset (load_from_disk).
        output_path: Where to save the merged dataset.

    Returns:
        Total rows in the merged dataset.
    """
    # Load existing dataset.
    print(f"Loading base dataset: {base_dataset_path}")
    base_ds = load_from_disk(str(base_dataset_path))
    print(f"  Base rows: {len(base_ds)}")
    print(f"  Columns: {base_ds.column_names}")

    # Load diagnostic SFT data.
    print(f"\nLoading diagnostic SFT: {diagnostic_jsonl}")
    diagnostic_rows = []
    with open(diagnostic_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)

            # Convert ChatML messages to the HF vision dataset format.
            # Existing format: messages = [{role, content: [{type, text}]}]
            messages = []
            for msg in data["messages"]:
                messages.append({
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["content"]}],
                })

            diagnostic_rows.append({
                "images": [],  # No board render for diagnostic text.
                "messages": messages,
                "task_type": data.get("task_type", "blocker_diagnosis"),
                "source_file": "diagnostic_sft",
            })

    print(f"  Diagnostic rows: {len(diagnostic_rows)}")

    # Create HF dataset from diagnostic rows.
    diag_ds = Dataset.from_list(diagnostic_rows)

    # Concatenate: base + diagnostic.
    merged = concatenate_datasets([base_ds, diag_ds])
    print(f"\nMerged dataset: {len(merged)} rows")

    # Shuffle for training stability.
    merged = merged.shuffle(seed=42)

    # Save.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save_to_disk(str(output_path))
    print(f"Saved to: {output_path}")

    # Verify.
    verify = load_from_disk(str(output_path))
    print(f"Verification: {len(verify)} rows, columns: {verify.column_names}")

    # Count by task_type.
    from collections import Counter
    task_counts = Counter(verify["task_type"])
    print("\nTask type distribution:")
    for task, count in task_counts.most_common():
        print(f"  {task}: {count}")

    return len(merged)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build merged Phase 106 vision dataset."
    )
    parser.add_argument(
        "--diagnostic-jsonl", required=True, type=Path,
        help="Path to combined diagnostic SFT JSONL.",
    )
    parser.add_argument(
        "--base-dataset", default=Path("training_output/unified_vision_data/train"),
        type=Path, help="Existing HF dataset path.",
    )
    parser.add_argument(
        "--output", default=Path("training_output/phase106_dataset/train"),
        type=Path, help="Output merged dataset path.",
    )
    args = parser.parse_args()

    total = build_merged_dataset(
        diagnostic_jsonl=args.diagnostic_jsonl,
        base_dataset_path=args.base_dataset,
        output_path=args.output,
    )
    print(f"\nDone. {total} total rows ready for Vast.ai training.")


if __name__ == "__main__":
    main()
