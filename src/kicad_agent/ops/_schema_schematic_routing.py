"""Schematic routing operation schemas -- pin resolution, collision detection, wire routing.

Schemas for the schematic routing engine (Phase 38). These operations read
schematic files to resolve pin positions, detect collisions, and plan wire
routes -- they are analysis/query operations, not mutations.

Security (threat model):
  T-38-01-01: target_file validated via TargetFile type (inherited H-01)
  T-38-01-02: ref field bounded to max_length=16 (component refs are short)
  T-38-02-01: target_file validated via TargetFile type (inherited H-01)
  T-38-02-02: collision_tolerance validated: gt=0, le=10 prevents extreme values
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ResolvePinPositionsOp(BaseModel):
    """Resolve absolute pin positions for schematic components.

    Reads a .kicad_sch file, parses lib_symbols and placed symbol instances,
    and returns absolute coordinates for every pin of every (or filtered)
    component, including multi-unit ICs and rotation transforms.

    Attributes:
        op_type: Discriminator literal ``"resolve_pin_positions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        ref: Optional component reference filter (e.g. ``"R55"``, ``"U21"``).
    """

    op_type: Literal["resolve_pin_positions"] = "resolve_pin_positions"
    target_file: TargetFile
    ref: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Filter to a single component reference (e.g. 'R55')",
    )


class DetectRoutingCollisionsOp(BaseModel):
    """Detect collision zones in a schematic where wires would short pins.

    Identifies vertical columns and horizontal rows where pins from different
    components share the same coordinate. Any wire drawn through these zones
    would create unintended short circuits between the overlapping pins.

    Attributes:
        op_type: Discriminator literal ``"detect_routing_collisions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        collision_tolerance: Max distance (mm) to group pins into a collision column.
    """

    op_type: Literal["detect_routing_collisions"] = "detect_routing_collisions"
    target_file: TargetFile
    collision_tolerance: float = Field(
        default=2.54,
        gt=0,
        le=10,
        description="Max distance (mm) to group pins into a collision column",
    )


class DetectPinOverlapsOp(BaseModel):
    """Detect pins from different nets at the exact same position.

    Finds layout bugs like R55/R56 where pins from different nets share
    coordinates. Any label or wire at that position applies to both pins,
    creating an unintended short.

    Attributes:
        op_type: Discriminator literal ``"detect_pin_overlaps"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        tolerance: Position tolerance (mm) for overlap detection.
    """

    op_type: Literal["detect_pin_overlaps"] = "detect_pin_overlaps"
    target_file: TargetFile
    tolerance: float = Field(
        default=0.01,
        gt=0,
        le=1.0,
        description="Position tolerance (mm) for overlap detection",
    )
