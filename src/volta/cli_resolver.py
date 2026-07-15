"""Shared kicad-cli discovery with nightly detection and fallback.

BUG-001 / FEAT-002: KiCad nightly builds produce slightly different file
formats than stable releases. This module provides:

1. kicad-cli discovery from PATH
2. Nightly CLI detection (common install locations)
3. Stable fallback when nightly fails to parse
4. Version detection for version-specific behavior

Usage:
    from volta.cli_resolver import find_kicad_cli, get_kicad_version

    cli_path = find_kicad_cli()
    version = get_kicad_version(cli_path)
    print(f"Using kicad-cli {version} at {cli_path}")
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CliInfo:
    """Information about a discovered kicad-cli binary."""

    path: str
    version: str
    is_nightly: bool

    @property
    def major(self) -> int:
        """Major version number (e.g. 10)."""
        m = re.search(r"(\d+)\.\d+", self.version)
        return int(m.group(1)) if m else 0

    @property
    def minor(self) -> int:
        """Minor version number (e.g. 0)."""
        m = re.search(r"\d+\.(\d+)", self.version)
        return int(m.group(1)) if m else 0


# Common nightly install paths by platform
_NIGHTLY_PATHS: dict[str, list[str]] = {
    "darwin": [
        "/Applications/KiCad-nightly.app/Contents/MacOS/kicad-cli",
        "/Applications/kicad-nightly.app/Contents/MacOS/kicad-cli",
    ],
    "linux": [
        "/usr/bin/kicad-cli-nightly",
        "/usr/local/bin/kicad-cli-nightly",
        "/opt/kicad-nightly/bin/kicad-cli",
    ],
    "win32": [
        r"C:\Program Files\KiCad\nightly\bin\kicad-cli.exe",
        r"C:\Program Files\KiCad-nightly\bin\kicad-cli.exe",
    ],
}

# Module-level cache to avoid repeated PATH lookups
_cached_cli: CliInfo | None = None


def _detect_platform() -> str:
    """Detect current platform key for nightly path lookup."""
    import sys
    return sys.platform


def _get_version(cli_path: str, *, timeout: int = 10) -> str:
    """Extract version string from kicad-cli --version output.

    Args:
        cli_path: Path to kicad-cli binary.
        timeout: Maximum seconds to wait.

    Returns:
        Version string (e.g. "10.0.1") or "unknown".
    """
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        # Typical output: "kicad-cli 10.0.1" or "kicad-cli (10.0.1-unknown)"
        m = re.search(r"(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)", output)
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


def find_kicad_cli(
    *, prefer_nightly: bool = False, timeout: int = 10,
) -> CliInfo:
    """Find kicad-cli on the system with nightly detection and fallback.

    Search order:
    1. If prefer_nightly: check nightly paths first, then PATH
    2. If not prefer_nightly: check PATH first, then nightly paths as fallback
    3. Cache result for subsequent calls

    Args:
        prefer_nightly: If True, prefer nightly builds over stable.
        timeout: Maximum seconds for version detection.

    Returns:
        CliInfo with path, version, and nightly status.

    Raises:
        FileNotFoundError: If no kicad-cli is found anywhere.
    """
    global _cached_cli

    if _cached_cli is not None:
        return _cached_cli

    platform = _detect_platform()
    nightly_paths = _NIGHTLY_PATHS.get(platform, [])

    def _try_path(path: str) -> CliInfo | None:
        if Path(path).is_file() and shutil.which(path):
            version = _get_version(path, timeout=timeout)
            is_nightly = "nightly" in path.lower() or "-unknown" in version or version == "unknown"
            logger.info("Found kicad-cli at %s (version=%s, nightly=%s)", path, version, is_nightly)
            return CliInfo(path=path, version=version, is_nightly=is_nightly)
        return None

    def _try_shutil(name: str = "kicad-cli") -> CliInfo | None:
        cli_path = shutil.which(name)
        if cli_path:
            version = _get_version(cli_path, timeout=timeout)
            is_nightly = "nightly" in cli_path.lower() or "-unknown" in version
            logger.info("Found kicad-cli at %s (version=%s, nightly=%s)", cli_path, version, is_nightly)
            return CliInfo(path=cli_path, version=version, is_nightly=is_nightly)
        return None

    # Build search order
    if prefer_nightly:
        search_order = [(p, _try_path) for p in nightly_paths] + [("PATH", _try_shutil)]
    else:
        search_order = [("PATH", _try_shutil)] + [(p, _try_path) for p in nightly_paths]

    for label, finder in search_order:
        if label == "PATH":
            result = finder()
        else:
            result = _try_path(label)
        if result is not None:
            _cached_cli = result
            return result

    raise FileNotFoundError(
        "kicad-cli not found on PATH or in common nightly locations. "
        "Install KiCad 10+ to get kicad-cli. "
        "On macOS: brew install --cask kicad"
    )


def find_stable_cli(*, timeout: int = 10) -> CliInfo:
    """Find stable (non-nightly) kicad-cli.

    Args:
        timeout: Maximum seconds for version detection.

    Returns:
        CliInfo for stable kicad-cli.

    Raises:
        FileNotFoundError: If no stable kicad-cli is found.
    """
    cli = find_kicad_cli(prefer_nightly=False, timeout=timeout)
    if not cli.is_nightly:
        return cli

    # Stable wasn't found in PATH, try nightly paths to confirm only nightly exists
    platform = _detect_platform()
    for nightly_path in _NIGHTLY_PATHS.get(platform, []):
        if Path(nightly_path).is_file():
            raise FileNotFoundError(
                "Only nightly kicad-cli found. Stable kicad-cli is required "
                "for automated validation. Install stable KiCad 10+ alongside nightly."
            )

    # PATH found nightly but no nightly-specific path exists — return it with warning
    logger.warning("Only nightly kicad-cli found at %s", cli.path)
    return cli


def find_nightly_cli(*, timeout: int = 10) -> CliInfo | None:
    """Find nightly kicad-cli if available.

    Returns:
        CliInfo for nightly kicad-cli, or None if not installed.
    """
    platform = _detect_platform()
    for path in _NIGHTLY_PATHS.get(platform, []):
        if Path(path).is_file():
            version = _get_version(path, timeout=timeout)
            return CliInfo(path=path, version=version, is_nightly=True)
    return None


def get_kicad_version(cli_path: str | None = None) -> str:
    """Get kicad-cli version string.

    Args:
        cli_path: Explicit path to kicad-cli. If None, uses find_kicad_cli().

    Returns:
        Version string (e.g. "10.0.1").
    """
    if cli_path is None:
        return find_kicad_cli().version
    return _get_version(cli_path)


def invalidate_cache() -> None:
    """Clear the cached CliInfo, forcing re-discovery on next call."""
    global _cached_cli
    _cached_cli = None


def _find_kicad_cli() -> str:
    """Backward-compatible alias for existing code.

    Returns the kicad-cli path as a plain string.

    Raises:
        FileNotFoundError: If kicad-cli is not found.
    """
    return find_kicad_cli().path
