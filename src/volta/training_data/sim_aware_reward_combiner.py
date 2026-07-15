"""Phase 159 TRAIN-04: SPICE-aware reward combiner.

Blends physical (SPICE degradation) + geometric (RES routing quality)
+ format scores into a single reward signal for GRPO training.
"""
from __future__ import annotations

from volta.spice.types import DegradationReport


def combine_rewards(
    spice_score: float = 1.0,
    res_score: float = 1.0,
    format_score: float = 1.0,
    weights: dict[str, float] | None = None,
) -> float:
    """Combine multiple reward signals into a single 0.0-1.0 score.

    Args:
        spice_score: SPICE simulation quality (0.0-1.0, from DegradationReport).
        res_score: Routing efficiency score (0.0-1.0, from routing_quality.py).
        format_score: Code format quality (0.0-1.0, from reward.py).
        weights: Optional custom weights (default: equal blend).

    Returns:
        Combined reward score 0.0-1.0.
    """
    w = weights or {"spice": 0.4, "res": 0.3, "format": 0.3}
    total_w = sum(w.values())

    reward = (
        w.get("spice", 0) * spice_score
        + w.get("res", 0) * res_score
        + w.get("format", 0) * format_score
    ) / total_w if total_w > 0 else 0.0

    return max(0.0, min(1.0, reward))


def compute_spice_reward(
    degradation: DegradationReport,
) -> float:
    """Convert a SPICE DegradationReport to a 0.0-1.0 reward.

    Uses the sim_score field which already accounts for gain loss,
    bandwidth reduction, and noise increase.

    Args:
        degradation: Pre vs post-route SPICE degradation report.

    Returns:
        Reward score 0.0-1.0 (1.0 = no degradation).
    """
    return degradation.sim_score


def compute_combined_reward(
    degradation: DegradationReport | None = None,
    res_score: float = 1.0,
    format_score: float = 1.0,
) -> float:
    """Compute the full combined reward from all signals.

    Args:
        degradation: SPICE degradation (None = no SPICE available, use 1.0).
        res_score: Routing quality score.
        format_score: Code format quality.

    Returns:
        Combined reward 0.0-1.0.
    """
    spice = compute_spice_reward(degradation) if degradation else 1.0
    return combine_rewards(spice, res_score, format_score)
