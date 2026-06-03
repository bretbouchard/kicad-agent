"""Component operation schemas -- add, remove, move, modify, duplicate, array."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    PositionSpec,
    TargetFile,
    _validate_safe_identifier,
    _validate_sexpr_safe_string,
)


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

    @field_validator("library_id")
    @classmethod
    def _validate_library_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "library_id")

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("value")
    @classmethod
    def _validate_value_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


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

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")


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

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")


class SnapComponentsToGridOp(BaseModel):
    """Snap all (or filtered) components to the nearest grid-aligned position.

    Moves component positions to the nearest grid point to eliminate off-grid
    violations caused by script-generated schematics.

    Attributes:
        op_type: Discriminator literal ``"snap_components_to_grid"``.
        target_file: Relative path to the target KiCad schematic file.
        grid_size: Grid spacing in mm (default 2.54 = KiCad 50mil standard grid).
        prefix_filter: Only snap components whose reference starts with this prefix.
            Empty string means all components.
        dry_run: If True, report what would move without making changes.
    """

    op_type: Literal["snap_components_to_grid"] = "snap_components_to_grid"
    target_file: TargetFile
    grid_size: float = Field(
        default=2.54,
        ge=0.01,
        le=50.0,
        description="Grid spacing in mm",
    )
    prefix_filter: str = Field(
        default="",
        description="Only snap components with this reference prefix (empty = all)",
    )
    dry_run: bool = Field(
        default=False,
        description="Report what would move without changing",
    )


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

    @field_validator("reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("property_name")
    @classmethod
    def _validate_property_name(cls, v: str) -> str:
        return _validate_safe_identifier(v, "property_name")

    @field_validator("new_value")
    @classmethod
    def _validate_new_value_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class DuplicateComponentOp(BaseModel):
    """Duplicate a component with fresh UUID and incremented reference.

    Attributes:
        op_type: Discriminator literal ``"duplicate_component"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        source_reference: Reference designator of the component to duplicate.
        offset: Optional position offset from source (x, y; angle is ignored).
        count: Number of copies to create (default 1, must be >= 1).
    """

    op_type: Literal["duplicate_component"] = "duplicate_component"
    target_file: TargetFile
    source_reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the component to duplicate",
    )
    offset: PositionSpec | None = None
    count: int = Field(default=1, ge=1, le=100, description="Number of copies (1-100)")

    @field_validator("source_reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "source_reference")


class ArrayReplicateOp(BaseModel):
    """Replicate a component in a linear, circular, or matrix array pattern.

    Attributes:
        op_type: Discriminator literal ``"array_replicate"``.
        target_file: Relative path to the target KiCad file (H-01 validated).
        source_reference: Reference designator of the component to replicate.
        pattern: Array pattern type (linear, circular, or matrix).
        count: Number of replications (for matrix: rows * cols).
        spacing: Position spacing specification.
        angle_step: Degrees per step (circular pattern only).
        center: Center point (circular pattern only).
        rows: Number of rows (matrix pattern only).
        cols: Number of columns (matrix pattern only).
    """

    op_type: Literal["array_replicate"] = "array_replicate"
    target_file: TargetFile
    source_reference: str = Field(
        min_length=1,
        max_length=64,
        description="Reference designator of the component to replicate",
    )
    pattern: Literal["linear", "circular", "matrix"]
    count: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Number of replications (1-100)",
    )
    spacing: PositionSpec
    angle_step: float | None = None
    center: PositionSpec | None = None
    rows: int | None = Field(default=None, ge=1, le=100)
    cols: int | None = Field(default=None, ge=1, le=100)

    @field_validator("source_reference")
    @classmethod
    def _validate_reference(cls, v: str) -> str:
        return _validate_safe_identifier(v, "source_reference")


class SwapSymbolOp(BaseModel):
    """Swap a component's symbol (lib_id) in-place, preserving position and properties.

    Replaces the component's lib_id reference with a new one. Optionally embeds
    the new symbol definition from the library into the schematic's lib_symbols
    section if it's not already present.

    The component's Reference, Value, position, and other properties are preserved.
    Wire connections are not affected (they reference UUIDs, not symbol types).

    Attributes:
        op_type: Discriminator literal ``"swap_symbol"``.
        target_file: Relative path to the .kicad_sch file.
        reference: Reference designator of the component to swap (e.g. ``"U1"``).
        new_lib_id: New library:symbol ID (e.g. ``"Analog-Ecosystem-SMD:RP2350B"``).
        library_path: Optional path to .kicad_sym for auto-embedding. If provided,
            the symbol definition will be embedded into lib_symbols if missing.
        preserve_position: Keep the component's current (at X Y) coordinates.
        preserve_properties: Keep the component's current properties (Value, Footprint, etc.).
    """

    op_type: Literal["swap_symbol"] = "swap_symbol"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=64)
    new_lib_id: str = Field(
        min_length=1, max_length=256,
        description="New library:symbol ID (e.g. 'Library:SymbolName')",
    )
    library_path: Optional[str] = Field(
        default=None, max_length=512,
        description="Optional path to .kicad_sym for auto-embedding",
    )
    preserve_position: bool = Field(
        default=True,
        description="Keep the component's current position",
    )
    preserve_properties: bool = Field(
        default=True,
        description="Keep the component's current properties",
    )

    @field_validator("reference")
    @classmethod
    def _validate_reference_swap(cls, v: str) -> str:
        return _validate_safe_identifier(v, "reference")

    @field_validator("new_lib_id")
    @classmethod
    def _validate_new_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "new_lib_id")
