"""Inference confidence scoring for best-of-N chain selection.

Provides InferenceConfidence dataclass and compute_confidence() function
that quantify agreement and variance across N generated chains. Confidence
metrics are advisory -- low confidence does not block output (T-79-03).

Usage:
    from volta.inference.confidence_scorer import InferenceConfidence, compute_confidence

    confidence = compute_confidence([0.85, 0.82, 0.87, 0.84])
    print(confidence.overall)  # 0.0-1.0
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceConfidence:
    """Confidence metrics for an inference result.

    Computed from the composite scores of N independently generated chains.
    High confidence means the chains agree on the output quality.

    Attributes:
        agreement_ratio: How much the N chains agree (1.0=all identical,
            0.0=maximum disagreement). Derived from std_dev normalized by
            the theoretical maximum for scores in [0, 1].
        score_variance: Statistical variance of composite scores across chains.
            0.0 for identical scores, higher values indicate disagreement.
        n_chains: Number of chains that were generated.
        overall: Weighted confidence combining agreement (weight 0.6) and
            inverse variance (weight 0.4). Range [0, 1].
    """

    agreement_ratio: float
    score_variance: float
    n_chains: int
    overall: float


def compute_confidence(scores: list[float]) -> InferenceConfidence:
    """Compute confidence metrics from a list of composite scores.

    Args:
        scores: List of composite scores from N independently generated chains.

    Returns:
        InferenceConfidence with agreement_ratio, score_variance, n_chains,
        and overall metrics.

    Raises:
        ValueError: If scores list is empty.
    """
    if not scores:
        raise ValueError("scores list must not be empty")

    n = len(scores)

    if n == 1:
        return InferenceConfidence(
            agreement_ratio=1.0,
            score_variance=0.0,
            n_chains=1,
            overall=1.0,
        )

    # Variance: standard statistical variance
    variance = statistics.variance(scores) if n > 1 else 0.0

    # Agreement ratio: 1.0 - (std_dev / max_possible_std)
    # Max possible std when scores span [0, 1] is 0.5 (half the range)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    max_possible_std = 0.5
    agreement_ratio = max(0.0, 1.0 - (std_dev / max_possible_std))

    # Overall: weighted combination of agreement and inverse variance
    # Inverse variance component: 1.0 - min(variance * 4.0, 1.0)
    # variance=0 -> 1.0, variance=0.25 -> 0.0
    inverse_variance_component = 1.0 - min(variance * 4.0, 1.0)
    overall = agreement_ratio * 0.6 + inverse_variance_component * 0.4
    overall = max(0.0, min(1.0, overall))

    return InferenceConfidence(
        agreement_ratio=agreement_ratio,
        score_variance=variance,
        n_chains=n,
        overall=overall,
    )
