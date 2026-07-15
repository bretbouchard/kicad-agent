"""Types, scoring, and reporting schemas for the spatial reasoning benchmark.

These were originally part of ``benchmark_runner.py`` (768 LOC). Split out
to keep each module under the 400-LOC soft budget (``~/.claude/rules/
coding-style.md``). Re-exported from ``benchmark_runner.py`` for backward
compatibility — existing imports continue to work unchanged.

Public surface:
    - ModelAdapter (Protocol)
    - TaskResult, CategoryScore, BenchmarkReport (dataclasses)
    - score_task + private scoring helpers (re-exported for tests)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from volta.analysis.spatial_benchmark import (
    SpatialReasoningTask,
    TaskCategory,
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
