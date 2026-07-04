"""D-04 anti-reward-hacking caps (Phase 107 RESEARCH.md §6).

Three caps close the documented reward-hacking vectors:

  1. CompactnessCap (§6 Pitfall 6: infinite-spread hacking):
     Penalize layouts where bounding box >> component footprint area.
     Returns multiplier in (0.0, 1.0]; 1.0 = no penalty. Uses tanh
     smoothing (no discontinuous cliffs per reward_hacking.smooth_penalty).

  2. CrossingsFloorCap (§6 Pitfall: over-routing):
     Penalize suspiciously low crossing counts. Zero crossings often
     means the model routed around everything to minimize crossings.
     Returns multiplier in {floor_multiplier, 1.0}.

  3. AlignmentJitter (§6 Pitfall: grid over-fitting):
     ±amplitude_mm perturbation during training (data augmentation).
     NOT a penalty — applied at data-prep time, not reward time.

Composition order (final legibility reward):
    final = base_legibility * compactness_penalty * crossings_penalty
    # alignment_jitter is applied at DATA PREP, not here

Caps consume CapInputs (a value object with bbox/footprint/crossing_count)
per CR-110-04 — no loose float parameters scattered across call sites.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from kicad_agent.training.rewards.cap_inputs import CapInputs


@dataclass(frozen=True)
class CompactnessCap:
    """D-04 cap 1: penalize layouts where bounding box >> component footprint area.

    Prevents infinite-spread reward hacking (107-RESEARCH.md §6 Pitfall 6).
    Returns multiplier in (0.0, 1.0]; 1.0 = no penalty.

    Formula:
        ratio = bbox_mm2 / max(footprint_mm2, 1.0)
        if ratio <= threshold_ratio: return 1.0
        excess = ratio - threshold_ratio
        # Steep tanh curve so ratio=3 (excess=1, ratio/threshold=1.5) lands near 0.5
        # and ratio=10 (excess=8, ratio/threshold=5) lands well below 0.2.
        # tanh(1.5)=0.905, tanh(5)≈0.9999 — so we use 1.0 - tanh(...) which
        # ranges from ~0 (asymptote) up to 1.0 at the threshold boundary.
        return max(0.1, 1.0 - math.tanh(excess / self.threshold_ratio))

    Attributes:
        threshold_ratio: bbox/footprint ratio above which penalty applies.
            D-04 default = 2.0.
    """

    threshold_ratio: float = 2.0  # D-04 locked default

    def penalty(self, inputs: CapInputs) -> float:
        """Return multiplier in (0.0, 1.0]."""
        # max-guard prevents div-by-zero when footprint is 0
        footprint = max(inputs.component_footprint_area_mm2, 1.0)
        ratio = inputs.bounding_box_mm2 / footprint
        if ratio <= self.threshold_ratio:
            return 1.0
        excess = ratio - self.threshold_ratio
        # Steep tanh curve so ratio=3 (excess=1, ratio/threshold=1.5) lands near 0.5
        # and ratio=10 (excess=8, ratio/threshold=5) lands well below 0.2.
        # tanh(1.5)=0.905, tanh(5)~0.9999 — so 1.0 - tanh(...) ranges from
        # ~0 (asymptote) up to 1.0 at the threshold boundary.
        return max(0.1, 1.0 - math.tanh(excess / self.threshold_ratio))


@dataclass(frozen=True)
class CrossingsFloorCap:
    """D-04 cap 2: penalize suspiciously low crossing counts (over-routing).

    Zero crossings is suspicious — model likely routed around everything
    to minimize crossings, creating absurd wire paths. Returns multiplier
    in {floor_multiplier, 1.0}.

    Attributes:
        min_crossings: Crossing count floor. D-04 default = 1.
        floor_multiplier: Multiplier applied when count < min. D-04 default = 0.3.
    """

    min_crossings: int = 1  # D-04 locked default
    floor_multiplier: float = 0.3  # D-04 locked default

    def penalty(self, inputs: CapInputs) -> float:
        """Return multiplier in {floor_multiplier, 1.0}."""
        if inputs.crossing_count < 0:
            raise ValueError(
                f"crossing_count must be >= 0, got {inputs.crossing_count}"
            )
        if inputs.crossing_count < self.min_crossings:
            return self.floor_multiplier
        return 1.0


@dataclass(frozen=True)
class AlignmentJitter:
    """D-04 cap 3: ±amplitude_mm perturbation during training (data augmentation).

    NOT a penalty — applied at data-prep time, not reward time. Prevents
    grid over-fitting per 107-RESEARCH.md §6.

    Attributes:
        amplitude_mm: Jitter amplitude in mm. D-04 default = 0.1.
    """

    amplitude_mm: float = 0.1  # D-04 locked default

    def perturb_coord(self, value_mm: float, rng: random.Random) -> float:
        """Return value_mm + uniform(-amplitude_mm, +amplitude_mm).

        Args:
            value_mm: Original coordinate in mm.
            rng: random.Random instance (caller owns state for reproducibility).

        Returns:
            Perturbed coordinate in [value_mm - amplitude_mm, value_mm + amplitude_mm].
        """
        return value_mm + rng.uniform(-self.amplitude_mm, self.amplitude_mm)
