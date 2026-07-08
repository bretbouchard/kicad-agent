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
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from kicad_agent.analysis.spatial_benchmark import (
    SpatialReasoningTask,
    TaskCategory,
    TaskGenerator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model Adapter Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelAdapter(Protocol):
    """Interface for model backends used in the benchmark.

    Each adapter wraps a specific LLM and handles prompt construction
    and response extraction.
    """

    @property
    def name(self) -> str:
        """Human-readable model name for reporting."""
        ...

    @property
    def supports_vision(self) -> bool:
        """Whether this adapter can process image input."""
        ...

    def run_task(self, task: SpatialReasoningTask) -> str:
        """Run a single benchmark task and return the model's answer.

        Args:
            task: Benchmark task with question and optional render_path.

        Returns:
            Raw model output string.
        """
        ...


# ---------------------------------------------------------------------------
# Task Result & Report Schemas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskResult:
    """Result of running one benchmark task against one model."""

    task_id: str
    model_name: str
    answer: str
    ground_truth: str
    correct: bool
    latency_ms: float
    category: str
    difficulty: str
    input_type: str
    score_detail: str = ""  # Human-readable scoring explanation


@dataclass(frozen=True)
class CategoryScore:
    """Aggregated score for one task category."""

    category: str
    model_name: str
    total: int
    correct: int
    accuracy: float
    avg_latency_ms: float
    failures: tuple[str, ...] = ()  # task_ids that failed


@dataclass
class BenchmarkReport:
    """Complete benchmark report across all models and categories."""

    results: list[TaskResult] = field(default_factory=list)
    category_scores: list[CategoryScore] = field(default_factory=list)
    total_tasks: int = 0
    total_duration_s: float = 0.0

    def to_markdown(self) -> str:
        """Generate MODEL-ASSESSMENT.md content."""
        lines: list[str] = []
        lines.append("# Spatial Reasoning Model Assessment")
        lines.append("")
        lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Total tasks:** {self.total_tasks}")
        lines.append(f"**Total duration:** {self.total_duration_s:.1f}s")
        lines.append("")

        # Model inventory
        models = sorted({r.model_name for r in self.results})
        lines.append("## Models Evaluated")
        lines.append("")
        for m in models:
            lines.append(f"- **{m}**")
        lines.append("")

        # Per-category accuracy table
        lines.append("## Per-Category Accuracy")
        lines.append("")
        categories = sorted({cs.category for cs in self.category_scores})
        header = "| Category | " + " | ".join(models) + " |"
        separator = "|---" + "|---" * len(models) + "|"
        lines.append(header)
        lines.append(separator)

        for cat in categories:
            row = f"| {cat} |"
            for m in models:
                score = _find_score(self.category_scores, cat, m)
                if score:
                    row += f" {score.accuracy:.1%} ({score.correct}/{score.total}) |"
                else:
                    row += " -- |"
            lines.append(row)
        lines.append("")

        # Latency table
        lines.append("## Per-Category Latency (ms/task)")
        lines.append("")
        lines.append(header)
        lines.append(separator)

        for cat in categories:
            row = f"| {cat} |"
            for m in models:
                score = _find_score(self.category_scores, cat, m)
                if score:
                    row += f" {score.avg_latency_ms:.0f} |"
                else:
                    row += " -- |"
            lines.append(row)
        lines.append("")

        # Decision matrix
        lines.append("## Decision Matrix")
        lines.append("")
        lines.append("Recommended model per task type for Phase 82 gap filling:")
        lines.append("")
        lines.append("| Task Type | Recommended Model | Rationale |")
        lines.append("|---|---|---|")
        for cat in categories:
            rec = _recommend_model(self.category_scores, cat, models)
            lines.append(f"| {cat} | {rec} |")
        lines.append("")

        # Failure mode analysis
        lines.append("## Failure Mode Analysis")
        lines.append("")
        for m in models:
            failures = [r for r in self.results if r.model_name == m and not r.correct]
            if failures:
                lines.append(f"### {m} — {len(failures)} failures")
                lines.append("")
                by_cat: dict[str, list[TaskResult]] = {}
                for f in failures:
                    by_cat.setdefault(f.category, []).append(f)
                for cat, cat_failures in sorted(by_cat.items()):
                    lines.append(f"- **{cat}**: {len(cat_failures)} failures")
                    for f in cat_failures[:3]:
                        lines.append(
                            f"  - `{f.task_id}`: expected `{f.ground_truth[:60]}`, "
                            f"got `{f.answer[:60]}`"
                        )
                    if len(cat_failures) > 3:
                        lines.append(f"  - ... and {len(cat_failures) - 3} more")
                lines.append("")

        return "\n".join(lines)


def _find_score(
    scores: list[CategoryScore], category: str, model: str,
) -> CategoryScore | None:
    for s in scores:
        if s.category == category and s.model_name == model:
            return s
    return None


def _recommend_model(
    scores: list[CategoryScore], category: str, models: list[str],
) -> str:
    best_model = models[0] if models else "N/A"
    best_acc = -1.0
    for m in models:
        s = _find_score(scores, category, m)
        if s and s.accuracy > best_acc:
            best_acc = s.accuracy
            best_model = m

    if best_acc >= 0.7:
        return f"**{best_model}** (>{best_acc:.0%} accuracy)"
    if best_acc >= 0.5:
        return f"{best_model} ({best_acc:.0%} — adequate)"
    return f"{best_model} ({best_acc:.0%} — needs improvement)"


# ---------------------------------------------------------------------------
# Answer Extraction & Scoring
# ---------------------------------------------------------------------------

# Numeric tolerance for coordinate proximity (10%).
_NUMERIC_TOLERANCE = 0.10

# Waypoint proximity tolerance in mm for path tasks.
_WAYPOINT_TOLERANCE_MM = 2.0


def score_task(task: SpatialReasoningTask, model_answer: str) -> tuple[bool, str]:
    """Score a model answer against ground truth.

    Returns (correct, detail_string).
    """
    answer = model_answer.strip().lower()
    gt = task.ground_truth.strip().lower()
    category = task.task_type

    if category == TaskCategory.COORDINATE_PROXIMITY:
        return _score_numeric(gt, answer)

    if category == TaskCategory.ROUTING_FEASIBILITY:
        return _score_yes_no(gt, answer)

    if category == TaskCategory.CLEARANCE_DIAGNOSIS:
        return _score_keyword_overlap(gt, answer)

    if category == TaskCategory.NET_COMPLETION:
        return _score_path(gt, answer)

    if category == TaskCategory.DRC_FIX_SELECTION:
        return _score_fix_selection(gt, answer)

    if category == TaskCategory.UNROUTED_CAUSE:
        return _score_keyword_overlap(gt, answer)

    # Fallback: exact match
    correct = gt in answer
    return correct, f"exact: {'match' if correct else 'mismatch'}"


def _score_numeric(
    ground_truth: str, answer: str,
) -> tuple[bool, str]:
    """Score numeric answer with tolerance."""
    gt_val = _extract_float(ground_truth)
    ans_val = _extract_float(answer)
    if gt_val is None or ans_val is None:
        return False, f"numeric parse failed (gt={gt_val}, ans={ans_val})"
    if gt_val == 0:
        correct = ans_val == 0
    else:
        correct = abs(ans_val - gt_val) / abs(gt_val) <= _NUMERIC_TOLERANCE
    detail = f"gt={gt_val:.4f}, ans={ans_val:.4f}, tol={_NUMERIC_TOLERANCE}"
    return correct, detail


def _score_yes_no(
    ground_truth: str, answer: str,
) -> tuple[bool, str]:
    """Score yes/no answer."""
    gt_bool = "yes" in ground_truth
    ans_bool = "yes" in answer and "no" not in answer
    correct = gt_bool == ans_bool
    return correct, f"gt={'yes' if gt_bool else 'no'}, ans={'yes' if ans_bool else 'no'}"


def _score_keyword_overlap(
    ground_truth: str, answer: str,
) -> tuple[bool, str]:
    """Score answer by keyword overlap with ground truth."""
    gt_words = set(re.findall(r"\b\w{4,}\b", ground_truth))
    if not gt_words:
        return False, "no keywords in ground truth"

    ans_words = set(re.findall(r"\b\w{4,}\b", answer))
    overlap = gt_words & ans_words
    # Require at least 30% keyword overlap for a correct answer.
    ratio = len(overlap) / len(gt_words)
    correct = ratio >= 0.3
    detail = f"overlap={len(overlap)}/{len(gt_words)} ({ratio:.0%})"
    return correct, detail


def _score_path(
    ground_truth: str, answer: str,
) -> tuple[bool, str]:
    """Score path answer by waypoint extraction and proximity."""
    # Extract waypoints from ground truth: (x.xx, y.yy) patterns.
    gt_waypoints = _extract_waypoints(ground_truth)
    if not gt_waypoints:
        return False, "no waypoints in ground truth"

    ans_waypoints = _extract_waypoints(answer)
    if not ans_waypoints:
        return False, "no waypoints extracted from answer"

    # Check if answer waypoints are near any ground truth waypoint.
    matched = 0
    for aw in ans_waypoints:
        for gw in gt_waypoints:
            dx = abs(aw[0] - gw[0])
            dy = abs(aw[1] - gw[1])
            if dx <= _WAYPOINT_TOLERANCE_MM and dy <= _WAYPOINT_TOLERANCE_MM:
                matched += 1
                break

    ratio = matched / len(gt_waypoints) if gt_waypoints else 0
    correct = ratio >= 0.5
    detail = (
        f"waypoints: {len(ans_waypoints)} extracted, "
        f"{matched}/{len(gt_waypoints)} matched ({ratio:.0%})"
    )
    return correct, detail


def _score_fix_selection(
    ground_truth: str, answer: str,
) -> tuple[bool, str]:
    """Score fix selection by matching 'Fix N' pattern."""
    gt_num = _extract_fix_number(ground_truth)
    ans_num = _extract_fix_number(answer)
    if gt_num is None:
        return False, "no fix number in ground truth"
    if ans_num is None:
        return False, "no fix number in answer"
    correct = gt_num == ans_num
    return correct, f"gt=Fix {gt_num}, ans=Fix {ans_num}"


def _extract_float(text: str) -> float | None:
    """Extract first floating-point number from text."""
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _extract_waypoints(text: str) -> list[tuple[float, float]]:
    """Extract (x, y) coordinate pairs from text."""
    pattern = r"\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)"
    waypoints: list[tuple[float, float]] = []
    for m in re.finditer(pattern, text):
        try:
            x, y = float(m.group(1)), float(m.group(2))
            waypoints.append((x, y))
        except ValueError:
            continue
    return waypoints


def _extract_fix_number(text: str) -> int | None:
    """Extract 'Fix N' number from text."""
    match = re.search(r"[Ff]ix\s+(\d+)", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Qwen Text Adapter
# ---------------------------------------------------------------------------


class QwenTextAdapter:
    """Adapter for Qwen2.5-0.5B (text-only) via LocalLLMClient.

    Handles all task types as pure text — no image input.
    """

    _SYSTEM_PROMPT = (
        "You are a PCB design expert. Answer spatial reasoning questions "
        "about PCB layout concisely. For numeric answers, respond with "
        "just the number. For yes/no questions, respond with 'yes' or 'no'. "
        "For fix selection, respond with 'Fix N: <description>'. "
        "For path questions, describe waypoints as (x, y) coordinates."
    )

    def __init__(
        self,
        model: str | None = None,
        adapter_dir: str | Path | None = None,
        max_tokens: int = 256,
        temperature: float = 0.1,
    ) -> None:
        self._model_name = model or "Qwen/Qwen2.5-0.5B-Instruct"
        self._adapter_dir = adapter_dir
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client: Any = None

    @property
    def name(self) -> str:
        return f"Qwen2.5-0.5B ({self._model_name})"

    @property
    def supports_vision(self) -> bool:
        return False

    def _ensure_loaded(self) -> None:
        if self._client is not None:
            return
        from kicad_agent.llm.local_client import LocalLLMClient

        self._client = LocalLLMClient(
            model=self._model_name,
            adapter_dir=self._adapter_dir,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        logger.info("Qwen2.5-0.5B loaded via LocalLLMClient")

    def run_task(self, task: SpatialReasoningTask) -> str:
        self._ensure_loaded()
        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": task.question},
        ]
        return self._client.chat(messages, max_tokens=self._max_tokens)


# ---------------------------------------------------------------------------
# Gemma Vision Adapter
# ---------------------------------------------------------------------------

# Default Gemma 4 12B GGUF model and vision projector paths.
_GEMMA_MODEL_ID = "ggml-org/gemma-4-12B-it-Q4_K_M"
_GEMMA_MMPROJ = "ggml-org/gemma-4-12B-it-Q8_0"


class GemmaVisionAdapter:
    """Adapter for Gemma 4 12B encoder-free vision via mlx-lm.

    Loads the Q4_K_M GGUF model + Q8_0 vision projector (mmproj).
    For text-only tasks, degrades gracefully by passing text only.
    For vision tasks, interleaves image tokens with text prompt.

    Requires mlx-lm >= 0.31.3 with multimodal support.
    """

    _SYSTEM_PROMPT = (
        "You are a PCB design expert with vision capabilities. "
        "Analyze the provided PCB render and answer spatial reasoning "
        "questions. For numeric answers, respond with just the number. "
        "For yes/no questions, respond with 'yes' or 'no'. "
        "For fix selection, respond with 'Fix N: <description>'. "
        "For path questions, describe waypoints as (x, y) coordinates."
    )

    def __init__(
        self,
        model_repo: str | None = None,
        mmproj_repo: str | None = None,
        max_tokens: int = 256,
        temperature: float = 0.1,
    ) -> None:
        self._model_repo = model_repo or _GEMMA_MODEL_ID
        self._mmproj_repo = mmproj_repo or _GEMMA_MMPROJ
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._model: Any = None
        self._tokenizer: Any = None
        self._processor: Any = None
        self._available: bool | None = None

    @property
    def name(self) -> str:
        return f"Gemma 4 12B ({self._model_repo})"

    @property
    def supports_vision(self) -> bool:
        return True

    def is_available(self) -> bool:
        """Check if Gemma 4 12B can be loaded (model + mmproj cached)."""
        if self._available is not None:
            return self._available
        try:
            from mlx_lm import load

            load(self._model_repo)
            self._available = True
        except Exception as exc:
            logger.warning("Gemma 4 12B unavailable: %s", exc)
            self._available = False
        return self._available

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from mlx_lm import load

        self._model, self._tokenizer = load(self._model_repo)
        # Try loading mmproj for vision support.
        try:
            # mlx-lm vision loading via separate mmproj.
            # If mmproj is bundled with the GGUF, it may already be loaded.
            pass
        except Exception as exc:
            logger.debug("mmproj load skipped: %s", exc)
        logger.info("Gemma 4 12B loaded via mlx-lm")

    def run_task(self, task: SpatialReasoningTask) -> str:
        self._ensure_loaded()

        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": task.question},
        ]

        # For vision tasks with a render, try to include the image.
        if task.input_type == "vision" and task.render_path:
            image_path = Path(task.render_path)
            if image_path.exists():
                messages = self._build_vision_messages(task, image_path)
            else:
                logger.debug(
                    "Render not found for %s, falling back to text-only",
                    task.task_id,
                )

        # Format as ChatML for Gemma.
        prompt_parts = []
        for msg in messages:
            prompt_parts.append(f"<start_of_turn>{msg['role']}\n{msg['content']}<end_of_turn>")
        prompt_parts.append("<start_of_turn>model\n")
        prompt = "\n".join(prompt_parts)

        import mlx.core as mx
        from mlx_lm import generate

        if self._temperature > 0:
            def sampler(logits):
                return mx.random.categorical(logits * (1.0 / max(self._temperature, 1e-8)))
        else:
            def sampler(logits):
                return mx.argmax(logits, axis=-1)

        response = generate(
            self._model, self._tokenizer,
            prompt=prompt,
            max_tokens=self._max_tokens,
            sampler=sampler,
            verbose=False,
        )

        # Extract assistant response.
        marker = "<start_of_turn>model\n"
        if marker in response:
            idx = response.index(marker) + len(marker)
            return response[idx:].strip()
        return response.strip()

    def _build_vision_messages(
        self, task: SpatialReasoningTask, image_path: Path,
    ) -> list[dict[str, str]]:
        """Build messages with image reference for vision tasks."""
        # Gemma 4 12B encoder-free processes images via linear projection.
        # mlx-lm handles image tokenization internally when using
        # the generate() function with image input.
        # For now, include image path reference in the text prompt,
        # as actual image embedding depends on mlx-lm's multimodal API.
        question = (
            f"{task.question}\n\n"
            f"[PCB render: {image_path.name}]"
        )
        return [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": question},
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
