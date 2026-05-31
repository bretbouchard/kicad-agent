"""ERC smart operations schemas -- classify violations, diagnose root causes.

Separate from _schema_repair.py to keep the repair schema focused on existing
operations. New smart ERC operations get their own module (D-01 from CONTEXT.md).
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ClassifyViolationsOp(BaseModel):
    """Classify ERC violations into actionable categories.

    Parses ERC output and categorizes each violation as fixable, pre-existing,
    benign, or config_issue with confidence levels and root cause explanations.

    Attributes:
        op_type: Discriminator literal ``"classify_violations"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        erc_report_path: Pre-generated ERC report path. If None, runs ERC via parse_erc.
    """

    op_type: Literal["classify_violations"] = "classify_violations"
    target_file: TargetFile
    erc_report_path: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Pre-generated ERC report path. If None, runs ERC via parse_erc.",
    )


class DiagnoseViolationsOp(BaseModel):
    """Diagnose root causes for fixable ERC violations and propose targeted fixes.

    Takes classified violations (from classify_violations) and generates
    concrete fix options with side effect analysis and confidence ratings.

    Attributes:
        op_type: Discriminator literal ``"diagnose_violations"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        violation_types: Specific violation types to diagnose. None = all fixable types.
    """

    op_type: Literal["diagnose_violations"] = "diagnose_violations"
    target_file: TargetFile
    violation_types: Optional[list[str]] = Field(
        default=None,
        description="Specific violation types to diagnose. None = all fixable types.",
    )
