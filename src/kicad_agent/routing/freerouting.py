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
import math
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


def _find_freeroute_batch(jar_path: str) -> Path | None:
    """Find compiled FreerouteBatch.class for classpath execution.

    Search order:
    1. Same directory as the JAR (e.g. ~/.kicad-agent/tools/FreerouteBatch.class)
    2. kicad-agent routing module directory (bundled at install time)

    If .class not found but .java exists in the routing module directory,
    attempt to compile it using ``javac``.

    Args:
        jar_path: Path to the Freerouting JAR file.

    Returns:
        Path to the directory containing FreerouteBatch.class, or None.
    """
    jar_dir = Path(jar_path).parent

    # Check same directory as JAR
    if (jar_dir / "FreerouteBatch.class").exists():
        return jar_dir

    # Check kicad-agent routing module directory
    routing_dir = Path(__file__).parent
    class_file = routing_dir / "FreerouteBatch.class"
    java_file = routing_dir / "FreerouteBatch.java"

    if class_file.exists():
        return routing_dir

    # Attempt compilation from source
    if java_file.exists():
        javac = shutil.which("javac")
        if javac:
            logger.info("Compiling FreerouteBatch.java from %s", java_file)
            try:
                result = subprocess.run(
                    [javac, "-cp", jar_path, str(java_file)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and class_file.exists():
                    return routing_dir
                logger.warning("FreerouteBatch.java compilation failed: %s", result.stderr)
            except subprocess.TimeoutExpired:
                logger.warning("FreerouteBatch.java compilation timed out")

    return None


def export_dsn(
    pcb_path: Path,
    output_dir: Path | None = None,
    *,
    layers: list[str] | None = None,
    snap_angle: str = "none",
) -> Path:
    """Export PCB in Specctra DSN format.

    KiCad 10 removed ``kicad-cli pcb export dsn``, so this generates
    DSN directly from PCB content using ``dsn_generator``.

    Args:
        pcb_path: Path to .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent.
        layers: Copper layers to include. Default ["F.Cu", "B.Cu"].
        snap_angle: Trace angle mode ("none", "fortyfive_degree", "ninety_degree").
            Threads through to generate_dsn (Phase 99 R-5 / BLOCKER-1).

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
    dsn_text = generate_dsn(pcb_content, pcb_path, layers=layers, snap_angle=snap_angle)

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
    snap_angle: str = "none",
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
        snap_angle: Trace angle mode ("none", "fortyfive_degree", "ninety_degree").
            Threads through export_dsn to generate_dsn (Phase 99 R-5 / BLOCKER-1).

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
        dsn_path = export_dsn(pcb_path, output_dir, snap_angle=snap_angle)
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

    # Try FreerouteBatch.java classpath pattern first (proven, more control)
    batch_dir = _find_freeroute_batch(jar)
    if batch_dir:
        cmd = [
            java,
            "-Djava.awt.headless=true",
            "-cp", f"{jar}:{batch_dir}",
            "FreerouteBatch",
            str(dsn_path), str(ses_path), str(max_passes),
            # Phase 99-03 SC-5: pass snap_angle so FreerouteBatch can configure
            # per-layer preferred directions (Freerouting ignores the DSN
            # (control (snap_angle ...)) directive in batch mode).
            str(snap_angle),
        ]
        logger.info("Using FreerouteBatch classpath pattern from %s", batch_dir)
    else:
        # Fall back to JAR -de/-do flags (existing behavior)
        cmd = [
            java,
            "-Djava.awt.headless=true",
            "-jar", jar,
            "-de", str(dsn_path),  # Input DSN file
            "-do", str(ses_path),  # Output SES file
            "-mp", str(max_passes),  # Max passes
        ]
        logger.info("Using JAR -de/-do fallback pattern")

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
    """A via extracted from an SES file.

    Phase 99 R-6: from_layer/to_layer replace the hardcoded "F.Cu" "B.Cu" that
    previously lived in ses_to_kicad_sexpr. Defaults preserve backward compat
    with any test fixture using the old single-layer form.
    """
    net: str
    x_mm: float
    y_mm: float
    size_mm: float
    drill_mm: float
    from_layer: str = "F.Cu"
    to_layer: str = "B.Cu"


@dataclass
class SesParseResult:
    """Result of parsing an SES file."""
    wires: list[SesWire] = field(default_factory=list)
    vias: list[SesVia] = field(default_factory=list)
    resolution_factor: float = 100000.0


def _layers_from_padstack_name(padstack_name: str) -> tuple[str, str]:
    """R-6: derive (from_layer, to_layer) from a DSN via padstack name.

    Freerouting v2.2.4 emits via instances as (via "Via[SPAN]" X Y ...) where
    SPAN encodes the layer pair. This helper decodes the common forms:

      Via[0-1]      -> ("F.Cu", "B.Cu")      # canonical THT padstack (always F.Cu/B.Cu)
      Via[0-In1]    -> ("F.Cu", "In1.Cu")   # blind, outer-to-first-inner
      Via[In1-In2]  -> ("In1.Cu", "In2.Cu") # buried, inner-to-inner

    Via[0-1] is special-cased: although "0-1" looks like a numeric span, it is
    the historical name for the default THT padstack that spans ALL layers. On
    a 2-layer board this is F.Cu/B.Cu (the only pair). KiCad's (via ...) block
    requires exactly two layers, so we emit the outer pair for THT vias.

    Falls back to ("F.Cu", "B.Cu") for unrecognized names (safe default).
    """
    # Strip quotes if present.
    name = padstack_name.strip().strip('"')
    # Via[0-1] is the canonical THT padstack — always F.Cu/B.Cu in KiCad output.
    if name == "Via[0-1]":
        return ("F.Cu", "B.Cu")
    # Extract the span between [ and ].
    if "[" not in name or "]" not in name:
        return ("F.Cu", "B.Cu")
    span = name[name.index("[") + 1:name.index("]")]
    if "-" not in span:
        return ("F.Cu", "B.Cu")
    parts = span.split("-", 1)
    if len(parts) != 2:
        return ("F.Cu", "B.Cu")
    left, right = parts[0].strip(), parts[1].strip()
    return (_layer_token_from_span_token(left), _layer_token_from_span_token(right))


def _layer_token_from_span_token(token: str) -> str:
    """Map a padstack span token to a KiCad layer name.

    "0"   -> "F.Cu"   (outer front)
    "1".."9" -> "In<N>.Cu" (inner copper; 1-based per KiCad convention)
    "In1" -> "In1.Cu" (already-named inner)
    "3" or higher even -> could be B.Cu on 2-layer, but ambiguous; treat as In<N>.Cu
    For "B.Cu" / "F.Cu" passthrough, return as-is.
    """
    if not token:
        return "F.Cu"
    if token in ("F.Cu", "B.Cu"):
        return token
    if token.startswith("In") and token.endswith(".Cu") is False:
        # "In1" -> "In1.Cu"
        if token.endswith(".Cu"):
            return token
        return f"{token}.Cu"
    if token.startswith("In") and token.endswith(".Cu"):
        return token
    # Numeric form: 0 = F.Cu, 1 = In1.Cu, 2 = In2.Cu, etc.
    try:
        idx = int(token)
        if idx == 0:
            return "F.Cu"
        return f"In{idx}.Cu"
    except ValueError:
        return "F.Cu"


def parse_ses(ses_text: str) -> SesParseResult:
    """Parse a Freerouting SES file into structured wire/via data.

    SES wire format: (wire (path LAYER WIDTH x1 y1 x2 y2 ...))
    SES via format (Freerouting v2.2.4): (via "Via[0-1]" X Y [SIZE DRILL] ...)
    Future-proof via format: (via F.Cu In1.Cu X Y SIZE DRILL)
    Coordinates are in 0.01um units when resolution is (resolution um 10).

    Args:
        ses_text: Raw SES file content.

    Returns:
        SesParseResult with wires, vias, and resolution factor.
    """
    res_match = re.search(r'\(resolution\s+(\w+)\s+(\d+)\)', ses_text)
    if res_match:
        res_unit = res_match.group(1)
        res_factor = int(res_match.group(2))
        # Rule 1 fix (Phase 99-03): the previous logic divided values by
        # (res_factor * 1000), treating (resolution um 10) as "1 unit = 10um"
        # and producing coordinates 10x too small. Empirical verification
        # against the Arduino_Mega reference SES (captured from Freerouting
        # v2.2.4 in Plan 99-02) shows Freerouting emits RAW um values
        # regardless of the declared resolution: a via physically at
        # 117.5mm appears as 117519.3 in the SES, which must parse to
        # 117.5mm. The correct divisor is therefore 1000 (um->mm), NOT
        # (res_factor * 1000). The (resolution um 10) declaration is
        # essentially decorative for Freerouting v2.2.4 output.
        if res_unit == "um":
            resolution = 1000.0
        else:
            resolution = 1.0  # already in mm
    else:
        resolution = 1000.0

    result = SesParseResult(resolution_factor=resolution)

    # R-6 fix: parse the (wiring ...) section — the actual Freerouting v2.2.4
    # SES format. Wires and vias live as top-level children of (wiring ...),
    # NOT nested inside (net ...) blocks. Each (wire ...) contains a
    # (polyline_path LAYER WIDTH coords...) or (path LAYER WIDTH coords...)
    # and a (net NAME N) child identifying the net.
    _parse_wiring_section(ses_text, resolution, result)

    # Legacy path: scan (net ...) blocks for nested (wire (path ...)).
    # Preserves backward compat with any SES fixture using the older
    # net-nested wire format. Safe no-op when wires already parsed above.
    if not result.wires and not result.vias:
        _parse_net_nested_wires(ses_text, resolution, result)

    return result


def _extract_paren_block(text: str, open_pos: int) -> str | None:
    """Extract a balanced (...) block starting at open_pos.

    Returns the block text including outer parens, or None if unbalanced.
    Respects quoted strings (double quotes).
    """
    if open_pos >= len(text) or text[open_pos] != "(":
        return None
    depth = 0
    i = open_pos
    in_string = False
    while i < len(text):
        c = text[i]
        if in_string:
            if c == '"':
                # DSN uses doubled quotes for literal " inside strings.
                if i + 1 < len(text) and text[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_pos:i + 1]
        i += 1
    return None


def _find_net_name_in_block(block: str) -> str:
    """Extract the net name from a (net NAME N) or (net "NAME" N) child."""
    m = re.search(r'\(net\s+(?:"([^"]+)"|(\S+))\s+\d+\)', block)
    if m:
        name = m.group(1) or m.group(2)
        return name.replace("{slash}", "/")
    return ""


def _parse_wire_block(
    block: str, resolution: float, result: SesParseResult
) -> None:
    """Parse a single (wire (polyline_path|path LAYER WIDTH coords...) ...) block."""
    # Match polyline_path OR path (Freerouting v2.2.4 uses polyline_path).
    path_m = re.search(
        r'\((?:polyline_path|path)\s+(\S+)\s+(\S+)\s', block
    )
    if not path_m:
        return
    layer_name = path_m.group(1)
    try:
        width_mm = float(path_m.group(2)) / resolution
    except ValueError:
        return

    # Collect coordinate pairs until closing paren of the path block.
    coords_start = path_m.end()
    path_depth = 0
    coords_text = ""
    k = coords_start
    while k < len(block):
        ch = block[k]
        if ch == "(":
            path_depth += 1
        elif ch == ")":
            if path_depth == 0:
                coords_text = block[coords_start:k]
                break
            path_depth -= 1
        k += 1

    coord_matches = re.findall(r'[-]?\d+\.?\d*', coords_text)
    points: list[tuple[float, float]] = []
    for ci in range(0, len(coord_matches) - 1, 2):
        try:
            x = float(coord_matches[ci]) / resolution
            y = float(coord_matches[ci + 1]) / resolution  # Phase 99-03: no negation (Freerouting preserves KiCad Y-down)
            points.append((x, y))
        except (ValueError, IndexError):
            continue

    if len(points) >= 2:
        net_name = _find_net_name_in_block(block)
        result.wires.append(SesWire(
            net=net_name,
            layer=layer_name,
            width_mm=width_mm,
            points=points,
        ))


def _parse_via_block(
    block: str, resolution: float, result: SesParseResult
) -> None:
    """Parse a single (via ...) block from the wiring section.

    Actual via instance format: (via "PADSTACK" X Y [SIZE DRILL] (net NAME N) ...)
    Future-proof: (via F.Cu In1.Cu X Y SIZE DRILL ...)

    Skips library/rule declarations: (via "Via[0-1]") or
    (via "Via[0-1]" "Via[0-1]" default) — these have < 2 numeric tokens.
    """
    # Strip the outer (via ... ) parens to get inner content.
    inner = block
    if inner.startswith("("):
        # Remove outermost paren pair.
        inner = inner[1:inner.rfind(")")]

    tokens = inner.split()
    if not tokens or tokens[0] != "via":
        return
    tokens = tokens[1:]  # drop the "via" symbol

    def _is_numeric(t: str) -> bool:
        try:
            float(t)
            return True
        except ValueError:
            return False

    numeric_tokens = [t for t in tokens if _is_numeric(t)]
    non_numeric = [t for t in tokens if not _is_numeric(t)]

    # Skip declarations with no coordinates.
    if len(numeric_tokens) < 2:
        return

    x_str, y_str = numeric_tokens[0], numeric_tokens[1]
    size_mm = 0.8
    drill_mm = 0.4
    if len(numeric_tokens) >= 4:
        size_mm = float(numeric_tokens[2]) / resolution
        drill_mm = float(numeric_tokens[3]) / resolution

    cleaned = [t.strip('"') for t in non_numeric]
    layer_tokens = [
        t for t in cleaned
        if "." in t and not t.startswith("Via[") and t != "default"
    ]
    padstack_tokens = [t for t in cleaned if t.startswith("Via[")]

    if len(layer_tokens) >= 2:
        from_layer, to_layer = layer_tokens[0], layer_tokens[1]
    elif padstack_tokens:
        from_layer, to_layer = _layers_from_padstack_name(padstack_tokens[0])
    else:
        from_layer, to_layer = "F.Cu", "B.Cu"

    net_name = _find_net_name_in_block(block)
    result.vias.append(SesVia(
        net=net_name,
        x_mm=float(x_str) / resolution,
        y_mm=float(y_str) / resolution,  # Phase 99-03: no negation (KiCad Y-down preserved)
        size_mm=size_mm,
        drill_mm=drill_mm,
        from_layer=from_layer,
        to_layer=to_layer,
    ))


def _parse_wiring_section(
    ses_text: str, resolution: float, result: SesParseResult
) -> None:
    """Parse the (wiring ...) section of an SES file.

    Freerouting v2.2.4 SES structure:
      (wiring
        (wire (polyline_path|path LAYER WIDTH x1 y1 x2 y2 ...) (net NAME N) ...)
        (via "PADSTACK" X Y [SIZE DRILL] ... (net NAME N) ...)
        ...
      )

    This is the authoritative location of routed wires and vias.
    """
    # Extract the (wiring ...) block by paren tracking.
    wiring_start = re.search(r'\(wiring\b', ses_text)
    if not wiring_start:
        return
    wiring_text = _extract_paren_block(ses_text, wiring_start.start())
    if not wiring_text:
        return

    # Parse (wire ...) blocks.
    for wm in re.finditer(r'\(wire\b', wiring_text):
        wire_block = _extract_paren_block(wiring_text, wm.start())
        if not wire_block:
            continue
        _parse_wire_block(wire_block, resolution, result)

    # Parse (via ...) blocks — only actual via instances (>= 2 numeric tokens).
    for vm in re.finditer(r'\(via\b', wiring_text):
        via_block = _extract_paren_block(wiring_text, vm.start())
        if not via_block:
            continue
        _parse_via_block(via_block, resolution, result)


def _parse_net_nested_wires(
    ses_text: str, resolution: float, result: SesParseResult
) -> None:
    """Legacy: parse wires nested inside (net ...) blocks (older SES format)."""
    net_pattern = re.compile(r'\(net\s+"([^"]+)"|\(net\s+(\S+)')
    i = 0
    n = len(ses_text)

    while i < n:
        m = net_pattern.search(ses_text, i)
        if not m:
            break

        net_name = m.group(1) or m.group(2)
        # Decode Freerouting {slash} encoding for hierarchical net paths
        net_name = net_name.replace("{slash}", "/")
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
                    y = float(coord_matches[ci + 1]) / resolution  # Phase 99-03: no negation (Freerouting preserves KiCad Y-down)
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

        # Note: via parsing for the actual Freerouting v2.2.4 format is handled
        # in _parse_wiring_section (vias live in (wiring ...), not (net ...)).
        # This legacy net-nested path only handles older SES fixtures where
        # wires were nested inside net blocks.

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
            # Phase 99-03 Rule 1 fix: skip zero-length segments. Freerouting
            # occasionally emits polyline points where start == end (visible
            # in the SES as consecutive identical coordinates). These produce
            # ``track_dangling`` DRC warnings on KiCad 10 ("Track has
            # unconnected end", length 0.0000mm) and add no routing value.
            if math.isclose(x1, x2, abs_tol=1e-9) and math.isclose(y1, y2, abs_tol=1e-9):
                continue
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
        # R-6 + WARN-2: route through bridge.ViaSegment.to_sexpr (single canonical
        # emitter). Deletes the parallel f-string builder that hardcoded
        # (layers "F.Cu" "B.Cu") — the R-6 multi-layer bug.
        from kicad_agent.routing.bridge import ViaSegment
        u = str(uuid.uuid4())
        via_seg = ViaSegment(
            x=via.x_mm,
            y=via.y_mm,
            from_layer=via.from_layer,
            to_layer=via.to_layer,
            diameter=via.size_mm,
            drill=via.drill_mm,
            net=via.net,
        )
        lines.append(via_seg.to_sexpr(uuid_tag=u))

    return "\n".join(lines) + "\n"


def extract_pcb_net_names(pcb_content: str) -> set[str]:
    """Extract all unique net names from PCB content.

    Handles both KiCad 10 top-level net declarations:
        (net 1 "NET_A")            # number + quoted name
        (net 0 "")                 # unconnected placeholder (skipped)
        (net "NET_A" 1)            # legacy/alternative form
    Also matches footprint/zone child net references:
        (net 1 "NET_A")            # inside pads and zones

    Rule 1 fix (Phase 99-03): the previous regex ``\\(net\\s+"([^"]+)"``
    required the name to immediately follow ``net``, but KiCad 10's
    canonical form puts the net NUMBER first (``(net N "NAME")``). On
    real fixtures this returned an empty set, causing import_ses_into_pcb
    to skip every routed wire (all nets looked unmatched).

    Args:
        pcb_content: Raw .kicad_pcb S-expression text.

    Returns:
        Set of non-empty net name strings.
    """
    nets: set[str] = set()
    # Match (net TOKEN "NAME") OR (net "NAME" TOKEN). Capture quoted name.
    # Skip empty names (net 0 "").
    for m in re.finditer(r'\(net\s+(?:"([^"]+)"|(?:\S+\s+"([^"]+)"))', pcb_content):
        name = m.group(1) or m.group(2)
        if name:
            nets.add(name)
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
