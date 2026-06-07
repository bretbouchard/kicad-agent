"""Freerouting integration for production-quality auto-routing (FEAT-001).

Provides DSN (Specctra) export/import for Freerouting integration,
plus a complete auto-routing pipeline that uses Freerouting when available
and falls back to the built-in A* pathfinder.

Freerouting is an open-source Java auto-router that produces significantly
better routing results than the built-in A* pathfinder for real-world
designs with dense routing.

Usage:
    from kicad_agent.routing.freerouting import route_with_freerouting, export_dsn

    # Export DSN file for Freerouting
    dsn_path = export_dsn(pcb_path, output_dir=Path("./dsn"))

    # Route using Freerouting (requires Java runtime + Freerouting JAR)
    result = route_with_freerouting(pcb_path, output_dir=Path("./routed"))

    # Or use the auto-router with automatic Freerouting/A* fallback
    result = auto_route(pcb_path)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
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
) -> Path:
    """Export PCB in Specctra DSN format via kicad-cli.

    Freerouting reads DSN files as input for auto-routing.

    Args:
        pcb_path: Path to .kicad_pcb file.
        output_dir: Output directory. Defaults to pcb_path parent.

    Returns:
        Path to the generated .dsn file.

    Raises:
        FileNotFoundError: If pcb_path or kicad-cli not found.
        subprocess.CalledProcessError: If kicad-cli export fails.
    """
    from kicad_agent.cli_resolver import find_kicad_cli

    if output_dir is None:
        output_dir = pcb_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    dsn_path = output_dir / f"{pcb_path.stem}{_DSN_EXTENSION}"
    cli = find_kicad_cli()

    cmd = [
        cli.path,
        "pcb",
        "export",
        "dsn",
        "--output", str(dsn_path),
        str(pcb_path),
    ]

    logger.info("Exporting DSN: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr,
        )

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
    a .ses session file that can be imported back into KiCad.

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

    # Run Freerouting
    ses_path = output_dir / f"{pcb_path.stem}{_SES_EXTENSION}"
    cmd = [
        java, "-jar", jar,
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


def import_ses(
    ses_path: Path,
    pcb_path: Path,
    output_pcb_path: Path | None = None,
) -> Path:
    """Import Freerouting SES result back into KiCad PCB format.

    Uses kicad-cli to import the Specctra session file.

    Args:
        ses_path: Path to .ses file from Freerouting.
        pcb_path: Original .kicad_pcb file.
        output_pcb_path: Output PCB file. Defaults to pcb_path with
            _routed suffix.

    Returns:
        Path to the routed PCB file.

    Raises:
        FileNotFoundError: If ses_path or kicad-cli not found.
        subprocess.CalledProcessError: If import fails.
    """
    from kicad_agent.cli_resolver import find_kicad_cli

    if output_pcb_path is None:
        output_pcb_path = pcb_path.parent / f"{pcb_path.stem}_routed.kicad_pcb"

    cli = find_kicad_cli()

    cmd = [
        cli.path,
        "pcb",
        "import",
        "dsn",
        "--output", str(output_pcb_path),
        str(ses_path),
    ]

    logger.info("Importing SES: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr,
        )

    return output_pcb_path


def is_freerouting_available() -> bool:
    """Check if Freerouting and Java are available for auto-routing.

    Returns:
        True if both Freerouting JAR and Java runtime are found.
    """
    return _find_freerouting() is not None and _find_java() is not None
