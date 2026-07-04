"""Phase 157: Floor planner — declarative placement intent.

Captures design intent (zones, keepouts, contextual placement rules)
in a YAML spec, then lowers it into the existing placement engine.

The contextual placement rules (Bead kicad-agent-24) are the key
innovation: edge_affinity, avoid, approach, orientation, region,
alignment — each carrying a rationale for AI training.
"""
from kicad_agent.floorplan.spec import (
    FloorPlanSpec,
    PlacementRule,
    RuleType,
    RulePriority,
    ZoneSpec,
    KeepoutSpec,
    load_floor_plan,
)
from kicad_agent.floorplan.lower import (
    PlacementVectors,
    lower_floor_plan,
    evaluate_rule_penalty,
    total_penalty,
)
from kicad_agent.floorplan.applier import apply_floor_plan, FloorPlanResult

__all__ = [
    "FloorPlanSpec",
    "PlacementRule",
    "RuleType",
    "RulePriority",
    "ZoneSpec",
    "KeepoutSpec",
    "load_floor_plan",
    "PlacementVectors",
    "lower_floor_plan",
    "evaluate_rule_penalty",
    "total_penalty",
    "apply_floor_plan",
    "FloorPlanResult",
]
