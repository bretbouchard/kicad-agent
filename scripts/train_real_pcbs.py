#!/usr/bin/env python3
"""Ingest local KiCad files and train reward model on real PCB data.

Scans a staging directory for .kicad_pcb + .kicad_sch pairs, parses each
into a board graph with spatial features, generates reasoning chains,
trains the reward model, and evaluates.

No GitHub token required — processes files already on disk.

Usage:
    python scripts/train_real_pcbs.py --staging-dir kicad_staging --output-dir training_data
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add src to path so this script works without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.real_dataset import run_local_pipeline  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_real_pcbs")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest local KiCad files and train on real PCB data",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=Path("kicad_staging"),
        help="Local dir with KiCad project subdirectories (default: kicad_staging)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_data"),
        help="Output dir for train.jsonl, val.jsonl, test.jsonl (default: training_data)",
    )
    args = parser.parse_args()

    start = time.time()
    logger.info("Starting local PCB ingestion from %s", args.staging_dir)

    dataset = run_local_pipeline(
        staging_dir=args.staging_dir,
        output_dir=args.output_dir,
    )

    elapsed = time.time() - start
    meta = dataset.metadata

    print(f"\n{'='*60}")
    print(f"Local PCB Ingestion Complete ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  Discovered:    {meta.get('n_discovered', 0)} PCB+SCH pairs")
    print(f"  Parsed:        {meta.get('n_parsed', 0)} boards")
    print(f"  Failed:        {meta.get('n_failed', 0)}")
    print(f"  Duplicates:    {meta.get('n_duplicates_removed', 0)} removed")
    print(f"  Low quality:   {meta.get('n_quality_removed', 0)} removed")
    print(f"  Final:         {len(dataset)} samples")
    print(f"  Difficulty:    {dataset.difficulty_counts}")
    print(f"  Output:        {args.output_dir}/")
    print(f"{'='*60}")

    if len(dataset) == 0:
        logger.error("No valid samples produced — check file versions and content")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
