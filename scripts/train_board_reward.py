#!/usr/bin/env python3
"""Train reward model on real PCB board data.

End-to-end pipeline:
1. Load ingested board data (train.jsonl / val.jsonl / test.jsonl)
2. Synthesize reasoning chains from board graphs
3. Score chains (correct + corrupted variants)
4. Train tokenizer on chain texts
5. Train reward model (supervised MSE)
6. Evaluate discrimination gap
7. Save report

Usage:
    # First ingest boards:
    python scripts/train_real_pcbs.py --staging-dir kicad_staging --output-dir training_data

    # Then train:
    python scripts/train_board_reward.py --data-dir training_data --output-dir training_output/board_run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.training.board_chains import (
    BoardReasoningChain,
    synthesize_board_chain,
    synthesize_corrupted_board_chain,
)
from kicad_agent.training.board_reward import score_board_chain
from kicad_agent.training.real_dataset import RealBoardDataset
from kicad_agent.training.reward_model import RewardModel, predict_reward, train_reward_model
from kicad_agent.training.tokenizer import ChainTokenizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_board_reward")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train reward model on real PCB board data",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("training_data"),
        help="Dir with train.jsonl, val.jsonl, test.jsonl (default: training_data)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/board_run"),
        help="Output dir for model and eval report",
    )
    parser.add_argument("--epochs", type=int, default=5, help="Training epochs (default: 5)")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate (default: 1e-4)")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size (default: 32)")
    parser.add_argument(
        "--device",
        default="cpu",
        help="Device: cpu, mps, or cuda (default: auto-detect)",
    )
    args = parser.parse_args()

    start = time.time()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Auto-detect device
    device = args.device
    if device == "cpu":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
        except ImportError:
            pass

    logger.info("Loading data from %s (device=%s)", args.data_dir, device)

    # 1. Load splits
    train_ds = RealBoardDataset.from_jsonl(args.data_dir / "train.jsonl")
    val_ds = RealBoardDataset.from_jsonl(args.data_dir / "val.jsonl")
    test_ds = RealBoardDataset.from_jsonl(args.data_dir / "test.jsonl")
    logger.info("Loaded: train=%d, val=%d, test=%d", len(train_ds), len(val_ds), len(test_ds))

    if len(train_ds) == 0:
        logger.error("No training data — run scripts/train_real_pcbs.py first")
        return 1

    # 2. Synthesize chains and score
    logger.info("Synthesizing chains for %d training samples...", len(train_ds))
    train_texts: list[str] = []
    train_labels: list[tuple[float, float, float]] = []

    for sample in train_ds.samples:
        # Correct chain
        chain = synthesize_board_chain(sample)
        reward = score_board_chain(chain, sample)

        train_texts.append(chain.chain_text)
        fmt_avg = sum(sr.format_score for sr in reward.step_rewards) / max(len(reward.step_rewards), 1)
        qual_avg = sum(sr.quality_score for sr in reward.step_rewards) / max(len(reward.step_rewards), 1)
        acc_avg = sum(sr.accuracy_score for sr in reward.step_rewards) / max(len(reward.step_rewards), 1)
        train_labels.append((fmt_avg, qual_avg, acc_avg))

        # Corrupted variant (provides contrast signal)
        corrupted = synthesize_corrupted_board_chain(sample, rng_seed=sample.sample_id)
        corrupt_reward = score_board_chain(corrupted, sample)

        train_texts.append(corrupted.chain_text)
        c_fmt = sum(sr.format_score for sr in corrupt_reward.step_rewards) / max(len(corrupt_reward.step_rewards), 1)
        c_qual = sum(sr.quality_score for sr in corrupt_reward.step_rewards) / max(len(corrupt_reward.step_rewards), 1)
        c_acc = sum(sr.accuracy_score for sr in corrupt_reward.step_rewards) / max(len(corrupt_reward.step_rewards), 1)
        train_labels.append((c_fmt, c_qual, c_acc))

    logger.info("Generated %d training texts (correct + corrupted)", len(train_texts))

    # Validation chains
    val_texts: list[str] = []
    val_labels: list[tuple[float, float, float]] = []
    for sample in val_ds.samples:
        chain = synthesize_board_chain(sample)
        reward = score_board_chain(chain, sample)
        val_texts.append(chain.chain_text)
        fmt_avg = sum(sr.format_score for sr in reward.step_rewards) / max(len(reward.step_rewards), 1)
        qual_avg = sum(sr.quality_score for sr in reward.step_rewards) / max(len(reward.step_rewards), 1)
        acc_avg = sum(sr.accuracy_score for sr in reward.step_rewards) / max(len(reward.step_rewards), 1)
        val_labels.append((fmt_avg, qual_avg, acc_avg))

    # 3. Train tokenizer
    logger.info("Training tokenizer on %d texts...", len(train_texts))
    tokenizer = ChainTokenizer(vocab_size=8000)
    tokenizer.train(train_texts)
    logger.info("Tokenizer vocab size: %d", tokenizer.vocab_size_actual)

    # 4. Train reward model
    logger.info("Training reward model on %d samples (epochs=%d)...", len(train_texts), args.epochs)
    reward_model = RewardModel(device=device)
    reward_model.set_tokenizer(tokenizer)

    if not reward_model.is_available:
        logger.error("PyTorch not available — cannot train")
        return 1

    history = train_reward_model(
        reward_model,
        train_texts,
        train_labels,
        val_texts=val_texts,
        val_labels=val_labels,
        n_epochs=args.epochs,
        learning_rate=args.lr,
        batch_size=args.batch_size,
    )

    # 5. Evaluate on test set
    logger.info("Evaluating on %d test samples...", len(test_ds))
    correct_scores: list[float] = []
    corrupted_scores: list[float] = []

    for sample in test_ds.samples:
        # Score correct chain
        correct_chain = synthesize_board_chain(sample)
        pred_correct = predict_reward(reward_model, correct_chain.chain_text)
        correct_score = (pred_correct.format_score + pred_correct.quality_score + pred_correct.accuracy_score) / 3.0
        correct_scores.append(correct_score)

        # Score corrupted chain
        corrupted = synthesize_corrupted_board_chain(sample, rng_seed=sample.sample_id + 1000)
        pred_corrupted = predict_reward(reward_model, corrupted.chain_text)
        corrupted_score = (pred_corrupted.format_score + pred_corrupted.quality_score + pred_corrupted.accuracy_score) / 3.0
        corrupted_scores.append(corrupted_score)

    avg_correct = sum(correct_scores) / len(correct_scores) if correct_scores else 0
    avg_corrupted = sum(corrupted_scores) / len(corrupted_scores) if corrupted_scores else 0
    discrimination_gap = avg_correct - avg_corrupted

    # Pass rate: how often correct scores higher than corrupted
    passes = sum(1 for c, x in zip(correct_scores, corrupted_scores) if c > x)
    pass_rate = passes / len(correct_scores) if correct_scores else 0

    elapsed = time.time() - start

    # 6. Build report
    report = {
        "config": {
            "data_dir": str(args.data_dir),
            "device": device,
            "epochs": args.epochs,
            "learning_rate": args.lr,
            "batch_size": args.batch_size,
            "n_train": len(train_ds),
            "n_val": len(val_ds),
            "n_test": len(test_ds),
            "difficulty_train": train_ds.difficulty_counts,
            "difficulty_test": test_ds.difficulty_counts,
        },
        "steps": {
            "chains": {
                "n_correct": len(train_ds),
                "n_corrupted": len(train_ds),
                "n_total_texts": len(train_texts),
            },
            "tokenizer": {
                "vocab_size": tokenizer.vocab_size_actual,
            },
            "reward_model": {
                "final_loss": history["losses"][-1] if history.get("losses") else None,
                "final_val_loss": history["val_losses"][-1] if history.get("val_losses") else None,
            },
            "evaluation": {
                "avg_correct_score": round(avg_correct, 4),
                "avg_corrupted_score": round(avg_corrupted, 4),
                "discrimination_gap": round(discrimination_gap, 4),
                "pass_rate": round(pass_rate, 4),
                "n_test": len(test_ds),
            },
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    report_path = output_dir / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"Board Reward Model Training Complete ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  Training:     {len(train_texts)} texts ({len(train_ds)} correct + {len(train_ds)} corrupted)")
    print(f"  Tokenizer:    {tokenizer.vocab_size_actual} vocab")
    print(f"  Final loss:   {report['steps']['reward_model']['final_loss']}")
    print(f"  Eval (test={len(test_ds)}):")
    print(f"    Correct avg:    {avg_correct:.4f}")
    print(f"    Corrupted avg:  {avg_corrupted:.4f}")
    print(f"    Discrim gap:    {discrimination_gap:+.4f}")
    print(f"    Pass rate:      {pass_rate:.1%}")
    print(f"  Difficulty:   {train_ds.difficulty_counts}")
    print(f"  Report:       {report_path}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
