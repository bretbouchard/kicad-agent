#!/usr/bin/env python3
"""Benchmark Gemma 4 12B baseline and decide whether fine-tuning is needed.

Gate check: fine-tuning is triggered if Gemma scores < 50% on
routing_feasibility OR net_completion. If Gemma is not available
locally, prints download instructions and exits cleanly.

Usage:
    python3 scripts/benchmark_gemma_baseline.py
    python3 scripts/benchmark_gemma_baseline.py --seed 42 --output /tmp/gemma_baseline.md
    python3 scripts/benchmark_gemma_baseline.py --quick 20
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_GEMMA_MODEL_ID = "ggml-org/gemma-4-12B-it-Q4_K_M"
_GATE_THRESHOLD = 0.50

_GATE_CATEGORIES = frozenset({
    "routing_feasibility",
    "net_completion",
})


def benchmark_gemma(
    seed: int = 42,
    quick: int | None = None,
    output_path: Path | None = None,
) -> tuple[bool, Any]:
    """Run Gemma 4 12B on the spatial benchmark and return gate decision.

    Args:
        seed: Random seed for task generation.
        quick: If set, only run this many tasks (for quick testing).
        output_path: Optional path to write markdown report.

    Returns:
        (should_finetune, report) where should_finetune is True if any
        gate category scored below threshold.
    """
    from kicad_agent.analysis.benchmark_runner import (
        BenchmarkRunner,
        GemmaVisionAdapter,
    )
    from kicad_agent.analysis.spatial_benchmark import TaskGenerator

    adapter = GemmaVisionAdapter()

    # Check availability.
    print(f"Checking Gemma 4 12B availability...")
    if not adapter.is_available():
        print(
            f"\nGemma 4 12B is not available locally.\n"
            f"Download with:\n"
            f"  huggingface-cli download {_GEMMA_MODEL_ID}\n\n"
            f"Then re-run this script. Gate check: CONSERVATIVE (assume fine-tune needed)."
        )
        return True, None

    # Generate tasks.
    gen = TaskGenerator(seed=seed)
    tasks = gen.generate_all()

    # Filter to vision tasks only (text tasks don't exercise Gemma's advantage).
    vision_tasks = [t for t in tasks if t.input_type == "vision"]
    if quick is not None:
        vision_tasks = vision_tasks[:quick]

    print(f"Running {len(vision_tasks)} vision tasks against Gemma 4 12B...")

    runner = BenchmarkRunner(adapters=[adapter], seed=seed)
    report = runner.run(tasks=vision_tasks)

    # Evaluate gate.
    should_finetune = False
    gate_scores: dict[str, float] = {}

    for score in report.category_scores:
        cat = score.category
        if cat in _GATE_CATEGORIES:
            gate_scores[cat] = score.accuracy
            if score.accuracy < _GATE_THRESHOLD:
                should_finetune = True

    # Print report.
    print(f"\n{'=' * 60}")
    print(f"Gemma 4 12B Baseline Results")
    print(f"{'=' * 60}")
    for score in report.category_scores:
        status = "PASS" if score.accuracy >= _GATE_THRESHOLD else "FAIL"
        marker = " [GATE]" if score.category in _GATE_CATEGORIES else ""
        print(f"  {score.category}: {score.accuracy:.1%} ({status}){marker}")

    print(f"\nGate Categories (threshold: {_GATE_THRESHOLD:.0%}):")
    for cat in sorted(_GATE_CATEGORIES):
        acc = gate_scores.get(cat, 0.0)
        status = "PASS" if acc >= _GATE_THRESHOLD else "FAIL"
        print(f"  {cat}: {acc:.1%} ({status})")

    decision = "FINE-TUNE" if should_finetune else "SKIP (base model sufficient)"
    print(f"\nDecision: {decision}")

    if output_path:
        _write_report(report, gate_scores, should_finetune, output_path)
        print(f"\nReport written to {output_path}")

    return should_finetune, report


def _write_report(
    report: Any,
    gate_scores: dict[str, float],
    should_finetune: bool,
    path: Path,
) -> None:
    """Write benchmark results to a markdown file."""
    lines = [
        "# Gemma 4 12B Baseline Benchmark",
        "",
        f"**Decision:** {'FINE-TUNE' if should_finetune else 'SKIP (base sufficient)'}",
        f"**Gate Threshold:** {_GATE_THRESHOLD:.0%}",
        "",
        "## Gate Categories",
        "",
    ]
    for cat in sorted(_GATE_CATEGORIES):
        acc = gate_scores.get(cat, 0.0)
        status = "PASS" if acc >= _GATE_THRESHOLD else "FAIL"
        lines.append(f"- **{cat}:** {acc:.1%} ({status})")

    lines.extend([
        "",
        "## All Categories",
        "",
        "| Category | Accuracy | Tasks | Avg Latency |",
        "|----------|----------|-------|-------------|",
    ])
    for score in report.category_scores:
        lines.append(
            f"| {score.category} | {score.accuracy:.1%} | {score.total} | {score.avg_latency_ms:.0f}ms |"
        )

    lines.extend([
        "",
        f"**Total tasks:** {report.total_tasks}",
        f"**Duration:** {report.total_duration_s:.1f}s",
        "",
    ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Gemma 4 12B and check fine-tuning gate.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quick", type=int, default=None, help="Run only N tasks")
    parser.add_argument("--output", type=Path, default=None, help="Write markdown report")
    args = parser.parse_args()

    should_finetune, report = benchmark_gemma(
        seed=args.seed,
        quick=args.quick,
        output_path=args.output,
    )

    return 1 if should_finetune else 0


if __name__ == "__main__":
    sys.exit(main())
