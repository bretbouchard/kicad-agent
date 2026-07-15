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
    ConstraintPropagator -- orchestrator that runs all extractors
    to_routing_constraints -- project to RoutingConstraints
    to_placement_constraints -- project to ConstraintSet
    to_net_class_defs -- project to list[NetClassDef]
"""
from __future__ import annotations

# Types module -- always available
from volta.constraints.types import (
    ClearanceConstraint,
    ConstraintType,
    DecouplingConstraint,
    DifferentialPairConstraint,
    ImpedanceConstraint,
    PCBConstraint,
    ThermalConstraint,
)

# Table module -- always available
from volta.constraints.table import ConstraintParams, lookup_params

# CoordinateConverter -- available since 50-01
from volta.constraints.coordinate import CoordinateConverter

# Converters -- available since 50-01
from volta.constraints.converters import (
    to_net_class_defs,
    to_placement_constraints,
    to_routing_constraints,
)

# Propagator -- available since 50-02
from volta.constraints.propagator import ConstraintPropagator


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
