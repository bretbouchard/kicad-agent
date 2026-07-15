"""Schema for the add_design_note operation (kicad-agent-29).

Design notes are intent-bearing text annotations on schematics:
- WHY a value was chosen (REASON)
- WHAT a subcircuit is for (BLOCK_HEADER)
- HOW a target was derived (MATH)
- General commentary (NOTE)

Inspired by Bart Instruments' DUAL SSI2130 VCO CORE which embeds inline
annotations like "10uA/oct", "target 47.17uA", "2.5/55000=45.5 [uA]"
that turn a pile of resistors into a legible design.

This op MUTATES the target schematic — appends a (text ...) S-expression
block. Routes through execute_schematic_op (Transaction + serialize).
"""
from typing import Literal

from pydantic import BaseModel, Field

from volta.ops.schema import PositionSpec, TargetFile


class AddDesignNoteOp(BaseModel):
    """Add a design-intent annotation to a schematic.

    Inserts a text element capturing the WHY/WHAT/HOW of a design choice.
    Unlike net labels or refdes, design notes preserve design intent for
    reviewers and future designers.

    Attributes:
        op_type: Discriminator literal ``"add_design_note"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        text: The annotation content. Multi-line via "\\n". Examples:
            "10uA/oct" (states expo converter constant)
            "target 47.17uA" (states design goal)
            "2.5/55000=45.5 [uA] + 5/1000000=5 [uA]" (derives the result)
            "EXPONENTIAL CONVERTER CVs" (block header)
        position: Placement coordinates (x, y in mm; angle in degrees, default 0).
        note_type: Semantic category — drives default styling. NOTE = general,
            REASON = explains a value choice, MATH = derives a result,
            BLOCK_HEADER = labels a subcircuit region. Default NOTE.
        target_ref: Optional reference designator this note annotates
            (e.g. "R7" for the scale trim resistor). Used for tooling
            linkage — does NOT affect schematic placement.
        font_size_mm: Text height in mm. Default 1.27 (KiCad 5-era standard).
    """

    op_type: Literal["add_design_note"] = "add_design_note"
    target_file: TargetFile
    text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Annotation content (1-2000 chars). Multi-line via \\n.",
    )
    position: PositionSpec
    note_type: Literal["NOTE", "REASON", "MATH", "BLOCK_HEADER"] = Field(
        default="NOTE",
        description="Semantic category — drives default styling",
    )
    target_ref: str | None = Field(
        default=None,
        description="Optional refdes this note annotates (e.g. 'R7')",
    )
    font_size_mm: float = Field(
        default=1.27,
        gt=0,
        lt=20,
        description="Text height in mm (default 1.27 = KiCad standard)",
    )
