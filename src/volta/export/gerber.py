"""Gerber and drill file export via kicad-cli.

GEN-02: Gerber/drill export wrappers with layer selection and format options.
FEAT-003: Complete manufacturing Gerber export with all required layers.

Wraps ``kicad-cli pcb export gerbers`` and ``kicad-cli pcb export drill``
with path validation, structured results, and timeout protection.

Usage:
    from volta.export.gerber import export_gerber, export_drill, export_manufacturing_package

    result = export_gerber(Path("board.kicad_pcb"))
    for f in result.files:
        print(f.name)

    # Complete manufacturing package with all required layers
    pkg = export_manufacturing_package(Path("board.kicad_pcb"))
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from volta.cli_resolver import find_kicad_cli

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportResult:
    """Structured result from a kicad-cli export command.

    Attributes:
        success: Whether the export completed without errors.
        output_dir: Directory where output files were written.
        files: List of generated file paths.
        command: The full command string that was executed.
        stderr: Captured stderr output (empty if no warnings/errors).
    """

    success: bool
    output_dir: Path
    files: tuple[Path, ...]
    command: str
    stderr: str = ""


def _find_kicad_cli() -> str:
    """Find kicad-cli on PATH.

    Returns:
        Absolute path to kicad-cli.

    Raises:
        FileNotFoundError: If kicad-cli is not found on PATH.
    """
    return find_kicad_cli().path


def _validate_pcb_path(pcb_path: Path) -> None:
    """Validate a PCB file path for export operations.

    Args:
        pcb_path: Path to validate.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a .kicad_pcb file or contains path traversal.
    """
    # Check suffix before existence so wrong type is always ValueError
    if pcb_path.suffix != ".kicad_pcb":
        raise ValueError(
            f"Expected .kicad_pcb file, got: {pcb_path.suffix}"
        )

    resolved = pcb_path.resolve()

    # Path traversal check (T-10-06)
    if ".." in pcb_path.parts:
        raise ValueError("Path must not contain '..' path traversal")

    if not resolved.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")


def _validate_output_dir(output_dir: Path) -> None:
    """Validate an output directory path.

    Args:
        output_dir: Path to validate.

    Raises:
        ValueError: If the path contains traversal characters.
    """
    # Path traversal check (T-10-06)
    if ".." in output_dir.parts:
        raise ValueError("Output path must not contain '..' path traversal")


def _run_kicad_export(args: list[str], timeout: int = 120) -> dict:
    """Run kicad-cli with the given arguments and capture output.

    Args:
        args: Command arguments to pass after kicad-cli.
        timeout: Maximum seconds to wait (default 120, T-10-05/08).

    Returns:
        Dict with: success, returncode, stdout, stderr, command.

    Raises:
        FileNotFoundError: If kicad-cli is not found.
        subprocess.TimeoutExpired: If kicad-cli exceeds timeout.
    """
    cli_path = _find_kicad_cli()
    cmd = [cli_path] + args
    cmd_str = " ".join(cmd)
    logger.debug("Running kicad-cli export: %s", cmd_str)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    return {
        "success": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": cmd_str,
    }


def export_gerber(
    pcb_path: Path,
    output_dir: Path | None = None,
    layers: list[str] | None = None,
    use_drill_origin: bool = True,
    subtract_soldermask: bool = True,
    no_protel_ext: bool = False,
) -> ExportResult:
    """Export Gerber files from a PCB via kicad-cli.

    Invokes ``kicad-cli pcb export gerbers`` with the specified options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent / "gerber".
        layers: Optional list of layer names to export (e.g. ["F.Cu", "B.Cu"]).
            None = all layers.
        use_drill_origin: Use drill/place file origin (default True).
        subtract_soldermask: Subtract soldermask from silkscreen (default True).
        no_protel_ext: Use KiCad file extensions instead of Protel (default False).

    Returns:
        ExportResult with success status, output directory, and generated file list.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
        subprocess.TimeoutExpired: If export exceeds timeout.
    """
    _validate_pcb_path(pcb_path)

    if output_dir is None:
        output_dir = pcb_path.parent / "gerber"
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # kicad-cli pcb export gerbers --output DIR [options] INPUT
    args = ["pcb", "export", "gerbers", "--output", str(output_dir)]

    if layers:
        # Layers are comma-separated for --layers flag
        args.extend(["--layers", ",".join(layers)])

    if use_drill_origin:
        args.append("--use-drill-file-origin")

    if subtract_soldermask:
        args.append("--subtract-soldermask")

    if no_protel_ext:
        args.append("--no-protel-ext")

    args.append(str(pcb_path))

    cli_result = _run_kicad_export(args)

    # Scan for all generated files in output directory.
    # KiCad uses various Gerber extensions: .gbr, .gtl, .gbl, .gts, .gbs,
    # .gto, .gbo, .gtp, .gbp, .gta, .gba, .gm1, .gbrjob, etc.
    output_files = tuple(sorted(f for f in output_dir.iterdir() if f.is_file()))

    return ExportResult(
        success=cli_result["success"] and len(output_files) > 0,
        output_dir=output_dir,
        files=output_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def export_drill(
    pcb_path: Path,
    output_dir: Path | None = None,
    format: str = "excellon",
    generate_map: bool = True,
    map_format: str = "gerberx2",
) -> ExportResult:
    """Export drill files from a PCB via kicad-cli.

    Invokes ``kicad-cli pcb export drill`` with format and map options.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent / "gerber".
        format: Drill format ("excellon" or "gerber").
        generate_map: Generate a drill map file (default True).
        map_format: Map format when generate_map is True (default "gerberx2").
            Options: pdf, gerberx2, ps, dxf, svg.

    Returns:
        ExportResult with success status, output directory, and generated file list.

    Raises:
        FileNotFoundError: If pcb_path does not exist or kicad-cli not found.
        ValueError: If pcb_path is not a .kicad_pcb file.
        subprocess.TimeoutExpired: If export exceeds timeout.
    """
    _validate_pcb_path(pcb_path)

    if output_dir is None:
        output_dir = pcb_path.parent / "gerber"
    _validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # kicad-cli pcb export drill --output DIR --format FORMAT [options] INPUT
    args = [
        "pcb", "export", "drill",
        "--output", str(output_dir),
        "--format", format,
    ]

    if generate_map:
        args.append("--generate-map")
        args.extend(["--map-format", map_format])

    args.append(str(pcb_path))

    cli_result = _run_kicad_export(args)

    # Scan for drill files (.drl for Excellon, plus map files)
    drl_files = tuple(sorted(output_dir.glob("*.drl")))
    # Drill map files have various extensions depending on map_format
    gbr_map = tuple(sorted(output_dir.glob("*.gbr"))) if generate_map and map_format == "gerberx2" else ()
    all_files = tuple(sorted(set(drl_files + gbr_map)))
    # Fallback: if specific extensions not found, use all files in output dir
    if not all_files:
        all_files = tuple(sorted(f for f in output_dir.iterdir() if f.is_file()))

    return ExportResult(
        success=cli_result["success"] and len(all_files) > 0,
        output_dir=output_dir,
        files=all_files,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


# Manufacturing layer presets (FEAT-003)
COPPER_LAYERS_2 = ["F.Cu", "B.Cu"]
COPPER_LAYERS_4 = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
EDGE_CUTS = ["Edge.Cuts"]
SILKSCREEN_LAYERS = ["F.SilkS", "B.SilkS"]
SOLDERMASK_LAYERS = ["F.Mask", "B.Mask"]
SOLDERPASTE_LAYERS = ["F.Paste", "B.Paste"]
FAB_LAYERS = ["F.Fab", "B.Fab"]
COURTYARD_LAYERS = ["F.CrtYd", "B.CrtYd"]
USER_LAYERS = ["F.Adhes", "B.Adhes", "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User"]

# Complete manufacturing set: copper + Edge.Cuts + silk + paste + mask
ALL_MANUFACTURING_LAYERS = (
    COPPER_LAYERS_2 + EDGE_CUTS + SILKSCREEN_LAYERS
    + SOLDERMASK_LAYERS + SOLDERPASTE_LAYERS
)


@dataclass(frozen=True)
class ManufacturingPackage:
    """Complete manufacturing export package with all required files.

    Attributes:
        gerber_result: Gerber export result.
        drill_result: Drill export result.
        all_files: Combined list of all generated files.
        output_dir: Root output directory.
    """

    gerber_result: ExportResult
    drill_result: ExportResult
    all_files: tuple[Path, ...]
    output_dir: Path

    @property
    def success(self) -> bool:
        return self.gerber_result.success and self.drill_result.success


def export_manufacturing_package(
    pcb_path: Path,
    output_dir: Path | None = None,
    *,
    layers: list[str] | None = None,
    include_drill: bool = True,
    no_dnp: bool = True,
) -> ManufacturingPackage:
    """Export complete manufacturing Gerber package (FEAT-003).

    Generates all layers required for PCB manufacturing:
    - Copper layers (F.Cu, B.Cu, and inner layers)
    - Edge.Cuts (board outline)
    - Silkscreen (F.SilkS, B.SilkS) with component references
    - Solder mask (F.Mask, B.Mask)
    - Solder paste (F.Paste, B.Paste) for SMD assembly
    - Drill files (Excellon format with Gerber map)

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent / "manufacturing".
        layers: Layers to include. Defaults to all manufacturing layers.
        include_drill: Whether to include drill file export (default True).
        no_dnp: Exclude DNP components from paste layers (default True).

    Returns:
        ManufacturingPackage with gerber/drill results and combined file list.
    """
    _validate_pcb_path(pcb_path)

    if output_dir is None:
        output_dir = pcb_path.parent / "manufacturing"
    _validate_output_dir(output_dir)

    gerber_dir = output_dir / "gerber"
    drill_dir = output_dir / "drill"

    # Export Gerber files with all manufacturing layers
    gerber_result = export_gerber(
        pcb_path,
        output_dir=gerber_dir,
        layers=layers or ALL_MANUFACTURING_LAYERS,
        subtract_soldermask=True,
    )

    # Export drill files
    drill_result = ExportResult(
        success=True,
        output_dir=drill_dir,
        files=(),
        command="",
    )
    if include_drill:
        drill_result = export_drill(
            pcb_path,
            output_dir=drill_dir,
            generate_map=True,
            map_format="gerberx2",
        )

    # Combine all files
    all_files = tuple(sorted(set(gerber_result.files + drill_result.files)))

    return ManufacturingPackage(
        gerber_result=gerber_result,
        drill_result=drill_result,
        all_files=all_files,
        output_dir=output_dir,
    )
