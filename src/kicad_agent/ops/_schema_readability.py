"""Schema for schematic readability review operation.

READ-01/02/03/04: Read-only operation that runs spatial rules,
computes readability score, and optionally invokes Claude vision review.
"""
from typing import Literal

from pydantic import BaseModel, Field


class ReviewSchematicOp(BaseModel):
    """Review a schematic for readability and spatial quality.

    Runs 6 readability rules, computes SRS score, and optionally
    renders the schematic for Claude vision review.

    This is a read-only operation -- no file mutation occurs.
    """

    operation_type: Literal["review_schematic"] = "review_schematic"
    file_path: str = Field(description="Path to .kicad_sch file to review")
    vision: bool = Field(
        default=False,
        description="Include Claude vision review of rendered schematic",
    )
    output_format: Literal["json", "markdown"] = Field(
        default="markdown",
        description="Output format for review report",
    )
    config_path: str | None = Field(
        default=None,
        description="Optional path to YAML rule configuration",
    )
