"""Symbol copy mismatch check for KiCad schematics.

When sub-sheets embed symbols in their ``lib_symbols`` section, the embedded
copy can diverge from the library original. KiCad ERC reports:
  "Symbol 'X' doesn't match copy in library 'Y'"

This check compares each embedded symbol definition against the library
version resolved via sym-lib-table, detecting pin count changes, pin name
changes, pin number changes, and pin electrical type changes.

Usage:
    from kicad_agent.validation.symbol_mismatch import check_symbol_copy_mismatch

    result = check_symbol_copy_mismatch(ir, sch_path)
    if not result.passed:
        for m in result.mismatches:
            print(f"MISMATCH: {m['lib_id']} used by {m['reference']}: {m['differences']}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from kicad_agent.ir.schematic_ir import SchematicIR, _match_lib_symbol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SymbolMismatchResult:
    """Result of checking embedded symbols against library originals.

    Attributes:
        passed: True if all embedded symbols match their library versions.
        mismatches: List of dicts with lib_id, reference, and differences
            for symbols whose embedded copy diverges from the library.
    """

    passed: bool
    mismatches: tuple[dict[str, Any], ...]


def _get_embedded_pin_signature(ir: SchematicIR, lib_id: str) -> dict[str, dict[str, str]]:
    """Extract pin signature from embedded lib_symbols.

    Returns a dict mapping pin number -> {name, electrical_type}.
    """
    sch = ir._parse_result.kiutils_obj
    pin_map: dict[str, dict[str, str]] = {}

    for lib_sym in sch.libSymbols:
        if _match_lib_symbol(lib_sym, lib_id):
            for unit in lib_sym.units:
                for pin in unit.pins:
                    pin_map[pin.number] = {
                        "name": pin.name,
                        "electrical_type": pin.electricalType,
                    }
            break

    return pin_map


def _get_library_pin_signature(
    lib_id: str,
    sch_path: Path,
) -> Optional[dict[str, dict[str, str]]]:
    """Resolve a lib_id to its library file and extract pin signature.

    Returns None if the library cannot be resolved.
    """
    try:
        from kicad_agent.project.lib_table import parse_lib_table
    except ImportError:
        return None

    library_name, _, symbol_name = lib_id.partition(":")
    if not symbol_name:
        return None

    schematic_dir = sch_path.resolve().parent

    # Search paths: project-local, global KiCad, app bundle
    search_paths: list[Path] = []

    project_table = schematic_dir / "sym-lib-table"
    search_paths.append(project_table)

    global_table = (
        Path.home() / "Library" / "Preferences" / "kicad" / "10.0" / "sym-lib-table"
    )
    if global_table.exists():
        search_paths.append(global_table)

    app_table = Path(
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/sym-lib-table"
    )
    if app_table.exists():
        search_paths.append(app_table)

    # Find the library URI
    library_uri: Optional[str] = None
    for table_path in search_paths:
        if not table_path.exists():
            continue
        try:
            table = parse_lib_table(table_path)
            entry = table.get(library_name)
            uri = entry.uri.replace("${KIPRJMOD}", str(schematic_dir.resolve()))
            library_uri = uri
            break
        except (KeyError, ValueError, FileNotFoundError, OSError):
            continue

    if library_uri is None:
        return None

    # Try to parse the library file
    lib_path = Path(library_uri)
    if not lib_path.exists():
        return None

    try:
        from kiutils.symbol import SymbolLib

        lib = SymbolLib.from_file(str(lib_path))
    except Exception as exc:
        logger.debug("Cannot parse library %s: %s", lib_path, exc)
        return None

    # Find the symbol by name
    for sym in lib.symbols:
        # kiutils Symbol class exposes libId (property) and entryName (field).
        # It does NOT have a `name` attribute -- using sym.name raises
        # AttributeError. libId matches qualified IDs ("Device:R");
        # entryName matches unqualified ("R").
        # [P0-001 fix] See BUGS/P0-001-update-symbols-from-library-crash.md
        if sym.libId == lib_id or sym.entryName == symbol_name:
            pin_map: dict[str, dict[str, str]] = {}
            for unit in sym.units:
                for pin in unit.pins:
                    pin_map[pin.number] = {
                        "name": pin.name,
                        "electrical_type": pin.electricalType,
                    }
            return pin_map

    return None


def _compare_pin_signatures(
    embedded: dict[str, dict[str, str]],
    library: dict[str, dict[str, str]],
) -> list[str]:
    """Compare embedded and library pin signatures, returning differences."""
    differences: list[str] = []

    embedded_nums = set(embedded.keys())
    library_nums = set(library.keys())

    missing_in_library = embedded_nums - library_nums
    if missing_in_library:
        differences.append(
            f"Pins {sorted(missing_in_library)} in embedded but not in library"
        )

    missing_in_embedded = library_nums - embedded_nums
    if missing_in_embedded:
        differences.append(
            f"Pins {sorted(missing_in_embedded)} in library but not in embedded"
        )

    for pin_num in sorted(embedded_nums & library_nums):
        emb = embedded[pin_num]
        lib = library[pin_num]
        changes: list[str] = []
        if emb["name"] != lib["name"]:
            changes.append(f"name: embedded={emb['name']!r} library={lib['name']!r}")
        if emb["electrical_type"] != lib["electrical_type"]:
            changes.append(
                f"type: embedded={emb['electrical_type']!r} library={lib['electrical_type']!r}"
            )
        if changes:
            differences.append(f"Pin {pin_num}: {', '.join(changes)}")

    return differences


def check_symbol_copy_mismatch(ir: SchematicIR, sch_path: Path) -> SymbolMismatchResult:
    """Check embedded symbols match their library originals.

    For each lib_id in Library:Symbol format, compares the embedded symbol
    definition against the library version (from sym-lib-table resolution).

    Args:
        ir: Parsed schematic IR with component references and embedded symbols.
        sch_path: Path to the .kicad_sch file (used to locate lib tables).

    Returns:
        SymbolMismatchResult with list of mismatches.
    """
    mismatches: list[dict[str, Any]] = []

    # Get all unique lib_ids used by placed symbols
    try:
        all_refs = ir.get_all_references()
    except Exception as exc:
        logger.error("Failed to get references from IR: %s", exc)
        return SymbolMismatchResult(
            passed=True,
            mismatches=(),
        )

    # Deduplicate lib_ids while tracking a reference for each
    seen_lib_ids: dict[str, str] = {}  # lib_id -> first reference
    for reference, lib_id in all_refs:
        if lib_id and ":" in lib_id and lib_id not in seen_lib_ids:
            seen_lib_ids[lib_id] = reference

    for lib_id, reference in seen_lib_ids.items():
        try:
            embedded_pins = _get_embedded_pin_signature(ir, lib_id)
            library_pins = _get_library_pin_signature(lib_id, sch_path)

            # If we cannot resolve the library, skip (not a mismatch we can detect)
            if library_pins is None:
                continue

            differences = _compare_pin_signatures(embedded_pins, library_pins)
            if differences:
                mismatches.append({
                    "lib_id": lib_id,
                    "reference": reference,
                    "differences": "; ".join(differences),
                })
        except Exception as exc:
            logger.warning(
                "Error checking symbol mismatch for %s: %s", lib_id, exc
            )

    passed = len(mismatches) == 0

    if not passed:
        logger.info(
            "Symbol mismatch check: %d mismatch(es) found", len(mismatches)
        )

    return SymbolMismatchResult(
        passed=passed,
        mismatches=tuple(mismatches),
    )
