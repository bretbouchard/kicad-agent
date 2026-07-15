"""Schema for schematic readability review operation.

READ-01/02/03/04: Read-only operation that runs spatial rules,
computes readability score, and optionally invokes Claude vision review.
"""
from typing import Literal

from pydantic import BaseModel, Field

from volta.ops.schema import TargetFile


class ReviewSchematicOp(BaseModel):
    """Review a schematic for readability and spatial quality.

    Runs 6 readability rules, computes SRS score, and optionally
    renders the schematic for Claude vision review.

    This is a read-only operation -- no file mutation occurs.

    Attributes:
        op_type: Discriminator literal ``"review_schematic"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        vision: Include Claude vision review of rendered schematic.
        output_format: Output format for review report.
        config_path: Optional path to YAML rule configuration.
    """

    op_type: Literal["review_schematic"] = "review_schematic"
    target_file: TargetFile
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
