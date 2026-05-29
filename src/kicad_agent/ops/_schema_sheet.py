"""Hierarchical sheet operation schemas."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    PositionSpec,
    TargetFile,
    _validate_safe_identifier,
    _validate_sexpr_safe_string,
)


class AddSheetOp(BaseModel):
    op_type: Literal["add_sheet"] = "add_sheet"
    target_file: TargetFile
    sheet_name: str = Field(min_length=1, max_length=128, description="Display name for the sheet symbol")
    file_name: str = Field(min_length=1, max_length=256, description="Relative path to child .kicad_sch")
    position: PositionSpec = Field(description="Position of the sheet symbol rectangle")
    width: float = Field(default=30.0, gt=0, le=500, description="Sheet symbol width in mm")
    height: float = Field(default=20.0, gt=0, le=500, description="Sheet symbol height in mm")
    create_sub_sheet: bool = Field(default=True, description="Auto-create child .kicad_sch if it doesn't exist")

    @field_validator("sheet_name")
    @classmethod
    def _validate_sheet_name(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class AddSheetPinOp(BaseModel):
    op_type: Literal["add_sheet_pin"] = "add_sheet_pin"
    target_file: TargetFile
    sheet_uuid: str = Field(min_length=36, max_length=36, description="UUID of target HierarchicalSheet")
    pin_name: str = Field(min_length=1, max_length=128, description="Pin name matching hierarchical label in child sheet")
    connection_type: Literal["input", "output", "bidirectional", "tri_state", "passive"] = Field(default="bidirectional")
    position: PositionSpec = Field(description="Pin position on sheet boundary")

    @field_validator("pin_name")
    @classmethod
    def _validate_pin_name(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class NavigateSheetsOp(BaseModel):
    op_type: Literal["navigate_hierarchy"] = "navigate_hierarchy"
    target_file: TargetFile
    max_depth: int = Field(default=-1, ge=-1, le=20, description="Max traversal depth (-1 = unlimited)")
