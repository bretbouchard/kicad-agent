"""Phase 110 reward module — LegibilityReward + D-04 anti-hack caps + CapInputs.

Public API:
    LegibilityReward — weighted-sum reward from CritiqueResult.factors (D-01)
    CompactnessCap — D-04 cap 1: penalize layouts where bbox >> footprint
    CrossingsFloorCap — D-04 cap 2: penalize suspiciously low crossing counts
    AlignmentJitter — D-04 cap 3: ±amplitude_mm perturbation (data augmentation)
    CapInputs — value object carrying bbox/footprint/crossing_count (CR-110-04)
"""
from __future__ import annotations

from kicad_agent.training.rewards.legibility import LegibilityReward
from kicad_agent.training.rewards.cap_inputs import CapInputs
from kicad_agent.training.rewards.anti_hack import (
    AlignmentJitter,
    CompactnessCap,
    CrossingsFloorCap,
)

__all__ = [
    "LegibilityReward",
    "CompactnessCap",
    "CrossingsFloorCap",
    "AlignmentJitter",
    "CapInputs",
]
