"""Schema for circuit_ir operations (SKIDL converter)."""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ConvertToSkidlOp(BaseModel):
    """Convert a KiCad schematic to SKIDL Python code.

    Reads a .kicad_sch file, extracts components and nets via build_circuit,
    and generates a Python build_*.py script using SKIDL (Phase 156).

    Attributes:
        op_type: Discriminator literal ``"convert_to_skidl"``.
        target_file: Relative path to the .kicad_sch file.
        output_file: Where to write the generated build_*.py (optional).
        level: Representation level — "L1" (pin-level) or "L2" (component-level).
    """

    op_type: Literal["convert_to_skidl"] = "convert_to_skidl"
    target_file: str = Field(min_length=1, max_length=512)
    output_file: Optional[str] = Field(
        default=None,
        description="Output path for generated build_*.py (default: return as string)"
    )
    level: Literal["L1", "L2"] = Field(
        default="L1",
        description="Representation level: L1=pin-level, L2=component-level"
    )


class ConvertFromSkidlOp(BaseModel):
    """Build a .kicad_sch from a SKIDL build_*.py program (Phase 156 CONV-08).

    Attributes:
        op_type: Discriminator literal ``"convert_from_skidl"``.
        target_file: Path to the OUTPUT .kicad_sch (created/overwritten).
        source: Path to SKIDL program (build_*.py) or netlist (.net).
        source_type: "skidl" (run Python) or "netlist" (parse .net directly).
    """

    op_type: Literal["convert_from_skidl"] = "convert_from_skidl"
    target_file: str = Field(min_length=1, max_length=512)
    source: str = Field(min_length=1, max_length=512)
    source_type: Literal["skidl", "netlist"] = Field(default="skidl")
