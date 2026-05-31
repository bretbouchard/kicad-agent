"""ERC smart operations schemas -- classify violations, diagnose root causes, auto-fix.

Separate from _schema_repair.py to keep the repair schema focused on existing
operations. New smart ERC operations get their own module (D-01 from CONTEXT.md).

Council H-02: ErcAutoFixOp migrated from _schema_repair.py to avoid duplicate
op_type discriminator in the Operation union.
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


class ErcAutoFixOp(BaseModel):
    """Meta-operation: run ERC, dispatch repairs by violation type, iterate.

    Chains parse_erc to violation-type analysis to repair dispatch, with
    iteration limits and structured result reporting. Supports two modes:

    - ``symptom`` (default): existing iteration-based repair. Groups violations
      by type and dispatches repair functions in priority order across multiple
      iterations.
    - ``root_cause``: classify first, diagnose fixable violations, apply targeted
      fixes, document pre-existing issues, suppress benign noise. Single-pass
      (diagnosis replaces iteration).

    Attributes:
        op_type: Discriminator literal ``"erc_auto_fix"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        max_iterations: Maximum repair iterations (default 3, max 10). Each
            iteration runs ERC then dispatches all applicable repairs.
        mode: ``"symptom"`` for existing behavior, ``"root_cause"`` for
            classify-diagnose-fix pipeline.
        fix_classes: In root_cause mode, only fix these violation classes.
            None = fixable only (default).
    """

    op_type: Literal["erc_auto_fix"] = "erc_auto_fix"
    target_file: TargetFile
    max_iterations: int = Field(
        default=3, ge=1, le=10,
        description="Maximum repair iterations (default 3)",
    )
    mode: Literal["symptom", "root_cause"] = Field(
        default="symptom",
        description="symptom: existing iteration-based repair. root_cause: classify first, fix only fixable.",
    )
    fix_classes: Optional[list[str]] = Field(
        default=None,
        description="In root_cause mode, only fix these classes. None = fixable only.",
    )
