"""Schema for the critique_sch operation (Phase 109 D-04 separate op).

AI legibility critic — Gemma 4 primary + Claude R-4 fallback. Scores
density/clarity/spacing/organization against the Phase 48.5 SRS signal.

This is a read-only operation — no .kicad_sch file mutation occurs. Routes
through execute_schematic_query (no Transaction, no serialize).
"""
from typing import Literal

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class CritiqueSchOp(BaseModel):
    """Critique a schematic for legibility using the hybrid Gemma + Claude stack.

    Attributes:
        op_type: Discriminator literal ``"critique_sch"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        gemma_only: Force Gemma primary, skip Claude fallback.
        claude_only: Force Claude, skip Gemma (debug / Phase 110 eval).
        include_suggestions: Emit suggestions list (False = fast batch scoring).
    """

    op_type: Literal["critique_sch"] = "critique_sch"
    target_file: TargetFile
    gemma_only: bool = Field(
        default=False,
        description="Force Gemma primary, skip Claude fallback",
    )
    claude_only: bool = Field(
        default=False,
        description="Force Claude, skip Gemma (debug / Phase 110 eval)",
    )
    include_suggestions: bool = Field(
        default=True,
        description="Emit suggestions list (False = fast batch scoring)",
    )
