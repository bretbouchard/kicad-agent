"""Report generator for demo pipeline Markdown reports.

Produces rich Markdown reports with embedded SVG image references,
ERC statistics, before/after comparisons, and duration metrics.
"""
from __future__ import annotations

import logging
from pathlib import Path

from volta.demo.pipeline import DemoReport

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate Markdown reports from DemoPipeline results.

    Args:
        output_dir: Directory where the report and SVGs live.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("demo-output")

    def generate(self, report: DemoReport) -> str:
        """Generate a Markdown report from a DemoReport.

        Args:
            report: DemoReport from pipeline execution.

        Returns:
            Markdown string with embedded SVG references.
        """
        lines = [
            f"# Demo Report: {report.template_used}",
            "",
            f"**Status:** {'Success' if report.success else 'Failed'}",
            f"**Duration:** {report.duration_seconds:.2f}s",
            f"**Stages:** {', '.join(report.stages_completed) or 'None'}",
            "",
        ]

        # Project directory
        if report.project_dir:
            lines.append(f"**Project:** `{report.project_dir}`")
            lines.append("")

        # ERC statistics
        if report.erc_before is not None or report.erc_after is not None:
            lines.append("## ERC Statistics")
            lines.append("")
            lines.append("| Metric | Count |")
            lines.append("|--------|-------|")
            if report.erc_before is not None:
                lines.append(f"| Violations (before fix) | {report.erc_before} |")
            if report.erc_after is not None:
                lines.append(f"| Violations (after fix) | {report.erc_after} |")
            if report.erc_before is not None and report.erc_after is not None:
                delta = report.erc_before - report.erc_after
                lines.append(f"| Violations fixed | {delta} |")
            lines.append("")

        # SVG renders
        if report.svg_paths:
            lines.append("## Rendered Output")
            lines.append("")
            for svg_path in report.svg_paths:
                p = Path(svg_path)
                lines.append(f"![{p.name}]({p.name})")
                lines.append("")

        # Errors
        if report.errors:
            lines.append("## Errors")
            lines.append("")
            for err in report.errors:
                lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines)

    def save(self, report: DemoReport, path: Path | None = None) -> Path:
        """Generate and save Markdown report to file.

        Args:
            report: DemoReport from pipeline execution.
            path: Output file path. Defaults to output_dir/report.md.

        Returns:
            Path to saved report.
        """
        if path is None:
            path = self.output_dir / f"{report.template_used}_report.md"

        path.parent.mkdir(parents=True, exist_ok=True)
        markdown = self.generate(report)
        path.write_text(markdown)
        return path
