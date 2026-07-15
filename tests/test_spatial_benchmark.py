"""Tests for spatial reasoning benchmark dataset generator.

Validates schemas, task generation, reproducibility, distribution,
and ground-truth accuracy across all six task categories.
"""

from __future__ import annotations

from collections import Counter

import pytest

from volta.analysis.spatial_benchmark import (
    BoardContext,
    Difficulty,
    SpatialReasoningTask,
    TaskCategory,
    TaskGenerator,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestTaskCategoryEnum:
    """Validate TaskCategory enum values."""

    def test_task_category_enum_values(self):
        """TaskCategory has exactly 6 expected members."""
        expected = {
            "coordinate_proximity",
            "routing_feasibility",
            "clearance_diagnosis",
            "net_completion",
            "drc_fix_selection",
            "unrouted_cause",
        }
        actual = {cat.value for cat in TaskCategory}
        assert actual == expected

    def test_task_category_is_str_enum(self):
        """TaskCategory values are strings."""
        for cat in TaskCategory:
            assert isinstance(cat.value, str)


class TestDifficultyEnum:
    """Validate Difficulty enum values."""

    def test_difficulty_enum_values(self):
        """Difficulty has easy, medium, hard."""
        expected = {"easy", "medium", "hard"}
        actual = {d.value for d in Difficulty}
        assert actual == expected

    def test_difficulty_is_str_enum(self):
        """Difficulty values are strings."""
        for d in Difficulty:
            assert isinstance(d.value, str)


class TestBoardContextSchema:
    """Validate BoardContext Pydantic model."""

    def test_board_context_schema(self):
        """BoardContext accepts valid data."""
        ctx = BoardContext(
            component_count=12,
            net_count=8,
            board_bounds_mm=(0.0, 0.0, 85.0, 56.0),
            layer_count=2,
            source_file="synthetic",
        )
        assert ctx.component_count == 12
        assert ctx.net_count == 8
        assert ctx.board_bounds_mm == (0.0, 0.0, 85.0, 56.0)
        assert ctx.layer_count == 2
        assert ctx.source_file == "synthetic"

    def test_board_context_rejects_missing_fields(self):
        """BoardContext requires all fields."""
        with pytest.raises(Exception):
            BoardContext(component_count=5)  # type: ignore[call-arg]


class TestSpatialReasoningTaskSchema:
    """Validate SpatialReasoningTask Pydantic model."""

    def test_spatial_reasoning_task_schema(self):
        """SpatialReasoningTask accepts all fields."""
        ctx = BoardContext(
            component_count=5,
            net_count=3,
            board_bounds_mm=(0.0, 0.0, 50.0, 50.0),
            layer_count=2,
            source_file="test.kicad_pcb",
        )
        task = SpatialReasoningTask(
            task_id="coord_prox_001",
            task_type=TaskCategory.COORDINATE_PROXIMITY,
            difficulty=Difficulty.EASY,
            board_context=ctx,
            question="What is the clearance between pad P1 and pad P2?",
            ground_truth="12.3456",
            input_type="text",
            render_path=None,
            metadata={"source": "test"},
        )
        assert task.task_id == "coord_prox_001"
        assert task.task_type == TaskCategory.COORDINATE_PROXIMITY
        assert task.difficulty == Difficulty.EASY
        assert task.input_type == "text"
        assert task.render_path is None
        assert task.metadata == {"source": "test"}

    def test_spatial_reasoning_task_vision_type(self):
        """Vision tasks have render_path set."""
        ctx = BoardContext(
            component_count=5,
            net_count=3,
            board_bounds_mm=(0.0, 0.0, 50.0, 50.0),
            layer_count=2,
            source_file="test.kicad_pcb",
        )
        task = SpatialReasoningTask(
            task_id="route_feas_001",
            task_type=TaskCategory.ROUTING_FEASIBILITY,
            difficulty=Difficulty.MEDIUM,
            board_context=ctx,
            question="Can net route between pads?",
            ground_truth="yes",
            input_type="vision",
            render_path="renders/route_feas_001.png",
        )
        assert task.input_type == "vision"
        assert task.render_path is not None


# ---------------------------------------------------------------------------
# Generation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def generator():
    """TaskGenerator with synthetic data and fixed seed."""
    return TaskGenerator(pcb_paths=[], seed=42)


@pytest.fixture
def tasks(generator):
    """Full set of generated tasks."""
    return generator.generate_all()


class TestTaskIds:
    """Validate task ID uniqueness."""

    def test_task_has_unique_ids(self, tasks):
        """All task IDs are unique."""
        ids = [t.task_id for t in tasks]
        assert len(ids) == len(set(ids))

    def test_task_ids_follow_pattern(self, tasks):
        """Task IDs follow the category_prefix_NNN pattern."""
        for t in tasks:
            parts = t.task_id.rsplit("_", 1)
            assert len(parts) == 2
            assert parts[1].isdigit() or parts[1] == ""
            # Verify prefix matches category.
            assert t.task_id[0:4] in (
                "coor", "rout", "clea", "net_", "drc_", "unro",
            )


class TestCoordinateProximity:
    """Tests for coordinate_proximity category."""

    def test_generate_coordinate_proximity_tasks(self, tasks):
        """Coordinate proximity tasks are generated."""
        cp_tasks = [t for t in tasks if t.task_type == TaskCategory.COORDINATE_PROXIMITY]
        assert len(cp_tasks) == 30

    def test_coordinate_proximity_ground_truth_accuracy(self, tasks):
        """Ground truth is a valid float distance string."""
        cp_tasks = [t for t in tasks if t.task_type == TaskCategory.COORDINATE_PROXIMITY]
        for task in cp_tasks:
            # Ground truth must be parseable as a float.
            value = float(task.ground_truth)
            assert value >= 0.0, f"Distance must be non-negative, got {value}"
            assert task.input_type == "text"

    def test_coordinate_proximity_question_format(self, tasks):
        """Questions mention clearance and mm."""
        cp_tasks = [t for t in tasks if t.task_type == TaskCategory.COORDINATE_PROXIMITY]
        for task in cp_tasks:
            assert "clearance" in task.question.lower() or "mm" in task.question.lower()


class TestRoutingFeasibility:
    """Tests for routing_feasibility category."""

    def test_generate_routing_feasibility_tasks(self, tasks):
        """Routing feasibility tasks are generated."""
        rf_tasks = [t for t in tasks if t.task_type == TaskCategory.ROUTING_FEASIBILITY]
        assert len(rf_tasks) == 27

    def test_routing_feasibility_covers_vision_type(self, tasks):
        """All routing feasibility tasks are vision type with render path."""
        rf_tasks = [t for t in tasks if t.task_type == TaskCategory.ROUTING_FEASIBILITY]
        for task in rf_tasks:
            assert task.input_type == "vision"
            assert task.render_path is not None
            assert task.ground_truth in ("yes", "no")


class TestClearanceDiagnosis:
    """Tests for clearance_diagnosis category."""

    def test_generate_clearance_diagnosis_tasks(self, tasks):
        """Clearance diagnosis tasks are generated."""
        cd_tasks = [t for t in tasks if t.task_type == TaskCategory.CLEARANCE_DIAGNOSIS]
        assert len(cd_tasks) == 27

    def test_clearance_diagnosis_text_type(self, tasks):
        """Clearance diagnosis tasks are text type."""
        cd_tasks = [t for t in tasks if t.task_type == TaskCategory.CLEARANCE_DIAGNOSIS]
        for task in cd_tasks:
            assert task.input_type == "text"

    def test_clearance_diagnosis_ground_truth_not_empty(self, tasks):
        """Ground truth provides a meaningful diagnosis."""
        cd_tasks = [t for t in tasks if t.task_type == TaskCategory.CLEARANCE_DIAGNOSIS]
        for task in cd_tasks:
            assert len(task.ground_truth) > 20
            assert any(
                kw in task.ground_truth.lower()
                for kw in (
                    "violation", "rule", "clearance", "keepout", "overlap",
                    "insufficient", "short circuit", "annular", "below",
                    "manufacturing", "prohibited", "drill", "soldering",
                )
            ), f"Ground truth lacks diagnostic keywords: {task.ground_truth}"


class TestNetCompletion:
    """Tests for net_completion category."""

    def test_generate_net_completion_tasks(self, tasks):
        """Net completion tasks are generated."""
        nc_tasks = [t for t in tasks if t.task_type == TaskCategory.NET_COMPLETION]
        assert len(nc_tasks) == 27

    def test_net_completion_vision_type(self, tasks):
        """Net completion tasks are vision type."""
        nc_tasks = [t for t in tasks if t.task_type == TaskCategory.NET_COMPLETION]
        for task in nc_tasks:
            assert task.input_type == "vision"
            assert task.render_path is not None

    def test_net_completion_ground_truth_has_route(self, tasks):
        """Ground truth includes route or path information."""
        nc_tasks = [t for t in tasks if t.task_type == TaskCategory.NET_COMPLETION]
        for task in nc_tasks:
            gt_lower = task.ground_truth.lower()
            assert "route" in gt_lower or "mm" in gt_lower


class TestDrcFixSelection:
    """Tests for drc_fix_selection category."""

    def test_generate_drc_fix_selection_tasks(self, tasks):
        """DRC fix selection tasks are generated."""
        df_tasks = [t for t in tasks if t.task_type == TaskCategory.DRC_FIX_SELECTION]
        assert len(df_tasks) == 27

    def test_drc_fix_selection_vision_type(self, tasks):
        """DRC fix selection tasks are vision type."""
        df_tasks = [t for t in tasks if t.task_type == TaskCategory.DRC_FIX_SELECTION]
        for task in df_tasks:
            assert task.input_type == "vision"
            assert task.render_path is not None


class TestUnroutedCause:
    """Tests for unrouted_cause category."""

    def test_generate_unrouted_cause_tasks(self, tasks):
        """Unrouted cause tasks are generated."""
        uc_tasks = [t for t in tasks if t.task_type == TaskCategory.UNROUTED_CAUSE]
        assert len(uc_tasks) == 24

    def test_unrouted_cause_ground_truth_not_empty(self, tasks):
        """Ground truth identifies a specific blocking feature."""
        uc_tasks = [t for t in tasks if t.task_type == TaskCategory.UNROUTED_CAUSE]
        for task in uc_tasks:
            assert len(task.ground_truth) > 10
            assert task.input_type == "vision"
            assert task.render_path is not None


class TestDistribution:
    """Validate difficulty and category distributions."""

    def test_generate_all_distribution(self, tasks):
        """Difficulty distribution is roughly 20/60/20."""
        counts = Counter(t.difficulty for t in tasks)
        total = len(tasks)

        easy_pct = counts[Difficulty.EASY] / total
        med_pct = counts[Difficulty.MEDIUM] / total
        hard_pct = counts[Difficulty.HARD] / total

        # Allow 5% tolerance for rounding.
        assert 0.15 <= easy_pct <= 0.25, f"Easy: {easy_pct:.2%}"
        assert 0.55 <= med_pct <= 0.65, f"Medium: {med_pct:.2%}"
        assert 0.15 <= hard_pct <= 0.25, f"Hard: {hard_pct:.2%}"

    def test_generate_all_reproducible_with_seed(self):
        """Same seed produces identical tasks."""
        gen1 = TaskGenerator(pcb_paths=[], seed=42)
        gen2 = TaskGenerator(pcb_paths=[], seed=42)
        tasks1 = gen1.generate_all()
        tasks2 = gen2.generate_all()

        assert len(tasks1) == len(tasks2)
        for t1, t2 in zip(tasks1, tasks2):
            assert t1.task_id == t2.task_id
            assert t1.ground_truth == t2.ground_truth
            assert t1.question == t2.question

    def test_different_seeds_produce_different_tasks(self):
        """Different seeds produce different task sets."""
        gen1 = TaskGenerator(pcb_paths=[], seed=42)
        gen2 = TaskGenerator(pcb_paths=[], seed=99)
        tasks1 = gen1.generate_all()
        tasks2 = gen2.generate_all()

        # At least some ground truths should differ.
        gt1 = {t.ground_truth for t in tasks1}
        gt2 = {t.ground_truth for t in tasks2}
        assert gt1 != gt2, "Different seeds should produce different results"

    def test_generate_all_count_minimum_150(self, tasks):
        """Total task count is at least 150."""
        assert len(tasks) >= 150

    def test_all_categories_present(self, tasks):
        """All 6 categories have at least 1 task."""
        cats = {t.task_type for t in tasks}
        assert len(cats) == 6

    def test_all_tasks_have_nonempty_ground_truth(self, tasks):
        """No task has an empty ground truth."""
        for task in tasks:
            assert task.ground_truth.strip(), f"Empty ground truth for {task.task_id}"

    def test_all_tasks_have_nonempty_question(self, tasks):
        """No task has an empty question."""
        for task in tasks:
            assert task.question.strip(), f"Empty question for {task.task_id}"

    def test_vision_tasks_have_render_path(self, tasks):
        """Vision tasks always have a render_path set."""
        for task in tasks:
            if task.input_type == "vision":
                assert task.render_path is not None, f"Vision task {task.task_id} missing render_path"
                assert task.render_path.endswith(".png")
