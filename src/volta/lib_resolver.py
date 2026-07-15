"""Footprint library resolver -- maps lib_id strings to .kicad_mod file paths.

Resolves footprint library references like
``"Package_TO_SOT_SMD:SOT-223-3_TabPin2"`` to the actual
``.kicad_mod`` file on disk by parsing ``fp-lib-table`` files.

Resolution order:
1. Project-local ``fp-lib-table`` (in the same directory as the PCB file)
2. Global KiCad fp-lib-table (referenced via ``type="Table"`` entries)
3. Environment variable expansion for ``${KIPRJMOD}``, ``${KICAD10_FOOTPRINT_DIR}``, etc.

Usage::

    from volta.lib_resolver import resolve_footprint_path

    path = resolve_footprint_path("Package_TO_SOT_SMD:SOT-223-3_TabPin2", pcb_path)
    # -> /Applications/KiCad/.../footprints/Package_TO_SOT_SMD.pretty/SOT-223-3_TabPin2.kicad_mod
"""

import os
import re
from pathlib import Path
from typing import Optional


# KiCad default footprint directories to search if env vars are unset
_KICAD_APP_FP_DIR = (
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
)
_KICAD_GLOBAL_TABLE = (
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/fp-lib-table")
)


def resolve_footprint_path(lib_id: str, pcb_path: Path) -> Path:
    """Resolve a footprint lib_id to a .kicad_mod file path.

    Args:
        lib_id: Footprint library reference, e.g. ``"Package_TO_SOT_SMD:SOT-223-3_TabPin2"``.
        pcb_path: Path to the .kicad_pcb file (used to find project-local fp-lib-table).

    Returns:
        Absolute Path to the .kicad_mod file.

    Raises:
        ValueError: If lib_id format is invalid.
        FileNotFoundError: If the footprint file cannot be found.
    """
    if ":" not in lib_id:
        raise ValueError(
            f"Invalid lib_id format (expected 'Library:Footprint'): {lib_id!r}"
        )

    nickname, footprint_name = lib_id.split(":", 1)

    # Search for fp-lib-table files
    search_paths = _get_lib_table_search_paths(pcb_path)

    for table_path in search_paths:
        if not table_path.exists():
            continue
        table_base = table_path.resolve().parent
        result = _search_table(table_path, nickname, footprint_name, table_base)
        if result is not None:
            return result

    raise FileNotFoundError(
        f"Could not resolve footprint '{lib_id}'. "
        f"Searched tables: {[str(p) for p in search_paths if p.exists()]}"
    )


def _get_lib_table_search_paths(pcb_path: Path) -> list[Path]:
    """Get fp-lib-table search paths in priority order."""
    paths = []

    # 1. PCB directory and up to 3 parent directories
    current = pcb_path.resolve().parent
    for _ in range(4):
        paths.append(current / "fp-lib-table")
        if current.parent == current:
            break
        current = current.parent

    # 2. Global KiCad fp-lib-table
    if _KICAD_GLOBAL_TABLE.exists():
        paths.append(_KICAD_GLOBAL_TABLE)

    return paths


def _search_table(
    table_path: Path,
    nickname: str,
    footprint_name: str,
    pcb_path: Path,
) -> Optional[Path]:
    """Parse an fp-lib-table and search for the given library nickname."""
    content = table_path.read_text(encoding="utf-8")

    # Parse (lib (name "...") (type "...") (uri "...") ...) entries
    lib_pattern = re.compile(
        r'\(\s*lib\s+'
        r'\(\s*name\s+"([^"]+)"\s*\)'
        r'\s*\(\s*type\s+"([^"]+)"\s*\)'
        r'\s*\(\s*uri\s+"([^"]+)"\s*\)',
        re.DOTALL,
    )

    for match in lib_pattern.finditer(content):
        lib_name, lib_type, lib_uri = match.group(1), match.group(2), match.group(3)

        if lib_name != nickname:
            continue

        # Expand environment variables
        expanded_uri = _expand_env_vars(lib_uri, pcb_path)

        if lib_type == "KiCad":
            # Direct .pretty directory
            pretty_dir = Path(expanded_uri)
            mod_file = pretty_dir / f"{footprint_name}.kicad_mod"
            if mod_file.exists():
                return mod_file

        elif lib_type == "Table":
            # Nested fp-lib-table -- resolve the path and recurse
            nested_table = Path(expanded_uri)
            if nested_table.exists():
                result = _search_table(nested_table, nickname, footprint_name, pcb_path)
                if result is not None:
                    return result

    return None


def _expand_env_vars(uri: str, project_dir: Path) -> str:
    """Expand KiCad environment variables in a URI string.

    Args:
        uri: URI string potentially containing ${KIPRJMOD} etc.
        project_dir: The project root directory for ${KIPRJMOD} expansion.
    """
    project_root = project_dir.resolve()

    # ${KIPRJMOD} -> project root directory
    uri = uri.replace("${KIPRJMOD}", str(project_root))

    # ${KICAD10_FOOTPRINT_DIR} / ${KICAD7_FOOTPRINT_DIR} / ${KISYSMOD}
    kicad_fp_dir = os.environ.get(
        "KICAD10_FOOTPRINT_DIR",
        os.environ.get(
            "KICAD7_FOOTPRINT_DIR",
            os.environ.get("KISYSMOD", str(_KICAD_APP_FP_DIR)),
        ),
    )
    uri = uri.replace("${KICAD10_FOOTPRINT_DIR}", kicad_fp_dir)
    uri = uri.replace("${KICAD7_FOOTPRINT_DIR}", kicad_fp_dir)
    uri = uri.replace("${KISYSMOD}", kicad_fp_dir)

    # Expand any remaining ${VAR} from environment
    for match in re.finditer(r"\$\{(\w+)\}", uri):
        env_val = os.environ.get(match.group(1), "")
        uri = uri.replace(match.group(0), env_val)

    return uri
