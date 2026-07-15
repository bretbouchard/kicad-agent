"""Tests for PCB MMLU benchmark runner and model wrappers.

TDD RED phase: Tests written first, implementations follow.
Covers BaselineRandom, BaselineHeuristic, BenchmarkRunner, and
BenchmarkResult scoring with per-category and per-difficulty breakdowns.
"""

from __future__ import annotations

import json
import tempfile
from typing import Any

import pytest

from volta.benchmarks.schemas import BenchmarkDataset, BenchmarkQuestion


# --- Fixtures ---


def _make_question(
    id_suffix: int = 1,
    category: str = "topology_recognition",
    difficulty: str = "medium",
    question: str = "What type of circuit is formed by U22 and surrounding components?",
    choices: list[str] | None = None,
    correct_index: int = 0,
    source: str = "test.kicad_sch",
) -> BenchmarkQuestion:
    """Helper to create a valid BenchmarkQuestion with defaults."""
    if choices is None:
        choices = ["VCA compressor", "Low-pass filter", "Oscillator", "Power supply"]
    return BenchmarkQuestion(
        id=f"pcb-mmlu-{id_suffix:04d}",
        category=category,
        difficulty=difficulty,
        question=question,
        choices=choices,
        correct_index=correct_index,
        explanation="Test explanation that meets the minimum length requirement.",
        source=source,
        source_type="schematic",
    )


ALL_CATEGORIES = [
    "component_identification",
    "topology_recognition",
    "signal_flow",
    "power_design",
    "pin_function",
    "net_purpose",
    "design_rules",
    "troubleshooting",
]


@pytest.fixture
def small_dataset() -> BenchmarkDataset:
    """Small fixture dataset with 10 questions across all 8 categories + extras."""
    questions: list[BenchmarkQuestion] = []
    for i, cat in enumerate(ALL_CATEGORIES):
        questions.append(
            _make_question(
                id_suffix=i + 1,
                category=cat,
                difficulty="medium",
                question=f"Test question for {cat} category?",
                correct_index=0,
            )
        )
    # Add 2 more for easy/hard coverage
    questions.append(
        _make_question(
            id_suffix=9,
            category="topology_recognition",
            difficulty="easy",
            correct_index=1,
        )
    )
    questions.append(
        _make_question(
            id_suffix=10,
            category="signal_flow",
            difficulty="hard",
            correct_index=2,
        )
    )
    return BenchmarkDataset(
        version="0.1.0",
        generated_at="2026-01-01T00:00:00Z",
        questions=questions,
        metadata={"seed": 42},
    )


@pytest.fixture
def topology_heavy_dataset() -> BenchmarkDataset:
    """Dataset heavy on topology_recognition questions for heuristic testing."""
    questions: list[BenchmarkQuestion] = []
    # topology_recognition questions with amplifier-related text
    for i in range(20):
        questions.append(
            _make_question(
                id_suffix=i + 100,
                category="topology_recognition",
                difficulty="medium",
                question=f"What type of amplifier circuit is formed by the opamp components?",
                choices=["Amplifier stage", "Power supply", "Oscillator", "Filter"],
                correct_index=0,
            )
        )
    # Other categories to fill out
    for j, cat in enumerate(["signal_flow", "power_design", "troubleshooting"]):
        questions.append(
            _make_question(
                id_suffix=200 + j,
                category=cat,
                difficulty="medium",
                correct_index=0,
            )
        )
    return BenchmarkDataset(
        version="0.1.0",
        generated_at="2026-01-01T00:00:00Z",
        questions=questions,
        metadata={},
    )


# ============================================================================
# Test BaselineRandom Model
# ============================================================================


class TestBaselineRandom:
    """Validate BaselineRandom model wrapper."""

    def test_returns_index_in_range(self) -> None:
        """Test 1: BaselineRandom returns index in [0,3] for any question."""
        from volta.benchmarks.models import BaselineRandom

        model = BaselineRandom()
        q = _make_question()
        for _ in range(50):
            result = model.predict(q)
            assert 0 <= result <= 3, f"predict returned {result}, expected 0-3"

    def test_random_distribution(self) -> None:
        """Test 2: BaselineRandom produces roughly uniform distribution over many calls."""
        from volta.benchmarks.models import BaselineRandom

        model = BaselineRandom()
        q = _make_question()
        counts = [0, 0, 0, 0]
        for _ in range(400):
            counts[model.predict(q)] += 1
        # Each bucket should get roughly 100 (within 50% tolerance)
        for i, count in enumerate(counts):
            assert count > 50, f"Bucket {i} got {count}, expected ~100 (within 50%)"

    def test_achieves_approx_25_percent_accuracy(self) -> None:
        """Test 3: BaselineRandom achieves ~25% accuracy on 100+ questions (within 10%)."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        # Build a dataset with 100 questions
        questions = []
        for i in range(100):
            questions.append(
                _make_question(
                    id_suffix=i + 500,
                    category=ALL_CATEGORIES[i % len(ALL_CATEGORIES)],
                    difficulty=["easy", "medium", "hard"][i % 3],
                    correct_index=i % 4,
                )
            )
        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=questions,
            metadata={},
        )
        model = BaselineRandom()
        runner = BenchmarkRunner(dataset, model)
        result = runner.evaluate()
        # Random should be ~25% with 10% tolerance
        assert 0.15 <= result.accuracy <= 0.35, (
            f"Random baseline accuracy {result.accuracy:.2%} outside 15%-35% range"
        )


# ============================================================================
# Test BaselineHeuristic Model
# ============================================================================


class TestBaselineHeuristic:
    """Validate BaselineHeuristic model wrapper."""

    def test_returns_index_in_range(self) -> None:
        """Test 4: BaselineHeuristic returns index in [0,3] for any question."""
        from volta.benchmarks.models import BaselineHeuristic

        model = BaselineHeuristic()
        q = _make_question()
        for _ in range(50):
            result = model.predict(q)
            assert 0 <= result <= 3, f"predict returned {result}, expected 0-3"

    def test_heuristic_beats_random_on_topology(self) -> None:
        """Test 5: BaselineHeuristic achieves >25% accuracy on topology_recognition
        category when questions contain keyword-matching text."""
        from volta.benchmarks.models import BaselineHeuristic
        from volta.benchmarks.runner import BenchmarkRunner

        questions: list[BenchmarkQuestion] = []
        # Create topology questions with amplifier keywords in both question and choices
        for i in range(50):
            questions.append(
                _make_question(
                    id_suffix=i + 600,
                    category="topology_recognition",
                    difficulty="medium",
                    question="What type of amplifier circuit uses an opamp for gain?",
                    choices=["Amplifier stage", "Power supply filter", "Oscillator circuit", "Digital logic"],
                    correct_index=0,
                )
            )
        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=questions,
            metadata={},
        )
        model = BaselineHeuristic()
        runner = BenchmarkRunner(dataset, model)
        result = runner.evaluate()
        # Heuristic should do better than random on topology with keyword-rich questions
        assert result.accuracy > 0.25, (
            f"Heuristic accuracy {result.accuracy:.2%} not > 25% on topology_recognition"
        )

    def test_heuristic_falls_back_to_random(self) -> None:
        """Test 6: BaselineHeuristic falls back to random when no keywords match."""
        from volta.benchmarks.models import BaselineHeuristic

        model = BaselineHeuristic()
        # Question with no recognizable keywords
        q = _make_question(
            question="What is the meaning of life in circuit design philosophy?",
            choices=["Alpha", "Beta", "Gamma", "Delta"],
        )
        results = set()
        for _ in range(50):
            results.add(model.predict(q))
        # Should produce multiple different values (not always same answer)
        assert len(results) > 1, "Heuristic always returns same index for unknown keywords"


# ============================================================================
# Test BenchmarkRunner
# ============================================================================


class TestBenchmarkRunner:
    """Validate BenchmarkRunner evaluation pipeline."""

    def test_evaluate_returns_result_with_correct_total(self, small_dataset: BenchmarkDataset) -> None:
        """Test 7: BenchmarkRunner.evaluate() returns BenchmarkResult with correct total_questions."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate()
        assert result.total_questions == len(small_dataset.questions)

    def test_accuracy_is_correct_ratio(self) -> None:
        """Test 8: BenchmarkResult.accuracy = correct / total."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        # Use deterministic seed for repeatable test
        import random
        random.seed(42)

        questions = []
        for i in range(20):
            questions.append(
                _make_question(
                    id_suffix=i + 700,
                    category="topology_recognition",
                    difficulty="medium",
                    correct_index=0,
                )
            )
        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=questions,
            metadata={},
        )
        model = BaselineRandom()
        runner = BenchmarkRunner(dataset, model)
        result = runner.evaluate()
        assert result.accuracy == result.correct / result.total_questions
        assert abs(result.accuracy - 0.25) < 0.2  # sanity check

    def test_category_accuracy_has_all_categories(self, small_dataset: BenchmarkDataset) -> None:
        """Test 9: BenchmarkResult.category_accuracy has entry for every category in dataset."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate()

        for cat in ALL_CATEGORIES:
            assert cat in result.category_accuracy, f"Missing category: {cat}"
            assert 0.0 <= result.category_accuracy[cat] <= 1.0

    def test_difficulty_accuracy_has_all_levels(self, small_dataset: BenchmarkDataset) -> None:
        """Test 10: BenchmarkResult.difficulty_accuracy has entry for easy/medium/hard."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate()

        for diff in ["easy", "medium", "hard"]:
            assert diff in result.difficulty_accuracy, f"Missing difficulty: {diff}"
            assert 0.0 <= result.difficulty_accuracy[diff] <= 1.0

    def test_empty_dataset_graceful(self) -> None:
        """Test 11: BenchmarkRunner handles empty-filtered dataset gracefully."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        # Create single-question dataset, filter to non-existent category
        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=[_make_question(category="topology_recognition")],
            metadata={},
        )
        model = BaselineRandom()
        runner = BenchmarkRunner(dataset, model)
        result = runner.evaluate(categories=["nonexistent_category"])
        assert result.total_questions == 0
        assert result.correct == 0
        assert result.accuracy == 0.0
        assert result.category_accuracy == {}
        assert result.difficulty_accuracy == {}

    def test_filter_by_category(self, small_dataset: BenchmarkDataset) -> None:
        """Test 12: BenchmarkRunner can filter by category."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate(categories=["topology_recognition"])
        # topology_recognition appears twice in small_dataset (index 1 and 8)
        assert result.total_questions == 2
        assert set(result.category_accuracy.keys()) == {"topology_recognition"}

    def test_filter_by_difficulty(self, small_dataset: BenchmarkDataset) -> None:
        """Test 13: BenchmarkRunner can filter by difficulty."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate(difficulty="easy")
        # Only 1 easy question in small_dataset (id_suffix=9)
        assert result.total_questions == 1
        assert set(result.difficulty_accuracy.keys()) == {"easy"}

    def test_filter_by_max_questions(self, small_dataset: BenchmarkDataset) -> None:
        """Test 14: BenchmarkRunner respects max_questions limit."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate(max_questions=3)
        assert result.total_questions == 3

    def test_result_has_metadata(self, small_dataset: BenchmarkDataset) -> None:
        """Test 15: BenchmarkResult includes model_name, dataset_version, duration, timestamp."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate()

        assert result.model_name == "BaselineRandom"
        assert result.dataset_version == small_dataset.version
        assert result.duration_seconds >= 0.0
        assert result.evaluated_at  # non-empty ISO timestamp


# ============================================================================
# Test BenchmarkResult Schema / Serialization
# ============================================================================


class TestBenchmarkResultSerialization:
    """Validate BenchmarkResult can be serialized and deserialized."""

    def test_result_serializes_to_json(self, small_dataset: BenchmarkDataset) -> None:
        """Test 16: BenchmarkResult serializes to valid JSON."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate()

        json_str = result.model_dump_json()
        parsed = json.loads(json_str)
        assert "model_name" in parsed
        assert "accuracy" in parsed
        assert "category_accuracy" in parsed
        assert "difficulty_accuracy" in parsed
        assert isinstance(parsed["category_accuracy"], dict)

    def test_result_round_trip(self, small_dataset: BenchmarkDataset) -> None:
        """Test 17: BenchmarkResult survives JSON round-trip."""
        from volta.benchmarks.models import BaselineRandom
        from volta.benchmarks.runner import BenchmarkResult, BenchmarkRunner

        model = BaselineRandom()
        runner = BenchmarkRunner(small_dataset, model)
        result = runner.evaluate()

        json_str = result.model_dump_json()
        reloaded = BenchmarkResult.model_validate_json(json_str)
        assert reloaded.model_name == result.model_name
        assert reloaded.accuracy == result.accuracy
        assert reloaded.total_questions == result.total_questions
        assert reloaded.correct == result.correct


# ============================================================================
# Test Model ABC Contract
# ============================================================================


class TestModelContract:
    """Validate model ABC contract."""

    def test_benchmark_model_is_abstract(self) -> None:
        """Test 18: BenchmarkModel cannot be instantiated directly."""
        from volta.benchmarks.models import BenchmarkModel

        with pytest.raises(TypeError):
            BenchmarkModel()  # type: ignore[abstract]

    def test_models_share_base_class(self) -> None:
        """Test 19: Both model classes inherit from BenchmarkModel."""
        from volta.benchmarks.models import BaselineHeuristic, BaselineRandom, BenchmarkModel

        assert issubclass(BaselineRandom, BenchmarkModel)
        assert issubclass(BaselineHeuristic, BenchmarkModel)


# ============================================================================
# Test CLI (Task 2 tests -- written here during RED phase)
# ============================================================================


class TestCLI:
    """Validate CLI entry point."""

    def test_cli_random_model_produces_result(self) -> None:
        """Test 20: CLI --model random writes valid JSON results to output file."""
        from volta.benchmarks.__main__ import main

        # Create temp dataset file
        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=[
                _make_question(id_suffix=i, category=ALL_CATEGORIES[i % 8], difficulty=["easy", "medium", "hard"][i % 3])
                for i in range(20)
            ],
            metadata={},
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as df:
            df.write(dataset.model_dump_json())
            dataset_path = df.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of:
            output_path = of.name

        try:
            import sys

            old_argv = sys.argv
            sys.argv = [
                "benchmarks",
                "--dataset", dataset_path,
                "--model", "random",
                "--output", output_path,
            ]
            try:
                main()
            finally:
                sys.argv = old_argv

            # Verify output JSON
            with open(output_path) as f:
                result = json.load(f)

            assert result["model_name"] == "BaselineRandom"
            assert result["total_questions"] == 20
            assert 0.0 <= result["accuracy"] <= 1.0
            assert "category_accuracy" in result
            assert "difficulty_accuracy" in result
        finally:
            import os

            os.unlink(dataset_path)
            os.unlink(output_path)

    def test_cli_heuristic_model(self) -> None:
        """Test 21: CLI --model heuristic produces valid results."""
        from volta.benchmarks.__main__ import main

        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=[_make_question(id_suffix=i, category=ALL_CATEGORIES[i % 8]) for i in range(10)],
            metadata={},
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as df:
            df.write(dataset.model_dump_json())
            dataset_path = df.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of:
            output_path = of.name

        try:
            import sys

            old_argv = sys.argv
            sys.argv = [
                "benchmarks",
                "--dataset", dataset_path,
                "--model", "heuristic",
                "--output", output_path,
            ]
            try:
                main()
            finally:
                sys.argv = old_argv

            with open(output_path) as f:
                result = json.load(f)

            assert result["model_name"] == "BaselineHeuristic"
            assert result["total_questions"] == 10
        finally:
            import os

            os.unlink(dataset_path)
            os.unlink(output_path)

    def test_cli_with_filters(self) -> None:
        """Test 22: CLI --categories and --difficulty filters work."""
        from volta.benchmarks.__main__ import main

        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=[
                _make_question(id_suffix=1, category="topology_recognition", difficulty="easy"),
                _make_question(id_suffix=2, category="topology_recognition", difficulty="hard"),
                _make_question(id_suffix=3, category="signal_flow", difficulty="easy"),
            ],
            metadata={},
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as df:
            df.write(dataset.model_dump_json())
            dataset_path = df.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of:
            output_path = of.name

        try:
            import sys

            old_argv = sys.argv
            sys.argv = [
                "benchmarks",
                "--dataset", dataset_path,
                "--model", "random",
                "--output", output_path,
                "--categories", "topology_recognition",
                "--difficulty", "easy",
            ]
            try:
                main()
            finally:
                sys.argv = old_argv

            with open(output_path) as f:
                result = json.load(f)

            # Only 1 question matches topology_recognition + easy
            assert result["total_questions"] == 1
        finally:
            import os

            os.unlink(dataset_path)
            os.unlink(output_path)

    def test_cli_max_questions(self) -> None:
        """Test 23: CLI --max-questions limits evaluation."""
        from volta.benchmarks.__main__ import main

        dataset = BenchmarkDataset(
            version="1.0.0",
            generated_at="2026-01-01T00:00:00Z",
            questions=[_make_question(id_suffix=i) for i in range(10)],
            metadata={},
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as df:
            df.write(dataset.model_dump_json())
            dataset_path = df.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of:
            output_path = of.name

        try:
            import sys

            old_argv = sys.argv
            sys.argv = [
                "benchmarks",
                "--dataset", dataset_path,
                "--model", "random",
                "--output", output_path,
                "--max-questions", "3",
            ]
            try:
                main()
            finally:
                sys.argv = old_argv

            with open(output_path) as f:
                result = json.load(f)

            assert result["total_questions"] == 3
        finally:
            import os

            os.unlink(dataset_path)
            os.unlink(output_path)
