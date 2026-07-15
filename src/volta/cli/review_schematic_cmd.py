"""CLI subcommand: volta review-schematic <file>

READ-01/02/03/04: Review a schematic for readability and spatial quality.

Usage:
    volta review-schematic compressor.kicad_sch
    volta review-schematic compressor.kicad_sch --vision
    volta review-schematic compressor.kicad_sch --format json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def review_schematic_command(args: argparse.Namespace) -> int:
    """Execute the review-schematic subcommand."""
    schematic_path = Path(args.schematic)
    if not schematic_path.exists():
        print(f"Error: schematic not found: {schematic_path}", file=sys.stderr)
        return 2

    from volta.parser import parse_schematic
    from volta.ir.schematic_ir import SchematicIR
    from volta.analysis.schematic_reviewer import SchematicReviewer

    try:
        result = parse_schematic(schematic_path)
        ir = SchematicIR(_parse_result=result)
    except Exception as e:
        print(f"Error parsing schematic: {e}", file=sys.stderr)
        return 2

    vision = getattr(args, "vision", False)
    reviewer = SchematicReviewer(ir)
    report = reviewer.review(vision=vision)

    output_format = getattr(args, "format", "markdown")
    if output_format == "json":
        output = json.dumps({
            "srs": round(report.srs, 3),
            "file": str(schematic_path),
            "rule_violations": len(report.rule_report.violations),
            "vision_findings": len(report.vision_findings),
            "factors": report.readability.factors,
            "suggestions": list(report.readability.suggestions),
            "rules_run": report.rule_report.rules_run,
            "rules_passed": report.rule_report.rules_passed,
            "rules_failed": report.rule_report.rules_failed,
        }, indent=2)
    else:
        lines = [
            f"# Schematic Readability Review: {schematic_path.name}",
            "",
            f"**SRS Score:** {report.srs:.2f} / 1.00",
            "",
            "## Factor Scores",
            "",
        ]
        for factor, score in report.readability.factors.items():
            bar = "#" * int(score * 20)
            lines.append(f"| {factor:15s} | {score:.2f} | {bar} |")
        lines.append("")

        if report.rule_report.violations:
            lines.append(f"## Rule Violations ({len(report.rule_report.violations)})")
            lines.append("")
            for v in report.rule_report.violations:
                lines.append(f"- [{v.severity.value}] **{v.rule_id}**: {v.description}")
            lines.append("")

        if report.readability.suggestions:
            lines.append("## Suggestions")
            lines.append("")
            for s in report.readability.suggestions:
                lines.append(f"- {s}")
            lines.append("")

        if report.vision_findings:
            lines.append(f"## Vision Findings ({len(report.vision_findings)})")
            lines.append("")
            for vf in report.vision_findings:
                lines.append(f"- [{vf.severity}] {vf.description}")
            lines.append("")

        output = "\n".join(lines)

    print(output)
    return 0 if report.srs >= 0.5 else 1


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the review-schematic subcommand."""
    parser = subparsers.add_parser(
        "run",
        help="Run readability review on a schematic",
    )
    parser.add_argument(
        "schematic",
        type=str,
        help="Path to .kicad_sch file to review",
    )
    parser.add_argument(
        "--vision",
        action="store_true",
        default=False,
        help="Include Claude vision review of rendered schematic",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.set_defaults(func=review_schematic_command)
