"""Freerouting integration for production-quality auto-routing (FEAT-001).

Provides DSN (Specctra) export and SES import for Freerouting integration.
kicad-cli does NOT support Specctra/DSN import, so SES files are parsed
directly and converted to KiCad segment/via S-expressions.

Freerouting is an open-source Java auto-router that produces significantly
better routing results than the built-in A* pathfinder for real-world
designs with dense routing.

Usage:
    from kicad_agent.routing.freerouting import route_with_freerouting, export_dsn

    # Export DSN file for Freerouting
    dsn_path = export_dsn(pcb_path, output_dir=Path("./dsn"))

    # Route using Freerouting (requires Java runtime + Freerouting JAR)
    result = route_with_freerouting(pcb_path, output_dir=Path("./routed"))

    # Import SES result back into PCB raw content
    new_content = import_ses_into_pcb(ses_path, pcb_raw_content)
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default Freerouting JAR name (downloaded from freerouting.org)
_FREEROUTING_JAR = "freerouting.jar"

# DSN export/import file extensions
_DSN_EXTENSION = ".dsn"
_SES_EXTENSION = ".ses"


def _find_freerouting() -> str | None:
    """Find Freerouting JAR or binary.

    Search order:
    1. FREEROUTING_JAR environment variable
    2. kicad-agent config directory
    3. Common install locations

    Returns:
        Path to Freerouting JAR file, or None if not found.
    """
    import os

    # Check environment variable
    env_jar = os.environ.get("FREEROUTING_JAR")
    if env_jar and Path(env_jar).exists():
        return env_jar

    # Check kicad-agent config directory
    config_dir = Path.home() / ".kicad-agent" / "tools"
    jar_path = config_dir / _FREEROUTING_JAR
    if jar_path.exists():
        return str(jar_path)

    # Check common locations
    common_paths = [
        Path("/usr/local/share/freerouting") / _FREEROUTING_JAR,
        Path("/opt/freerouting") / _FREEROUTING_JAR,
        Path.home() / "Applications" / _FREEROUTING_JAR,
    ]
    for path in common_paths:
        if path.exists():
            return str(path)

    return None


def _find_java() -> str | None:
    """Find Java runtime for Freerouting.

    Returns:
        Path to java binary, or None if Java is not installed.
    """
    return shutil.which("java")


def export_dsn(
    pcb_path: Path,
    output_dir: Path | None = None,
    *,
    layers: list[str] | None = None,
) -> Path:
    """Export PCB in Specctra DSN format.

    KiCad 10 removed ``kicad-cli pcb export dsn``, so this generates
    DSN directly from PCB content using ``dsn_generator``.

    Args:
        pcb_path: Path to .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent.
        layers: Copper layers to include. Default ["F.Cu", "B.Cu"].

    Returns:
        Path to the generated .dsn file.

    Raises:
        FileNotFoundError: If pcb_path does not exist.
    """
    from kicad_agent.routing.dsn_generator import generate_dsn

    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    if output_dir is None:
        output_dir = pcb_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    dsn_path = output_dir / f"{pcb_path.stem}{_DSN_EXTENSION}"

    pcb_content = pcb_path.read_text(encoding="utf-8")
    dsn_text = generate_dsn(pcb_content, pcb_path, layers=layers)

    dsn_path.write_text(dsn_text, encoding="utf-8")
    logger.info("Generated DSN: %s (%d bytes)", dsn_path, len(dsn_text))

    return dsn_path


@dataclass(frozen=True)
class FreeroutingResult:
    """Result from a Freerouting run.

    Attributes:
        success: Whether routing completed successfully.
        ses_path: Path to the output .ses (Specctra session) file.
        dsn_path: Path to the input .dsn file.
        stderr: Captured stderr output.
        used_freerouting: True if Freerouting was used, False if fell back.
    """

    success: bool
    ses_path: Path | None
    dsn_path: Path | None
    stderr: str = ""
    used_freerouting: bool = True


def route_with_freerouting(
    pcb_path: Path,
    output_dir: Path | None = None,
    *,
    freerouting_jar: str | None = None,
    max_passes: int = 5,
) -> FreeroutingResult:
    """Auto-route a PCB using Freerouting.

    Exports the PCB to DSN format, runs Freerouting, and produces
    a .ses session file. Use ``import_ses_into_pcb()`` to merge results
    back into the PCB content.

    Args:
        pcb_path: Path to .kicad_pcb file.
        output_dir: Output directory for DSN and SES files.
        freerouting_jar: Explicit path to Freerouting JAR. If None, auto-detects.
        max_passes: Maximum routing passes (default 5).

    Returns:
        FreeroutingResult with success status and file paths.
    """
    if output_dir is None:
        output_dir = pcb_path.parent / "freerouting"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find Freerouting
    jar = freerouting_jar or _find_freerouting()
    if jar is None:
        return FreeroutingResult(
            success=False,
            ses_path=None,
            dsn_path=None,
            stderr="Freerouting not found. Set FREEROUTING_JAR env var or install Freerouting.",
            used_freerouting=False,
        )

    # Find Java
    java = _find_java()
    if java is None:
        return FreeroutingResult(
            success=False,
            ses_path=None,
            dsn_path=None,
            stderr="Java runtime not found. Install Java to use Freerouting.",
            used_freerouting=False,
        )

    try:
        # Export DSN
        dsn_path = export_dsn(pcb_path, output_dir)
    except Exception as e:
        return FreeroutingResult(
            success=False,
            ses_path=None,
            dsn_path=None,
            stderr=f"DSN export failed: {e}",
            used_freerouting=True,
        )

    # Run Freerouting with headless mode (no GUI needed)
    ses_path = output_dir / f"{pcb_path.stem}{_SES_EXTENSION}"
    cmd = [
        java,
        "-Djava.awt.headless=true",
        "-jar", jar,
        "-de", str(dsn_path),  # Input DSN file
        "-do", str(ses_path),  # Output SES file
        "-mp", str(max_passes),  # Max passes
    ]

    logger.info("Running Freerouting: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )
    except subprocess.TimeoutExpired:
        return FreeroutingResult(
            success=False,
            ses_path=ses_path,
            dsn_path=dsn_path,
            stderr="Freerouting timed out after 600s",
            used_freerouting=True,
        )

    if result.returncode != 0 or not ses_path.exists():
        return FreeroutingResult(
            success=False,
            ses_path=ses_path if ses_path.exists() else None,
            dsn_path=dsn_path,
            stderr=result.stderr or f"Freerouting exited with code {result.returncode}",
            used_freerouting=True,
        )

    return FreeroutingResult(
        success=True,
        ses_path=ses_path,
        dsn_path=dsn_path,
        stderr=result.stderr,
        used_freerouting=True,
    )


@dataclass(frozen=True)
class SesWire:
    """A wire path extracted from an SES file."""
    net: str
    layer: str
    width_mm: float
    points: list[tuple[float, float]]


@dataclass(frozen=True)
class SesVia:
    """A via extracted from an SES file."""
    net: str
    x_mm: float
    y_mm: float
    size_mm: float
    drill_mm: float


@dataclass
class SesParseResult:
    """Result of parsing an SES file."""
    wires: list[SesWire] = field(default_factory=list)
    vias: list[SesVia] = field(default_factory=list)
    resolution_factor: float = 100000.0


def parse_ses(ses_text: str) -> SesParseResult:
    """Parse a Freerouting SES file into structured wire/via data.

    SES wire format: (wire (path LAYER WIDTH x1 y1 x2 y2 ...))
    SES via format: (via LAYER X Y SIZE DRILL)
    Coordinates are in 0.01um units when resolution is (resolution um 10).

    Args:
        ses_text: Raw SES file content.

    Returns:
        SesParseResult with wires, vias, and resolution factor.
    """
    # Detect resolution factor
    res_match = re.search(r'\(resolution\s+(\w+)\s+(\d+)\)', ses_text)
    if res_match:
        res_unit = res_match.group(1)
        res_factor = int(res_match.group(2))
        # (resolution um 10) → values in 0.01um, divide by 100000 for mm
        if res_unit == "um":
            resolution = res_factor * 10000.0
        else:
            resolution = res_factor * 1000000.0  # mm-based, unlikely
    else:
        resolution = 100000.0

    result = SesParseResult(resolution_factor=resolution)

    # Extract wires by scanning (net "name" ...) or (net name ...) blocks
    # Freerouting SES may use quoted or unquoted net names with spaces
    net_pattern = re.compile(r'\(net\s+"([^"]+)"|\(net\s+(\S+)')
    i = 0
    n = len(ses_text)

    while i < n:
        m = net_pattern.search(ses_text, i)
        if not m:
            break

        net_name = m.group(1) or m.group(2)
        net_start = m.end()

        # Find end of (net ...) block by paren tracking
        depth = 1
        j = net_start
        while j < n and depth > 0:
            if ses_text[j] == '(':
                depth += 1
            elif ses_text[j] == ')':
                depth -= 1
            j += 1
        net_end = j - 1

        net_text = ses_text[net_start:net_end]

        # Find all (wire (path LAYER WIDTH ...)) within this net
        path_pattern = re.compile(r'\(path\s+(\S+)\s+(\S+)\s')
        for pm in path_pattern.finditer(net_text):
            layer_name = pm.group(1)
            try:
                width_um = float(pm.group(2))
            except ValueError:
                continue
            width_mm = width_um / resolution

            # Collect coordinate pairs until closing paren of (path ...)
            coords_start = pm.end()
            path_depth = 0
            coords_text = ""
            k = coords_start
            while k < len(net_text):
                ch = net_text[k]
                if ch == '(':
                    path_depth += 1
                elif ch == ')':
                    if path_depth == 0:
                        coords_text = net_text[coords_start:k]
                        break
                    path_depth -= 1
                k += 1

            coord_matches = re.findall(r'[-]?\d+\.?\d*', coords_text)
            points = []
            for ci in range(0, len(coord_matches) - 1, 2):
                try:
                    x = float(coord_matches[ci]) / resolution
                    y = -float(coord_matches[ci + 1]) / resolution  # Y negated
                    points.append((x, y))
                except (ValueError, IndexError):
                    continue

            if len(points) >= 2:
                result.wires.append(SesWire(
                    net=net_name,
                    layer=layer_name,
                    width_mm=width_mm,
                    points=points,
                ))

        i = net_end + 1

    return result


def ses_to_kicad_sexpr(
    ses_result: SesParseResult,
    pcb_net_names: set[str] | None = None,
) -> str:
    """Convert parsed SES data to KiCad segment/via S-expressions.

    Args:
        ses_result: Parsed SES data.
        pcb_net_names: Set of valid net names in the PCB. Wires with
            unmatched nets are skipped. If None, all wires are included.

    Returns:
        String of KiCad (segment ...) and (via ...) S-expressions.
    """
    lines = []

    for wire in ses_result.wires:
        if pcb_net_names is not None and wire.net not in pcb_net_names:
            continue

        for i in range(len(wire.points) - 1):
            x1, y1 = wire.points[i]
            x2, y2 = wire.points[i + 1]
            u = str(uuid.uuid4())
            lines.append(
                f'  (segment (start {x1:.6f} {y1:.6f}) '
                f'(end {x2:.6f} {y2:.6f}) '
                f'(width {wire.width_mm:.6f}) '
                f'(layer "{wire.layer}") '
                f'(net "{wire.net}") '
                f'(uuid "{u}"))'
            )

    for via in ses_result.vias:
        if pcb_net_names is not None and via.net not in pcb_net_names:
            continue
        u = str(uuid.uuid4())
        lines.append(
            f'  (via (at {via.x_mm:.6f} {via.y_mm:.6f}) '
            f'(size {via.size_mm:.6f}) '
            f'(drill {via.drill_mm:.6f}) '
            f'(layers "F.Cu" "B.Cu") '
            f'(net "{via.net}") '
            f'(uuid "{u}"))'
        )

    return "\n".join(lines) + "\n"


def extract_pcb_net_names(pcb_content: str) -> set[str]:
    """Extract all unique net names from PCB content.

    Args:
        pcb_content: Raw .kicad_pcb S-expression text.

    Returns:
        Set of net name strings.
    """
    nets: set[str] = set()
    for m in re.finditer(r'\(net\s+"([^"]+)"', pcb_content):
        nets.add(m.group(1))
    return nets


def import_ses_into_pcb(
    ses_path: Path,
    pcb_content: str,
) -> tuple[str, dict[str, int]]:
    """Import Freerouting SES result into PCB raw content.

    Parses the SES file, converts wire/via data to KiCad S-expressions,
    and inserts them into the PCB content before the closing paren.

    Args:
        ses_path: Path to the .ses file from Freerouting.
        pcb_content: Raw .kicad_pcb S-expression text.

    Returns:
        Tuple of (modified PCB content, stats dict with keys:
            segments, vias, skipped, nets_routed).
    """
    ses_text = ses_path.read_text(encoding="utf-8")
    ses_result = parse_ses(ses_text)

    pcb_nets = extract_pcb_net_names(pcb_content)
    sexpr = ses_to_kicad_sexpr(ses_result, pcb_nets)

    # Count stats
    total_wires = len(ses_result.wires)
    matched_wires = sum(1 for w in ses_result.wires if w.net in pcb_nets)
    total_segments = sum(len(w.points) - 1 for w in ses_result.wires)
    matched_segments = sum(
        len(w.points) - 1 for w in ses_result.wires if w.net in pcb_nets
    )

    # Insert before the last closing paren of the PCB
    if sexpr.strip():
        last_close = pcb_content.rfind(")")
        if last_close > 0:
            insertion = "\n" + sexpr
            pcb_content = pcb_content[:last_close] + insertion + pcb_content[last_close:]

    stats = {
        "segments": matched_segments,
        "vias": len(ses_result.vias),
        "skipped": total_wires - matched_wires,
        "nets_routed": matched_wires,
    }
    return pcb_content, stats


def is_freerouting_available() -> bool:
    """Check if Freerouting and Java are available for auto-routing.

    Returns:
        True if both Freerouting JAR and Java runtime are found.
    """
    return _find_freerouting() is not None and _find_java() is not None
