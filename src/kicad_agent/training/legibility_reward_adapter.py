"""LegibilityRewardAdapter — bridges Plan 01 reward module into GRPO (Plan 04).

Composes:
  - Plan 01 LegibilityReward (D-01 weighted sum from CritiqueResult.factors)
  - Plan 01 D-04 caps (CompactnessCap, CrossingsFloorCap) via CapInputs
  - Phase 109 CritiqueResult (SHIPPED — consumed directly per CR-110-01)
  - D-03 multi-objective combine (correctness + completeness + legibility)

Hardening:
  - CR-110-01: CritiqueResult is the SHIPPED Phase 109 type. Consumed directly.
  - CR-110-04: Caps consume CapInputs (value object with bbox/footprint/crossing_count).
  - HI-110-05: completeness_source is explicit — "none" collapses weight into
    correctness. v1 trains as 0.8*correctness + 0.2*legibility.
  - LO-110-11: malformed critique (missing factor, out-of-range value) is
    caught here. Returns 0.0 with a logged warning. Training never crashes
    on a single bad critique.

Frozen per Phase 100 CR-01.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, TYPE_CHECKING

from kicad_agent.training.rewards import (
    CapInputs,
    CompactnessCap,
    CrossingsFloorCap,
    LegibilityReward,
)

if TYPE_CHECKING:
    from kicad_agent.analysis.legibility_critic import CritiqueResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RewardWeights:
    """Multi-objective reward weights per CONTEXT.md D-03.

    Must sum to 1.0 (validated at construction).

    Attributes:
        correctness: Weight for (format + quality + accuracy) / 3 score.
        completeness: Weight for layout completeness (HI-110-05 source-gated).
        legibility: Weight for SRS legibility score (Plan 01 reward module).
    """

    correctness: float = 0.40
    completeness: float = 0.40
    legibility: float = 0.20

    def __post_init__(self) -> None:
        total = self.correctness + self.completeness + self.legibility
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"reward_weights must sum to 1.0, got {total}"
            )


@dataclass(frozen=True)
class LegibilityRewardAdapter:
    """Bridges Plan 01 LegibilityReward + D-04 caps + Phase 109 CritiqueResult into GRPO.

    CR-110-01: CritiqueResult is the SHIPPED Phase 109 type — consumed directly.
    CR-110-04: Caps consume CapInputs (value object with bbox/footprint/crossing_count).
    HI-110-05: completeness_source is explicit — "none" collapses weight into correctness.
    LO-110-11: malformed critique (missing factor, out-of-range value) is caught
        here — returns 0.0 with a logged warning. Training never crashes on a
        single bad critique.

    Frozen per Phase 100 CR-01.

    Attributes:
        base_reward: LegibilityReward instance (D-01 weighted sum).
        compactness_cap: D-04 cap 1 — penalize infinite spread.
        crossings_floor_cap: D-04 cap 2 — penalize over-routing.
        weights: RewardWeights for D-03 multi-objective combine.
        completeness_source: HI-110-05 — "none" (default), "layout_result", or "fixed_value".
        completeness_fixed_value: Used only when completeness_source="fixed_value".
    """

    base_reward: LegibilityReward
    compactness_cap: CompactnessCap
    crossings_floor_cap: CrossingsFloorCap
    weights: RewardWeights = field(default_factory=RewardWeights)
    completeness_source: str = "none"  # HI-110-05: "none" | "layout_result" | "fixed_value"
    completeness_fixed_value: float = 0.5  # only used when completeness_source="fixed_value"

    def compute_legibility(
        self,
        critique: "CritiqueResult",
        cap_inputs: CapInputs,
    ) -> float:
        """Compute the legibility term from a Phase 109 CritiqueResult + CapInputs.

        LO-110-11: malformed critique (missing factor, out-of-range) is caught
        here — returns 0.0 with a logged warning. Training never crashes on a
        single bad critique.
        """
        try:
            base = self.base_reward.score(critique.factors_view())
            compactness_mult = self.compactness_cap.penalty(cap_inputs)
            crossings_mult = self.crossings_floor_cap.penalty(cap_inputs)
            return base * compactness_mult * crossings_mult
        except (KeyError, ValueError) as exc:
            logger.warning(
                "compute_legibility malformed critique (model_used=%s): %s: %s — "
                "returning 0.0, training continues",
                getattr(critique, "model_used", "unknown"),
                type(exc).__name__, exc,
            )
            return 0.0

    def combine(
        self,
        correctness: float,
        completeness: Optional[float],
        legibility: float,
    ) -> float:
        """Combine the three terms per D-03 weights.

        HI-110-05: when completeness_source="none" OR completeness is None,
        the completeness weight folds into correctness. v1 trains as
        0.8*correctness + 0.2*legibility.
        """
        if self.completeness_source == "none" or completeness is None:
            # Fold completeness weight into correctness (HI-110-05)
            folded_correctness_weight = self.weights.correctness + self.weights.completeness
            return folded_correctness_weight * correctness + self.weights.legibility * legibility
        return (
            self.weights.correctness * correctness
            + self.weights.completeness * completeness
            + self.weights.legibility * legibility
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "LegibilityRewardAdapter":
        """Parse config.json training block, construct adapter.

        Expected config shape (see Plan 04 interfaces):
            {
                "training": {
                    "reward_weights": {correctness, completeness, legibility},
                    "completeness_source": "none" | "layout_result" | "fixed_value",
                    "legibility_factor_weights": {density, clarity, spacing, organization},
                    "anti_hack": {
                        "compactness_threshold_ratio": 2.0,
                        "crossings_floor_min": 1,
                        "crossings_floor_multiplier": 0.3,
                        "alignment_jitter_mm": 0.1
                    }
                }
            }
        """
        training = dict(config.get("training", {}))
        weights_block = dict(training.get("reward_weights", {}))
        weights = RewardWeights(
            correctness=weights_block.get("correctness", 0.40),
            completeness=weights_block.get("completeness", 0.40),
            legibility=weights_block.get("legibility", 0.20),
        )
        factor_weights = dict(training.get("legibility_factor_weights", {}))
        anti_hack = dict(training.get("anti_hack", {}))
        return cls(
            base_reward=(
                LegibilityReward(weights=factor_weights)
                if factor_weights
                else LegibilityReward()
            ),
            compactness_cap=CompactnessCap(
                threshold_ratio=anti_hack.get("compactness_threshold_ratio", 2.0),
            ),
            crossings_floor_cap=CrossingsFloorCap(
                min_crossings=anti_hack.get("crossings_floor_min", 1),
                floor_multiplier=anti_hack.get("crossings_floor_multiplier", 0.3),
            ),
            weights=weights,
            completeness_source=training.get("completeness_source", "none"),
            completeness_fixed_value=training.get("completeness_fixed_value", 0.5),
        )
