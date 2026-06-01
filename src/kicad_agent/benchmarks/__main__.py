"""CLI entry point for running PCB MMLU benchmarks.

Usage:
    # Run benchmark
    python -m kicad_agent.benchmarks \
        --dataset benchmarks/pcb-mmlu-v1.json \
        --model heuristic \
        --output /tmp/results.json

    # Run benchmark with regression check
    python -m kicad_agent.benchmarks \
        --dataset benchmarks/pcb-mmlu-v1.json \
        --model heuristic \
        --output /tmp/results.json \
        --regression-check

    # Run with explicit baseline path
    python -m kicad_agent.benchmarks \
        --dataset benchmarks/pcb-mmlu-v1.json \
        --model heuristic \
        --output /tmp/results.json \
        --regression-check \
        --baseline benchmarks/results/baseline.json

Active flags:
    --dataset           Path to benchmark JSON dataset (required)
    --model             Model to evaluate: random, heuristic (required)
    --output            Path for results JSON output (required)
    --categories        Filter to specific categories (optional, space-separated)
    --difficulty        Filter to easy/medium/hard (optional)
    --max-questions     Limit number of questions evaluated (optional)
    --regression-check  Compare results against baseline for regression detection
    --baseline          Path to baseline JSON for regression check (default: benchmarks/results/baseline.json)

Future flags (Phase 44):
    --adversarial       Run adversarial test variants
    --count             Number of questions to sample (default: 500)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicad_agent.benchmarks.models import BaselineHeuristic, BaselineRandom
from kicad_agent.benchmarks.regression import RegressionDetector
from kicad_agent.benchmarks.runner import BenchmarkRunner
from kicad_agent.benchmarks.schemas import BenchmarkDataset

MODEL_REGISTRY: dict[str, type] = {
    "random": BaselineRandom,
    "heuristic": BaselineHeuristic,
}


def main() -> None:
    """Parse CLI arguments, run benchmark, and write results to JSON."""
    parser = argparse.ArgumentParser(
        description="Run PCB MMLU benchmark evaluation",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to benchmark JSON dataset file",
    )
    parser.add_argument(
        "--model",
        required=True,
        choices=list(MODEL_REGISTRY.keys()),
        help="Model to evaluate against the benchmark",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for results JSON output file",
    )
    parser.add_argument(
        "--categories",
        nargs="*",
        help="Filter to specific categories (space-separated)",
    )
    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        help="Filter to a specific difficulty level",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        help="Maximum number of questions to evaluate",
    )
    parser.add_argument(
        "--regression-check",
        action="store_true",
        help="Compare results against baseline for regression detection",
    )
    parser.add_argument(
        "--baseline",
        default="benchmarks/results/baseline.json",
        help="Path to baseline JSON for regression check (default: benchmarks/results/baseline.json)",
    )
    args = parser.parse_args()

    # Validate dataset path exists and is within size limits
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Error: Dataset file not found: {args.dataset}", file=sys.stderr)
        sys.exit(1)
    max_dataset_size = 100 * 1024 * 1024  # 100 MB
    if dataset_path.stat().st_size > max_dataset_size:
        print(f"Error: Dataset file exceeds 100 MB limit: {dataset_path.stat().st_size / 1024 / 1024:.1f} MB", file=sys.stderr)
        sys.exit(1)

    # Load dataset
    with open(args.dataset) as f:
        dataset = BenchmarkDataset.model_validate_json(f.read())

    # Create model instance
    model_cls = MODEL_REGISTRY[args.model]
    model = model_cls()

    # Run evaluation
    runner = BenchmarkRunner(dataset, model)
    result = runner.evaluate(
        categories=args.categories,
        difficulty=args.difficulty,
        max_questions=args.max_questions,
    )

    # Write results
    with open(args.output, "w") as f:
        json.dump(result.model_dump(), f, indent=2)

    # Print summary to stdout
    print(f"Model: {result.model_name}")
    print(f"Accuracy: {result.accuracy:.1%} ({result.correct}/{result.total_questions})")
    print(f"Duration: {result.duration_seconds:.1f}s")

    # Print per-category breakdown
    if result.category_accuracy:
        print("\nPer-category accuracy:")
        for cat, acc in sorted(result.category_accuracy.items()):
            print(f"  {cat}: {acc:.1%}")

    # Regression check
    if args.regression_check:
        detector = RegressionDetector()
        baseline = detector.load_baseline()
        report = detector.compare(result, baseline)
        print("\n--- Regression Check ---")
        if report.is_regression:
            print(f"REGRESSION DETECTED in: {report.regression_categories}")
            for cat in report.regression_categories:
                delta = report.delta[cat]
                print(f"  {cat}: {delta:+.1%} (threshold: -{detector.threshold:.0%})")
            print(f"Overall: {report.overall_delta:+.1%}")
            sys.exit(1)
        else:
            print(f"OK: No regression detected")
            print(f"Overall delta: {report.overall_delta:+.1%}")
            for cat, acc in sorted(result.category_accuracy.items()):
                delta = report.delta.get(cat, 0)
                print(f"  {cat}: {acc:.1%} ({delta:+.1%})")


if __name__ == "__main__":
    main()
