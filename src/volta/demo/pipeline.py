"""Demo pipeline: one-command schematic generation with validation and rendering.

Orchestration flow:
  1. Select template (by name or "random")
  2. Generate schematic via generate_design()
  3. Run ERC, capture violations
  4. Auto-fix ERC violations (if erc_auto_fix available)
  5. Re-run ERC, capture delta
  6. Render SVG via kicad-cli sch export svg
  7. Return DemoReport
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

from volta.demo.templates import get_template, get_random_template
from volta.generation.pipeline import generate_design

logger = logging.getLogger(__name__)


class DemoReport(BaseModel):
    """Structured report from the demo pipeline.

    Attributes:
        template_used: Name of the template that was used.
        stages_completed: List of stage names that completed successfully.
        erc_before: ERC violation count before auto-fix (None if not run).
        erc_after: ERC violation count after auto-fix (None if not run).
        svg_paths: Paths to generated SVG files.
        duration_seconds: Total pipeline execution time.
        success: Whether the pipeline completed without fatal errors.
        errors: Non-fatal error messages encountered.
        project_dir: Path to the generated project directory.
    """

    template_used: str
    stages_completed: list[str] = Field(default_factory=list)
    erc_before: int | None = None
    erc_after: int | None = None
    svg_paths: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    success: bool = False
    errors: list[str] = Field(default_factory=list)
    project_dir: str | None = None


class DemoPipeline:
    """Orchestrate the demo workflow: generate -> validate -> render -> report.

    Args:
        output_dir: Directory for generated projects. Defaults to ./demo-output.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("demo-output")

    def run(self, template_name: str) -> DemoReport:
        """Run the full demo pipeline for the named template.

        Args:
            template_name: Template name or "random" for random selection.

        Returns:
            DemoReport with results from all pipeline stages.
        """
        start = time.monotonic()
        report = DemoReport(template_used=template_name)

        try:
            # Stage 1: Select template
            template = self._select_template(template_name)
            report.template_used = template.name
            report.stages_completed.append("select")

            # Stage 2: Generate schematic
            project_dir = self.output_dir / template.name
            project_dir.mkdir(parents=True, exist_ok=True)

            gen_result = generate_design(template.intent, output_dir=project_dir)
            report.project_dir = str(gen_result.project_dir)
            report.stages_completed.append("generate")

            if not gen_result.success:
                report.errors.extend(gen_result.errors)
                report.success = False
                report.duration_seconds = time.monotonic() - start
                return report

            # Stage 3: Run ERC (before fix)
            erc_before = self._run_erc(gen_result.schematic_path)
            if erc_before is not None:
                report.erc_before = erc_before
                report.stages_completed.append("erc_before")

            # Stage 4: Auto-fix ERC (best effort)
            self._auto_fix(gen_result.schematic_path)

            # Stage 5: Re-run ERC (after fix)
            erc_after = self._run_erc(gen_result.schematic_path)
            if erc_after is not None:
                report.erc_after = erc_after
                report.stages_completed.append("erc_after")

            # Stage 6: Render SVG
            svg_paths = self._render_svg(gen_result.schematic_path, project_dir)
            report.svg_paths = [str(p) for p in svg_paths]
            if svg_paths:
                report.stages_completed.append("render")

            report.success = True

        except Exception as exc:
            report.errors.append(f"{type(exc).__name__}: {exc}")
            report.success = False

        report.duration_seconds = time.monotonic() - start
        return report

    def _select_template(self, name: str):
        """Select template by name or 'random'."""
        if name == "random":
            return get_random_template()
        return get_template(name)

    def _run_erc(self, schematic_path: Path | None) -> int | None:
        """Run ERC and return violation count."""
        if schematic_path is None or not schematic_path.exists():
            return None
        try:
            result = subprocess.run(
                ["kicad-cli", "sch", "erc", str(schematic_path)],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            return self._parse_erc_count(output)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("ERC failed: %s", exc)
            return None

    def _parse_erc_count(self, erc_output: str) -> int:
        """Parse ERC violation count from kicad-cli output."""
        count = 0
        for line in erc_output.splitlines():
            line = line.strip()
            if line and not line.startswith(("ERC ", "Running", "Info")):
                count += 1
        return count

    def _auto_fix(self, schematic_path: Path | None) -> None:
        """Best-effort ERC auto-fix."""
        if schematic_path is None or not schematic_path.exists():
            return
        try:
            from volta.parser.schematic_parser import parse_schematic
            from volta.ir.schematic_ir import SchematicIR
            from volta.ops.erc_auto_fix import erc_auto_fix
            result = parse_schematic(schematic_path)
            ir = SchematicIR(result)
            erc_auto_fix(ir, file_path=schematic_path, max_iterations=3)
        except (ImportError, Exception) as exc:
            logger.debug("Auto-fix skipped: %s", exc)

    def _render_svg(self, schematic_path: Path | None, output_dir: Path) -> list[Path]:
        """Render schematic as SVG via kicad-cli."""
        if schematic_path is None or not schematic_path.exists():
            return []
        svg_path = output_dir / f"{schematic_path.stem}.svg"
        try:
            subprocess.run(
                ["kicad-cli", "sch", "export", "svg", str(schematic_path), "-o", str(svg_path)],
                capture_output=True, text=True, timeout=120,
            )
            if svg_path.exists():
                return [svg_path]
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("SVG render failed: %s", exc)
        return []
