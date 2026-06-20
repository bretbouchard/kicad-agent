"""Placement operation schemas -- auto-place, export/import positions, zone-aware placement."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class AutoPlaceOp(BaseModel):
    """Auto-place components on a PCB with overlap-free guarantee.

    Attributes:
        op_type: Discriminator literal ``"auto_place"``.
        target_file: Relative path to the .kicad_pcb file.
        component_refs: References of components to place (empty = all unplaced).
        board_width: Board width in mm (optional, read from PCB if omitted).
        board_height: Board height in mm (optional, read from PCB if omitted).
        min_clearance: Minimum clearance between components in mm.
        fixed_refs: References of components that must not move.
        keepout_zones: Forbidden regions as (x1, y1, x2, y2) tuples.
    """

    op_type: Literal["auto_place"] = "auto_place"
    target_file: TargetFile
    component_refs: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="References of components to place (empty = all unplaced)",
    )
    board_width: float | None = Field(
        default=None, gt=0,
        description="Board width in mm (read from PCB if omitted)",
    )
    board_height: float | None = Field(
        default=None, gt=0,
        description="Board height in mm (read from PCB if omitted)",
    )
    min_clearance: float = Field(
        default=1.0,
        gt=0,
        description="Minimum clearance between components in mm",
    )
    fixed_refs: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="References of components that must not move",
    )
    keepout_zones: list[tuple[float, float, float, float]] = Field(
        default_factory=list,
        max_length=100,
        description="Forbidden regions as (x1, y1, x2, y2) tuples",
    )


class ExportPositionsOp(BaseModel):
    """Export current footprint positions from a PCB to a JSON file.

    Extracts (at X Y angle) from each footprint block and writes
    a JSON file with all positions. Useful for locking manually-placed
    components across pipeline runs.

    Attributes:
        op_type: Discriminator literal ``"export_positions"``.
        target_file: Relative path to the .kicad_pcb file.
        output_file: Relative path for the JSON output (relative to PCB dir).
        refs: Specific references to export (empty = all footprints).
    """

    op_type: Literal["export_positions"] = "export_positions"
    target_file: TargetFile
    output_file: str = Field(
        min_length=1,
        max_length=256,
        description="JSON output path (relative to PCB directory)",
    )
    refs: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="References to export (empty = all footprints)",
    )


class ImportPositionsOp(BaseModel):
    """Import footprint positions from a JSON file and apply to PCB.

    Reads a positions JSON file (as produced by export_positions) and
    updates each footprint's (at X Y angle) in the PCB.

    Attributes:
        op_type: Discriminator literal ``"import_positions"``.
        target_file: Relative path to the .kicad_pcb file.
        positions_file: Relative path to the JSON positions file.
        refs: Specific references to import (empty = all in file).
    """

    op_type: Literal["import_positions"] = "import_positions"
    target_file: TargetFile
    positions_file: str = Field(
        min_length=1,
        max_length=256,
        description="JSON positions input path (relative to PCB directory)",
    )
    refs: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="References to import (empty = all in file)",
    )


class ZoneDefinition(BaseModel):
    """Definition of a functional placement zone.

    Attributes:
        name: Human-readable zone name (e.g. "input_stage", "power").
        x_range: Horizontal extent (x_min, x_max) in mm.
        y_range: Vertical extent (y_min, y_max) in mm.
        priority_refs: References that MUST be placed in this zone.
        fill_order: Sweep direction within the zone.
    """

    name: str = Field(
        min_length=1,
        max_length=64,
        description="Zone name",
    )
    x_range: tuple[float, float] = Field(
        description="Horizontal extent (x_min, x_max) in mm",
    )
    y_range: tuple[float, float] = Field(
        description="Vertical extent (y_min, y_max) in mm",
    )
    priority_refs: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="References that must be placed in this zone",
    )
    fill_order: Literal["left-to-right", "right-to-left", "top-to-bottom", "bottom-to-top"] = Field(
        default="left-to-right",
        description="Sweep direction within the zone",
    )


class AutoPlaceZonedOp(BaseModel):
    """Zone-aware placement with AABB collision and optional SA optimization.

    Places components within named functional zones using priority refs
    and round-robin heuristics for unmatched components. Supports locking
    specific positions and running simulated annealing for wire-length
    optimization.

    Attributes:
        op_type: Discriminator literal ``"auto_place_zoned"``.
        target_file: Relative path to the .kicad_pcb file.
        zones: Functional zone definitions with boundaries and priority refs.
        fixed_positions: Locked component positions (ref -> (x, y, angle)).
        clearance: Minimum clearance between components in mm.
        grid: Placement grid step in mm.
        optimize: Run SA refinement after initial sweep.
        schematic_file: Optional schematic for net-aware placement.
    """

    op_type: Literal["auto_place_zoned"] = "auto_place_zoned"
    target_file: TargetFile
    zones: list[ZoneDefinition] = Field(
        min_length=1,
        max_length=20,
        description="Functional zone definitions",
    )
    fixed_positions: dict[str, tuple[float, float, float]] = Field(
        default_factory=dict,
        max_length=500,
        description="Locked positions: ref -> (x, y, angle_degrees)",
    )
    clearance: float = Field(
        default=1.5,
        gt=0,
        description="Minimum clearance between components in mm",
    )
    grid: float = Field(
        default=1.0,
        gt=0,
        description="Placement grid step in mm",
    )
    optimize: bool = Field(
        default=True,
        description="Run SA refinement after initial sweep",
    )
    schematic_file: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Schematic path for net-aware HPWL scoring",
    )
