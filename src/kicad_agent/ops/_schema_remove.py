"""Remove operation schemas -- remove_wire, remove_label, remove_junction, remove_no_connect."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_sexpr_safe_string,
)


class RemoveWireOp(BaseModel):
    """Remove a wire segment by UUID.

    Attributes:
        op_type: Discriminator literal ``"remove_wire"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        uuid: UUID of the wire Connection object to remove.
    """

    op_type: Literal["remove_wire"] = "remove_wire"
    target_file: TargetFile
    uuid: str = Field(
        min_length=1,
        max_length=64,
        description="UUID of the wire to remove",
    )

    @field_validator("uuid")
    @classmethod
    def _validate_uuid_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class RemoveLabelOp(BaseModel):
    """Remove a net label by UUID.

    Attributes:
        op_type: Discriminator literal ``"remove_label"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        uuid: UUID of the label object to remove.
        label_type: Label scope -- ``"local"``, ``"global"``, or ``"hierarchical"``.
    """

    op_type: Literal["remove_label"] = "remove_label"
    target_file: TargetFile
    uuid: str = Field(
        min_length=1,
        max_length=64,
        description="UUID of the label to remove",
    )
    label_type: Literal["local", "global", "hierarchical"] = Field(
        description="Label scope: local, global, or hierarchical",
    )

    @field_validator("uuid")
    @classmethod
    def _validate_uuid_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class RemoveJunctionOp(BaseModel):
    """Remove a junction dot by UUID.

    Attributes:
        op_type: Discriminator literal ``"remove_junction"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        uuid: UUID of the Junction object to remove.
    """

    op_type: Literal["remove_junction"] = "remove_junction"
    target_file: TargetFile
    uuid: str = Field(
        min_length=1,
        max_length=64,
        description="UUID of the junction to remove",
    )

    @field_validator("uuid")
    @classmethod
    def _validate_uuid_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class RemoveNoConnectOp(BaseModel):
    """Remove a no-connect flag by UUID.

    Attributes:
        op_type: Discriminator literal ``"remove_no_connect"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        uuid: UUID of the NoConnect object to remove.
    """

    op_type: Literal["remove_no_connect"] = "remove_no_connect"
    target_file: TargetFile
    uuid: str = Field(
        min_length=1,
        max_length=64,
        description="UUID of the no-connect to remove",
    )

    @field_validator("uuid")
    @classmethod
    def _validate_uuid_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)
