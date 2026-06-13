"""Unified gate model for design stage transitions.

A design progresses through 5 stages, and each transition requires passing a
deterministic gate that returns a structured GateResult. Gates fail closed:
GateResult.pass=False blocks downstream operations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DesignStage(str, Enum):
    """The 5 stages of PCB design, in execution order."""

    SCHEMATIC = "schematic"
    PCB_SETUP = "pcb_setup"
    PLACEMENT = "placement"
    ROUTING = "routing"
    MANUFACTURING = "manufacturing"


class GateResult(BaseModel):
    """Structured result from a gate check.

    Invariants enforced by validators:
    - pass=True implies blockers is empty
    - pass=False implies blockers is non-empty
    """

    model_config = {"populate_by_name": True, "frozen": True}

    pass_: bool = Field(alias="pass", default=True)
    gate_name: str = ""
    stage: DesignStage = DesignStage.SCHEMATIC
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _blockers_invariant(self) -> GateResult:
        """pass=True requires empty blockers; pass=False requires non-empty."""
        if self.pass_ is True and len(self.blockers) > 0:
            raise ValueError("blockers must be empty when pass=True")
        if self.pass_ is False and len(self.blockers) == 0:
            raise ValueError("blockers must be non-empty when pass=False")
        return self

    @property
    def pass_bool(self) -> bool:
        """Access pass without alias conflict."""
        return self.pass_

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict.

        Produces a shape compatible with the legacy pre_pcb_schematic_gate
        return dict so existing callers continue to work unchanged.
        """
        return {
            "pass": self.pass_,
            "gate": self.gate_name,
            "ready_for_pcb": self.pass_,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "artifacts": list(self.artifacts),
            "next_actions": list(self.next_actions),
            "recommendations": list(self.warnings) + list(self.next_actions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateResult:
        """Construct a GateResult from a plain dict (reverse of to_dict).

        Handles both the new shape and legacy pre_pcb_schematic_gate shape.
        Legacy failing dicts often have recommendations but no explicit blockers;
        recommendations are promoted to blockers to satisfy the fail-closed invariant.
        """
        pass_val = data.get("pass", data.get("ready_for_pcb", True))
        blockers = data.get("blockers", [])
        warnings = data.get("warnings", [])
        recommendations = data.get("recommendations", [])

        # Legacy dicts: promote recommendations to blockers when pass=False
        if not pass_val and not blockers and recommendations:
            blockers = recommendations
        elif not blockers and recommendations:
            warnings = warnings or recommendations

        return cls(
            pass_=bool(pass_val),
            gate_name=data.get("gate", ""),
            stage=data.get("stage", DesignStage.SCHEMATIC),
            blockers=blockers,
            warnings=warnings,
            artifacts=data.get("artifacts", []),
            next_actions=data.get("next_actions", []),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)


@dataclass(frozen=True)
class GateDefinition:
    """Specification for a gate that can be registered with GateRunner.

    Uses string-based check_fn_name for registry lookup (serializable,
    follows existing op_type dispatch pattern).
    """

    name: str
    from_stage: DesignStage
    to_stage: DesignStage
    check_fn_name: str
    block_on_fail: bool = True
