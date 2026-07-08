"""Benchmark runner for spatial reasoning model evaluation.

Runs the 162 tasks from spatial_benchmark.py against multiple models
(Qwen2.5-0.5B text-only, Gemma 4 12B encoder-free vision) and produces
per-category accuracy tables, latency stats, and a MODEL-ASSESSMENT.md.

All inference is local via mlx-lm. No cloud dependencies.

Usage::

    from kicad_agent.analysis.benchmark_runner import BenchmarkRunner
    from kicad_agent.analysis.benchmark_runner import QwenTextAdapter

    runner = BenchmarkRunner(adapters=[QwenTextAdapter()])
    report = runner.run()
    print(report.to_markdown())

.. note::

   This module was split into three focused files to stay under the
   400-LOC soft budget (``~/.claude/rules/coding-style.md``):

   * :mod:`kicad_agent.analysis.benchmark_types` — Protocol, dataclasses,
     scoring helpers.
   * :mod:`kicad_agent.analysis.benchmark_adapters` — ``QwenTextAdapter``
     and ``GemmaVisionAdapter``.
   * This module — ``BenchmarkRunner`` orchestrator only.

   All public symbols are re-exported here so existing imports
   (``from kicad_agent.analysis.benchmark_runner import ...``) continue
   to work unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from kicad_agent.analysis.benchmark_adapters import (
    GemmaVisionAdapter,
    QwenTextAdapter,
)
from kicad_agent.analysis.benchmark_types import (
    BenchmarkReport,
    CategoryScore,
    ModelAdapter,
    TaskResult,
    _extract_fix_number,
    _extract_float,
    _extract_waypoints,
    _find_score,
    _recommend_model,
    score_task,
)
from kicad_agent.analysis.spatial_benchmark import (
    SpatialReasoningTask,
    TaskCategory,
    TaskGenerator,
)

# Re-export Gemma module constants for any external consumers.
from kicad_agent.analysis.benchmark_adapters import _GEMMA_MODEL_ID, _GEMMA_MMPROJ

if TYPE_CHECKING:
    pass  # imports above are real; this block kept for future type-only additions

logger = logging.getLogger(__name__)


__all__ = [
    # Types
    "ModelAdapter",
    "TaskResult",
    "CategoryScore",
    "BenchmarkReport",
    # Adapters
    "QwenTextAdapter",
    "GemmaVisionAdapter",
    # Orchestrator
    "BenchmarkRunner",
    # Scoring
    "score_task",
]


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------


class BenchmarkRunner:
    """Orchestrates benchmark execution across multiple models.

    Generates tasks from TaskGenerator, runs each against all compatible
    model adapters, scores answers, and produces a BenchmarkReport.

    Gracefully handles missing models: if a vision adapter is not available,
    vision tasks are skipped with a warning.

    Args:
        adapters: List of model adapters to evaluate.
        pcb_paths: PCB fixture paths for task generation.
        seed: Random seed for reproducibility.
        skip_categories: Optional set of categories to skip.
    """

    def __init__(
        self,
        adapters: list[ModelAdapter],
        pcb_paths: list[str] | None = None,
        seed: int = 42,
        skip_categories: set[TaskCategory] | None = None,
        force_text_baseline: bool = False,
    ) -> None:
        self._adapters = adapters
        self._pcb_paths = pcb_paths
        self._seed = seed
        self._skip_categories = skip_categories or set()
        self._force_text_baseline = force_text_baseline

    def run(self, tasks: list[SpatialReasoningTask] | None = None) -> BenchmarkReport:
        """Execute the full benchmark.

        Args:
            tasks: Pre-generated tasks. If None, generates from fixtures.

        Returns:
            BenchmarkReport with all results and aggregated scores.
        """
        if tasks is None:
            gen = TaskGenerator(pcb_paths=self._pcb_paths, seed=self._seed)
            tasks = gen.generate_all()

        # Filter skipped categories.
        if self._skip_categories:
            tasks = [t for t in tasks if t.task_type not in self._skip_categories]

        results: list[TaskResult] = []
        start_time = time.monotonic()

        for task in tasks:
            for adapter in self._adapters:
                # Skip vision tasks for text-only adapters unless
                # force_text_baseline is enabled (runs all as text).
                if (
                    task.input_type == "vision"
                    and not adapter.supports_vision
                    and not self._force_text_baseline
                ):
                    logger.debug(
                        "Skipping vision task %s for text adapter %s",
                        task.task_id,
                        adapter.name,
                    )
                    continue

                result = self._run_single(task, adapter)
                results.append(result)

        elapsed = time.monotonic() - start_time

        # Aggregate scores.
        category_scores = self._aggregate(results)

        report = BenchmarkReport(
            results=results,
            category_scores=category_scores,
            total_tasks=len(tasks),
            total_duration_s=elapsed,
        )
        return report

    def _run_single(
        self, task: SpatialReasoningTask, adapter: ModelAdapter,
    ) -> TaskResult:
        """Run a single task against one model."""
        try:
            t0 = time.monotonic()
            answer = adapter.run_task(task)
            latency_ms = (time.monotonic() - t0) * 1000

            correct, detail = score_task(task, answer)
            return TaskResult(
                task_id=task.task_id,
                model_name=adapter.name,
                answer=answer,
                ground_truth=task.ground_truth,
                correct=correct,
                latency_ms=latency_ms,
                category=task.task_type.value,
                difficulty=task.difficulty.value,
                input_type=task.input_type,
                score_detail=detail,
            )
        except Exception as exc:
            logger.error(
                "Error running %s on %s: %s",
                adapter.name,
                task.task_id,
                exc,
            )
            return TaskResult(
                task_id=task.task_id,
                model_name=adapter.name,
                answer="",
                ground_truth=task.ground_truth,
                correct=False,
                latency_ms=0.0,
                category=task.task_type.value,
                difficulty=task.difficulty.value,
                input_type=task.input_type,
                score_detail=f"error: {exc}",
            )

    @staticmethod
    def _aggregate(results: list[TaskResult]) -> list[CategoryScore]:
        """Aggregate results into per-category, per-model scores."""
        buckets: dict[tuple[str, str], list[TaskResult]] = {}
        for r in results:
            key = (r.category, r.model_name)
            buckets.setdefault(key, []).append(r)

        scores: list[CategoryScore] = []
        for (cat, model), cat_results in sorted(buckets.items()):
            total = len(cat_results)
            correct = sum(1 for r in cat_results if r.correct)
            accuracy = correct / total if total > 0 else 0.0
            avg_lat = sum(r.latency_ms for r in cat_results) / total if total > 0 else 0.0
            failures = tuple(r.task_id for r in cat_results if not r.correct)
            scores.append(CategoryScore(
                category=cat,
                model_name=model,
                total=total,
                correct=correct,
                accuracy=accuracy,
                avg_latency_ms=avg_lat,
                failures=failures,
            ))
        return scores
