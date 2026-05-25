#!/usr/bin/env python3
"""Ingest local KiCad files and train reward model on real PCB data.

Scans a staging directory for .kicad_pcb + .kicad_sch pairs, parses each
into a board graph with spatial features, generates reasoning chains,
trains the reward model, and evaluates.

No GitHub token required — processes files already on disk.

Usage:
    # Ingest only (no training):
    python scripts/train_real_pcbs.py --staging-dir kicad_staging --ingest-only

    # Full training:
    python scripts/train_real_pcbs.py --staging-dir kicad_staging --output-dir training_output/real_pcb_run

    # From pre-ingested data:
    python scripts/train_real_pcbs.py --data-dir training_data --output-dir training_output/real_pcb_run
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

from kicad_agent.training.real_dataset import RealBoardDataset, run_local_pipeline  # noqa: E402

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
        "--data-dir",
        type=Path,
        default=None,
        help="Use pre-existing train/val/test JSONL from this dir instead of ingesting",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/real_pcb_run"),
        help="Output dir for training artifacts and eval report",
    )
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Only ingest data (no training). Writes JSONL to --output-dir",
    )
    parser.add_argument(
        "--n-epochs",
        type=int,
        default=5,
        help="Number of training epochs (default: 5)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Device: cpu, mps, cuda (default: cpu, auto-detects)",
    )
    args = parser.parse_args()
    start = time.time()

    # --- Phase 1: Ingest or load data ---
    if args.ingest_only:
        logger.info("Ingest-only mode: scanning %s", args.staging_dir)
        dataset = run_local_pipeline(
            staging_dir=args.staging_dir,
            output_dir=args.output_dir,
        )
        meta = dataset.metadata
        elapsed = time.time() - start
        _print_ingest_summary(meta, dataset, elapsed)
        return 0 if len(dataset) > 0 else 1

    if args.data_dir and (args.data_dir / "train.jsonl").exists():
        logger.info("Loading pre-existing data from %s", args.data_dir)
        train_ds = RealBoardDataset.from_jsonl(args.data_dir / "train.jsonl")
        val_ds = RealBoardDataset.from_jsonl(args.data_dir / "val.jsonl")
        test_ds = RealBoardDataset.from_jsonl(args.data_dir / "test.jsonl")
        meta = {"source": "pre-existing", "data_dir": str(args.data_dir)}
    else:
        logger.info("Phase 1: Ingesting PCBs from %s", args.staging_dir)
        dataset = run_local_pipeline(
            staging_dir=args.staging_dir,
            output_dir=args.output_dir,
        )
        meta = dataset.metadata
        train_ds, val_ds, test_ds = dataset.split()

    print(f"\nDataset: {len(train_ds)} train / {len(val_ds)} val / {len(test_ds)} test")
    print(f"Difficulty: {meta.get('difficulty_counts', {})}\n")

    if len(train_ds) == 0:
        logger.error("No training data available — aborting")
        return 1

    # --- Phase 2: Synthesize reasoning chains ---
    logger.info("Phase 2: Synthesizing board reasoning chains...")
    from kicad_agent.training.board_chains import synthesize_board_chains  # noqa: E402

    train_texts, train_labels = synthesize_board_chains(train_ds.samples)
    val_texts, val_labels = synthesize_board_chains(val_ds.samples)
    test_texts, test_labels = synthesize_board_chains(test_ds.samples)
    logger.info("Chains: %d train / %d val / %d test",
                len(train_texts), len(val_texts), len(test_texts))

    # --- Phase 3: Train tokenizer + reward model ---
    logger.info("Phase 3: Training tokenizer and reward model...")
    from kicad_agent.training.tokenizer import ChainTokenizer  # noqa: E402
    from kicad_agent.training.reward_model import (  # noqa: E402
        RewardModel,
        predict_reward,
        train_reward_model,
    )

    tokenizer = ChainTokenizer(vocab_size=8000)
    tokenizer.train(train_texts)
    logger.info("Tokenizer vocab size: %d", tokenizer.vocab_size_actual)

    reward_model = RewardModel(device=args.device)
    reward_model.set_tokenizer(tokenizer)

    if not reward_model.is_available:
        logger.error("PyTorch not available — cannot train reward model")
        return 1

    history = train_reward_model(
        reward_model,
        train_texts,
        train_labels,
        val_texts=val_texts,
        val_labels=val_labels,
        n_epochs=args.n_epochs,
        learning_rate=1e-4,
        batch_size=32,
    )

    # --- Phase 4: Evaluate ---
    logger.info("Phase 4: Evaluating trained model...")
    from kicad_agent.training.board_chains import synthesize_corrupted_board_chain  # noqa: E402

    correct_scores = []
    for text in test_texts[::2]:  # even indices = correct chains
        pred = predict_reward(reward_model, text)
        correct_scores.append((pred.format_score + pred.quality_score + pred.accuracy_score) / 3)

    corrupted_scores = []
    for sample in test_ds.samples:
        corrupted = synthesize_corrupted_board_chain(sample, "random")
        if corrupted:
            pred = predict_reward(reward_model, corrupted.chain_text)
            corrupted_scores.append((pred.format_score + pred.quality_score + pred.accuracy_score) / 3)

    avg_correct = sum(correct_scores) / max(len(correct_scores), 1)
    avg_corrupted = sum(corrupted_scores) / max(len(corrupted_scores), 1)
    discrimination_gap = avg_correct - avg_corrupted

    elapsed = time.time() - start

    # --- Save report ---
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "config": {
            "staging_dir": str(args.staging_dir),
            "n_epochs": args.n_epochs,
            "device": reward_model._device,
        },
        "dataset": meta,
        "splits": {"train": len(train_ds), "val": len(val_ds), "test": len(test_ds)},
        "training": {
            "n_chains": len(train_texts),
            "final_loss": history.get("losses", [None])[-1],
            "tokenizer_vocab": tokenizer.vocab_size_actual,
        },
        "evaluation": {
            "avg_correct_score": round(avg_correct, 4),
            "avg_corrupted_score": round(avg_corrupted, 4),
            "discrimination_gap": round(discrimination_gap, 4),
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    report_path = output_dir / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Training complete in {elapsed:.1f}s")
    print(f"  Chains:        {len(train_texts)} train")
    print(f"  Correct avg:   {avg_correct:.4f}")
    print(f"  Corrupted avg: {avg_corrupted:.4f}")
    print(f"  Discrim gap:   {discrimination_gap:.4f}")
    print(f"  Report:        {report_path}")
    print(f"{'='*60}")
    return 0


def _print_ingest_summary(meta: dict, dataset: RealBoardDataset, elapsed: float) -> None:
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
    print(f"{'='*60}")


if __name__ == "__main__":
    raise SystemExit(main())
