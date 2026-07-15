"""General export wrappers: position, netlist, STEP, PDF, and board statistics.

GEN-02: Position, netlist, STEP, PDF exports via kicad-cli and board statistics
from parsed PCB (no kicad-cli dependency).

Wraps multiple kicad-cli subcommands and provides a pure-Python board statistics
function using existing parse_pcb + PcbIR.

Usage:
    from volta.export.general import (
        export_position,
        export_netlist,
        export_step,
        export_schematic_pdf,
        get_board_statistics,
    )

    stats = get_board_statistics(Path("board.kicad_pcb"))
    print(f"Components: {stats['component_count']}")
"""

import logging
import re
from pathlib import Path

from volta.export.gerber import (
    ExportResult,
    _find_kicad_cli,
    _run_kicad_export,
    _validate_output_dir,
    _validate_pcb_path,
)

logger = logging.getLogger(__name__)


def _validate_sch_path(sch_path: Path) -> None:
    """Validate a schematic file path.

    Args:
        sch_path: Path to validate.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a .kicad_sch file.
    """
    if sch_path.suffix != ".kicad_sch":
        raise ValueError(
            f"Expected .kicad_sch file, got: {sch_path.suffix}"
        )

    if ".." in sch_path.parts:
        raise ValueError("Path must not contain '..' path traversal")

    if not sch_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {sch_path}")


def export_position(
    pcb_path: Path,
    output_dir: Path | None = None,
    format: str = "ascii",
    units: str = "mm",
    side: str = "both",
) -> ExportResult:
    """Export component position files from a PCB via kicad-cli.

    Invokes ``kicad-cli pcb export pos`` with format, units, and side options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent.
        format: Output format ("ascii", "csv", or "gerber").
        units: Output units ("mm" or "in").
        side: Which side to export ("front", "back", or "both").

    Returns:
        ExportResult with generated position file list.

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

    output_file = output_dir / f"{pcb_path.stem}-pos.{format}"

    args = [
        "pcb", "export", "pos",
        "--output", str(output_file),
        "--format", format,
        "--units", units,
        "--side", side,
        str(pcb_path),
    ]

    cli_result = _run_kicad_export(args)

    # Scan for position files
    pos_files = tuple(sorted(
        f for f in output_dir.iterdir()
        if f.is_file() and ("-pos" in f.name or f.name == output_file.name)
    ))
    if not pos_files and output_file.exists():
        pos_files = (output_file,)

    return ExportResult(
        success=cli_result["success"] and len(pos_files) > 0,
        output_dir=output_dir,
        files=pos_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_netlist(
    pcb_path: Path,
    output_dir: Path | None = None,
    format: str = "kicadsexpr",
) -> ExportResult:
    """Export netlist from a PCB via kicad-cli.

    Invokes ``kicad-cli pcb export netlist`` (note: netlist is a sch export,
    but KiCad exposes it through both paths).

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent.
        format: Netlist format ("kicadsexpr", "kicadxml").

    Returns:
        ExportResult with generated netlist file.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
    """
    _validate_pcb_path(pcb_path)

    if output_dir is None:
        output_dir = pcb_path.parent
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = "net" if format == "kicadsexpr" else "xml"
    output_file = output_dir / f"{pcb_path.stem}.{ext}"

    args = [
        "pcb", "export", "netlist",
        "--output", str(output_file),
        "--format", format,
        str(pcb_path),
    ]

    cli_result = _run_kicad_export(args)

    files: tuple[Path, ...] = ()
    if output_file.exists():
        files = (output_file,)

    return ExportResult(
        success=cli_result["success"] and len(files) > 0,
        output_dir=output_dir,
        files=files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_step(
    pcb_path: Path,
    output_path: Path | None = None,
    no_dnp: bool = True,
    origin: str = "grid",
) -> ExportResult:
    """Export STEP 3D model from a PCB via kicad-cli.

    Invokes ``kicad-cli pcb export step`` with origin and DNP options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Output .step file path. Defaults to pcb_path parent /
            {stem}.step.
        no_dnp: Exclude DNP (Do Not Populate) components (default True).
        origin: Origin mode ("grid" or "drill").

    Returns:
        ExportResult with generated STEP file.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
        subprocess.TimeoutExpired: If export exceeds timeout (STEP can be slow).
    """
    _validate_pcb_path(pcb_path)

    if output_path is None:
        output_path = pcb_path.parent / f"{pcb_path.stem}.step"

    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = [
        "pcb", "export", "step",
        "--output", str(output_path),
    ]

    if no_dnp:
        args.append("--no-dnp")

    if origin == "grid":
        args.append("--grid-origin")
    elif origin == "drill":
        args.append("--drill-origin")

    args.append(str(pcb_path))

    cli_result = _run_kicad_export(args, timeout=120)

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


def export_schematic_pdf(
    sch_path: Path,
    output_path: Path | None = None,
    theme: str | None = None,
) -> ExportResult:
    """Export schematic as PDF via kicad-cli.

    Invokes ``kicad-cli sch export pdf`` with optional theme.

    Args:
        sch_path: Path to the .kicad_sch file.
        output_path: Output .pdf file path. Defaults to sch_path parent /
            {stem}.pdf.
        theme: Color theme name. None = default theme.

    Returns:
        ExportResult with generated PDF file.

    Raises:
        FileNotFoundError: If sch_path does not exist or kicad-cli not found.
        ValueError: If sch_path is not a .kicad_sch file.
    """
    _validate_sch_path(sch_path)

    if output_path is None:
        output_path = sch_path.parent / f"{sch_path.stem}.pdf"

    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = [
        "sch", "export", "pdf",
        "--output", str(output_path),
    ]

    if theme:
        args.extend(["--theme", theme])

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


def get_board_statistics(pcb_path: Path) -> dict:
    """Extract board statistics from a parsed PCB file.

    This function does NOT call kicad-cli. It parses the PCB directly
    using existing parse_pcb + PcbIR and extracts component/net/layer
    counts and board dimensions.

    Args:
        pcb_path: Path to the .kicad_pcb file.

    Returns:
        Dict with keys:
            component_count: Total number of footprints.
            unique_footprints: Number of distinct footprint library IDs.
            net_count: Number of named nets (excluding empty net 0).
            layer_count: Number of copper layers.
            board_width_mm: Board width in mm.
            board_height_mm: Board height in mm.
            has_drc_errors: None (not checked by this function).

    Raises:
        FileNotFoundError: If pcb_path does not exist.
        ValueError: If pcb_path is not a .kicad_pcb file.
    """
    if pcb_path.suffix != ".kicad_pcb":
        raise ValueError(
            f"Expected .kicad_pcb file, got: {pcb_path.suffix}"
        )

    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    from volta.parser import parse_pcb
    from volta.parser.uuid_extractor import extract_uuids
    from volta.ir.pcb_ir import PcbIR

    parse_result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(parse_result.raw_content, "pcb")
    ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)

    board = ir.board

    # Component count = number of footprints
    component_count = len(board.footprints)

    # Unique footprint lib IDs
    unique_lib_ids = set(fp.libId for fp in board.footprints)
    unique_footprints = len(unique_lib_ids)

    # Net count (exclude empty net 0)
    net_count = len([n for n in board.nets if n.name != ""])

    # Layer count from general section
    layer_count = len(board.general.layers) if hasattr(board.general, 'layers') else len(board.layers)

    # Board dimensions from edge cuts
    board_width_mm = 0.0
    board_height_mm = 0.0
    try:
        _extract_board_dimensions(parse_result.raw_content)
        board_width_mm, board_height_mm = _extract_board_dimensions(
            parse_result.raw_content
        )
    except Exception:
        pass

    return {
        "component_count": component_count,
        "unique_footprints": unique_footprints,
        "net_count": net_count,
        "layer_count": layer_count,
        "board_width_mm": board_width_mm,
        "board_height_mm": board_height_mm,
        "has_drc_errors": None,
    }


def _extract_board_dimensions(raw_content: str) -> tuple[float, float]:
    """Extract board width and height from Edge.Cuts graphics in raw PCB content.

    Looks for line/arc/rect segments on Edge.Cuts layer and computes
    bounding box. Uses re.DOTALL to handle multi-line S-expression blocks.

    Args:
        raw_content: Raw PCB file text.

    Returns:
        Tuple of (width_mm, height_mm).
    """
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    def _update_bounds(x1: float, y1: float, x2: float, y2: float) -> None:
        nonlocal min_x, max_x, min_y, max_y
        min_x = min(min_x, x1, x2)
        max_x = max(max_x, x1, x2)
        min_y = min(min_y, y1, y2)
        max_y = max(max_y, y1, y2)

    # Match gr_line blocks on Edge.Cuts (multiline: blocks span multiple lines)
    for match in re.finditer(
        r'\(gr_line\s+\(start\s+(\S+)\s+(\S+)\)\s+\(end\s+(\S+)\s+(\S+)\).*?\(layer\s+"Edge\.Cuts"\)',
        raw_content,
        re.DOTALL,
    ):
        _update_bounds(
            float(match.group(1)), float(match.group(2)),
            float(match.group(3)), float(match.group(4)),
        )

    # Match gr_rect blocks on Edge.Cuts
    for match in re.finditer(
        r'\(gr_rect\s+\(start\s+(\S+)\s+(\S+)\)\s+\(end\s+(\S+)\s+(\S+)\).*?\(layer\s+"Edge\.Cuts"\)',
        raw_content,
        re.DOTALL,
    ):
        _update_bounds(
            float(match.group(1)), float(match.group(2)),
            float(match.group(3)), float(match.group(4)),
        )

    # Match gr_arc blocks on Edge.Cuts (start + mid + end points)
    for match in re.finditer(
        r'\(gr_arc\s+\(start\s+(\S+)\s+(\S+)\)\s+\(mid\s+(\S+)\s+(\S+)\)\s+\(end\s+(\S+)\s+(\S+)\).*?\(layer\s+"Edge\.Cuts"\)',
        raw_content,
        re.DOTALL,
    ):
        _update_bounds(
            float(match.group(1)), float(match.group(2)),
            float(match.group(5)), float(match.group(6)),
        )
        # Include mid point
        _update_bounds(
            float(match.group(3)), float(match.group(4)),
            float(match.group(3)), float(match.group(4)),
        )

    if min_x == float("inf"):
        return 0.0, 0.0

    return (max_x - min_x, max_y - min_y)
