"""Pure converter functions from PCBConstraint to downstream types.

CP-03: PCBConstraint is the single upstream source of truth.
Pure converter functions project into existing types:
- to_routing_constraints -> RoutingConstraints
- to_placement_constraints -> ConstraintSet
- to_net_class_defs -> list[NetClassDef]

Existing types remain unchanged. Converters have no side effects.
"""
from __future__ import annotations

from kicad_agent.constraints.types import (
    ClearanceConstraint,
    DecouplingConstraint,
    ImpedanceConstraint,
    PCBConstraint,
    ThermalConstraint,
)
from kicad_agent.placement.interactive import ConstraintSet
from kicad_agent.project.design_rules import NetClassDef
from kicad_agent.routing.constraints import RoutingConstraints


def to_routing_constraints(constraints: list[PCBConstraint]) -> RoutingConstraints:
    """Project PCBConstraint list into RoutingConstraints.

    Extracts ClearanceConstraint -> clearance_mm and
    ImpedanceConstraint -> trace_width_mm. Takes the tightest
    (smallest) values when multiple constraints apply.

    Args:
        constraints: List of PCBConstraint instances.

    Returns:
        RoutingConstraints with values from applicable constraints.
        Returns default RoutingConstraints() if no relevant constraints.
    """
    clearance: float | None = None
    trace_width: float | None = None

    for c in constraints:
        if isinstance(c, ClearanceConstraint):
            if clearance is None or c.min_clearance_mm < clearance:
                clearance = c.min_clearance_mm
        elif isinstance(c, ImpedanceConstraint):
            if trace_width is None or c.trace_width_mm < trace_width:
                trace_width = c.trace_width_mm

    if clearance is None and trace_width is None:
        return RoutingConstraints()

    return RoutingConstraints(
        clearance_mm=clearance if clearance is not None else 0.2,
        trace_width_mm=trace_width if trace_width is not None else 0.25,
    )


def to_placement_constraints(constraints: list[PCBConstraint]) -> ConstraintSet:
    """Project PCBConstraint list into ConstraintSet.

    Extracts proximity constraints from DecouplingConstraint (max_distance_mm)
    and ThermalConstraint (heat_dissipation_w -> clearance estimate).
    Takes the tightest (smallest) clearance.

    Args:
        constraints: List of PCBConstraint instances.

    Returns:
        ConstraintSet with min_clearance from applicable constraints.
    """
    min_clearance: float | None = None

    for c in constraints:
        if isinstance(c, DecouplingConstraint):
            if min_clearance is None or c.max_distance_mm < min_clearance:
                min_clearance = c.max_distance_mm
        elif isinstance(c, ThermalConstraint):
            # Estimate thermal clearance from heat dissipation:
            # sqrt(heat_dissipation_w) gives a rough mm margin
            if c.heat_dissipation_w > 0:
                thermal_clearance = c.heat_dissipation_w ** 0.5
                if min_clearance is None or thermal_clearance < min_clearance:
                    min_clearance = thermal_clearance

    if min_clearance is None:
        return ConstraintSet()

    return ConstraintSet(min_clearance=min_clearance)


def to_net_class_defs(constraints: list[PCBConstraint]) -> list[NetClassDef]:
    """Project PCBConstraint list into list[NetClassDef].

    Extracts ClearanceConstraint and ImpedanceConstraint instances.
    Groups by net_class_name (falls back to source_rule).
    Merges multiple constraints targeting the same net class.

    Args:
        constraints: List of PCBConstraint instances.

    Returns:
        List of NetClassDef with values from applicable constraints.
    """
    # Group constraints by net class name
    groups: dict[str, dict[str, float]] = {}

    for c in constraints:
        if isinstance(c, ClearanceConstraint):
            name = c.net_class_name or c.source_rule
            entry = groups.setdefault(name, {})
            # Take tighter clearance
            if "clearance" not in entry or c.min_clearance_mm < entry["clearance"]:
                entry["clearance"] = c.min_clearance_mm
        elif isinstance(c, ImpedanceConstraint):
            name = c.source_rule
            entry = groups.setdefault(name, {})
            # Take narrower trace width
            if "track_width" not in entry or c.trace_width_mm < entry["track_width"]:
                entry["track_width"] = c.trace_width_mm

    # Build NetClassDef instances
    result: list[NetClassDef] = []
    for name, values in groups.items():
        result.append(NetClassDef(
            name=name,
            clearance=values.get("clearance", 0.0),
            track_width=values.get("track_width", 0.0),
        ))

    return result
