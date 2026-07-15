"""Reference operation schemas -- renumber, validate, annotate, cross-ref check."""

from typing import Literal

from pydantic import BaseModel, Field

from volta.ops.schema import TargetFile


class RenumberRefsOp(BaseModel):
    """Renumber component references with configurable prefix and sequencing.

    Attributes:
        op_type: Discriminator literal ``"renumber_refs"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        prefix: Only renumber components with this prefix. Empty means all (default).
        start_index: Starting index for numbering (default 1, must be >= 1).
        step: Step between indices (default 1, must be >= 1).
    """

    op_type: Literal["renumber_refs"] = "renumber_refs"
    target_file: TargetFile
    prefix: str = Field(
        default="",
        max_length=16,
        description="Prefix filter. Empty means renumber all prefixes.",
    )
    start_index: int = Field(
        default=1,
        ge=1,
        description="Starting index for numbering",
    )
    step: int = Field(
        default=1,
        ge=1,
        description="Step between sequential indices",
    )


class ValidateRefsOp(BaseModel):
    """Validate that all component references are unique.

    Attributes:
        op_type: Discriminator literal ``"validate_refs"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["validate_refs"] = "validate_refs"
    target_file: TargetFile


class AnnotateOp(BaseModel):
    """Auto-assign references to unannotated components (refs ending in '?').

    Attributes:
        op_type: Discriminator literal ``"annotate"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        prefix_filter: Only annotate components matching this prefix. Empty means all.
    """

    op_type: Literal["annotate"] = "annotate"
    target_file: TargetFile
    prefix_filter: str = Field(
        default="",
        max_length=16,
        description="Prefix filter for annotation. Empty means annotate all.",
    )


class SafeAnnotateOp(BaseModel):
    """Non-destructive reference designator renumbering via raw S-expr edits.

    Mirrors safe_sync_pcb_from_schematic (ae-26): never calls kiutils
    Schematic.to_file(). All edits via SchematicRawWriter + atomic_write.

    Replaces the forbidden ``annotate`` op (P0-006) which corrupts KiCad 10
    schematics via kiutils re-serialization.

    Attributes:
        op_type: Discriminator literal ``"safe_annotate"``.
        target_file: Relative path to the target KiCad schematic file.
            For scope="whole_project", this is the root sheet; sub-sheets
            are discovered by walking (sheet ...) blocks.
        scope: ``"whole_project"`` walks all sub-sheets; ``"current_sheet"``
            operates on target_file only. Default: whole_project.
        reset: When True, strip all refs to ``<prefix>?`` before renumbering.
            Required when cross-sheet duplicates exist. Default: False.
        order: Sort order for renumbering. Default: by_x_position (KiCad GUI
            default).
        dry_run: When True, return the rename plan without writing files.
            Default: False.
    """

    op_type: Literal["safe_annotate"] = "safe_annotate"
    target_file: TargetFile
    scope: Literal["whole_project", "current_sheet"] = Field(
        default="whole_project",
        description="Annotation scope: whole_project walks sub-sheets; current_sheet is target only.",
    )
    reset: bool = Field(
        default=False,
        description="Strip refs to <prefix>? before renumber. Required for duplicate resolution.",
    )
    order: Literal["by_x_position", "by_y_position", "sheet_order"] = Field(
        default="by_x_position",
        description="Sort order for sequential ref assignment.",
    )
    dry_run: bool = Field(
        default=False,
        description="Return rename plan without writing files.",
    )


class CrossRefCheckOp(BaseModel):
    """Verify all symbol libIds resolve to entries in the embedded libSymbols.

    Attributes:
        op_type: Discriminator literal ``"cross_ref_check"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["cross_ref_check"] = "cross_ref_check"
    target_file: TargetFile
