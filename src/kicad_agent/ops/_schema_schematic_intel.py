"""Schematic intelligence operation schemas -- net extraction, conflict detection, name suggestion."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ExtractNetsOp(BaseModel):
    """Extract complete net topology from a schematic file.

    SCH-INTEL-01: Returns a mapping of net names to connected pin lists.

    Attributes:
        op_type: Discriminator literal "extract_nets".
        target_file: Relative path to the target .kicad_sch file.
        include_positions: Include pin positions in output (default True).
        netlist_path: Optional path to .net file for net name resolution.
    """

    op_type: Literal["extract_nets"] = "extract_nets"
    target_file: TargetFile
    include_positions: bool = Field(default=True, description="Include pin positions in output")
    netlist_path: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Optional path to .net file for net name resolution",
    )
