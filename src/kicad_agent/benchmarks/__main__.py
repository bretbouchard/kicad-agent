"""CLI entry point for running PCB MMLU benchmarks.

Usage:
    python -m kicad_agent.benchmarks \\
        --dataset benchmarks/pcb-mmlu-v1.json \\
        --model random \\
        --output results/random-baseline.json

Active flags:
    --dataset        Path to benchmark JSON dataset (required)
    --model          Model to evaluate: random, heuristic (required)
    --output         Path for results JSON output (required)
    --categories     Filter to specific categories (optional, space-separated)
    --difficulty     Filter to easy/medium/hard (optional)
    --max-questions  Limit number of questions evaluated (optional)

Future flags (planned for Phase 43/44):
    --regression-check  Compare results against baseline for regression detection
    --baseline          Path to baseline JSON for regression check
    --adversarial       Run adversarial test variants
    --count             Number of questions to sample (default: 500)
"""

from __future__ import annotations

import argparse
import json
import sys

from kicad_agent.benchmarks.models import BaselineHeuristic, BaselineRandom
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
    # Future flags (Phase 43/44):
    # parser.add_argument("--regression-check", action="store_true",
    #                     help="Compare results against baseline for regression")
    # parser.add_argument("--baseline",
    #                     help="Path to baseline JSON for regression check")
    # parser.add_argument("--adversarial", action="store_true",
    #                     help="Run adversarial test variants")
    # parser.add_argument("--count", type=int, default=500,
    #                     help="Number of questions to sample")
    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
