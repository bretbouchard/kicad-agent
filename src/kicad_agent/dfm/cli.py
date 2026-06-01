"""CLI subcommand: kicad-agent dfm <board>

DFM-05: Run DFM (Design for Manufacturing) analysis on a PCB.

Usage:
    kicad-agent dfm board.kicad_pcb
    kicad-agent dfm board.kicad_pcb --manufacturer jlcpcb
    kicad-agent dfm board.kicad_pcb --manufacturer pcbway --format json --output report.json
    kicad-agent dfm board.kicad_pcb --profile custom_profile.yaml
    kicad-agent dfm board.kicad_pcb --stage post-route
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from kicad_agent.dfm.profiles import ManufacturerProfile, load_profile

logger = logging.getLogger(__name__)


def dfm_command(args: argparse.Namespace) -> int:
    """Execute the DFM analysis subcommand.

    Args:
        args: Parsed CLI arguments with:
            board: Path to .kicad_pcb file.
            manufacturer: Built-in profile name (optional).
            profile: Path to custom YAML/JSON profile (optional).
            format: Output format ("json" or "markdown").
            output: Optional output file path.
            stage: Analysis stage ("footprint", "placement", "post-route", "all").

    Returns:
        Exit code: 0 if overall_score >= 0.5, 1 if < 0.5, 2 on error.
    """
    # 1. Resolve and validate board path
    board_path = Path(args.board)
    if not board_path.exists():
        print(f"Error: board not found: {board_path}", file=sys.stderr)
        return 2
    if board_path.suffix.lower() != ".kicad_pcb":
        print(f"Error: not a .kicad_pcb file: {board_path}", file=sys.stderr)
        return 2

    # 2. Resolve manufacturer profile
    profile_path = getattr(args, "profile", None)
    manufacturer_name = getattr(args, "manufacturer", None)

    try:
        if profile_path:
            profile = ManufacturerProfile.from_yaml(profile_path)
        elif manufacturer_name:
            profile = load_profile(manufacturer_name)
        else:
            profile = load_profile("generic")
    except (ValueError, FileNotFoundError, OSError) as e:
        print(f"Error loading profile: {e}", file=sys.stderr)
        return 2

    # 3. Parse PCB to PcbSpatialModel
    spatial_model = _build_spatial_model(board_path)
    if spatial_model is None:
        return 2

    # 4. Run DFM analysis
    stage = getattr(args, "stage", "all")
    try:
        if stage == "all":
            from kicad_agent.dfm.scoring import run_multistage_dfm
            report = run_multistage_dfm(spatial_model, profile)
            overall_score = report.overall_score
        else:
            from kicad_agent.dfm.scoring import _filter_checks, _FOOTPRINT_AUDIT_CHECKS, _PLACEMENT_CHECK_CHECKS, _POST_ROUTE_CHECK_CHECKS
            from kicad_agent.dfm.checker import DfmChecker

            stage_map = {
                "footprint": _FOOTPRINT_AUDIT_CHECKS,
                "placement": _PLACEMENT_CHECK_CHECKS,
                "post-route": _POST_ROUTE_CHECK_CHECKS,
            }
            check_names = stage_map[stage]
            checker = DfmChecker(checks=_filter_checks(check_names))
            dfm_report = checker.run(spatial_model, profile)
            report = dfm_report
            overall_score = dfm_report.manufacturability_score
    except Exception as e:
        print(f"Error running DFM analysis: {e}", file=sys.stderr)
        logger.error("DFM analysis failed", exc_info=True)
        return 2

    # 5. Format and write output
    output_format = getattr(args, "format", "markdown")
    output_path = getattr(args, "output", None)

    if output_format == "json":
        output_text = _format_json(report, stage)
    else:
        output_text = _format_markdown(report, stage, board_path, profile)

    if output_path:
        Path(output_path).write_text(output_text, encoding="utf-8")
        print(f"Report written to {output_path}")
    else:
        print(output_text)

    # 6. Return exit code based on score
    return 0 if overall_score >= 0.5 else 1


def _build_spatial_model(board_path: Path) -> Any:
    """Parse a .kicad_pcb file and build PcbSpatialModel.

    Returns None with error message if Phase 51 dependency not available.

    Args:
        board_path: Path to .kicad_pcb file.

    Returns:
        PcbSpatialModel or None on failure.
    """
    try:
        from kicad_agent.parser import parse_pcb
        from kicad_agent.ir.pcb_ir import PcbIR
        from kicad_agent.parser.uuid_extractor import extract_uuids
        from kicad_agent.spatial.pcb_model import PcbSpatialModel

        result = parse_pcb(board_path)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        pcb_ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
        return PcbSpatialModel.build_from_pcb_ir(pcb_ir)
    except ImportError:
        print(
            "Error: PcbSpatialModel not available. "
            "Phase 51 (spatial intelligence) is required for DFM analysis.",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(f"Error parsing PCB: {e}", file=sys.stderr)
        return None


def _format_json(report: Any, stage: str) -> str:
    """Format DFM report as JSON.

    Args:
        report: MultiStageDfmReport or DfmReport.
        stage: Analysis stage that was run.

    Returns:
        JSON string with indent=2.
    """
    if stage == "all":
        return report.model_dump_json(indent=2)
    return report.model_dump_json(indent=2)


def _format_markdown(report: Any, stage: str, board_path: Path, profile: ManufacturerProfile) -> str:
    """Format DFM report as human-readable markdown.

    Args:
        report: MultiStageDfmReport or DfmReport.
        stage: Analysis stage that was run.
        board_path: Path to the PCB file.
        profile: Manufacturer profile used.

    Returns:
        Markdown-formatted report string.
    """
    lines: list[str] = []

    if stage == "all":
        lines.append(f"# DFM Analysis Report")
        lines.append("")
        lines.append(f"**Board:** {board_path}")
        lines.append(f"**Manufacturer:** {profile.name}")
        lines.append(f"**Overall Score:** {report.overall_score:.1%}")
        lines.append(f"**Total Findings:** {report.total_findings}")
        lines.append("")

        # Stage summaries
        lines.append("## Stage Results")
        lines.append("")
        lines.append(f"| Stage | Score | Findings |")
        lines.append(f"|-------|-------|----------|")
        lines.append(f"| Footprint Audit | {report.footprint_audit.manufacturability_score:.1%} | {len(report.footprint_audit.findings)} |")
        lines.append(f"| Placement Check | {report.placement_check.manufacturability_score:.1%} | {len(report.placement_check.findings)} |")
        lines.append(f"| Post-Route Check | {report.post_route_check.manufacturability_score:.1%} | {len(report.post_route_check.findings)} |")
        lines.append("")

        # Panelization
        lines.append("## Panelization Readiness")
        lines.append("")
        p = report.panelization
        lines.append(f"- **Score:** {p.score:.1%}")
        lines.append(f"- **Fiducials:** {p.fiducial_count} ({'OK' if p.has_fiducials else 'MISSING'})")
        lines.append(f"- **Tooling Holes:** {p.tooling_hole_count} ({'OK' if p.has_tooling_holes else 'MISSING'})")
        lines.append(f"- **Component Orientation:** {'OK' if p.component_orientation_ok else 'ISSUES'}")
        lines.append(f"- **Edge Clearance:** {'OK' if p.edge_clearance_ok else 'ISSUES'}")
        lines.append("")

        # Assembly
        lines.append("## Assembly Checks")
        lines.append("")
        a = report.assembly
        lines.append(f"- **Assembly Score:** {a.assembly_score:.1%}")
        lines.append(f"- **Orientation Issues:** {len(a.orientation_findings)}")
        lines.append(f"- **Spacing Issues:** {len(a.spacing_findings)}")
        lines.append(f"- **Polarity Notes:** {len(a.polarity_findings)}")
        lines.append("")

        # All findings table
        all_findings = (
            list(report.footprint_audit.findings)
            + list(report.placement_check.findings)
            + list(report.post_route_check.findings)
            + list(report.panelization.findings)
        )
    else:
        lines.append(f"# DFM Analysis Report ({stage})")
        lines.append("")
        lines.append(f"**Board:** {board_path}")
        lines.append(f"**Manufacturer:** {profile.name}")
        lines.append(f"**Score:** {report.manufacturability_score:.1%}")
        lines.append("")
        all_findings = list(report.findings)

    if all_findings:
        lines.append("## Findings")
        lines.append("")
        lines.append("| Severity | Check | Location | Description | Suggestion |")
        lines.append("|----------|-------|----------|-------------|------------|")
        for f in all_findings:
            desc = f.description[:60] + "..." if len(f.description) > 60 else f.description
            sugg = f.suggestion[:50] + "..." if len(f.suggestion) > 50 else f.suggestion
            lines.append(f"| {f.severity.value} | {f.check_id} | {f.location} | {desc} | {sugg} |")
        lines.append("")

    elapsed = report.elapsed_ms if hasattr(report, 'elapsed_ms') else 0
    lines.append(f"---")
    lines.append(f"*Analysis completed in {elapsed:.1f}ms*")

    return "\n".join(lines)


def register_dfm_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the DFM subcommand with argparse.

    Args:
        subparsers: Subparser group from main CLI.
    """
    parser = subparsers.add_parser(
        "dfm",
        help="Run DFM (Design for Manufacturing) analysis on a PCB",
    )
    parser.add_argument(
        "board",
        type=str,
        help="Path to .kicad_pcb file to analyze",
    )
    parser.add_argument(
        "--manufacturer", "-m",
        type=str,
        default=None,
        choices=["jlcpcb", "pcbway", "osh_park", "generic"],
        help="Built-in manufacturer profile (default: generic)",
    )
    parser.add_argument(
        "--profile", "-p",
        type=str,
        default=None,
        help="Path to custom YAML/JSON manufacturer profile",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--stage",
        choices=["footprint", "placement", "post-route", "all"],
        default="all",
        help="Analysis stage to run (default: all)",
    )
    parser.set_defaults(func=dfm_command)
