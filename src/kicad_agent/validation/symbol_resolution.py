"""Symbol resolution validator for KiCad schematics.

Checks that every lib_id reference in placed symbols resolves to an actual
symbol definition. Unresolved symbols appear as question-mark boxes in KiCad GUI.

Resolution order:
  1. Embedded lib_symbols in the schematic file
  2. Project-local sym-lib-table (same directory as schematic)
  3. Global KiCad sym-lib-table

Usage:
    from kicad_agent.validation.symbol_resolution import validate_symbol_resolution

    result = validate_symbol_resolution(ir, schematic_path)
    if not result.passed:
        for u in result.unresolved:
            print(f"UNRESOLVED: {u.lib_id} (used by {u.reference})")
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.project.lib_table import parse_lib_table, LibTable

logger = logging.getLogger(__name__)

# Valid library reference format: LIBRARY_NAME:SYMBOL_NAME (both non-empty)
_LIBRARY_REF_PATTERN = re.compile(r"^[^:]+:[^:]+$")

# Common bare symbol names and suggested Library:Symbol mappings
_BARE_LIB_ID_SUGGESTIONS: dict[str, str] = {
    "R": "Device:R",
    "C": "Device:C",
    "L": "Device:L",
    "D": "Device:D",
    "LED": "Device:LED",
    "Q_NPN": "Device:Q_NPN",
    "Q_PNP": "Device:Q_PNP",
    "Q_NMOS": "Device:Q_NMOS_GDS",
    "Q_PMOS": "Device:Q_PMOS_GDS",
    "OPAMP": "Amplifier_Operational:OPAMP",
    "GND": "power:GND",
    "VCC": "power:VCC",
    "+5V": "power:+5V",
    "+3V3": "power:+3V3",
    "+3.3V": "power:+3V3",
    "-5V": "power:-5V",
    "GNDPWR": "power:GNDPWR",
    "PWR_FLAG": "power:PWR_FLAG",
    "F": "Device:F",
    "T": "Device:T",
    "SW": "Switch:SW",
    "J": "Connector:J",
    "U": "MCU_Module:U",
    "Y": "Device:Crystal",
    "Crystal": "Device:Crystal",
    "SPST": "Switch:SW_SPST",
    "Transformer": "Device:Transformer",
    "Fuse": "Device:Fuse",
    "Relay": "Relay:Relay",
    "Battery": "Device:Battery",
    "Buzzer": "Device:Buzzer",
    "Motor": "Motor:Motor",
}

# macOS global sym-lib-table path (KiCad 10.0)
_KICAD_GLOBAL_SYM_TABLE = (
    Path.home() / "Library" / "Preferences" / "kicad" / "10.0" / "sym-lib-table"
)

# KiCad app bundle sym-lib-table (fallback)
_KICAD_APP_SYM_TABLE = (
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/sym-lib-table")
)


@dataclass(frozen=True)
class UnresolvedSymbol:
    """A symbol reference that could not be resolved to a definition.

    Attributes:
        lib_id: The unresolved library reference (e.g. "Device:R").
        reference: The component reference designator (e.g. "R1").
        detail: Explanation of why resolution failed.
    """

    lib_id: str
    reference: str
    detail: str


@dataclass(frozen=True)
class ResolvedSymbol:
    """A symbol reference that was successfully resolved.

    Attributes:
        lib_id: The library reference that was resolved (e.g. "Device:R").
        reference: The component reference designator (e.g. "R1").
        source: Where the definition was found (e.g. "embedded" or a file path).
    """

    lib_id: str
    reference: str
    source: str


@dataclass(frozen=True)
class SymbolResolutionResult:
    """Result of validating all symbol references in a schematic.

    Attributes:
        passed: True if every lib_id resolves to a definition.
        resolved: Tuple of successfully resolved symbols.
        unresolved: Tuple of symbols that could not be resolved.
        error_message: Non-None if a parse or I/O error prevented validation.
    """

    passed: bool
    resolved: tuple[ResolvedSymbol, ...]
    unresolved: tuple[UnresolvedSymbol, ...]
    error_message: Optional[str] = None


def _expand_kiprjmod(uri: str, schematic_dir: Path) -> str:
    """Expand ${KIPRJMOD} in a library URI to the schematic's parent directory.

    Args:
        uri: URI string that may contain ``${KIPRJMOD}``.
        schematic_dir: Directory containing the schematic file.

    Returns:
        URI with ``${KIPRJMOD}`` replaced by the resolved directory path.
    """
    return uri.replace("${KIPRJMOD}", str(schematic_dir.resolve()))


def _get_sym_table_search_paths(schematic_path: Path) -> list[Path]:
    """Return sym-lib-table search paths in priority order.

    Args:
        schematic_path: Path to the .kicad_sch file.

    Returns:
        Ordered list of sym-lib-table paths to check.
    """
    paths: list[Path] = []

    # 1. Project-local sym-lib-table (same directory as schematic)
    project_table = schematic_path.resolve().parent / "sym-lib-table"
    paths.append(project_table)

    # 2. Global KiCad sym-lib-table (user preferences)
    if _KICAD_GLOBAL_SYM_TABLE.exists():
        paths.append(_KICAD_GLOBAL_SYM_TABLE)

    # 3. KiCad app bundle fallback
    if _KICAD_APP_SYM_TABLE.exists():
        paths.append(_KICAD_APP_SYM_TABLE)

    return paths


def _find_library_uri(
    library_name: str,
    search_paths: list[Path],
    schematic_dir: Path,
) -> Optional[str]:
    """Search sym-lib-table files for a library name and return its expanded URI.

    Args:
        library_name: The library nickname to find (e.g. "Device", "power").
        search_paths: Ordered list of sym-lib-table file paths.
        schematic_dir: Directory containing the schematic (for ${KIPRJMOD}).

    Returns:
        Expanded URI string if found, or None.
    """
    for table_path in search_paths:
        if not table_path.exists():
            continue
        try:
            table = parse_lib_table(table_path)
        except (ValueError, FileNotFoundError, OSError) as exc:
            logger.debug("Skipping unparseable sym-lib-table %s: %s", table_path, exc)
            continue

        try:
            entry = table.get(library_name)
        except KeyError:
            continue

        return _expand_kiprjmod(entry.uri, schematic_dir)

    return None


def validate_symbol_resolution(
    ir: SchematicIR,
    schematic_path: Path,
) -> SymbolResolutionResult:
    """Validate that every lib_id in the schematic resolves to a symbol definition.

    Checks each placed symbol's lib_id against, in order:
      1. Embedded lib_symbols definitions in the schematic file
      2. Project-local sym-lib-table
      3. Global KiCad sym-lib-table

    Args:
        ir: Parsed schematic IR with component references.
        schematic_path: Path to the .kicad_sch file (used to locate lib tables).

    Returns:
        SymbolResolutionResult with resolved/unresolved lists. If a parse error
        prevents validation, returns a failed result with error_message set.
    """
    # Collect all (reference, libId) pairs from the schematic
    try:
        all_refs = ir.get_all_references()
    except Exception as exc:
        logger.error("Failed to get references from IR: %s", exc)
        return SymbolResolutionResult(
            passed=False,
            resolved=(),
            unresolved=(),
            error_message=f"Failed to read schematic references: {exc}",
        )

    if not all_refs:
        return SymbolResolutionResult(
            passed=True,
            resolved=(),
            unresolved=(),
        )

    # Build set of embedded symbol libIds from the schematic's libSymbols
    embedded_lib_ids: set[str] = set()
    try:
        lib_symbols = ir._parse_result.kiutils_obj.libSymbols
        if lib_symbols:
            for sym in lib_symbols:
                sym_lib_id = getattr(sym, "libId", None)
                if sym_lib_id:
                    embedded_lib_ids.add(sym_lib_id)
    except Exception as exc:
        logger.warning("Could not read embedded libSymbols: %s", exc)

    # Prepare sym-lib-table search paths (computed once, reused)
    schematic_dir = schematic_path.resolve().parent
    search_paths = _get_sym_table_search_paths(schematic_path)

    resolved_list: list[ResolvedSymbol] = []
    unresolved_list: list[UnresolvedSymbol] = []

    for reference, lib_id in all_refs:
        # Check for empty lib_id
        if not lib_id:
            unresolved_list.append(
                UnresolvedSymbol(
                    lib_id="",
                    reference=reference,
                    detail="Empty lib_id (expected 'Library:Symbol')",
                )
            )
            continue

        # Check for bare lib_id (no colon -- e.g. "R" instead of "Device:R")
        if ":" not in lib_id:
            suggestion = _BARE_LIB_ID_SUGGESTIONS.get(lib_id, "")
            suggestion_text = f" (suggestion: {suggestion})" if suggestion else ""
            unresolved_list.append(
                UnresolvedSymbol(
                    lib_id=lib_id,
                    reference=reference,
                    detail=(
                        f"Bare lib_id '{lib_id}' missing library prefix; "
                        f"use 'Library:{lib_id}' format{suggestion_text}"
                    ),
                )
            )
            continue

        # Validate full format (Library:Symbol with no empty parts)
        if not _LIBRARY_REF_PATTERN.match(lib_id):
            unresolved_list.append(
                UnresolvedSymbol(
                    lib_id=lib_id,
                    reference=reference,
                    detail="Invalid lib_id format (expected 'Library:Symbol')",
                )
            )
            continue

        # 1. Check embedded definitions
        if lib_id in embedded_lib_ids:
            resolved_list.append(
                ResolvedSymbol(
                    lib_id=lib_id,
                    reference=reference,
                    source="embedded",
                )
            )
            continue

        # 2. Check sym-lib-table files (project-local, then global)
        library_name = lib_id.split(":", 1)[0]
        library_uri = _find_library_uri(library_name, search_paths, schematic_dir)

        if library_uri is not None:
            resolved_list.append(
                ResolvedSymbol(
                    lib_id=lib_id,
                    reference=reference,
                    source=library_uri,
                )
            )
            continue

        # Not found anywhere
        unresolved_list.append(
            UnresolvedSymbol(
                lib_id=lib_id,
                reference=reference,
                detail=(
                    f"Library '{library_name}' not found in embedded symbols, "
                    "project-local sym-lib-table, or global sym-lib-table"
                ),
            )
        )

    passed = len(unresolved_list) == 0

    if not passed:
        logger.warning(
            "Symbol resolution: %d unresolved out of %d total references",
            len(unresolved_list),
            len(all_refs),
        )
    else:
        logger.debug(
            "Symbol resolution: all %d references resolved", len(all_refs)
        )

    return SymbolResolutionResult(
        passed=passed,
        resolved=tuple(resolved_list),
        unresolved=tuple(unresolved_list),
    )
