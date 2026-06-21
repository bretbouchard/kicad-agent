"""Gap analysis and gap-filling operation schemas."""

from typing import Literal

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import TargetFile


class FillZonesOp(BaseModel):
    """Fill existing copper zones on a PCB using KiCad's pcbnew API.

    Uses pcbnew.ZONE_FILLER to compute and store zone fill geometry.
    Requires KiCad's bundled Python (not system Python) for pcbnew access.
    This is the exception to the "no kiutils for PCBs" rule because zone fill
    geometry must come from KiCad's own engine (pcbnew.SaveBoard is safe).

    Attributes:
        op_type: Discriminator literal ``"fill_zones"``.
        target_file: Relative path to the target .kicad_pcb file.
        layers: Layers to fill, or ``["all"]`` for every zone on the board.
        dry_run: If True, list zones without filling.
    """

    op_type: Literal["fill_zones"] = "fill_zones"
    target_file: TargetFile
    layers: list[str] = Field(
        default=["all"],
        description="Layers to fill, or ['all'] for every zone",
    )
    dry_run: bool = Field(
        default=False,
        description="List zones without filling",
    )


class AnalyzeGapsOp(BaseModel):
    """Analyze a PCB for routing gaps, DRC violations, and naming issues.

    Attributes:
        op_type: Discriminator literal ``"analyze_gaps"``.
        target_file: Relative path to the target .kicad_pcb file.
        run_drc: Whether to run DRC during analysis. Defaults to True.
    """

    op_type: Literal["analyze_gaps"] = "analyze_gaps"
    target_file: TargetFile
    run_drc: bool = Field(default=True, description="Run DRC during analysis")


class FillGapsOp(BaseModel):
    """Run the AI-powered gap-filling engine on a PCB.

    Attributes:
        op_type: Discriminator literal ``"fill_gaps"``.
        target_file: Relative path to the target .kicad_pcb file.
        max_iterations: Maximum analyze-fill-verify iterations (1-3).
        target_route_pct: Target route percentage to converge on (0-100).
        run_drc: Whether to run DRC between iterations.
        use_ai: Whether to use the AI model for prioritization and fix suggestions.
    """

    op_type: Literal["fill_gaps"] = "fill_gaps"
    target_file: TargetFile
    max_iterations: int = Field(
        default=3, ge=1, le=3, description="Max analyze-fill-verify iterations",
    )
    target_route_pct: float = Field(
        default=95.0, ge=0, le=100, description="Target route percentage",
    )
    run_drc: bool = Field(default=True, description="Run DRC between iterations")
    use_ai: bool = Field(default=True, description="Use AI for prioritization")
