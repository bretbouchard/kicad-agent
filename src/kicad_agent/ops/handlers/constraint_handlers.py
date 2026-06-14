"""Constraint operation handlers -- set and get design constraints.

SetConstraintsOp validates and propagates DesignConstraints to:
1. .kicad_dru via project/design_rules.py (ConstraintPropagator)
2. Sidecar file .kicad_agent/constraints.json for reliable round-trip

GetConstraintsOp reads constraints from the persisted sidecar file.

Both schemas validate project_dir against path traversal attacks (88-02-H1),
matching the pcb_transfer.py:73-85 pattern.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from kicad_agent.validation.gates.constraint_schema import DesignConstraints

logger = logging.getLogger(__name__)

# Sidecar file path (relative to project_dir)
_CONSTRAINTS_SIDECAR = ".kicad_agent/constraints.json"


# ---------------------------------------------------------------------------
# Path validator (88-02-H1: matches pcb_transfer.py:73-85)
# ---------------------------------------------------------------------------


def _validate_project_dir(v: str | None) -> str | None:
    """Reject path traversal and unsafe characters.

    Rejects null bytes, absolute paths, and '..' path traversal.
    Matches the pattern from pcb_transfer.py:73-85.
    """
    if v is not None:
        if "\x00" in v:
            raise ValueError("file path contains null bytes")
        if v.startswith("/"):
            raise ValueError("file path must be a relative path")
        parts = Path(v).parts
        if ".." in parts:
            raise ValueError("file path must not contain '..' path traversal")
    return v


# ---------------------------------------------------------------------------
# Operation schemas
# ---------------------------------------------------------------------------


class SetConstraintsOp(BaseModel):
    """Set design constraints for a PCB project.

    Validates constraints via DesignConstraints model, propagates to .kicad_dru
    via ConstraintPropagator, and writes canonical JSON to the sidecar file
    .kicad_agent/constraints.json for reliable round-trip (88-02-M2).

    Attributes:
        op_type: Discriminator literal ``"set_constraints"``.
        constraints: DesignConstraints JSON dict or DesignConstraints instance.
        project_dir: Optional relative path to the project directory.
        dry_run: If True, validate only without writing any files.
    """

    op_type: Literal["set_constraints"] = "set_constraints"
    constraints: DesignConstraints
    project_dir: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Relative path to project directory",
    )
    dry_run: bool = Field(
        default=False,
        description="Validate only without writing files",
    )

    @field_validator("project_dir", mode="before")
    @classmethod
    def _validate_project_dir(cls, v: str | None) -> str | None:
        return _validate_project_dir(v)


class GetConstraintsOp(BaseModel):
    """Get design constraints for a PCB project.

    Reads from the persisted sidecar file .kicad_agent/constraints.json.
    If the sidecar file does not exist, raises a clear error directing
    the user to run SetConstraintsOp first (88-02-M2).

    Attributes:
        op_type: Discriminator literal ``"get_constraints"``.
        project_dir: Optional relative path to the project directory.
    """

    op_type: Literal["get_constraints"] = "get_constraints"
    project_dir: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Relative path to project directory",
    )

    @field_validator("project_dir", mode="before")
    @classmethod
    def _validate_project_dir(cls, v: str | None) -> str | None:
        return _validate_project_dir(v)


# ---------------------------------------------------------------------------
# Handler functions
# ---------------------------------------------------------------------------


def handle_set_constraints(op: SetConstraintsOp) -> dict[str, Any]:
    """Execute SetConstraintsOp: validate and propagate constraints.

    Steps:
    1. Validate constraints via DesignConstraints model (already done by Pydantic).
    2. Run cross-constraint validation.
    3. If dry_run, return validation result without writing.
    4. Propagate to .kicad_dru via ConstraintPropagator.
    5. Write canonical JSON to .kicad_agent/constraints.json sidecar file.

    Returns:
        Dict with validation result, written paths, and constraint counts.
    """
    constraints = op.constraints
    project_dir = Path(op.project_dir) if op.project_dir else Path.cwd()

    # Cross-constraint validation
    cross_warnings = constraints.validate_cross_constraints()
    fab_warnings = constraints.fab.validate_achievable(constraints.electrical)
    all_warnings = cross_warnings + fab_warnings

    # Dry run: validate only
    if op.dry_run:
        return {
            "status": "validated",
            "dry_run": True,
            "electrical_count": len(constraints.electrical),
            "mechanical_present": constraints.mechanical is not None,
            "fab_profile": {
                "layer_count": constraints.fab.layer_count,
                "material": constraints.fab.material,
                "min_trace_width_mm": constraints.fab.min_trace_width_mm,
            },
            "warnings": all_warnings,
            "written_paths": [],
        }

    # Propagate to .kicad_dru via ConstraintPropagator
    from kicad_agent.validation.gates.constraint_gate import ConstraintPropagator

    propagator = ConstraintPropagator()
    dru_path = project_dir / "board.kicad_dru"
    dru_warnings = propagator.propagate(constraints, dru_path)
    all_warnings.extend(dru_warnings)

    # Write sidecar file for reliable round-trip
    sidecar_path = project_dir / _CONSTRAINTS_SIDECAR
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_json = constraints.model_dump(mode="json")
    sidecar_path.write_text(
        json.dumps(sidecar_json, indent=2, default=str),
        encoding="utf-8",
    )

    return {
        "status": "written",
        "dry_run": False,
        "electrical_count": len(constraints.electrical),
        "mechanical_present": constraints.mechanical is not None,
        "fab_profile": {
            "layer_count": constraints.fab.layer_count,
            "material": constraints.fab.material,
            "min_trace_width_mm": constraints.fab.min_trace_width_mm,
        },
        "written_paths": [
            str(dru_path),
            str(sidecar_path),
        ],
        "warnings": all_warnings,
    }


def handle_get_constraints(op: GetConstraintsOp) -> dict[str, Any]:
    """Execute GetConstraintsOp: read constraints from sidecar file.

    Reads from .kicad_agent/constraints.json and returns the deserialized
    DesignConstraints. Raises clear error if sidecar file does not exist.

    Returns:
        Dict with DesignConstraints data.
    """
    project_dir = Path(op.project_dir) if op.project_dir else Path.cwd()
    sidecar_path = project_dir / _CONSTRAINTS_SIDECAR

    if not sidecar_path.exists():
        raise FileNotFoundError(
            f"Constraints sidecar file not found at '{sidecar_path}'. "
            f"Run set_constraints operation first to create it."
        )

    raw = sidecar_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    constraints = DesignConstraints.model_validate(data)

    return {
        "status": "loaded",
        "constraints": constraints.model_dump(mode="json"),
        "source_path": str(sidecar_path),
    }
