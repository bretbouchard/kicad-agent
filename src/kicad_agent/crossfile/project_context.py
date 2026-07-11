"""Project context detection and auto-discovery for KiCad projects.

XFILE-04: Given any file path within a KiCad project, detect the project root,
discover all related files, parse .kicad_pro configuration, and provide a
summary of the project state.

Threat model mitigations:
- T-06-10: Upward walk capped at 20 levels; resolve() prevents .. tricks
- T-06-11: Malformed .kicad_pro returns empty list (tolerant regex parsing)
- T-06-12: 20-level cap prevents deep directory traversal DoS
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_WALK_LEVELS = 20


@dataclass(frozen=True)
class ProjectContext:
    """Immutable snapshot of a KiCad project's file structure.

    Attributes:
        project_root: Absolute path to the project root directory.
        pro_file: Path to the .kicad_pro file, or None if not found.
        schematic_files: All .kicad_sch files found in the project.
        pcb_files: All .kicad_pcb files found in the project.
        sym_lib_files: All .kicad_sym files found in the project.
        footprint_files: All .kicad_mod files found in the project.
        library_paths: lib_dir values extracted from the .kicad_pro file.
        build_spec_files: All ``.kicad_build_spec.json`` sidecars found in
            the project (manufacturing specs persisted by Phase 205). Empty
            list when none exist (backward-compatible default).
        builds_dir: The project's ``builds/`` directory (project-scoped,
            INTEG-04) if it exists as a direct child of the project root,
            otherwise None. No upward walk is performed.
    """

    project_root: Path
    pro_file: Optional[Path]
    schematic_files: list[Path] = field(default_factory=list)
    pcb_files: list[Path] = field(default_factory=list)
    sym_lib_files: list[Path] = field(default_factory=list)
    footprint_files: list[Path] = field(default_factory=list)
    library_paths: list[str] = field(default_factory=list)
    build_spec_files: list[Path] = field(default_factory=list)
    builds_dir: Optional[Path] = None


def detect_project_root(file_path: Path) -> Path:
    """Walk upward from a file path to find the KiCad project root.

    The project root is the directory containing a .kicad_pro file.

    Args:
        file_path: Path to any file or directory within a KiCad project.

    Returns:
        Absolute Path to the project root directory.

    Raises:
        FileNotFoundError: If no .kicad_pro file is found within 20 levels.
    """
    resolved = file_path.resolve()

    # Start from parent if given a file, or the path itself if a directory
    current = resolved.parent if resolved.is_file() else resolved

    for _ in range(_MAX_WALK_LEVELS):
        pro_files = list(current.glob("*.kicad_pro"))
        if pro_files:
            return current

        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    raise FileNotFoundError(
        f"No .kicad_pro found within {_MAX_WALK_LEVELS} levels above "
        f"{file_path}"
    )


def discover_project(project_root: Path) -> ProjectContext:
    """Discover all KiCad files within a project directory.

    Scans the project root for all KiCad file types (.kicad_sch, .kicad_pcb,
    .kicad_sym, .kicad_mod, .kicad_pro) and parses the .kicad_pro configuration
    for library paths.

    Args:
        project_root: Path to the project root directory.

    Returns:
        ProjectContext with all discovered files and parsed configuration.

    Raises:
        ValueError: If project_root is not a directory.
    """
    resolved_root = project_root.resolve()

    if not resolved_root.is_dir():
        raise ValueError(
            f"Project root {project_root} is not a directory"
        )

    # Find .kicad_pro (only at root level, not nested)
    pro_files = list(resolved_root.glob("*.kicad_pro"))
    pro_file: Optional[Path] = pro_files[0] if pro_files else None

    # Discover all KiCad files using glob patterns
    schematic_files = sorted(resolved_root.glob("**/*.kicad_sch"))
    pcb_files = sorted(resolved_root.glob("**/*.kicad_pcb"))
    sym_lib_files = sorted(resolved_root.glob("**/*.kicad_sym"))
    footprint_files = sorted(resolved_root.glob("**/*.kicad_mod"))

    # Parse library paths from .kicad_pro if present
    library_paths: list[str] = []
    if pro_file is not None:
        library_paths = _parse_kicad_pro(pro_file)

    # Discover manufacturing sidecars + project-scoped builds/ dir (INTEG-03,
    # INTEG-04). Same glob depth as the file-type globs above; no upward walk.
    build_spec_files = sorted(resolved_root.glob("**/*.kicad_build_spec.json"))
    _builds_dir_path = resolved_root / "builds"
    builds_dir = _builds_dir_path if _builds_dir_path.is_dir() else None

    return ProjectContext(
        project_root=resolved_root,
        pro_file=pro_file,
        schematic_files=schematic_files,
        pcb_files=pcb_files,
        sym_lib_files=sym_lib_files,
        footprint_files=footprint_files,
        library_paths=library_paths,
        build_spec_files=build_spec_files,
        builds_dir=builds_dir,
    )


def _parse_kicad_pro(pro_path: Path) -> list[str]:
    """Parse a .kicad_pro file to extract library directory paths.

    Uses regex to find (lib_dir "...") entries in the S-expression format.
    Tolerant of malformed content -- returns empty list on parse failure.

    Args:
        pro_path: Path to the .kicad_pro file.

    Returns:
        List of lib_dir values found in the file.
    """
    try:
        content = pro_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read .kicad_pro at %s: %s", pro_path, exc)
        return []

    # Match (lib_dir "...") entries, capturing the quoted value
    pattern = re.compile(r'\(lib_dir\s+"([^"]*)"\)')
    matches = pattern.findall(content)

    if not matches:
        logger.debug("No lib_dir entries found in %s", pro_path)

    return matches
