"""Tests for spatial reasoning benchmark runner, scoring, model adapters, and report generation.

Tests the Phase 80-02 benchmark runner that evaluates Qwen2.5-0.5B and
Gemma 4 12B against the 162 spatial reasoning tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from kicad_agent.analysis.benchmark_runner import (
    BenchmarkReport,
    BenchmarkRunner,
    CategoryScore,
    GemmaVisionAdapter,
    ModelAdapter,
    QwenTextAdapter,
    TaskResult,
    _extract_fix_number,
    _extract_float,
    _extract_waypoints,
    _recommend_model,
    score_task,
)
from kicad_agent.analysis.spatial_benchmark import (
    BoardContext,
    Difficulty,
    SpatialReasoningTask,
    TaskCategory,
    TaskGenerator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DEFAULT_CTX = BoardContext(
    component_count=12,
    net_count=8,
    board_bounds_mm=(0.0, 0.0, 85.0, 56.0),
    layer_count=2,
    source_file="synthetic",
)


def _make_task(
    task_id: str = "test_001",
    category: TaskCategory = TaskCategory.COORDINATE_PROXIMITY,
    question: str = "What is the clearance?",
    ground_truth: str = "1.5000",
    input_type: str = "text",
    render_path: str | None = None,
    difficulty: Difficulty = Difficulty.MEDIUM,
) -> SpatialReasoningTask:
    return SpatialReasoningTask(
        task_id=task_id,
        task_type=category,
        difficulty=difficulty,
        board_context=_DEFAULT_CTX,
        question=question,
        ground_truth=ground_truth,
        input_type=input_type,
        render_path=render_path,
    )


@dataclass
class MockAdapter:
    """Test double for ModelAdapter."""

    _name: str = "mock-model"
    _supports_vision: bool = False
    _answers: dict[str, str] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_vision(self) -> bool:
        return self._supports_vision

    def run_task(self, task: SpatialReasoningTask) -> str:
        if self._answers and task.task_id in self._answers:
            return self._answers[task.task_id]
        return "mock answer"


# ---------------------------------------------------------------------------
# Answer Extraction Tests
# ---------------------------------------------------------------------------


class TestExtractFloat:
    def test_integer(self):
        assert _extract_float("42") == 42.0

    def test_decimal(self):
        assert _extract_float("3.14159") == pytest.approx(3.14159)

    def test_negative(self):
        assert _extract_float("-2.5") == pytest.approx(-2.5)

    def test_scientific(self):
        assert _extract_float("1.5e-3") == pytest.approx(0.0015)

    def test_in_text(self):
        result = _extract_float("The clearance is 1.2345mm")
        assert result == pytest.approx(1.2345)

    def test_no_number(self):
        assert _extract_float("no numbers here") is None

    def test_empty(self):
        assert _extract_float("") is None


class TestExtractWaypoints:
    def test_single_waypoint(self):
        result = _extract_waypoints("(45.0, 22.0)")
        assert len(result) == 1
        assert result[0] == pytest.approx((45.0, 22.0))

    def test_multiple_waypoints(self):
        text = "Route via (10.0, 20.0) -> (30.0, 40.0) -> (50.0, 60.0)"
        result = _extract_waypoints(text)
        assert len(result) == 3
        assert result[0] == pytest.approx((10.0, 20.0))
        assert result[2] == pytest.approx((50.0, 60.0))

    def test_no_waypoints(self):
        assert _extract_waypoints("no coordinates") == []

    def test_negative_coords(self):
        result = _extract_waypoints("(-5.5, -3.2)")
        assert result[0] == pytest.approx((-5.5, -3.2))


class TestExtractFixNumber:
    def test_fix_0(self):
        assert _extract_fix_number("Fix 0: increase pad") == 0

    def test_fix_2(self):
        assert _extract_fix_number("Fix 2: move component") == 2

    def test_lowercase_fix(self):
        assert _extract_fix_number("fix 1: route trace") == 1

    def test_no_fix(self):
        assert _extract_fix_number("no fix mentioned") is None


# ---------------------------------------------------------------------------
# Scoring Tests
# ---------------------------------------------------------------------------


class TestScoreNumeric:
    def test_exact_match(self):
        correct, detail = score_task(
            _make_task(ground_truth="1.5000"), "1.5000"
        )
        assert correct is True
        assert "gt=1.5000" in detail

    def test_within_tolerance(self):
        correct, _ = score_task(
            _make_task(ground_truth="1.5000"), "1.6000"
        )
        assert correct is True  # 6.7% error, within 10%

    def test_outside_tolerance(self):
        correct, _ = score_task(
            _make_task(ground_truth="1.5000"), "2.0000"
        )
        assert correct is False  # 33% error, exceeds 10%

    def test_completely_wrong(self):
        correct, _ = score_task(
            _make_task(ground_truth="1.5000"), "100.0"
        )
        assert correct is False

    def test_parse_failure(self):
        correct, detail = score_task(
            _make_task(ground_truth="1.5000"), "unknown"
        )
        assert correct is False
        assert "parse failed" in detail


class TestScoreYesNo:
    def test_yes_correct(self):
        task = _make_task(
            category=TaskCategory.ROUTING_FEASIBILITY,
            ground_truth="yes",
        )
        correct, _ = score_task(task, "Yes, the route is feasible")
        assert correct is True

    def test_no_correct(self):
        task = _make_task(
            category=TaskCategory.ROUTING_FEASIBILITY,
            ground_truth="no",
        )
        correct, _ = score_task(task, "No, the route is blocked")
        assert correct is True

    def test_yes_but_gt_no(self):
        task = _make_task(
            category=TaskCategory.ROUTING_FEASIBILITY,
            ground_truth="no",
        )
        correct, _ = score_task(task, "Yes it can route")
        assert correct is False


class TestScoreKeywordOverlap:
    def test_good_overlap(self):
        task = _make_task(
            category=TaskCategory.CLEARANCE_DIAGNOSIS,
            ground_truth=(
                "Adjacent pads are placed too close together, "
                "violating the minimum pad-to-pad clearance rule."
            ),
        )
        answer = "The pads are too close, violating pad-to-pad clearance."
        correct, _ = score_task(task, answer)
        assert correct is True

    def test_poor_overlap(self):
        task = _make_task(
            category=TaskCategory.CLEARANCE_DIAGNOSIS,
            ground_truth="Adjacent pads are placed too close together",
        )
        correct, _ = score_task(task, "The board needs more vias")
        assert correct is False

    def test_unrouted_cause(self):
        task = _make_task(
            category=TaskCategory.UNROUTED_CAUSE,
            ground_truth=(
                "A component footprint blocks the direct path between "
                "source and target pads."
            ),
        )
        answer = "A footprint component blocks the path between pads"
        correct, _ = score_task(task, answer)
        assert correct is True


class TestScorePath:
    def test_waypoint_match(self):
        task = _make_task(
            category=TaskCategory.NET_COMPLETION,
            ground_truth=(
                "Route via waypoints: (10.0, 20.0) -> (30.0, 40.0). "
                "Length: 28.28mm."
            ),
        )
        answer = "Go from (10.0, 20.0) to (30.0, 40.0)"
        correct, detail = score_task(task, answer)
        assert correct is True
        assert "2/2" in detail

    def test_partial_waypoint_match(self):
        task = _make_task(
            category=TaskCategory.NET_COMPLETION,
            ground_truth=(
                "Route via waypoints: (10.0, 20.0) -> (30.0, 40.0) -> (50.0, 60.0)."
            ),
        )
        answer = "Waypoints: (10.0, 20.0) and (50.0, 60.0)"
        correct, detail = score_task(task, answer)
        assert correct is True  # 2/3 >= 50%

    def test_no_waypoints_in_answer(self):
        task = _make_task(
            category=TaskCategory.NET_COMPLETION,
            ground_truth="Route via waypoints: (10.0, 20.0).",
        )
        correct, detail = score_task(task, "direct path")
        assert correct is False
        assert "no waypoints" in detail


class TestScoreFixSelection:
    def test_correct_fix(self):
        task = _make_task(
            category=TaskCategory.DRC_FIX_SELECTION,
            ground_truth="Fix 1: Route a trace between pin U1.5 and pin R3.2",
        )
        answer = "I recommend Fix 1: Route a trace"
        correct, detail = score_task(task, answer)
        assert correct is True
        assert "gt=Fix 1" in detail

    def test_wrong_fix(self):
        task = _make_task(
            category=TaskCategory.DRC_FIX_SELECTION,
            ground_truth="Fix 0: Increase pad clearance",
        )
        answer = "Fix 2: remove the net"
        correct, _ = score_task(task, answer)
        assert correct is False


# ---------------------------------------------------------------------------
# Model Adapter Tests
# ---------------------------------------------------------------------------


class TestQwenTextAdapter:
    def test_name(self):
        adapter = QwenTextAdapter()
        assert "Qwen2.5-0.5B" in adapter.name

    def test_no_vision(self):
        adapter = QwenTextAdapter()
        assert adapter.supports_vision is False

    def test_custom_model(self):
        adapter = QwenTextAdapter(model="custom/model")
        assert "custom/model" in adapter.name


class TestGemmaVisionAdapter:
    def test_name(self):
        adapter = GemmaVisionAdapter()
        assert "Gemma 4 12B" in adapter.name

    def test_supports_vision(self):
        adapter = GemmaVisionAdapter()
        assert adapter.supports_vision is True

    def test_custom_model(self):
        adapter = GemmaVisionAdapter(model_repo="custom/gemma")
        assert "custom/gemma" in adapter.name


class TestModelAdapterProtocol:
    def test_mock_adapter_satisfies_protocol(self):
        mock = MockAdapter()
        assert isinstance(mock, ModelAdapter)

    def test_qwen_satisfies_protocol(self):
        adapter = QwenTextAdapter()
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "supports_vision")
        assert hasattr(adapter, "run_task")

    def test_gemma_satisfies_protocol(self):
        adapter = GemmaVisionAdapter()
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "supports_vision")
        assert hasattr(adapter, "run_task")


# ---------------------------------------------------------------------------
# BenchmarkRunner Tests
# ---------------------------------------------------------------------------


class TestBenchmarkRunner:
    def test_run_with_mock_adapter(self):
        adapter = MockAdapter(_answers={"coord_prox_001": "1.5000"})
        task = _make_task(
            task_id="coord_prox_001",
            ground_truth="1.5000",
        )
        runner = BenchmarkRunner(adapters=[adapter])
        report = runner.run(tasks=[task])
        assert len(report.results) == 1
        assert report.results[0].correct is True
        assert report.total_tasks == 1

    def test_skip_vision_for_text_adapter(self):
        text_adapter = MockAdapter(_name="text-only", _supports_vision=False)
        vision_task = _make_task(
            task_id="vision_001",
            input_type="vision",
        )
        runner = BenchmarkRunner(adapters=[text_adapter])
        report = runner.run(tasks=[vision_task])
        assert len(report.results) == 0  # skipped

    def test_vision_adapter_runs_vision_tasks(self):
        vision_adapter = MockAdapter(
            _name="vision-model",
            _supports_vision=True,
        )
        vision_task = _make_task(
            task_id="vision_001",
            input_type="vision",
        )
        runner = BenchmarkRunner(adapters=[vision_adapter])
        report = runner.run(tasks=[vision_task])
        assert len(report.results) == 1

    def test_multiple_adapters(self):
        a1 = MockAdapter(_name="model-a", _answers={"t1": "yes"})
        a2 = MockAdapter(_name="model-b", _answers={"t1": "no"})
        task = _make_task(
            task_id="t1",
            category=TaskCategory.ROUTING_FEASIBILITY,
            ground_truth="yes",
        )
        runner = BenchmarkRunner(adapters=[a1, a2])
        report = runner.run(tasks=[task])
        assert len(report.results) == 2
        assert report.results[0].correct is True   # model-a: yes
        assert report.results[1].correct is False  # model-b: no

    def test_skip_categories(self):
        adapter = MockAdapter(_answers={"t1": "1.5"})
        task = _make_task(
            task_id="t1",
            category=TaskCategory.COORDINATE_PROXIMITY,
        )
        runner = BenchmarkRunner(
            adapters=[adapter],
            skip_categories={TaskCategory.COORDINATE_PROXIMITY},
        )
        report = runner.run(tasks=[task])
        assert len(report.results) == 0

    def test_error_handling(self):
        failing = MockAdapter(_name="failing")
        failing.run_task = MagicMock(side_effect=RuntimeError("OOM"))
        task = _make_task(task_id="err_001")
        runner = BenchmarkRunner(adapters=[failing])
        report = runner.run(tasks=[task])
        assert len(report.results) == 1
        assert report.results[0].correct is False
        assert "OOM" in report.results[0].score_detail

    def test_aggregate_scores(self):
        adapter = MockAdapter(_name="m1")
        tasks = [
            _make_task(
                task_id="c1",
                category=TaskCategory.COORDINATE_PROXIMITY,
                ground_truth="1.0",
            ),
            _make_task(
                task_id="c2",
                category=TaskCategory.COORDINATE_PROXIMITY,
                ground_truth="2.0",
            ),
        ]
        runner = BenchmarkRunner(adapters=[adapter])
        report = runner.run(tasks=tasks)
        assert len(report.category_scores) == 1
        score = report.category_scores[0]
        assert score.category == "coordinate_proximity"
        assert score.total == 2
        assert score.model_name == "m1"


class TestBenchmarkReport:
    def test_to_markdown(self):
        results = [
            TaskResult(
                task_id="t1",
                model_name="model-a",
                answer="1.5",
                ground_truth="1.5000",
                correct=True,
                latency_ms=100.0,
                category="coordinate_proximity",
                difficulty="medium",
                input_type="text",
            ),
            TaskResult(
                task_id="t2",
                model_name="model-a",
                answer="wrong",
                ground_truth="2.0",
                correct=False,
                latency_ms=120.0,
                category="coordinate_proximity",
                difficulty="easy",
                input_type="text",
            ),
        ]
        report = BenchmarkReport(
            results=results,
            total_tasks=2,
            total_duration_s=1.0,
        )
        report.category_scores = [
            BenchmarkRunner._aggregate(results)[0],
        ]
        md = report.to_markdown()
        assert "# Spatial Reasoning Model Assessment" in md
        assert "coordinate_proximity" in md
        assert "Decision Matrix" in md

    def test_recommend_model(self):
        scores = [
            CategoryScore("cat_a", "model-x", 10, 8, 0.8, 100.0),
            CategoryScore("cat_a", "model-y", 10, 5, 0.5, 200.0),
        ]
        rec = _recommend_model(scores, "cat_a", ["model-x", "model-y"])
        assert "model-x" in rec
        assert "80%" in rec


# ---------------------------------------------------------------------------
# Integration: Full Pipeline Test
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Test the full generate -> run -> score -> report pipeline."""

    def test_pipeline_with_synthetic_data(self):
        gen = TaskGenerator(seed=42)
        tasks = gen.generate_all()

        adapter = MockAdapter(
            _name="synthetic-model",
            _supports_vision=True,
            # Return ground truth as answer for all tasks (perfect scorer).
            _answers={t.task_id: t.ground_truth for t in tasks},
        )

        # Only run first 10 tasks to keep test fast.
        subset = tasks[:10]
        runner = BenchmarkRunner(adapters=[adapter])
        report = runner.run(tasks=subset)

        assert report.total_tasks == 10
        assert len(report.results) == 10
        # All should be correct since we return ground truth.
        correct_count = sum(1 for r in report.results if r.correct)
        assert correct_count >= 8  # At least 80% for GT-matched answers
        assert "Spatial Reasoning Model Assessment" in report.to_markdown()
