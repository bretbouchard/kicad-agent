"""Wire/label/power operation schemas -- wire, label, power, no-connect, junction."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import (
    PositionSpec,
    TargetFile,
    _validate_sexpr_safe_string,
)


class AddWireOp(BaseModel):
    """Add a wire segment between two points in a schematic.

    Phase 129 -- net-aware wire generation:

        By default the operation validates that both endpoints resolve to the
        same net (or at least one endpoint is unlabelled). A ``ValueError`` is
        raised when the endpoints would short two different nets, preventing
        the schematic corruption seen in the backplane power rails.

        Set ``force=True`` to override validation when merging ground variants
        or wiring unlabelled positions. The override is recorded in the
        mutation log for auditability.

    Attributes:
        op_type: Discriminator literal ``"add_wire"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        start_x: Start X coordinate in mm.
        start_y: Start Y coordinate in mm.
        end_x: End X coordinate in mm.
        end_y: End Y coordinate in mm.
        force: When ``True``, skip net-conflict validation. Default ``False``.
    """

    op_type: Literal["add_wire"] = "add_wire"
    target_file: TargetFile
    start_x: float = Field(description="Start X coordinate in mm")
    start_y: float = Field(description="Start Y coordinate in mm")
    end_x: float = Field(description="End X coordinate in mm")
    end_y: float = Field(description="End Y coordinate in mm")
    force: bool = Field(
        default=False,
        description=(
            "Override net-conflict validation. Use when intentionally merging "
            "ground variants (e.g. GND/AGND) or wiring unlabelled positions. "
            "The override is logged in the mutation trail."
        ),
    )

    @field_validator("start_x", "start_y", "end_x", "end_y")
    @classmethod
    def _reject_non_finite(cls, v: float) -> float:
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Coordinate values must be finite (not NaN or Infinity)")
        return v


class AddLabelOp(BaseModel):
    """Add a net label to a schematic (local, global, or hierarchical).

    Attributes:
        op_type: Discriminator literal ``"add_label"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        name: Label text (e.g. ``"SDA"``, ``"+5V"``).
        label_type: Label scope -- ``"local"``, ``"global"``, or ``"hierarchical"``.
        position: Placement coordinates (x, y, angle).
        shape: Graphical shape for global/hierarchical labels (e.g. ``"input"``,
               ``"output"``, ``"bidirectional"``, ``"tri_state"``, ``"passive"``).
    """

    op_type: Literal["add_label"] = "add_label"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=128,
        description="Label text (e.g. 'SDA', '+5V')",
    )
    label_type: Literal["local", "global", "hierarchical"] = Field(
        default="local",
        description="Label scope: local, global, or hierarchical",
    )
    position: PositionSpec
    shape: str = Field(
        default="input",
        description="Shape for global/hierarchical labels (input, output, bidirectional, tri_state, passive)",
    )

    @field_validator("name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class AddPowerOp(BaseModel):
    """Add a power symbol to a schematic (e.g. +5V, GND, +3V3).

    Places a power library symbol (``power:<name>``) at the specified position.
    Power symbols have a single pin that connects to the named net.

    Attributes:
        op_type: Discriminator literal ``"add_power"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        name: Power net name (e.g. ``"+5V"``, ``"GND"``, ``"+3V3"``).
        position: Placement coordinates.
    """

    op_type: Literal["add_power"] = "add_power"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=64,
        description="Power net name (e.g. '+5V', 'GND', '+3V3')",
    )
    position: PositionSpec

    @field_validator("name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class AddNoConnectOp(BaseModel):
    """Add a no-connect flag to a schematic pin.

    Attributes:
        op_type: Discriminator literal ``"add_no_connect"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        position: Placement coordinates (x, y; angle is ignored).
    """

    op_type: Literal["add_no_connect"] = "add_no_connect"
    target_file: TargetFile
    position: PositionSpec


class AddJunctionOp(BaseModel):
    """Add a junction dot at a wire intersection in a schematic.

    Attributes:
        op_type: Discriminator literal ``"add_junction"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        position: Placement coordinates (x, y; angle is ignored).
    """

    op_type: Literal["add_junction"] = "add_junction"
    target_file: TargetFile
    position: PositionSpec


class RenameNetLabelOp(BaseModel):
    """Rename all labels matching a given name to a new name.

    Finds and renames all labels (local, global, hierarchical, or a subset)
    matching ``old_name`` to ``new_name``. Warns if ``new_name`` already
    exists as a different label.

    Attributes:
        op_type: Discriminator literal ``"rename_net_label"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        old_name: Current label text to find and rename.
        new_name: Replacement label text.
        label_type: Which label types to rename: ``"label"``, ``"global"``,
            ``"hierarchical"``, or ``"all"`` (default).
        dry_run: If True, report what would change without modifying.
    """

    op_type: Literal["rename_net_label"] = "rename_net_label"
    target_file: TargetFile
    old_name: str = Field(
        min_length=1,
        max_length=128,
        description="Current label text to find and rename",
    )
    new_name: str = Field(
        min_length=1,
        max_length=128,
        description="Replacement label text",
    )
    label_type: Literal["label", "global", "hierarchical", "all"] = Field(
        default="all",
        description="Which label types to rename",
    )
    dry_run: bool = Field(
        default=False,
        description="Report what would change without modifying",
    )

    @field_validator("old_name", "new_name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class AddPowerFlagOp(BaseModel):
    """Place PWR_FLAG symbols at power_pin_not_driven ERC violation positions.

    SCHREPAIR-06: ERC-driven power flag placement.

    Attributes:
        op_type: Discriminator literal ``"add_power_flag"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
    """

    op_type: Literal["add_power_flag"] = "add_power_flag"
    target_file: TargetFile
