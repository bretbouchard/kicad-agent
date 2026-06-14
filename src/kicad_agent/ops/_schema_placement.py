"""Placement operation schema -- auto-place components with overlap-free guarantee."""

from typing import Literal

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
