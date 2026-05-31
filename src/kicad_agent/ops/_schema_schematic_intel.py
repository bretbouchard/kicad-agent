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


class DetectNetConflictsOp(BaseModel):
    """Detect net naming conflicts in a schematic file.

    SCH-INTEL-02: Returns structured conflict list without running ERC.

    Attributes:
        op_type: Discriminator literal "detect_net_conflicts".
        target_file: Relative path to the target .kicad_sch file.
        check_case_variants: Detect case-variant net names (default True).
        check_mixed_labels: Detect mixed label types on same net (default True).
        check_unlabeled_junctions: Detect junctions merging unnamed nets (default True).
    """

    op_type: Literal["detect_net_conflicts"] = "detect_net_conflicts"
    target_file: TargetFile
    check_case_variants: bool = Field(default=True, description="Detect case-variant net names")
    check_mixed_labels: bool = Field(default=True, description="Detect mixed label types on same net")
    check_unlabeled_junctions: bool = Field(default=True, description="Detect junctions merging unnamed nets")
