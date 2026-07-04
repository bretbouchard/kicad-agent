"""LegibilityReward — weighted-sum reward from Phase 109 CritiqueResult.factors.

D-01 (Phase 110 CONTEXT.md): reward = 0.25*density + 0.25*clarity +
0.25*spacing + 0.25*organization. Matches Phase 48.5 SRS factor weighting
exactly so the model optimizes the same metric the verifier checks.

Pure compute — no I/O, no model calls, no imports from legibility_critic.
Consumes any Mapping[str, float]; Plan 04's adapter calls
CritiqueResult.factors_view() and passes the resulting MappingProxyType here.

Frozen per Phase 100 CR-01.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class LegibilityReward:
    """Weighted-sum legibility reward from CritiqueResult.factors (D-01).

    Per CONTEXT.md D-01: reward = 0.25*density + 0.25*clarity +
    0.25*spacing + 0.25*organization. Matches Phase 48.5 SRS factor
    weighting exactly. Consumes the factors Mapping from a Phase 109
    CritiqueResult — call .factors_view() first for immutability per
    MED-02 Option B.

    Frozen per Phase 100 CR-01. Pure compute — no I/O, no model calls.

    Attributes:
        weights: Per-factor weights. MUST sum to 1.0 (validated at
            construction). Default is uniform 0.25 per D-01.
    """

    weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "density": 0.25,
            "clarity": 0.25,
            "spacing": 0.25,
            "organization": 0.25,
        }
    )

    def __post_init__(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"weights must sum to 1.0, got {total}"
            )
        for k in ("density", "clarity", "spacing", "organization"):
            if k not in self.weights:
                raise ValueError(f"missing required weight {k!r}")

    def score(self, factors: Mapping[str, float]) -> float:
        """Return the weighted sum of factor scores.

        Args:
            factors: Mapping with keys density/clarity/spacing/organization.
                Values MUST be floats in [0.0, 1.0]. Accepts a MappingProxyType
                (CritiqueResult.factors_view() return value) or a plain dict.

        Returns:
            Weighted-sum reward in [0.0, 1.0].

        Raises:
            KeyError: If any of the 4 factor keys is missing. The error
                message names the missing factor (fail fast — no silent
                defaults that could mask a broken CritiqueResult).
            ValueError: If any factor value is outside [0.0, 1.0].
        """
        # Validate all 4 keys present (fail fast on malformed CritiqueResult)
        for k in self.weights:
            if k not in factors:
                raise KeyError(f"missing factor {k!r} in factors Mapping")
        # Validate each value in [0.0, 1.0]
        for k in self.weights:
            v = float(factors[k])
            if v < 0.0 or v > 1.0:
                raise ValueError(
                    f"factor {k!r} must be in [0.0, 1.0], got {v}"
                )
        # Return weighted sum
        return sum(self.weights[k] * float(factors[k]) for k in self.weights)
