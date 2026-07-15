"""Phase 157: Floor plan lowering — compile FloorPlanSpec into placement vectors.

Converts the declarative YAML spec into the existing LayoutAwarePlacer
inputs: fixed_positions, keepout_zones, and SA objective penalties.

This is the bridge between "design intent" (the YAML) and "placement
optimization" (the SA engine). The placement rules become penalties
in the simulated annealing objective function.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from volta.floorplan.spec import (
    FloorPlanSpec,
    PlacementRule,
    RulePriority,
    RuleType,
)

logger = logging.getLogger(__name__)

# SA penalty weights.
_HARD_PENALTY = 1000.0  # Near-infinite for hard rules.
_SOFT_PENALTY = 10.0    # Moderate for soft rules.


@dataclass
class PlacementVectors:
    """The output of lowering — inputs to LayoutAwarePlacer.

    Attributes:
        fixed_positions: ref → (x, y, rotation) for locked components.
        keepout_zones: List of (x1, y1, x2, y2) boxes.
        rule_penalties: List of penalty functions for the SA objective.
    """

    fixed_positions: dict[str, tuple[float, float, float]]
    keepout_zones: list[tuple[float, float, float, float]]
    rule_penalties: list[dict]  # Serialized rule specs for the SA engine.


def lower_floor_plan(
    spec: FloorPlanSpec,
    component_refs: list[str],
) -> PlacementVectors:
    """Compile a FloorPlanSpec into LayoutAwarePlacer vectors.

    Args:
        spec: The floor plan specification.
        component_refs: All component reference designators on the board.

    Returns:
        PlacementVectors with fixed positions, keepouts, and rule penalties.
    """
    fixed: dict[str, tuple[float, float, float]] = {}
    keepouts: list[tuple[float, float, float, float]] = []
    penalties: list[dict] = []

    # 1. Pre-placed anchors → fixed positions.
    for ref, coords in spec.pre_placed.items():
        fixed[ref] = coords

    # 2. Explicit keepouts.
    for k in spec.keepouts:
        keepouts.append(k.bounds)

    # 3. Edge clearance keepout (band inside the board edge).
    if spec.edge_clearance_mm > 0 and spec.board_width_mm > 0:
        ec = spec.edge_clearance_mm
        w, h = spec.board_width_mm, spec.board_height_mm
        # Top, bottom, left, right bands.
        keepouts.extend([
            (0, 0, w, ec),           # top
            (0, h - ec, w, h),       # bottom
            (0, 0, ec, h),           # left
            (w - ec, 0, w, h),       # right
        ])

    # 4. Zone keepouts — components not in their zone get penalized.
    for zone in spec.zones:
        # The zone itself is valid — the complement is the keepout.
        # But we use soft penalties instead of hard keepouts for zones.
        for ref in component_refs:
            if ref in zone.priority_refs:
                continue  # Already assigned.
            # Soft penalty for being outside the assigned zone.
            penalties.append({
                "type": "zone_membership",
                "subject_ref": ref,
                "zone_name": zone.name,
                "zone_bounds": (zone.x_range[0], zone.y_range[0],
                                zone.x_range[1], zone.y_range[1]),
                "weight": _SOFT_PENALTY,
            })

    # 5. Contextual placement rules → SA penalties.
    for rule in spec.placement_rules:
        weight = _HARD_PENALTY if rule.priority == RulePriority.HARD else _SOFT_PENALTY

        if rule.rule_type == RuleType.AVOID:
            penalties.append({
                "type": "avoid",
                "subject_ref": rule.subject_ref,
                "target_ref": rule.target,
                "min_mm": rule.min_mm or 10.0,
                "weight": weight,
                "rationale": rule.rationale,
            })

        elif rule.rule_type == RuleType.APPROACH:
            penalties.append({
                "type": "approach",
                "subject_ref": rule.subject_ref,
                "target_ref": rule.target,
                "max_mm": rule.max_mm or 10.0,
                "weight": weight,
                "rationale": rule.rationale,
            })

        elif rule.rule_type == RuleType.EDGE_AFFINITY:
            penalties.append({
                "type": "edge_affinity",
                "subject_ref": rule.subject_ref,
                "max_mm": rule.max_mm or 5.0,
                "edge_sides": list(rule.edge_sides),
                "board_bounds": (0, 0, spec.board_width_mm, spec.board_height_mm),
                "weight": weight,
                "rationale": rule.rationale,
            })

        elif rule.rule_type == RuleType.ORIENTATION:
            # Hard: lock rotation.
            if rule.priority == RulePriority.HARD:
                for ref in rule.subject_ref.split(","):
                    ref = ref.strip()
                    if ref in fixed:
                        x, y, _ = fixed[ref]
                        fixed[ref] = (x, y, rule.orientation_deg or 0.0)
                    else:
                        fixed[ref] = (0.0, 0.0, rule.orientation_deg or 0.0)
            else:
                penalties.append({
                    "type": "orientation",
                    "subject_ref": rule.subject_ref,
                    "target_deg": rule.orientation_deg or 0.0,
                    "weight": weight,
                    "rationale": rule.rationale,
                })

        elif rule.rule_type == RuleType.REGION:
            penalties.append({
                "type": "region",
                "subject_ref": rule.subject_ref,
                "target_zone": rule.target,
                "weight": weight,
                "rationale": rule.rationale,
            })

    logger.info(
        "Lowered floor plan: %d fixed, %d keepouts, %d penalties",
        len(fixed), len(keepouts), len(penalties),
    )

    return PlacementVectors(
        fixed_positions=fixed,
        keepout_zones=keepouts,
        rule_penalties=penalties,
    )


def evaluate_rule_penalty(
    positions: dict[str, tuple[float, float, float]],
    penalty: dict,
) -> float:
    """Evaluate a single placement rule penalty.

    Args:
        positions: Current component positions (ref → (x, y, rot)).
        penalty: The penalty spec from lower_floor_plan.

    Returns:
        Penalty value (0.0 = satisfied, higher = more violated).
    """
    ptype = penalty["type"]
    weight = penalty["weight"]

    if ptype == "avoid":
        a = positions.get(penalty["subject_ref"])
        b = positions.get(penalty["target_ref"])
        if a and b:
            dist = math.hypot(a[0] - b[0], a[1] - b[1])
            min_mm = penalty["min_mm"]
            if dist < min_mm:
                return weight * (min_mm - dist) / min_mm
        return 0.0

    elif ptype == "approach":
        a = positions.get(penalty["subject_ref"])
        b = positions.get(penalty["target_ref"])
        if a and b:
            dist = math.hypot(a[0] - b[0], a[1] - b[1])
            max_mm = penalty["max_mm"]
            if dist > max_mm:
                return weight * (dist - max_mm) / max_mm
        return 0.0

    elif ptype == "edge_affinity":
        a = positions.get(penalty["subject_ref"])
        if a:
            x1, y1, x2, y2 = penalty["board_bounds"]
            max_mm = penalty["max_mm"]
            # Distance to nearest valid edge.
            edges = penalty.get("edge_sides", ["top", "bottom", "left", "right"])
            min_edge_dist = float("inf")
            if "left" in edges:
                min_edge_dist = min(min_edge_dist, a[0] - x1)
            if "right" in edges:
                min_edge_dist = min(min_edge_dist, x2 - a[0])
            if "top" in edges:
                min_edge_dist = min(min_edge_dist, a[1] - y1)
            if "bottom" in edges:
                min_edge_dist = min(min_edge_dist, y2 - a[1])
            if min_edge_dist > max_mm:
                return weight * (min_edge_dist - max_mm) / max_mm
        return 0.0

    elif ptype == "orientation":
        a = positions.get(penalty["subject_ref"])
        if a:
            target = penalty["target_deg"]
            actual = a[2]  # rotation
            diff = abs(((target - actual + 180) % 360) - 180)
            if diff > 1.0:  # >1 degree off
                return weight * diff / 180.0
        return 0.0

    elif ptype == "zone_membership" or ptype == "region":
        a = positions.get(penalty["subject_ref"])
        if a:
            bounds = penalty.get("zone_bounds") or (0, 0, 999, 999)
            x1, y1, x2, y2 = bounds
            if not (x1 <= a[0] <= x2 and y1 <= a[1] <= y2):
                # Outside the zone — penalty proportional to distance.
                dx = max(x1 - a[0], 0, a[0] - x2)
                dy = max(y1 - a[1], 0, a[1] - y2)
                return weight * math.hypot(dx, dy) / 10.0
        return 0.0

    return 0.0


def total_penalty(
    positions: dict[str, tuple[float, float, float]],
    penalties: list[dict],
) -> float:
    """Sum all placement rule penalties for a given position set."""
    return sum(evaluate_rule_penalty(positions, p) for p in penalties)
