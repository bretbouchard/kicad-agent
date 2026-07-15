"""3D rendering and visual export wrappers for kicad-agent.

Provides Python wrappers for kicad-cli render and visual export commands
(SVG, PDF) for both schematics and PCBs. These are read-only convenience
wrappers that invoke kicad-cli and return structured results.

Usage:
    from volta.export.render import (
        render_pcb,
        export_schematic_svg,
        export_pcb_svg,
        export_pcb_pdf,
    )

    result = render_pcb(Path("board.kicad_pcb"))
    print(f"Rendered: {result.output_path}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from volta.export.gerber import (
    ExportResult,
    _find_kicad_cli,
    _run_kicad_export,
    _validate_output_dir,
    _validate_pcb_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------


def _validate_sch_path(sch_path: Path) -> None:
    """Validate a schematic file path.

    Args:
        sch_path: Path to validate.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a .kicad_sch file or contains path traversal.
    """
    if sch_path.suffix not in (".kicad_sch",):
        raise ValueError(
            f"Expected .kicad_sch file, got: {sch_path.suffix}"
        )
    if ".." in sch_path.parts:
        raise ValueError("Path must not contain '..' path traversal")
    if not sch_path.resolve().exists():
        raise FileNotFoundError(f"Schematic file not found: {sch_path}")


# ---------------------------------------------------------------------------
# PCB 3D Render
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderResult:
    """Structured result from a kicad-cli render command.

    Attributes:
        success: Whether the render completed without errors.
        output_path: Path to the rendered image file.
        width_px: Render width in pixels.
        height_px: Render height in pixels.
        command: The full command string that was executed.
        stderr: Captured stderr output (empty if no warnings/errors).
    """

    success: bool
    output_path: Path
    width_px: int
    height_px: int
    command: str
    stderr: str = ""


def render_pcb(
    pcb_path: Path,
    output_path: Path | None = None,
    width: int = 1600,
    height: int = 1200,
    background_color: str | None = None,
    side: str | None = None,
    rotate: str | None = None,
    zoom: float | None = None,
) -> RenderResult:
    """Render a 3D view of a PCB via kicad-cli.

    Invokes ``kicad-cli pcb render`` to generate a PNG or JPEG image of the
    3D board view. Supports rotation, zoom, side selection, and background
    color options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Output image path. Defaults to pcb_path parent /
            {stem}-render.png.
        width: Render width in pixels (default 1600).
        height: Render height in pixels (default 1200).
        background_color: Hex color string (e.g. "#FFFFFF") or None for default.
        side: Board side to render ("front", "back", or None for default).
        rotate: Rotation string (e.g. "-45,0,45") for isometric views.
        zoom: Zoom factor (default 1.0, kicad-cli will scale).

    Returns:
        RenderResult with success status, output path, and render dimensions.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
        subprocess.TimeoutExpired: If render exceeds timeout.
    """
    _validate_pcb_path(pcb_path)

    if output_path is None:
        ext = ".png"
        output_path = pcb_path.parent / f"{pcb_path.stem}-render{ext}"

    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # kicad-cli pcb render --width W --height H [options] INPUT
    args = ["pcb", "render", "--width", str(width), "--height", str(height)]

    if background_color:
        args.extend(["--background", background_color])

    if side:
        args.extend(["--side", side])

    if rotate:
        args.extend(["--rotate", rotate])

    if zoom is not None:
        args.extend(["--zoom", str(zoom)])

    args.extend(["--output", str(output_path), str(pcb_path)])

    cli_result = _run_kicad_export(args, timeout=180)

    return RenderResult(
        success=cli_result["success"] and output_path.exists(),
        output_path=output_path,
        width_px=width,
        height_px=height,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


# ---------------------------------------------------------------------------
# SVG Exports
# ---------------------------------------------------------------------------


def export_schematic_svg(
    sch_path: Path,
    output_path: Path | None = None,
    theme: str | None = None,
    page: str | None = None,
) -> ExportResult:
    """Export schematic as SVG via kicad-cli.

    Invokes ``kicad-cli sch export svg`` with optional theme and page selection.

    Args:
        sch_path: Path to the .kicad_sch file.
        output_path: Output .svg file path. Defaults to sch_path parent /
            {stem}.svg.
        theme: Color theme name. None = default theme.
        page: Page identifier for multi-sheet schematics. None = all pages.

    Returns:
        ExportResult with success status and generated SVG file.

    Raises:
        FileNotFoundError: If sch_path does not exist or kicad-cli not found.
        ValueError: If sch_path is not a .kicad_sch file.
    """
    _validate_sch_path(sch_path)

    if output_path is None:
        output_path = sch_path.parent / f"{sch_path.stem}.svg"

    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = ["sch", "export", "svg", "--output", str(output_path)]

    if theme:
        args.extend(["--theme", theme])

    if page:
        args.extend(["--page", page])

    args.append(str(sch_path))

    cli_result = _run_kicad_export(args)

    files: tuple[Path, ...] = ()
    if output_path.exists():
        files = (output_path,)

    return ExportResult(
        success=cli_result["success"] and len(files) > 0,
        output_dir=output_path.parent,
        files=files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_pcb_svg(
    pcb_path: Path,
    output_path: Path | None = None,
    theme: str | None = None,
    layers: list[str] | None = None,
    page: str | None = None,
) -> ExportResult:
    """Export PCB as SVG via kicad-cli.

    Invokes ``kicad-cli pcb export svg`` with optional theme, layer, and
    page selection.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Output .svg file path. Defaults to pcb_path parent /
            {stem}.svg.
        theme: Color theme name. None = default theme.
        layers: Optional list of layer names to export.
        page: Page identifier for multi-page output.

    Returns:
        ExportResult with success status and generated SVG file.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
    """
    _validate_pcb_path(pcb_path)

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}.svg"

    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = ["pcb", "export", "svg", "--output", str(output_path)]

    if theme:
        args.extend(["--theme", theme])

    if layers:
        args.extend(["--layers", ",".join(layers)])

    if page:
        args.extend(["--page", page])

    args.append(str(pcb_path))

    cli_result = _run_kicad_export(args)

    files: tuple[Path, ...] = ()
    if output_path.exists():
        files = (output_path,)

    return ExportResult(
        success=cli_result["success"] and len(files) > 0,
        output_dir=output_path.parent,
        files=files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


# ---------------------------------------------------------------------------
# PCB PDF Export
# ---------------------------------------------------------------------------


def export_pcb_pdf(
    pcb_path: Path,
    output_path: Path | None = None,
    theme: str | None = None,
) -> ExportResult:
    """Export PCB as PDF via kicad-cli.

    Invokes ``kicad-cli pcb export pdf`` with optional theme selection.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Output .pdf file path. Defaults to pcb_path parent /
            {stem}.pdf.
        theme: Color theme name. None = default theme.

    Returns:
        ExportResult with success status and generated PDF file.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
    """
    _validate_pcb_path(pcb_path)

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}.pdf"

    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = ["pcb", "export", "pdf", "--output", str(output_path)]

    if theme:
        args.extend(["--theme", theme])

    args.append(str(pcb_path))

    cli_result = _run_kicad_export(args)

    files: tuple[Path, ...] = ()
    if output_path.exists():
        files = (output_path,)

    return ExportResult(
        success=cli_result["success"] and len(files) > 0,
        output_dir=output_path.parent,
        files=files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )
