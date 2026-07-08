#!/usr/bin/env python3
"""Run the spatial reasoning benchmark against local models.

Executes all 162 tasks from TaskGenerator against Qwen2.5-0.5B (text)
and optionally Gemma 4 12B (vision), producing MODEL-ASSESSMENT.md.

Usage:
    # Text-only benchmark (Qwen2.5-0.5B + GRPO adapter)
    python scripts/run_spatial_benchmark.py

    # With Gemma 4 12B vision model
    python scripts/run_spatial_benchmark.py --gemma

    # Custom output path
    python scripts/run_spatial_benchmark.py --output /path/to/ASSESSMENT.md

    # Run only N tasks (fast dev mode)
    python scripts/run_spatial_benchmark.py --quick 20
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.analysis.benchmark_runner import (
    BenchmarkRunner,
    QwenTextAdapter,
)
from kicad_agent.analysis.spatial_benchmark import TaskGenerator

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / ".planning" / "research" / "MODEL-ASSESSMENT.md"
FIXTURE_PATHS = [
    str(Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "RPi" / "board.kicad_pcb"),
    str(Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"),
    str(Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "smd_test_board.kicad_pcb"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run spatial reasoning benchmark")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="Output markdown path")
    parser.add_argument("--gemma", action="store_true", help="Include Gemma 4 12B vision model")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--quick", type=int, default=None, help="Run only N tasks (dev mode)")
    parser.add_argument("--adapter-dir", type=str, default=None, help="LoRA adapter directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print(f"=== Spatial Reasoning Benchmark ===")
    print(f"Seed: {args.seed}")
    print()

    # 1. Generate tasks.
    t0 = time.monotonic()
    print("Generating tasks...")
    gen = TaskGenerator(pcb_paths=FIXTURE_PATHS, seed=args.seed)
    tasks = gen.generate_all()

    if args.quick:
        tasks = tasks[: args.quick]
        print(f"Quick mode: running {len(tasks)} tasks")
    else:
        print(f"Generated {len(tasks)} tasks across 6 categories")

    # Count by type.
    text_count = sum(1 for t in tasks if t.input_type == "text")
    vision_count = sum(1 for t in tasks if t.input_type == "vision")
    print(f"  Text tasks: {text_count}")
    print(f"  Vision tasks: {vision_count}")
    print()

    # 2. Build adapters.
    adapters = []

    print("Loading Qwen2.5-0.5B + GRPO adapter...")
    qwen = QwenTextAdapter(
        adapter_dir=args.adapter_dir,
        max_tokens=256,
        temperature=0.1,
    )
    adapters.append(qwen)
    print(f"  Adapter: {qwen.name}")
    print()

    if args.gemma:
        print("Loading Gemma 4 12B (vision)...")
        try:
            from kicad_agent.analysis.benchmark_runner import GemmaVisionAdapter

            gemma = GemmaVisionAdapter()
            if gemma.is_available():
                adapters.append(gemma)
                print(f"  Adapter: {gemma.name}")
            else:
                print("  WARNING: Gemma 4 12B not available, skipping vision tasks")
                print("  Download: huggingface-cli download ggml-org/gemma-4-12B-it-Q4_K_M")
        except Exception as exc:
            print(f"  WARNING: Gemma adapter failed to load: {exc}")
        print()

    # 3. Run benchmark.
    print("Running benchmark...")
    print(f"  Models: {len(adapters)}")
    print(f"  Tasks: {len(tasks)}")
    print()

    runner = BenchmarkRunner(adapters=adapters, seed=args.seed, force_text_baseline=True)
    report = runner.run(tasks=tasks)

    elapsed = time.monotonic() - t0

    # 4. Print summary.
    print()
    print("=== Results ===")
    print(f"Total tasks: {report.total_tasks}")
    print(f"Total results: {len(report.results)}")
    print(f"Duration: {elapsed:.1f}s")
    print()

    for cs in report.category_scores:
        print(f"  {cs.category:30s} | {cs.model_name:30s} | {cs.accuracy:6.1%} ({cs.correct}/{cs.total}) | {cs.avg_latency_ms:7.0f}ms")

    print()

    # 5. Write report.
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    md = report.to_markdown()
    output_path.write_text(md)
    print(f"Report written to: {output_path}")
    print()


if __name__ == "__main__":
    main()
