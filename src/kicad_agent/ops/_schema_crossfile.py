"""Cross-file operation schemas -- atomic multi-file mutations.

XFILE-07: Cross-file operations coordinate mutations across multiple KiCad files
in a single atomic transaction. If any file fails, all files roll back.

D-03 is relaxed for cross-file operations: target_file is required for execute()
routing, while target_files lists all files to mutate atomically.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import TargetFile, _validate_safe_identifier


class PropagateSymbolChangeOp(BaseModel):
    """Propagate a symbol/footprint library reference change across multiple files atomically.

    Attributes:
        op_type: Discriminator literal ``"propagate_symbol_change"``.
        target_file: Primary file path (used by execute() routing, must be first in target_files).
        target_files: List of relative file paths to mutate (schematic and/or PCB files).
        old_lib_id: Current library ID to match, e.g. "Device:R_Small_US".
        new_lib_id: Replacement library ID, e.g. "MyLib:R_Small_US".
    """

    op_type: Literal["propagate_symbol_change"] = "propagate_symbol_change"
    target_file: TargetFile = Field(
        description="Primary file for execute() routing (first entry in target_files)",
    )
    target_files: list[TargetFile] = Field(
        min_length=1,
        max_length=20,
        description="List of files to update atomically",
    )
    old_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Current library ID to match",
    )
    new_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Replacement library ID",
    )

    @field_validator("old_lib_id")
    @classmethod
    def _validate_old_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "old_lib_id")

    @field_validator("new_lib_id")
    @classmethod
    def _validate_new_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "new_lib_id")
