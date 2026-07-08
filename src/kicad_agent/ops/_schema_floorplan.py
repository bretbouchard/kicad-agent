"""Schema for the apply_floor_plan operation (kicad-agent-24 op integration).

Phase 157 shipped the FloorPlanSpec + PlacementRule infrastructure but
did not expose it as a kicad-agent op. This op closes that gap — users
can now apply a YAML floor plan to a PCB via the standard op API:

    /kicad-agent '{
        "op_type": "apply_floor_plan",
        "target_file": "board.kicad_pcb",
        "floor_plan_file": "board.floorplan.yaml"
    }'

Returns applied=True with fixed_count, keepout_count, violations, and
total_penalty in details. Hard-rule violations block the operation
(applied=False, modified_content = original).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ApplyFloorPlanOp(BaseModel):
    """Apply a declarative floor plan (YAML) to a PCB.

    Lowers the floor plan into placement vectors, applies fixed component
    positions, injects keepout zones, and verifies hard placement rules.

    Attributes:
        op_type: Discriminator literal ``"apply_floor_plan"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        floor_plan_file: Relative path to the YAML floor plan spec
            (per Phase 157 spec format: zones, keepouts, rules with rationale).
        fail_on_violations: If True (default), hard-rule violations block
            the operation — original PCB content is preserved. If False,
            violations are reported but the operation succeeds with soft
            rules applied.
    """

    op_type: Literal["apply_floor_plan"] = "apply_floor_plan"
    target_file: TargetFile
    floor_plan_file: str = Field(
        ...,
        description="Relative path to the YAML floor plan spec",
    )
    fail_on_violations: bool = Field(
        default=True,
        description="Block operation on hard-rule violations (default True)",
    )

