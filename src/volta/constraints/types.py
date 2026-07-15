"""PCBConstraint type hierarchy for constraint propagation.

CP-02: Frozen Pydantic BaseModel hierarchy with 5 typed subclasses.
Each subclass adds type-specific fields for IDE autocompletion and
type-safe dispatch via isinstance.

Security:
  T-50-05: Pydantic Field validators enforce positive dimensions,
  bounded strings, confidence range 0.0-1.0.

Usage:
    from volta.constraints.types import DifferentialPairConstraint

    c = DifferentialPairConstraint(
        net_names=("D+", "D-"),
        source_rule="diff_pair_extractor",
        confidence=0.9,
        rationale="USB differential pair",
        gap_mm=0.1,
        width_mm=0.15,
    )
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ConstraintType(str, Enum):
    """Discriminator for PCBConstraint subclasses."""

    DIFFERENTIAL_PAIR = "DIFFERENTIAL_PAIR"
    CLEARANCE = "CLEARANCE"
    IMPEDANCE = "IMPEDANCE"
    DECOUPLING = "DECOUPLING"
    THERMAL = "THERMAL"


class PCBConstraint(BaseModel):
    """Abstract base model for all PCB design constraints.

    Do not instantiate directly -- use one of the typed subclasses.
    All subclasses share these common fields and are frozen (immutable).

    Attributes:
        constraint_type: Discriminator identifying the constraint kind.
        net_names: Tuple of net names this constraint applies to.
        source_rule: Name of the extractor that produced this constraint.
        confidence: Confidence score 0.0-1.0 for this constraint.
        component_refs: Tuple of component reference designators affected.
        rationale: Human-readable explanation for why this was generated.
    """

    constraint_type: ConstraintType
    net_names: tuple[str, ...] = ()
    source_rule: str = Field(max_length=128)
    confidence: float = Field(ge=0.0, le=1.0)
    component_refs: tuple[str, ...] = ()
    rationale: str = Field(default="", max_length=2000)

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def _prevent_direct_instantiation(self) -> "PCBConstraint":
        """Prevent direct instantiation of PCBConstraint base class."""
        if type(self) is PCBConstraint:
            raise ValueError(
                "PCBConstraint is abstract; use a typed subclass "
                "(DifferentialPairConstraint, ClearanceConstraint, etc.)"
            )
        return self


class DifferentialPairConstraint(PCBConstraint):
    """Constraint for differential pair routing.

    Attributes:
        gap_mm: Required gap between differential pair traces (mm).
        width_mm: Required trace width for each trace (mm).
        length_match_tolerance_mm: Allowed length mismatch (mm).
    """

    constraint_type: Literal[ConstraintType.DIFFERENTIAL_PAIR] = (
        ConstraintType.DIFFERENTIAL_PAIR
    )
    gap_mm: float = Field(gt=0)
    width_mm: float = Field(gt=0)
    length_match_tolerance_mm: float = Field(default=0.5, ge=0)


class ClearanceConstraint(PCBConstraint):
    """Constraint for minimum copper clearance.

    Attributes:
        min_clearance_mm: Minimum clearance between copper features (mm).
        layer_constraint: Layer restriction (e.g. "copper", "all").
        net_class_name: Net class this clearance applies to.
    """

    constraint_type: Literal[ConstraintType.CLEARANCE] = ConstraintType.CLEARANCE
    min_clearance_mm: float = Field(gt=0)
    layer_constraint: str = "copper"
    net_class_name: str = ""


class ImpedanceConstraint(PCBConstraint):
    """Constraint for controlled-impedance traces.

    Attributes:
        target_impedance_ohm: Target impedance in ohms.
        layer: Copper layer for this constraint.
        trace_width_mm: Required trace width to achieve impedance (mm).
        reference_layer: Reference plane layer.
    """

    constraint_type: Literal[ConstraintType.IMPEDANCE] = ConstraintType.IMPEDANCE
    target_impedance_ohm: float = Field(gt=0)
    layer: str = "F.Cu"
    trace_width_mm: float = Field(gt=0)
    reference_layer: str = "F.Cu"


class DecouplingConstraint(PCBConstraint):
    """Constraint for IC decoupling capacitor proximity.

    Attributes:
        ic_ref: Reference designator of the IC.
        cap_ref: Reference designator of the decoupling capacitor.
        max_distance_mm: Maximum allowed distance between IC and cap (mm).
        priority: Placement priority -- "critical", "high", or "normal".
    """

    constraint_type: Literal[ConstraintType.DECOUPLING] = ConstraintType.DECOUPLING
    ic_ref: str = Field(min_length=1)
    cap_ref: str = Field(min_length=1)
    max_distance_mm: float = Field(gt=0)
    priority: Literal["critical", "high", "normal"] = "normal"


class ThermalConstraint(PCBConstraint):
    """Constraint for thermal management.

    Attributes:
        max_junction_temp_c: Maximum junction temperature in Celsius.
        thermal_resistance_c_per_w: Thermal resistance (C/W).
        heat_dissipation_w: Heat dissipation in watts.
    """

    constraint_type: Literal[ConstraintType.THERMAL] = ConstraintType.THERMAL
    component_refs: tuple[str, ...] = ()
    max_junction_temp_c: float = Field(gt=0)
    thermal_resistance_c_per_w: float = Field(default=0.0, ge=0)
    heat_dissipation_w: float = Field(default=0.0, ge=0)
