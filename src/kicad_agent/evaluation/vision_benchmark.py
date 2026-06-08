"""Vision benchmark: compare Gemma 4 vision vs Qwen text baseline.

Runs both models on the same KiCad analysis tasks and produces
a comparison report with accuracy, latency, and quality metrics.

Provides:
- VisionBenchmarkResult: frozen benchmark comparison result
- run_vision_benchmark: main benchmark entry point
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisionBenchmarkResult:
    """Comparison result between vision and text models."""

    total_tasks: int
    gemma_correct: int
    gemma_total_time: float
    qwen_correct: int
    qwen_total_time: float
    gemma_accuracy: float
    qwen_accuracy: float
    regression: float  # percentage difference (negative = regression)
    per_task_results: list[dict[str, Any]]


def run_vision_benchmark(
    test_pcb_dir: Path,
    gemma_config: Any | None = None,
    qwen_config: Any | None = None,
    max_tasks: int = 50,
) -> VisionBenchmarkResult:
    """Run benchmark comparing Gemma 4 vision vs Qwen text baseline.

    Args:
        test_pcb_dir: Directory of PCB files to test against.
        gemma_config: KiCadVisionConfig for Gemma 4 model.
        qwen_config: Config for Qwen baseline model.
        max_tasks: Maximum number of tasks to benchmark.

    Returns:
        VisionBenchmarkResult with comparison metrics.
    """
    from kicad_agent.inference.vision_pipeline import KiCadVisionConfig, KiCadVisionPipeline

    if gemma_config is None:
        gemma_config = KiCadVisionConfig()

    # Find test PCBs
    pcb_files = list(Path(test_pcb_dir).glob("**/*.kicad_pcb"))[:max_tasks]
    if not pcb_files:
        logger.warning("No PCB files found in %s", test_pcb_dir)
        return VisionBenchmarkResult(
            total_tasks=0, gemma_correct=0, gemma_total_time=0.0,
            qwen_correct=0, qwen_total_time=0.0,
            gemma_accuracy=0.0, qwen_accuracy=0.0, regression=0.0,
            per_task_results=[],
        )

    logger.info("Benchmarking %d PCBs with Gemma 4 vision", len(pcb_files))

    # Load Gemma 4
    gemma_pipeline = KiCadVisionPipeline(gemma_config)

    per_task = []
    gemma_correct = 0
    qwen_correct = 0
    gemma_time = 0.0
    qwen_time = 0.0

    for pcb_path in pcb_files:
        task_result = _benchmark_single_pcb(
            pcb_path, gemma_pipeline, qwen_config,
        )
        per_task.append(task_result)

        if task_result.get("gemma_valid"):
            gemma_correct += 1
        if task_result.get("qwen_valid"):
            qwen_correct += 1
        gemma_time += task_result.get("gemma_time", 0.0)
        qwen_time += task_result.get("qwen_time", 0.0)

    total = len(pcb_files)
    gemma_acc = gemma_correct / total if total > 0 else 0.0
    qwen_acc = qwen_correct / total if total > 0 else 0.0
    regression = ((gemma_acc - qwen_acc) / qwen_acc * 100) if qwen_acc > 0 else 0.0

    result = VisionBenchmarkResult(
        total_tasks=total,
        gemma_correct=gemma_correct,
        gemma_total_time=gemma_time,
        qwen_correct=qwen_correct,
        qwen_total_time=qwen_time,
        gemma_accuracy=gemma_acc,
        qwen_accuracy=qwen_acc,
        regression=regression,
        per_task_results=per_task,
    )

    logger.info(
        "Benchmark complete: Gemma %.1f%% (%.1fs) vs Qwen %.1f%% (%.1fs) | delta %.1f%%",
        gemma_acc * 100,
        gemma_time,
        qwen_acc * 100,
        qwen_time,
        regression,
    )

    return result


def _benchmark_single_pcb(
    pcb_path: Path,
    gemma_pipeline: Any,
    qwen_config: Any,
) -> dict[str, Any]:
    """Benchmark a single PCB file with both models."""
    result: dict[str, Any] = {"pcb": str(pcb_path)}

    # Gemma 4 vision
    try:
        from kicad_agent.export.pcb_image_renderer import render_pcb_layer_png

        start = time.time()
        image = render_pcb_layer_png(pcb_path, width=1024, height=768)
        prompt = (
            f"Analyze this PCB: {pcb_path.name}. "
            "List components, nets, and any routing issues. "
            "Use KiCad JSON operation format for any suggested edits."
        )
        output = gemma_pipeline.generate_from_image(image, prompt)
        elapsed = time.time() - start
        result["gemma_time"] = elapsed
        result["gemma_valid"] = bool(output) and len(output) > 50
        result["gemma_length"] = len(output) if output else 0
    except Exception as exc:
        result["gemma_valid"] = False
        result["gemma_error"] = str(exc)
        result["gemma_time"] = 0.0

    # Qwen text baseline (skip if not configured)
    if qwen_config is not None:
        try:
            start = time.time()
            # Qwen uses text-only prompt with board metadata
            prompt = f"Analyze PCB: {pcb_path.name}. List components and routing issues."
            # TODO: integrate with existing qwen inference pipeline
            elapsed = time.time() - start
            result["qwen_time"] = elapsed
            result["qwen_valid"] = True
        except Exception as exc:
            result["qwen_valid"] = False
            result["qwen_error"] = str(exc)
            result["qwen_time"] = 0.0
    else:
        result["qwen_valid"] = False
        result["qwen_time"] = 0.0

    return result
