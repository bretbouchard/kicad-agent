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


class StripShortsOp(BaseModel):
    """Remove shorting track segments identified by DRC shorting_items violations.

    Parses DRC report for shorting_items, matches by net name and exact
    endpoint coordinates within tolerance, then removes matched (segment ...)
    blocks from raw PCB S-expression text.

    Attributes:
        op_type: Discriminator literal ``"strip_shorts"``.
        target_file: Relative path to the target .kicad_pcb file.
        drc_report: Path to existing DRC report. If None, auto-runs kicad-cli pcb drc.
        tolerance_mm: Coordinate matching tolerance in mm (default 0.01).
    """

    op_type: Literal["strip_shorts"] = "strip_shorts"
    target_file: TargetFile
    drc_report: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Path to existing DRC report. If None, auto-runs kicad-cli pcb drc",
    )
    tolerance_mm: float = Field(
        default=0.01,
        gt=0,
        le=1.0,
        description="Coordinate matching tolerance in mm",
    )


class RemoveDanglingTracksOp(BaseModel):
    """Iteratively remove dangling tracks and vias from a PCB.

    Runs DRC, parses track_dangling and via_dangling violations, matches
    coordinates to PCB segments/vias, removes fully-dangling elements (both
    endpoints orphaned), then iterates until convergence.

    Attributes:
        op_type: Discriminator literal ``"remove_dangling_tracks"``.
        target_file: Relative path to the target .kicad_pcb file.
        max_iterations: Maximum cleanup iterations for cascading orphans (default 30).
        tolerance_mm: Coordinate matching tolerance in mm (default 0.001).
    """

    op_type: Literal["remove_dangling_tracks"] = "remove_dangling_tracks"
    target_file: TargetFile
    max_iterations: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Maximum cleanup iterations for cascading orphans",
    )
    tolerance_mm: float = Field(
        default=0.001,
        gt=0,
        le=1.0,
        description="Coordinate matching tolerance in mm",
    )


class AutoRouteFreeroutingOp(BaseModel):
    """Full auto-route pipeline: DSN export -> Freerouting -> SES import -> cleanup.

    Chains the complete Freerouting auto-routing pipeline into a single operation:
    1. Export PCB to Specctra DSN format
    2. Run Freerouting headless batch auto-router
    3. Import SES routing result back into PCB
    4. Strip shorting segments (optional cleanup)
    5. Remove dangling tracks/vias (optional cleanup)

    Consolidates the 5-script manual pipeline (export_dsn_raw.py + FreerouteBatch.java
    + import_ses.py + strip_shorts.py + remove_dangling.py) into one kicad-agent
    operation. No project needs its own Freerouting JAR copy.

    Attributes:
        op_type: Discriminator literal ``"auto_route_freerouting"``.
        target_file: Relative path to the target .kicad_pcb file.
        passes: Maximum Freerouting routing passes (default 25).
        cleanup_shorts: Run strip_shorts after SES import (default True).
        cleanup_dangling: Run remove_dangling_tracks after strip_shorts (default True).
    """

    op_type: Literal["auto_route_freerouting"] = "auto_route_freerouting"
    target_file: TargetFile
    passes: int = Field(
        default=25,
        ge=1,
        le=200,
        description="Maximum Freerouting routing passes",
    )
    cleanup_shorts: bool = Field(
        default=True,
        description="Run strip_shorts after import",
    )
    cleanup_dangling: bool = Field(
        default=True,
        description="Run remove_dangling_tracks after import",
    )


class GenerateBomOp(BaseModel):
    """Generate a BOM with LCSC/JLCPCB part numbers from a KiCad schematic.

    Parses component instances (symbol blocks) from a .kicad_sch file,
    looks up each component in an externalized YAML part mapping table,
    aggregates by part+value, and returns a structured BOM with LCSC codes,
    quantities, and estimated costs.

    This is a read-only operation -- it never modifies the schematic.

    Attributes:
        op_type: Discriminator literal ``"generate_bom"``.
        target_file: Relative path to the target .kicad_sch file.
        supplier: Supplier name for part lookup (default ``"lcsc"``).
        mapping_file: Optional path to custom part mapping YAML.
            Defaults to the bundled ``data/part-mappings.yaml``.
    """

    op_type: Literal["generate_bom"] = "generate_bom"
    target_file: TargetFile
    supplier: str = Field(
        default="lcsc",
        min_length=1,
        max_length=32,
        description="Supplier name for part lookup",
    )
    mapping_file: str | None = Field(
        default=None,
        max_length=512,
        description="Path to custom part mapping YAML. Defaults to bundled part-mappings.yaml",
    )
