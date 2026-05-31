"""Evaluation regression detection for training runs.

TRAIN-02: Detects when evaluation metrics drop below configurable thresholds
compared to baseline. Provides baseline persistence for cross-run comparison.

Usage:
    from kicad_agent.training.regression import detect_regression, BaselineStore

    result = detect_regression(baseline_eval, current_eval)
    if result.is_regression:
        print("Regression detected:", result.regressions)

    store = BaselineStore()
    result = store.compare_or_update("model_v1", current_eval)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.training.evaluation import EvalResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegressionThresholds:
    """Thresholds for flagging metric regressions.

    Attributes:
        max_reward_drop: Maximum acceptable drop in avg_reward.
        max_accuracy_drop: Maximum acceptable drop in avg_accuracy.
        max_pass_rate_drop: Maximum acceptable drop in pass_rate.
    """

    max_reward_drop: float = 0.05
    max_accuracy_drop: float = 0.10
    max_pass_rate_drop: float = 0.05


@dataclass(frozen=True)
class RegressionResult:
    """Result of regression detection between two evaluations.

    Attributes:
        is_regression: True if any metric dropped below its threshold.
        regressions: Human-readable descriptions of flagged regressions.
        baseline: The baseline EvalResult.
        current: The current EvalResult.
        deltas: Computed deltas for each metric (negative = drop).
    """

    is_regression: bool
    regressions: list[str]
    baseline: EvalResult
    current: EvalResult
    deltas: dict[str, float]


def detect_regression(
    baseline: EvalResult,
    current: EvalResult,
    thresholds: RegressionThresholds = RegressionThresholds(),
) -> RegressionResult:
    """Detect regression by comparing current metrics against baseline.

    Args:
        baseline: Previous evaluation result.
        current: New evaluation result.
        thresholds: Configurable thresholds for each metric.

    Returns:
        RegressionResult with regression status and details.
    """
    deltas: dict[str, float] = {
        "reward": current.avg_reward - baseline.avg_reward,
        "accuracy": current.avg_accuracy - baseline.avg_accuracy,
        "pass_rate": current.pass_rate - baseline.pass_rate,
    }

    regressions: list[str] = []

    if deltas["reward"] < -thresholds.max_reward_drop:
        regressions.append(
            f"Reward dropped by {abs(deltas['reward']):.4f} "
            f"(threshold: {thresholds.max_reward_drop:.4f})"
        )

    if deltas["accuracy"] < -thresholds.max_accuracy_drop:
        regressions.append(
            f"Accuracy dropped by {abs(deltas['accuracy']):.4f} "
            f"(threshold: {thresholds.max_accuracy_drop:.4f})"
        )

    if deltas["pass_rate"] < -thresholds.max_pass_rate_drop:
        regressions.append(
            f"Pass rate dropped by {abs(deltas['pass_rate']):.4f} "
            f"(threshold: {thresholds.max_pass_rate_drop:.4f})"
        )

    return RegressionResult(
        is_regression=len(regressions) > 0,
        regressions=regressions,
        baseline=baseline,
        current=current,
        deltas=deltas,
    )


class BaselineStore:
    """Persist and compare evaluation baselines across training runs.

    Stores EvalResult objects as JSON files on disk for cross-run comparison.

    Args:
        store_dir: Directory for baseline JSON files.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        if store_dir is None:
            store_dir = Path("training_output/baselines/")
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def save_baseline(self, name: str, result: EvalResult) -> Path:
        """Save an EvalResult as a baseline.

        Args:
            name: Baseline identifier (e.g., model name).
            result: Evaluation result to persist.

        Returns:
            Path to saved baseline file.
        """
        path = self.store_dir / f"{name}_baseline.json"
        data = {
            "model_name": result.model_name,
            "n_samples": result.n_samples,
            "avg_reward": result.avg_reward,
            "avg_accuracy": result.avg_accuracy,
            "coordinate_coverage": result.coordinate_coverage,
            "chain_length_mean": result.chain_length_mean,
            "chain_length_std": result.chain_length_std,
            "pass_rate": result.pass_rate,
            "discrimination_gap": result.discrimination_gap,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved baseline '%s' to %s", name, path)
        return path

    def load_baseline(self, name: str) -> EvalResult | None:
        """Load a baseline EvalResult by name.

        Args:
            name: Baseline identifier.

        Returns:
            EvalResult if found, None otherwise.
        """
        from kicad_agent.training.evaluation import EvalResult

        path = self.store_dir / f"{name}_baseline.json"
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return EvalResult(
            model_name=data["model_name"],
            n_samples=data["n_samples"],
            avg_reward=data["avg_reward"],
            avg_accuracy=data["avg_accuracy"],
            coordinate_coverage=data["coordinate_coverage"],
            chain_length_mean=data["chain_length_mean"],
            chain_length_std=data["chain_length_std"],
            pass_rate=data["pass_rate"],
            discrimination_gap=data.get("discrimination_gap", 0.0),
        )

    def compare_or_update(
        self,
        name: str,
        current: EvalResult,
        thresholds: RegressionThresholds = RegressionThresholds(),
    ) -> RegressionResult:
        """Compare current result against stored baseline, update if improved.

        If no baseline exists, saves current as the new baseline.
        If current is not a regression, saves current as the new baseline.
        If regression detected, keeps the existing baseline.

        Args:
            name: Baseline identifier.
            current: Current evaluation result.
            thresholds: Regression thresholds.

        Returns:
            RegressionResult with comparison details.
        """
        baseline = self.load_baseline(name)

        if baseline is None:
            # First run: save current as baseline, no regression possible
            self.save_baseline(name, current)
            return RegressionResult(
                is_regression=False,
                regressions=[],
                baseline=current,
                current=current,
                deltas={},
            )

        result = detect_regression(baseline, current, thresholds)

        if not result.is_regression:
            # Improved or within threshold: update baseline
            self.save_baseline(name, current)
            logger.info("Updated baseline '%s' (no regression)", name)
        else:
            logger.warning(
                "Regression detected for '%s': %s",
                name,
                "; ".join(result.regressions),
            )

        return result
