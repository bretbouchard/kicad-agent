"""Schematic routing operation schemas -- pin resolution, collision detection, wire routing.

Schemas for the schematic routing engine (Phase 38). These operations read
schematic files to resolve pin positions, detect collisions, and plan wire
routes -- they are analysis/query operations, not mutations.

Security (threat model):
  T-38-01-01: target_file validated via TargetFile type (inherited H-01)
  T-38-01-02: ref field bounded to max_length=16 (component refs are short)
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class ResolvePinPositionsOp(BaseModel):
    """Resolve absolute pin positions for schematic components.

    Reads a .kicad_sch file, parses lib_symbols and placed symbol instances,
    and returns absolute coordinates for every pin of every (or filtered)
    component, including multi-unit ICs and rotation transforms.

    Attributes:
        op_type: Discriminator literal ``"resolve_pin_positions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        ref: Optional component reference filter (e.g. ``"R55"``, ``"U21"``).
    """

    op_type: Literal["resolve_pin_positions"] = "resolve_pin_positions"
    target_file: TargetFile
    ref: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Filter to a single component reference (e.g. 'R55')",
    )
