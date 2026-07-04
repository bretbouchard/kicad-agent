"""Phase 156: Operation schemas for SKIDL conversion ops."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConvertToSkidlOp(BaseModel):
    """CONV-01: Read a .kicad_sch and generate a SKIDL build_*.py program.

    Reads components + nets via extract_nets, builds a CircuitIR with
    pin-name-based wiring, emits build_<stem>.py.
    """

    op_type: Literal["convert_to_skidl"] = "convert_to_skidl"
    target_file: str = Field(..., description="Path to .kicad_sch file")
    representation: Literal["L1", "L2", "both"] = Field(
        default="L1",
        description="L1=pin-level exact, L2=component-level training, both",
    )
    output_dir: Optional[str] = Field(
        default=None, max_length=512,
        description="Output directory (default: alongside source)",
    )
    flatten_hierarchy: bool = Field(
        default=True, description="Recursively flatten sub-sheets",
    )


class ConvertFromSkidlOp(BaseModel):
    """CONV-08: Build a .kicad_sch from a SKIDL build_*.py program."""

    op_type: Literal["convert_from_skidl"] = "convert_from_skidl"
    target_file: str = Field(
        ..., description="Path to OUTPUT .kicad_sch (created/overwritten)"
    )
    source: str = Field(
        ..., min_length=1, max_length=512,
        description="Path to SKIDL program or netlist",
    )
    source_type: Literal["skidl", "netlist"] = Field(
        default="skidl", description="Source type",
    )
