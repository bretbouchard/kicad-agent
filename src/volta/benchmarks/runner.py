"""Benchmark runner for evaluating models against PCB MMLU dataset.

Provides BenchmarkResult (scored evaluation output) and BenchmarkRunner
(evaluation engine). The runner evaluates any BenchmarkModel against
a BenchmarkDataset, producing per-category and per-difficulty accuracy
breakdowns.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from volta.benchmarks.schemas import BenchmarkDataset, BenchmarkQuestion

if TYPE_CHECKING:
    from volta.benchmarks.models import BenchmarkModel


class BenchmarkResult(BaseModel):
    """Scored evaluation result from running a model against a benchmark.

    Attributes:
        model_name: Class name of the evaluated model.
        dataset_version: Version string from the benchmark dataset.
        total_questions: Number of questions evaluated.
        correct: Number of correctly answered questions.
        accuracy: Overall accuracy (correct / total_questions), 0.0 for empty.
        category_accuracy: Per-category accuracy breakdown.
        difficulty_accuracy: Per-difficulty accuracy breakdown.
        evaluated_at: ISO 8601 timestamp of evaluation.
        duration_seconds: Wall-clock time of evaluation in seconds.
    """

    model_name: str
    dataset_version: str
    total_questions: int
    correct: int
    accuracy: float = Field(ge=0.0, le=1.0)
    category_accuracy: dict[str, float] = Field(default_factory=dict)
    difficulty_accuracy: dict[str, float] = Field(default_factory=dict)
    evaluated_at: str
    duration_seconds: float = Field(ge=0.0)


def _compute_accuracy(values: list[bool]) -> float:
    """Compute accuracy from a list of boolean correctness indicators.

    Args:
        values: List of True/False indicating correct/incorrect predictions.

    Returns:
        Fraction of True values, or 0.0 if the list is empty.
    """
    if not values:
        return 0.0
    return sum(values) / len(values)


class BenchmarkRunner:
    """Evaluation engine that runs a model against a benchmark dataset.

    Evaluates a BenchmarkModel by calling predict() on each question,
    comparing predictions to correct_index, and computing overall,
    per-category, and per-difficulty accuracy.

    Usage:
        model = BaselineRandom()
        dataset = BenchmarkDataset.from_json("benchmarks/pcb-mmlu-v1.json")
        runner = BenchmarkRunner(dataset, model)
        result = runner.evaluate()
        print(f"Accuracy: {result.accuracy:.1%}")
    """

    def __init__(self, dataset: BenchmarkDataset, model: BenchmarkModel) -> None:
        """Initialize runner with dataset and model.

        Args:
            dataset: The benchmark dataset to evaluate against.
            model: The model to evaluate.
        """
        self.dataset = dataset
        self.model = model

    def evaluate(
        self,
        categories: list[str] | None = None,
        difficulty: str | None = None,
        max_questions: int | None = None,
    ) -> BenchmarkResult:
        """Run evaluation and return scored results.

        Args:
            categories: If provided, only evaluate questions in these categories.
            difficulty: If provided, only evaluate questions at this difficulty level.
            max_questions: If provided, limit evaluation to this many questions.

        Returns:
            BenchmarkResult with accuracy breakdowns.
        """
        start = time.time()

        questions = self._filter_questions(
            self.dataset.questions,
            categories=categories,
            difficulty=difficulty,
            max_questions=max_questions,
        )

        correct = 0
        category_results: dict[str, list[bool]] = {}
        difficulty_results: dict[str, list[bool]] = {}

        for q in questions:
            predicted = self.model.predict(q)
            # Threat model T-41-02-01: validate predicted index is in [0,3]
            is_correct = predicted == q.correct_index if 0 <= predicted <= 3 else False

            if is_correct:
                correct += 1

            category_results.setdefault(q.category, []).append(is_correct)
            difficulty_results.setdefault(q.difficulty, []).append(is_correct)

        duration = time.time() - start

        return BenchmarkResult(
            model_name=self.model.__class__.__name__,
            dataset_version=self.dataset.version,
            total_questions=len(questions),
            correct=correct,
            accuracy=correct / len(questions) if questions else 0.0,
            category_accuracy={
                cat: _compute_accuracy(vals) for cat, vals in category_results.items()
            },
            difficulty_accuracy={
                diff: _compute_accuracy(vals) for diff, vals in difficulty_results.items()
            },
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(duration, 2),
        )

    @staticmethod
    def _filter_questions(
        questions: list[BenchmarkQuestion],
        categories: list[str] | None = None,
        difficulty: str | None = None,
        max_questions: int | None = None,
    ) -> list[BenchmarkQuestion]:
        """Filter questions by category, difficulty, and count.

        Args:
            questions: Full list of benchmark questions.
            categories: Optional category filter.
            difficulty: Optional difficulty filter.
            max_questions: Optional maximum number of questions.

        Returns:
            Filtered list of questions.
        """
        filtered = questions
        if categories:
            category_set = set(categories)
            filtered = [q for q in filtered if q.category in category_set]
        if difficulty:
            filtered = [q for q in filtered if q.difficulty == difficulty]
        if max_questions is not None and max_questions > 0:
            filtered = filtered[:max_questions]
        return filtered
