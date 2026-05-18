"""Pydantic v2 operation schema -- the JSON contract the LLM uses to express edit intents.

Design decisions (from CONTEXT.md):
  D-01: One Pydantic model per operation type (not a generic dict).
  D-02: Atomic operations -- one mutation per operation, no compound ops.
  D-03: Single file per operation via ``target_file`` field.
  D-04: Export full JSON Schema via ``model_json_schema()`` for LLM consumption.

Security mitigations (Council review):
  H-01: TargetFile type rejects path traversal (``..``), absolute paths,
        null bytes, and non-KiCad extensions.
  M-04: All string fields enforce min_length / max_length to prevent abuse.

Usage::

    from kicad_agent.ops import Operation

    op = Operation.model_validate({
        "root": {
            "op_type": "add_component",
            "target_file": "motor-driver.kicad_sch",
            "library_id": "Device:R_Small_US",
            "position": {"x": 50.0, "y": 30.0},
        }
    })

    # Export schema for LLM tool contract
    schema = op.model_json_schema()
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


# ---------------------------------------------------------------------------
# Shared field types
# ---------------------------------------------------------------------------


class PositionSpec(BaseModel):
    """Position specification for place operations.

    Attributes:
        x: X coordinate in mm.
        y: Y coordinate in mm.
        angle: Rotation angle in degrees (default 0).
    """

    x: float
    y: float
    angle: float = 0.0


class PropertySpec(BaseModel):
    """A named property with a string value.

    Attributes:
        name: Property key (e.g. ``"Value"``, ``"Footprint"``).
        value: Property value string.
    """

    name: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=1024)


# ---------------------------------------------------------------------------
# TargetFile -- path-safe type (Council H-01)
# ---------------------------------------------------------------------------


def _validate_target_file(v: str) -> str:
    """Reject path traversal, absolute paths, null bytes, and non-KiCad extensions."""
    if "\x00" in v:
        raise ValueError("target_file contains null bytes")
    if v.startswith("/"):
        raise ValueError("target_file must be a relative path")
    parts = Path(v).parts
    if ".." in parts:
        raise ValueError("target_file must not contain '..' path traversal")
    if not v.endswith((".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod")):
        raise ValueError("target_file must be a KiCad file type")
    return v


TargetFile = Annotated[
    str,
    Field(min_length=1, max_length=512),
    BeforeValidator(_validate_target_file),
]


# ---------------------------------------------------------------------------
# Operation type models (D-01)
# ---------------------------------------------------------------------------


class AddComponentOp(BaseModel):
    """Add a component to a schematic or PCB.

    Attributes:
        op_type: Discriminator literal ``"add_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        library_id: Library reference, e.g. ``"Device:R_Small_US"``.
        reference: Reference designator (default ``"R?"``).
        value: Component value string (default empty).
        position: Placement coordinates.
    """

    op_type: Literal["add_component"] = "add_component"
    target_file: TargetFile
    library_id: str = Field(
        min_length=1,
        max_length=256,
        description="Library reference, e.g. 'Device:R_Small_US'",
    )
    reference: str = Field(
        default="R?",
        min_length=1,
        max_length=64,
        description="Reference designator",
    )
    value: str = Field(
        default="",
        max_length=256,
        description="Component value",
    )
    position: PositionSpec


class RemoveComponentOp(BaseModel):
    """Remove a component by reference designator.

    Attributes:
        op_type: Discriminator literal ``"remove_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Reference designator to remove.
    """

    op_type: Literal["remove_component"] = "remove_component"
    target_file: TargetFile
    reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator to remove",
    )


class MoveComponentOp(BaseModel):
    """Move a component to a new position.

    Attributes:
        op_type: Discriminator literal ``"move_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Reference designator of the component to move.
        position: Target placement coordinates.
    """

    op_type: Literal["move_component"] = "move_component"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=64)
    position: PositionSpec


class ModifyPropertyOp(BaseModel):
    """Modify a component property (value, footprint, reference, custom field).

    Attributes:
        op_type: Discriminator literal ``"modify_property"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        reference: Reference designator of the target component.
        property_name: Name of the property to modify.
        new_value: New value for the property.
    """

    op_type: Literal["modify_property"] = "modify_property"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=64)
    property_name: str = Field(min_length=1, max_length=128)
    new_value: str = Field(max_length=1024)


# ---------------------------------------------------------------------------
# Discriminated union (D-01, D-02, D-03)
# ---------------------------------------------------------------------------


class Operation(BaseModel):
    """Discriminated union of all operation types.

    Per D-02: each operation is atomic (one mutation).
    Per D-03: each operation targets one file via ``target_file``.
    Per D-04: export full JSON Schema via ``model_json_schema()``.
    """

    root: Annotated[
        AddComponentOp | RemoveComponentOp | MoveComponentOp | ModifyPropertyOp,
        Field(discriminator="op_type"),
    ]


# ---------------------------------------------------------------------------
# Schema export helper (D-04)
# ---------------------------------------------------------------------------


def get_operation_schema() -> dict:
    """Export the full JSON Schema for LLM consumption (D-04)."""
    return Operation.model_json_schema()
