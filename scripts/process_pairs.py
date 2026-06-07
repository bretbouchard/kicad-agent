#!/usr/bin/env python3
"""Process pre-discovered PCB+SCH pairs into training JSONL.

Reads a tab-separated pair list (from /tmp/staging_pairs.txt), runs the
graph builder on each pair, deduplicates against existing training data
hashes, and writes train/val/test splits.

Usage:
    python3 scripts/process_pairs.py \
        --pairs /tmp/staging_pairs.txt \
        --exclude-hashes /tmp/existing_hashes.txt \
        --output-dir training_data_unused \
        --checkpoint-every 100
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.real_dataset import (
    RealBoardSample,
    RealBoardDataset,
    _graph_result_to_sample,
    filter_quality,
)
from kicad_agent.training.graph_builder import (
    MIN_KICAD_VERSION,
    build_board_graph,
    detect_kicad_version,
    is_likely_parseable,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("process_pairs")


def _board_hash(sch_path: str, pcb_path: str) -> str:
    """Compute SHA256 hash of combined file contents."""
    h = hashlib.sha256()
    try:
        h.update(Path(pcb_path).read_bytes())
    except OSError:
        pass
    try:
        h.update(Path(sch_path).read_bytes())
    except OSError:
        pass
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Process PCB+SCH pairs into training JSONL")
    parser.add_argument("--pairs", required=True, help="Tab-separated pair list file")
    parser.add_argument("--exclude-hashes", default=None, help="File with existing board hashes to skip")
    parser.add_argument("--output-dir", required=True, help="Output directory for JSONL splits")
    parser.add_argument("--checkpoint-every", type=int, default=100, help="Flush checkpoint every N samples")
    args = parser.parse_args()

    start = time.time()

    # Load existing hashes for cross-dedup
    existing_hashes: set[str] = set()
    if args.exclude_hashes:
        with open(args.exclude_hashes) as f:
            existing_hashes = {line.strip() for line in f if line.strip()}
        logger.info("Loaded %d existing hashes for dedup", len(existing_hashes))

    # Load pair list
    pairs: list[tuple[str, str]] = []
    with open(args.pairs) as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            sch, pcb = line.split("\t", 1)
            pairs.append((sch, pcb))
    logger.info("Loaded %d PCB+SCH pairs", len(pairs))

    # Process pairs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.jsonl"

    # Resume from checkpoint
    seen_hashes: set[str] = set(existing_hashes)
    samples: list[dict] = []
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            for line in f:
                try:
                    s = json.loads(line.strip())
                    samples.append(s)
                    seen_hashes.add(s["board_hash"])
                except (json.JSONDecodeError, KeyError):
                    pass
        logger.info("Resumed from checkpoint: %d existing samples", len(samples))

    n_parsed = 0
    n_failed = 0
    n_skipped = 0
    sample_id = len(samples)
    since_checkpoint = 0

    for idx, (sch_path, pcb_path) in enumerate(pairs):
        # Skip if already processed
        bhash = _board_hash(sch_path, pcb_path)
        if bhash in seen_hashes:
            n_skipped += 1
            continue

        # Version check
        try:
            pcb_text = Path(pcb_path).read_text(encoding="utf-8", errors="replace")
            if not is_likely_parseable(pcb_text):
                n_failed += 1
                continue
            pcb_ver = detect_kicad_version(pcb_text)
            if pcb_ver is None or pcb_ver < MIN_KICAD_VERSION:
                n_failed += 1
                continue
        except Exception:
            n_failed += 1
            continue

        # Derive repo name from path
        rel = pcb_path
        parts = Path(pcb_path).parts
        repo_name = parts[1] if len(parts) > 1 else ""

        try:
            result = build_board_graph(
                sch_path=Path(sch_path),
                pcb_path=Path(pcb_path),
                sample_id=sample_id,
                repo_url="",
                repo_name=repo_name,
                sch_repo_path=sch_path,
                pcb_repo_path=pcb_path,
            )

            if result is None:
                n_failed += 1
                continue

            sample_dict = {
                "sample_id": sample_id,
                "repo_url": result.repo_url,
                "repo_name": result.repo_name,
                "schematic_path": result.schematic_path,
                "pcb_path": result.pcb_path,
                "component_count": result.component_count,
                "net_count": result.net_count,
                "layer_count": result.layer_count,
                "board_width_mm": result.board_width_mm,
                "board_height_mm": result.board_height_mm,
                "difficulty": result.difficulty,
                "board_hash": result.board_hash,
                "graph_json": result.graph_json,
                "spatial_summary_json": result.spatial_summary_json,
                "source_format": "kicad_pcb",
            }

            samples.append(sample_dict)
            seen_hashes.add(result.board_hash)
            sample_id += 1
            n_parsed += 1
            since_checkpoint += 1

        except Exception as e:
            logger.warning("Failed to parse %s: %s", pcb_path, e)
            n_failed += 1

        # Checkpoint
        if since_checkpoint >= args.checkpoint_every:
            with open(checkpoint_path, "w") as f:
                for s in samples:
                    f.write(json.dumps(s) + "\n")
            logger.info(
                "Checkpoint: %d parsed, %d failed, %d skipped | %d/%d pairs processed",
                n_parsed, n_failed, n_skipped, idx + 1, len(pairs),
            )
            since_checkpoint = 0

    # Final checkpoint
    with open(checkpoint_path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")

    # Quality filter
    filtered_dicts = []
    for s in samples:
        if s["component_count"] >= 3 and s["net_count"] >= 2:
            filtered_dicts.append(s)
    n_quality_removed = len(samples) - len(filtered_dicts)

    # Split
    import random
    rng = random.Random(42)
    indices = list(range(len(filtered_dicts)))
    rng.shuffle(indices)
    shuffled = [filtered_dicts[i] for i in indices]

    n = len(shuffled)
    train_end = int(n * 0.8)
    val_end = train_end + int(n * 0.1)

    for split_name, split_data in [
        ("train", shuffled[:train_end]),
        ("val", shuffled[train_end:val_end]),
        ("test", shuffled[val_end:]),
    ]:
        path = output_dir / f"{split_name}.jsonl"
        with open(path, "w") as f:
            for s in split_data:
                f.write(json.dumps(s) + "\n")

    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"Pair processing complete ({elapsed:.1f}s)")
    print(f"  Pairs input:     {len(pairs)}")
    print(f"  Skipped (dup):   {n_skipped}")
    print(f"  Parsed OK:       {n_parsed}")
    print(f"  Parse failed:    {n_failed}")
    print(f"  Quality removed: {n_quality_removed}")
    print(f"  Final samples:   {len(filtered_dicts)}")
    print(f"  Splits:          {train_end} train / {val_end - train_end} val / {n - val_end} test")
    print(f"  Output:          {output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
