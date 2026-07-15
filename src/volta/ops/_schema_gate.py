"""Gate operation schemas -- check and status operations for design stage gates."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RunGateCheckOp(BaseModel):
    """Run a named gate check against the current design.

    Check operations are read-only: they inspect the design and return
    a GateResult without mutating any files.

    Attributes:
        op_type: Discriminator literal ``"run_gate_check"``.
        gate_name: Name of the gate to run (must be registered with GateRunner).
        project_dir: Optional project directory path.
    """

    op_type: Literal["run_gate_check"] = "run_gate_check"
    gate_name: str = Field(
        min_length=1,
        max_length=100,
        description="Name of the gate to run (e.g. 'pre_pcb_schematic')",
    )
    project_dir: Optional[str] = Field(
        default=None,
        description="Project directory containing the design files",
    )


class GateStatusOp(BaseModel):
    """Query the current design stage and gate states.

    Returns the current DesignStage, registered gates, and last gate results.

    Attributes:
        op_type: Discriminator literal ``"gate_status"``.
        project_dir: Optional project directory path.
    """

    op_type: Literal["gate_status"] = "gate_status"
    project_dir: Optional[str] = Field(
        default=None,
        description="Project directory containing the design files",
    )
