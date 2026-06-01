"""Regression detection for benchmark pipeline.

Provides RegressionDetector for comparing benchmark results against baselines
and RegressionReport for representing comparison outcomes. Historical results
are stored as timestamped JSON files in a configurable results directory.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from kicad_agent.benchmarks.runner import BenchmarkResult


class RegressionReport(BaseModel):
    """Comparison report between current and baseline benchmark results.

    Attributes:
        current: The benchmark result being evaluated.
        baseline: The baseline result to compare against.
        delta: Per-category accuracy change (current - baseline).
        overall_delta: Overall accuracy change (current.accuracy - baseline.accuracy).
        is_regression: True if any category dropped beyond the threshold.
        regression_categories: Categories that regressed beyond the threshold.
    """

    current: BenchmarkResult
    baseline: BenchmarkResult
    delta: dict[str, float]
    overall_delta: float
    is_regression: bool
    regression_categories: list[str]


class RegressionDetector:
    """Detects accuracy regressions by comparing benchmark results against a baseline.

    Compares per-category accuracy between current and baseline results, flagging
    any category that drops beyond a configurable threshold (default 2%).
    Supports historical tracking via timestamped JSON files and baseline management.

    Usage:
        detector = RegressionDetector()
        report = detector.compare(current_result, baseline_result)
        if report.is_regression:
            print(f"Regressed: {report.regression_categories}")
    """

    def __init__(
        self,
        results_dir: str = "benchmarks/results",
        threshold: float = 0.02,
    ) -> None:
        """Initialize detector with results directory and regression threshold.

        Args:
            results_dir: Directory for storing historical results and baseline.
            threshold: Maximum acceptable accuracy drop per category (default 0.02 = 2%).
        """
        self.results_dir = Path(results_dir)
        self.threshold = threshold

    def compare(
        self, current: BenchmarkResult, baseline: BenchmarkResult
    ) -> RegressionReport:
        """Compare current result against baseline and produce a regression report.

        Computes per-category accuracy deltas and flags any category that drops
        more than the configured threshold. Categories present in current but not
        in baseline are treated as improvements (baseline accuracy = 0). Categories
        present in baseline but not in current are treated as regressions (current
        accuracy = 0).

        Args:
            current: The benchmark result to evaluate.
            baseline: The baseline result to compare against.

        Returns:
            RegressionReport with deltas, regression flag, and affected categories.
        """
        delta: dict[str, float] = {}
        regression_categories: list[str] = []

        all_categories = set(
            list(baseline.category_accuracy.keys())
            + list(current.category_accuracy.keys())
        )

        for cat in all_categories:
            base_acc = baseline.category_accuracy.get(cat, 0.0)
            curr_acc = current.category_accuracy.get(cat, 0.0)
            diff = curr_acc - base_acc
            delta[cat] = round(diff, 4)
            if diff < -self.threshold:
                regression_categories.append(cat)

        return RegressionReport(
            current=current,
            baseline=baseline,
            delta=delta,
            overall_delta=round(current.accuracy - baseline.accuracy, 4),
            is_regression=len(regression_categories) > 0,
            regression_categories=regression_categories,
        )

    def store_result(self, result: BenchmarkResult) -> Path:
        """Store a benchmark result as a timestamped JSON file.

        Creates the results directory if it does not exist. The filename
        includes the model name and sanitized timestamp for sortability.

        Args:
            result: The benchmark result to store.

        Returns:
            Path to the created JSON file.
        """
        self.results_dir.mkdir(parents=True, exist_ok=True)
        # Sanitize timestamp for filesystem (replace colons and dots with dashes)
        ts = result.evaluated_at.replace(":", "-").replace(".", "-")
        path = self.results_dir / f"{result.model_name}_{ts}.json"
        path.write_text(result.model_dump_json(indent=2))
        return path

    def load_history(self) -> list[BenchmarkResult]:
        """Load all stored results sorted by filename (chronological order).

        Returns:
            List of BenchmarkResult objects sorted by filename.
        """
        results: list[BenchmarkResult] = []
        for path in sorted(self.results_dir.glob("*.json")):
            if path.name == "baseline.json":
                continue
            results.append(BenchmarkResult.model_validate_json(path.read_text()))
        return results

    def load_baseline(self) -> BenchmarkResult:
        """Load the baseline result from the results directory.

        Returns:
            The baseline BenchmarkResult.

        Raises:
            FileNotFoundError: If baseline.json does not exist in results_dir.
        """
        baseline_path = self.results_dir / "baseline.json"
        if not baseline_path.exists():
            raise FileNotFoundError(
                f"Baseline file not found: {baseline_path}"
            )
        return BenchmarkResult.model_validate_json(baseline_path.read_text())

    def set_baseline(self, result: BenchmarkResult) -> None:
        """Update the baseline with the given result.

        Creates the results directory if it does not exist. Overwrites
        any existing baseline.

        Args:
            result: The benchmark result to set as the new baseline.
        """
        self.results_dir.mkdir(parents=True, exist_ok=True)
        (self.results_dir / "baseline.json").write_text(
            result.model_dump_json(indent=2)
        )
