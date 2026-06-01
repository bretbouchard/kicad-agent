"""Constraint propagation module for PCB design.

CP-01: Translates schematic intent into PCB design constraints.

Public API:
    PCBConstraint -- abstract base (use subclasses)
    DifferentialPairConstraint
    ClearanceConstraint
    ImpedanceConstraint
    DecouplingConstraint
    ThermalConstraint
    ConstraintType -- enum discriminator
    ConstraintParams -- dimension parameters from lookup table
    lookup_params -- deterministic lookup
    CoordinateConverter -- schematic <-> PCB coordinate transform
    to_routing_constraints -- project to RoutingConstraints
    to_placement_constraints -- project to ConstraintSet
    to_net_class_defs -- project to list[NetClassDef]
"""
from __future__ import annotations

# Types module -- always available
from kicad_agent.constraints.types import (
    ClearanceConstraint,
    ConstraintType,
    DecouplingConstraint,
    DifferentialPairConstraint,
    ImpedanceConstraint,
    PCBConstraint,
    ThermalConstraint,
)

# Table module -- always available
from kicad_agent.constraints.table import ConstraintParams, lookup_params

# CoordinateConverter and converters -- available after Task 2
try:
    from kicad_agent.constraints.coordinate import CoordinateConverter
except ImportError:
    pass

try:
    from kicad_agent.constraints.converters import (
        to_net_class_defs,
        to_placement_constraints,
        to_routing_constraints,
    )
except ImportError:
    pass


class ConstraintPropagator:
    """Placeholder for Phase 50-02 ConstraintPropagator orchestrator.

    Will consume topology, subcircuits, intent, and rule report
    to produce list[PCBConstraint].
    """

    pass


__all__ = [
    "PCBConstraint",
    "ConstraintType",
    "DifferentialPairConstraint",
    "ClearanceConstraint",
    "ImpedanceConstraint",
    "DecouplingConstraint",
    "ThermalConstraint",
    "ConstraintParams",
    "lookup_params",
    "CoordinateConverter",
    "ConstraintPropagator",
    "to_routing_constraints",
    "to_placement_constraints",
    "to_net_class_defs",
]
