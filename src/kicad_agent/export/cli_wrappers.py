"""Python wrappers for kicad-cli render and SVG/PDF export commands.

Wraps 6 kicad-cli commands that previously had no Python wrapper:
- kicad-cli pcb render (3D board rendering with full options)
- kicad-cli sch export svg (schematic SVG export)
- kicad-cli sym export svg (symbol library SVG export)
- kicad-cli fp export svg (footprint library SVG export)
- kicad-cli pcb export svg (PCB SVG export with layer selection)
- kicad-cli pcb export pdf (PCB PDF export)

All wrappers reuse shared infrastructure from gerber.py (_find_kicad_cli,
_validate_pcb_path, _validate_output_dir, _run_kicad_export, ExportResult)
and general.py (_validate_sch_path). Zero subprocess duplication.

Usage:
    from kicad_agent.export.cli_wrappers import render_pcb_3d, export_pcb_svg

    result = render_pcb_3d(Path("board.kicad_pcb"), Path("render.png"),
                          rotation="-45,0,45", side="bottom")
    print(f"Image: {result['image_path']}")

    svg_result = export_pcb_svg(Path("board.kicad_pcb"), layers=["F.Cu", "B.Cu"])
    for f in svg_result.files:
        print(f.name)
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from kicad_agent.export.gerber import (
    ExportResult,
    _find_kicad_cli,
    _run_kicad_export,
    _validate_output_dir,
    _validate_pcb_path,
)
from kicad_agent.export.general import _validate_sch_path

logger = logging.getLogger(__name__)

# Hex color pattern for background validation (T-79-06)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def render_pcb_3d(
    pcb_path: Path,
    output_path: Path | None = None,
    rotation: str | None = None,
    side: str = "top",
    distance: int = 500,
    width: int = 4096,
    height: int = 4096,
    theme: str | None = None,
    background: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Render a 3D view of a PCB via kicad-cli pcb render.

    Invokes ``kicad-cli pcb render`` with rotation, side, distance, resolution,
    theme, and background options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Output image path (.png). Defaults to pcb_path parent /
            {stem}.png.
        rotation: Rotation string e.g. "-45,0,45". None = no rotation.
        side: Board side to render, "top" or "bottom" (default "top").
        distance: Camera distance in mm (default 500).
        width: Output image width in pixels (default 4096).
        height: Output image height in pixels (default 4096).
        theme: Color theme name. None = default theme.
        background: Background color as hex string "#RRGGBB". None = default.
        timeout: Maximum seconds to wait (default 120).

    Returns:
        Dict with: image_path, width_px, height_px, command, stderr.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not .kicad_pcb, path traversal detected,
            invalid side, or invalid background color format.
        subprocess.TimeoutExpired: If render exceeds timeout.
    """
    _validate_pcb_path(pcb_path)

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}.png"

    if ".." in output_path.parts:
        raise ValueError("Path must not contain '..' path traversal")

    if side not in ("top", "bottom"):
        raise ValueError(f"side must be 'top' or 'bottom', got: {side}")

    if background is not None and not _HEX_COLOR_RE.match(background):
        raise ValueError(
            f"background must be a hex color (#RRGGBB), got: {background}"
        )

    cli_path = _find_kicad_cli()
    args = [cli_path, "pcb", "render", "-o", str(output_path)]

    if rotation:
        args.extend(["--rotate", rotation])

    args.extend(["--side", side])
    args.extend(["--distance", str(distance)])
    args.extend(["--width", str(width)])
    args.extend(["--height", str(height)])

    if theme:
        args.extend(["--theme", theme])

    if background:
        args.extend(["--background", background])

    args.append(str(pcb_path))

    cmd_str = " ".join(args)
    logger.debug("Running kicad-cli render: %s", cmd_str)

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    return {
        "image_path": output_path,
        "width_px": width,
        "height_px": height,
        "command": cmd_str,
        "stderr": result.stderr,
        "success": result.returncode == 0,
    }


def export_schematic_svg(
    sch_path: Path,
    output_dir: Path | None = None,
    theme: str | None = None,
    page: str | None = None,
) -> ExportResult:
    """Export schematic as SVG via kicad-cli sch export svg.

    Invokes ``kicad-cli sch export svg`` with optional theme and page selection.

    Args:
        sch_path: Path to the .kicad_sch file.
        output_dir: Output directory. Defaults to sch_path parent.
        theme: Color theme name. None = default theme.
        page: Page number for multi-page schematics. None = all pages.

    Returns:
        ExportResult with generated SVG file(s).

    Raises:
        FileNotFoundError: If sch_path does not exist or kicad-cli not found.
        ValueError: If sch_path is not a .kicad_sch file.
        subprocess.TimeoutExpired: If export exceeds timeout.
    """
    _validate_sch_path(sch_path)

    if output_dir is None:
        output_dir = sch_path.parent
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    args = ["sch", "export", "svg", "--output", str(output_dir)]

    if theme:
        args.extend(["--theme", theme])

    if page:
        args.extend(["--page", page])

    args.append(str(sch_path))

    cli_result = _run_kicad_export(args)

    svg_files = tuple(sorted(
        f for f in output_dir.iterdir()
        if f.suffix == ".svg" and f.is_file()
    ))

    return ExportResult(
        success=cli_result["success"] and len(svg_files) > 0,
        output_dir=output_dir,
        files=svg_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_symbol_svg(
    sym_path: Path,
    output_dir: Path | None = None,
) -> ExportResult:
    """Export symbol library as SVG via kicad-cli sym export svg.

    Invokes ``kicad-cli sym export svg`` for .kicad_sym library files.

    Args:
        sym_path: Path to the .kicad_sym file.
        output_dir: Output directory. Defaults to sym_path parent.

    Returns:
        ExportResult with generated SVG file(s).

    Raises:
        FileNotFoundError: If sym_path does not exist or kicad-cli not found.
        ValueError: If sym_path is not a .kicad_sym file.
    """
    if sym_path.suffix != ".kicad_sym":
        raise ValueError(
            f"Expected .kicad_sym file, got: {sym_path.suffix}"
        )

    if ".." in sym_path.parts:
        raise ValueError("Path must not contain '..' path traversal")

    if not sym_path.exists():
        raise FileNotFoundError(f"Symbol library not found: {sym_path}")

    if output_dir is None:
        output_dir = sym_path.parent
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    args = ["sym", "export", "svg", "--output", str(output_dir), str(sym_path)]

    cli_result = _run_kicad_export(args)

    svg_files = tuple(sorted(
        f for f in output_dir.iterdir()
        if f.suffix == ".svg" and f.is_file()
    ))

    return ExportResult(
        success=cli_result["success"] and len(svg_files) > 0,
        output_dir=output_dir,
        files=svg_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_footprint_svg(
    fp_path: Path,
    output_dir: Path | None = None,
) -> ExportResult:
    """Export footprint library as SVG via kicad-cli fp export svg.

    Invokes ``kicad-cli fp export svg`` for .kicad_mod library files.

    Args:
        fp_path: Path to the .kicad_mod file.
        output_dir: Output directory. Defaults to fp_path parent.

    Returns:
        ExportResult with generated SVG file(s).

    Raises:
        FileNotFoundError: If fp_path does not exist or kicad-cli not found.
        ValueError: If fp_path is not a .kicad_mod file.
    """
    if fp_path.suffix != ".kicad_mod":
        raise ValueError(
            f"Expected .kicad_mod file, got: {fp_path.suffix}"
        )

    if ".." in fp_path.parts:
        raise ValueError("Path must not contain '..' path traversal")

    if not fp_path.exists():
        raise FileNotFoundError(f"Footprint library not found: {fp_path}")

    if output_dir is None:
        output_dir = fp_path.parent
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    args = ["fp", "export", "svg", "--output", str(output_dir), str(fp_path)]

    cli_result = _run_kicad_export(args)

    svg_files = tuple(sorted(
        f for f in output_dir.iterdir()
        if f.suffix == ".svg" and f.is_file()
    ))

    return ExportResult(
        success=cli_result["success"] and len(svg_files) > 0,
        output_dir=output_dir,
        files=svg_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_pcb_svg(
    pcb_path: Path,
    output_dir: Path | None = None,
    layers: list[str] | None = None,
    theme: str | None = None,
    exclude_drawing_sheet: bool = True,
) -> ExportResult:
    """Export PCB as SVG via kicad-cli pcb export svg.

    Invokes ``kicad-cli pcb export svg`` with layer selection, theme, and
    drawing sheet options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent.
        layers: Optional list of layer names to export (e.g. ["F.Cu", "B.Cu"]).
            None = all layers.
        theme: Color theme name. None = default theme.
        exclude_drawing_sheet: Exclude drawing sheet frame (default True).

    Returns:
        ExportResult with generated SVG file(s).

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
        subprocess.TimeoutExpired: If export exceeds timeout.
    """
    _validate_pcb_path(pcb_path)

    if output_dir is None:
        output_dir = pcb_path.parent
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    args = ["pcb", "export", "svg", "--output", str(output_dir)]

    if layers:
        args.extend(["--layers", ",".join(layers)])

    if theme:
        args.extend(["--theme", theme])

    if exclude_drawing_sheet:
        args.append("--exclude-drawing-sheet")

    args.append(str(pcb_path))

    cli_result = _run_kicad_export(args)

    svg_files = tuple(sorted(
        f for f in output_dir.iterdir()
        if f.suffix == ".svg" and f.is_file()
    ))

    return ExportResult(
        success=cli_result["success"] and len(svg_files) > 0,
        output_dir=output_dir,
        files=svg_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_pcb_pdf(
    pcb_path: Path,
    output_path: Path | None = None,
    theme: str | None = None,
) -> ExportResult:
    """Export PCB as PDF via kicad-cli pcb export pdf.

    Invokes ``kicad-cli pcb export pdf`` with optional theme.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Output .pdf file path. Defaults to pcb_path parent /
            {stem}.pdf.
        theme: Color theme name. None = default theme.

    Returns:
        ExportResult with generated PDF file.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
        subprocess.TimeoutExpired: If export exceeds timeout.
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
