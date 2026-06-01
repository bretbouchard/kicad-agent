"""Tests for regression detection in benchmark pipeline.

Covers RegressionDetector comparison, RegressionReport schema validation,
historical tracking with file storage, and CLI workflow validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_agent.benchmarks.runner import BenchmarkResult
from kicad_agent.benchmarks.regression import RegressionDetector, RegressionReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASELINE = BenchmarkResult(
    model_name="BaselineHeuristic",
    dataset_version="1.0.0",
    total_questions=500,
    correct=200,
    accuracy=0.40,
    category_accuracy={
        "topology_recognition": 0.50,
        "troubleshooting": 0.30,
        "component_identification": 0.60,
    },
    difficulty_accuracy={"easy": 0.60, "medium": 0.35, "hard": 0.20},
    evaluated_at="2026-01-01T00:00:00",
    duration_seconds=10.0,
)

# Improved: topology up 5%, troubleshooting same
IMPROVED = BenchmarkResult(
    model_name="ImprovedModel",
    dataset_version="1.0.0",
    total_questions=500,
    correct=210,
    accuracy=0.42,
    category_accuracy={
        "topology_recognition": 0.55,
        "troubleshooting": 0.30,
        "component_identification": 0.63,
    },
    difficulty_accuracy={"easy": 0.65, "medium": 0.35, "hard": 0.22},
    evaluated_at="2026-02-01T00:00:00",
    duration_seconds=12.0,
)

# Regressed: troubleshooting drops 5% (below 2% threshold)
REGRESSED = BenchmarkResult(
    model_name="RegressedModel",
    dataset_version="1.0.0",
    total_questions=500,
    correct=190,
    accuracy=0.38,
    category_accuracy={
        "topology_recognition": 0.50,
        "troubleshooting": 0.25,
        "component_identification": 0.58,
    },
    difficulty_accuracy={"easy": 0.55, "medium": 0.30, "hard": 0.18},
    evaluated_at="2026-03-01T00:00:00",
    duration_seconds=11.0,
)

# Within threshold: troubleshooting drops only 1% (within 2% threshold)
MARGINAL = BenchmarkResult(
    model_name="MarginalModel",
    dataset_version="1.0.0",
    total_questions=500,
    correct=200,
    accuracy=0.40,
    category_accuracy={
        "topology_recognition": 0.50,
        "troubleshooting": 0.29,
        "component_identification": 0.60,
    },
    difficulty_accuracy={"easy": 0.60, "medium": 0.35, "hard": 0.20},
    evaluated_at="2026-04-01T00:00:00",
    duration_seconds=10.5,
)

# Has a new category not present in baseline
WITH_NEW_CATEGORY = BenchmarkResult(
    model_name="NewCatModel",
    dataset_version="1.0.0",
    total_questions=600,
    correct=250,
    accuracy=0.4167,
    category_accuracy={
        "topology_recognition": 0.50,
        "troubleshooting": 0.30,
        "component_identification": 0.60,
        "signal_flow": 0.45,  # New category not in baseline
    },
    difficulty_accuracy={"easy": 0.60, "medium": 0.35, "hard": 0.20},
    evaluated_at="2026-05-01T00:00:00",
    duration_seconds=13.0,
)


# ---------------------------------------------------------------------------
# TestRegressionReport -- Report schema validation
# ---------------------------------------------------------------------------


class TestRegressionReport:
    """Tests for RegressionReport Pydantic model."""

    def test_report_has_required_fields(self) -> None:
        """RegressionReport has current, baseline, delta, overall_delta,
        is_regression, regression_categories fields."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert hasattr(report, "current")
        assert hasattr(report, "baseline")
        assert hasattr(report, "delta")
        assert hasattr(report, "overall_delta")
        assert hasattr(report, "is_regression")
        assert hasattr(report, "regression_categories")

    def test_report_current_is_current_result(self) -> None:
        """Report stores the current result."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert report.current.model_name == "ImprovedModel"

    def test_report_baseline_is_baseline_result(self) -> None:
        """Report stores the baseline result."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert report.baseline.model_name == "BaselineHeuristic"

    def test_report_delta_is_dict(self) -> None:
        """Delta is a dict mapping category names to float accuracy changes."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert isinstance(report.delta, dict)
        for key, value in report.delta.items():
            assert isinstance(key, str)
            assert isinstance(value, float)

    def test_report_overall_delta_is_float(self) -> None:
        """Overall delta is a float."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert isinstance(report.overall_delta, float)

    def test_report_is_regression_is_bool(self) -> None:
        """is_regression is a boolean."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert isinstance(report.is_regression, bool)

    def test_report_regression_categories_is_list(self) -> None:
        """regression_categories is a list of strings."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert isinstance(report.regression_categories, list)
        for cat in report.regression_categories:
            assert isinstance(cat, str)


# ---------------------------------------------------------------------------
# TestRegressionDetector -- Comparison and detection tests
# ---------------------------------------------------------------------------


class TestRegressionDetector:
    """Tests for RegressionDetector compare and detection logic."""

    def test_compare_returns_regression_report(self) -> None:
        """compare() returns a RegressionReport instance."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert isinstance(report, RegressionReport)

    def test_improved_no_regression(self) -> None:
        """When all categories improve or stay the same, is_regression is False."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert report.is_regression is False

    def test_regressed_flags_regression(self) -> None:
        """When a category drops > threshold, is_regression is True."""
        detector = RegressionDetector()
        report = detector.compare(REGRESSED, BASELINE)
        assert report.is_regression is True

    def test_marginal_no_regression(self) -> None:
        """When category drops but within threshold, is_regression is False."""
        detector = RegressionDetector()
        report = detector.compare(MARGINAL, BASELINE)
        assert report.is_regression is False

    def test_regressed_categories_list(self) -> None:
        """regression_categories lists only categories that dropped beyond threshold."""
        detector = RegressionDetector()
        report = detector.compare(REGRESSED, BASELINE)
        assert "troubleshooting" in report.regression_categories
        # topology stayed at 0.50 -> not regressed
        assert "topology_recognition" not in report.regression_categories

    def test_delta_values_correct(self) -> None:
        """Delta per category is computed as current - baseline, rounded to 4 decimals."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert report.delta["topology_recognition"] == 0.05
        assert report.delta["troubleshooting"] == 0.0
        assert report.delta["component_identification"] == pytest.approx(0.03)

    def test_overall_accuracy_delta(self) -> None:
        """Overall delta is current.accuracy - baseline.accuracy."""
        detector = RegressionDetector()
        report = detector.compare(IMPROVED, BASELINE)
        assert report.overall_delta == pytest.approx(0.02)

    def test_overall_accuracy_delta_regressed(self) -> None:
        """Overall delta is negative when overall accuracy drops."""
        detector = RegressionDetector()
        report = detector.compare(REGRESSED, BASELINE)
        assert report.overall_delta == pytest.approx(-0.02)

    def test_missing_categories_in_baseline(self) -> None:
        """New category in current not in baseline is treated as improvement (delta from 0)."""
        detector = RegressionDetector()
        report = detector.compare(WITH_NEW_CATEGORY, BASELINE)
        # signal_flow is new (baseline=0, current=0.45) -> not a regression
        assert report.delta["signal_flow"] == 0.45
        assert "signal_flow" not in report.regression_categories

    def test_missing_categories_in_current(self) -> None:
        """Category in baseline but missing in current is treated as drop to 0."""
        # Swap so baseline has a category current doesn't
        detector = RegressionDetector()
        report = detector.compare(BASELINE, WITH_NEW_CATEGORY)
        # signal_flow exists in WITH_NEW_CATEGORY but not in BASELINE (current)
        assert report.delta["signal_flow"] == -0.45
        assert "signal_flow" in report.regression_categories

    def test_custom_threshold(self) -> None:
        """Custom threshold of 0.01 flags marginal as regression."""
        detector = RegressionDetector(threshold=0.01)
        report = detector.compare(MARGINAL, BASELINE)
        # troubleshooting dropped 1% (0.30 -> 0.29), threshold is 1%
        assert report.is_regression is True
        assert "troubleshooting" in report.regression_categories

    def test_default_threshold_is_two_percent(self) -> None:
        """Default threshold is 0.02 (2%)."""
        detector = RegressionDetector()
        assert detector.threshold == 0.02

    def test_empty_category_accuracy(self) -> None:
        """Handles empty category_accuracy dicts without error."""
        detector = RegressionDetector()
        empty_current = BenchmarkResult(
            model_name="Empty",
            dataset_version="1.0.0",
            total_questions=0,
            correct=0,
            accuracy=0.0,
            category_accuracy={},
            difficulty_accuracy={},
            evaluated_at="2026-01-01T00:00:00",
            duration_seconds=0.0,
        )
        empty_baseline = BenchmarkResult(
            model_name="EmptyBase",
            dataset_version="1.0.0",
            total_questions=0,
            correct=0,
            accuracy=0.0,
            category_accuracy={},
            difficulty_accuracy={},
            evaluated_at="2026-01-01T00:00:00",
            duration_seconds=0.0,
        )
        report = detector.compare(empty_current, empty_baseline)
        assert report.is_regression is False
        assert report.delta == {}
        assert report.regression_categories == []


# ---------------------------------------------------------------------------
# TestHistoricalTracking -- Store/load tests with temp directory
# ---------------------------------------------------------------------------


class TestHistoricalTracking:
    """Tests for storing and loading historical benchmark results."""

    def test_store_result_creates_file(self, tmp_path: Path) -> None:
        """store_result() writes a JSON file in results_dir."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        path = detector.store_result(BASELINE)
        assert path.exists()
        assert path.suffix == ".json"

    def test_stored_result_round_trips(self, tmp_path: Path) -> None:
        """Stored result can be loaded back and matches original."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        detector.store_result(BASELINE)
        history = detector.load_history()
        assert len(history) == 1
        assert history[0].model_name == BASELINE.model_name
        assert history[0].accuracy == BASELINE.accuracy

    def test_load_history_sorted_by_date(self, tmp_path: Path) -> None:
        """load_history() returns results sorted by filename (date order)."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        detector.store_result(REGRESSED)   # 2026-03-01
        detector.store_result(BASELINE)    # 2026-01-01
        detector.store_result(IMPROVED)    # 2026-02-01
        history = detector.load_history()
        assert len(history) == 3
        # Sorted by filename, which starts with model_name then timestamp
        names = [r.model_name for r in history]
        assert names == ["BaselineHeuristic", "ImprovedModel", "RegressedModel"]

    def test_store_result_returns_path(self, tmp_path: Path) -> None:
        """store_result() returns the Path to the created file."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        path = detector.store_result(BASELINE)
        assert isinstance(path, Path)
        assert path.parent == tmp_path

    def test_store_creates_results_dir(self, tmp_path: Path) -> None:
        """store_result() creates results_dir if it doesn't exist."""
        nested = tmp_path / "results" / "deep"
        detector = RegressionDetector(results_dir=str(nested))
        detector.store_result(BASELINE)
        assert nested.exists()

    def test_set_baseline_creates_file(self, tmp_path: Path) -> None:
        """set_baseline() creates baseline.json in results_dir."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        detector.set_baseline(BASELINE)
        baseline_path = tmp_path / "baseline.json"
        assert baseline_path.exists()

    def test_set_baseline_round_trips(self, tmp_path: Path) -> None:
        """Baseline can be set and loaded back."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        detector.set_baseline(BASELINE)
        loaded = detector.load_baseline()
        assert loaded.model_name == BASELINE.model_name
        assert loaded.accuracy == BASELINE.accuracy
        assert loaded.category_accuracy == BASELINE.category_accuracy

    def test_set_baseline_overwrites(self, tmp_path: Path) -> None:
        """set_baseline() overwrites existing baseline."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        detector.set_baseline(BASELINE)
        detector.set_baseline(IMPROVED)
        loaded = detector.load_baseline()
        assert loaded.model_name == IMPROVED.model_name

    def test_load_history_empty_dir(self, tmp_path: Path) -> None:
        """load_history() returns empty list when no results stored."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        history = detector.load_history()
        assert history == []

    def test_load_baseline_file_missing_raises(self, tmp_path: Path) -> None:
        """load_baseline() raises FileNotFoundError when no baseline file."""
        detector = RegressionDetector(results_dir=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            detector.load_baseline()


# ---------------------------------------------------------------------------
# TestCIWorkflow -- CI workflow file validation
# ---------------------------------------------------------------------------


class TestCIWorkflow:
    """Tests for the GitHub Actions benchmark workflow."""

    def test_workflow_file_exists(self) -> None:
        """benchmark.yml workflow file exists."""
        workflow_path = Path(".github/workflows/benchmark.yml")
        assert workflow_path.exists()

    def test_workflow_is_valid_yaml(self) -> None:
        """Workflow file is valid YAML."""
        import yaml

        workflow_path = Path(".github/workflows/benchmark.yml")
        content = workflow_path.read_text()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)
        assert "name" in parsed

    def test_workflow_triggers_on_pull_request(self) -> None:
        """Workflow triggers on pull_request events."""
        import yaml

        workflow_path = Path(".github/workflows/benchmark.yml")
        parsed = yaml.safe_load(workflow_path.read_text())
        assert "on" in parsed
        on_config = parsed["on"]
        assert "pull_request" in on_config

    def test_workflow_has_benchmark_job(self) -> None:
        """Workflow has a benchmark job."""
        import yaml

        workflow_path = Path(".github/workflows/benchmark.yml")
        parsed = yaml.safe_load(workflow_path.read_text())
        assert "jobs" in parsed
        assert "benchmark" in parsed["jobs"]

    def test_workflow_checks_out_code(self) -> None:
        """Workflow includes checkout step."""
        import yaml

        workflow_path = Path(".github/workflows/benchmark.yml")
        parsed = yaml.safe_load(workflow_path.read_text())
        steps = parsed["jobs"]["benchmark"]["steps"]
        step_uses = [s.get("uses", "") for s in steps if "uses" in s]
        assert any("checkout" in u for u in step_uses)

    def test_workflow_runs_regression_check(self) -> None:
        """Workflow includes a regression check step."""
        import yaml

        workflow_path = Path(".github/workflows/benchmark.yml")
        parsed = yaml.safe_load(workflow_path.read_text())
        steps = parsed["jobs"]["benchmark"]["steps"]
        step_names = [s.get("name", "").lower() for s in steps if "name" in s]
        assert any("regression" in n for n in step_names)


# ---------------------------------------------------------------------------
# TestBaselineFile -- Baseline result file validation
# ---------------------------------------------------------------------------


class TestBaselineFile:
    """Tests for the baseline result file."""

    def test_baseline_file_exists(self) -> None:
        """benchmarks/results/baseline.json exists."""
        baseline_path = Path("benchmarks/results/baseline.json")
        assert baseline_path.exists()

    def test_baseline_file_valid_json(self) -> None:
        """baseline.json contains valid JSON."""
        baseline_path = Path("benchmarks/results/baseline.json")
        content = baseline_path.read_text()
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_baseline_file_validates_as_result(self) -> None:
        """baseline.json validates as a BenchmarkResult."""
        baseline_path = Path("benchmarks/results/baseline.json")
        content = baseline_path.read_text()
        result = BenchmarkResult.model_validate_json(content)
        assert result.model_name
        assert result.dataset_version
        assert 0.0 <= result.accuracy <= 1.0
        assert result.total_questions > 0
