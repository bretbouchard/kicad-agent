"""Add component operation handler.

Creates a SchematicSymbol with correct library reference, properties,
position, and UUID. Appends to SchematicIR.components and records mutation.

Security (threat model):
- T-04-01: UUID v4 generated server-side, never from LLM input
- T-04-02: library_id validated for single-colon format

Usage:
    from volta.ops.add_component import add_component, AddComponentError

    op = AddComponentOp(
        target_file="schematic.kicad_sch",
        library_id="Device:R_Small_US",
        reference="R1",
        value="10k",
        position=PositionSpec(x=50.0, y=30.0),
    )
    result = add_component(op, ir, file_path)
"""

import logging
import uuid
from typing import Any

from kiutils.items.common import Effects, Font, Position, Property
from kiutils.items.schitems import SchematicSymbol

from volta.ops.schema import AddComponentOp

logger = logging.getLogger(__name__)


class AddComponentError(Exception):
    """Error raised when add_component operation fails."""


def add_component(
    op: AddComponentOp,
    ir: Any,
    file_path: Any,
) -> dict[str, Any]:
    """Add a component to a schematic.

    Creates a SchematicSymbol with correct library reference, standard
    properties (Reference, Value, Footprint, Datasheet), position, and
    a fresh UUID v4. Appends to SchematicIR.components and records mutation.

    Args:
        op: AddComponentOp with library_id, reference, value, position.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Path to the schematic file.

    Returns:
        Dict with component details: reference, library_id, uuid, position.

    Raises:
        AddComponentError: If library_id is malformed or reference already exists.
    """
    # T-04-02: Validate library_id format -- must contain exactly one colon
    parts = op.library_id.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise AddComponentError(
            f"Invalid library_id format: {op.library_id!r}. "
            "Expected 'Library:Symbol' with exactly one colon separator."
        )
    library_nickname = parts[0]
    entry_name = parts[1]

    # Check reference uniqueness -- "?"-suffixed references (like "R?") are allowed duplicates
    if not op.reference.endswith("?"):
        existing = ir.get_component_by_ref(op.reference)
        if existing is not None:
            raise AddComponentError(
                f"Component with reference {op.reference!r} already exists."
            )

    # T-04-01: Generate UUID v4 server-side, never from LLM input
    new_uuid = uuid.uuid4()

    # Create kiutils Position (angle=None when 0.0, matching KiCad convention)
    angle = op.position.angle if op.position.angle != 0.0 else None
    pos = Position(X=op.position.x, Y=op.position.y, angle=angle)

    # Create standard properties with default Effects (KiCad font size 1.27)
    standard_font = Font(height=1.27, width=1.27)
    properties = [
        Property(
            key="Reference",
            value=op.reference,
            id=0,
            position=Position(),
            effects=Effects(font=standard_font),
        ),
        Property(
            key="Value",
            value=op.value,
            id=1,
            position=Position(),
            effects=Effects(font=standard_font),
        ),
        Property(
            key="Footprint",
            value="",
            id=2,
            position=Position(),
            effects=Effects(font=standard_font, hide=True),
        ),
        Property(
            key="Datasheet",
            value="~",
            id=3,
            position=Position(),
            effects=Effects(font=standard_font, hide=True),
        ),
    ]

    # Create SchematicSymbol with all fields
    # inBom/onBoard default to True — standard for real component instances.
    # Power symbols use False, handled separately.
    symbol = SchematicSymbol(
        libraryNickname=library_nickname,
        entryName=entry_name,
        libName=op.library_id,
        position=pos,
        uuid=str(new_uuid),
        properties=properties,
        inBom=True,
        onBoard=True,
        unit=1,
    )

    # Append to schematicSymbols list
    ir._parse_result.kiutils_obj.schematicSymbols.append(symbol)

    # Auto-embed lib_symbol definition so the component has pins
    embed_result = _auto_embed_lib_symbol(
        op.library_id, library_nickname, entry_name,
        ir, file_path,
    )

    # Populate pin UUID references from the embedded lib_symbol.
    # KiCad 10 requires (pin "N" (uuid ...)) entries in every component
    # instance to link pins to the lib_symbol definition. Without these,
    # kicad-cli ERC refuses to load the schematic.
    _populate_pin_uuids(symbol, op.library_id, ir)

    # Record mutation for audit trail
    ir._record_mutation(
        "add_component",
        {
            "reference": op.reference,
            "library_id": op.library_id,
            "uuid": str(new_uuid),
            "lib_symbol_embedded": embed_result,
        },
    )

    return {
        "reference": op.reference,
        "library_id": op.library_id,
        "uuid": str(new_uuid),
        "position": {"x": op.position.x, "y": op.position.y, "angle": op.position.angle},
        "lib_symbol_embedded": embed_result,
    }


def _auto_embed_lib_symbol(
    library_id: str,
    library_nickname: str,
    entry_name: str,
    ir: Any,
    file_path: Any,
) -> str:
    """Auto-embed a symbol definition from KiCad libraries if not already present.

    Resolves the library path from sym-lib-table, loads the symbol definition,
    and injects it into the schematic's libSymbols section.

    Returns:
        "embedded", "already_exists", or "not_found"
    """
    import copy
    import logging

    from kiutils.symbol import SymbolLib

    logger = logging.getLogger(__name__)
    sch = ir._parse_result.kiutils_obj

    # Check if already embedded
    for existing in sch.libSymbols:
        if existing.libId == library_id:
            return "already_exists"

    # Resolve library path from sym-lib-table
    lib_path = _resolve_library_path(library_nickname, file_path)
    if lib_path is None:
        logger.warning(
            "Could not resolve library path for %s. "
            "Symbol will have no pin definitions until manually embedded.",
            library_id,
        )
        return "not_found"

    # Load the library and find the symbol
    try:
        lib = SymbolLib.from_file(str(lib_path))
    except Exception as exc:
        logger.warning("Cannot parse library file %s: %s", lib_path, exc)
        return "not_found"

    source_symbol = None
    for sym in lib.symbols:
        if sym.entryName == entry_name or sym.libId == library_id:
            source_symbol = sym
            break

    if source_symbol is None:
        logger.warning("Symbol %r not found in %s", entry_name, lib_path.name)
        return "not_found"

    # Deep copy and embed
    new_symbol = copy.deepcopy(source_symbol)
    new_symbol.libraryNickname = library_nickname
    sch.libSymbols.append(new_symbol)

    # Recursively embed parent symbols if this symbol extends another
    _embed_parent_chain(new_symbol, lib, library_nickname, sch, logger)

    logger.info("Auto-embedded symbol %s from %s", library_id, lib_path.name)
    return "embedded"


def _embed_parent_chain(child_symbol: Any, lib: Any, lib_nickname: str, sch: Any, logger: Any) -> None:
    """Flatten symbol inheritance by merging parent pins/graphics into child.

    KiCad symbols can use (extends "ParentSymbol") to inherit from a base.
    kicad-cli 10.0.1 cannot parse (extends ...) in embedded lib_symbols even
    when the parent is present. The fix: recursively flatten the inheritance
    chain by merging parent data into the child and removing the extends field.
    """
    import copy

    extends = getattr(child_symbol, "extends", None)
    if not extends:
        return

    # Find parent in the library
    parent = None
    for sym in lib.symbols:
        if sym.entryName == extends:
            parent = sym
            break

    if parent is None:
        logger.warning(
            "Parent symbol %r (extended by %s) not found in library. "
            "Cannot flatten inheritance.",
            extends,
            getattr(child_symbol, "libId", "?"),
        )
        return

    # Recursively flatten the parent first (in case parent extends grandparent)
    parent_copy = copy.deepcopy(parent)
    _embed_parent_chain(parent_copy, lib, lib_nickname, sch, logger)

    # Merge parent's units (graphic sub-symbols + pin sub-symbols) into child
    # KiCad Symbol uses `units: List[Symbol]` for sub-symbols
    parent_units = getattr(parent_copy, "units", [])
    child_units = getattr(child_symbol, "units", [])

    # Also merge pins from parent (child may have no pins if it relies on parent)
    parent_pins = getattr(parent_copy, "pins", [])
    child_pins = getattr(child_symbol, "pins", [])
    if not child_pins:
        child_pins.extend(parent_pins)

    # Merge properties from parent that child doesn't override
    parent_props = getattr(parent_copy, "properties", [])
    child_props = getattr(child_symbol, "properties", [])
    parent_prop_keys = {p.key for p in child_props}
    for pp in parent_props:
        if pp.key not in parent_prop_keys:
            child_props.append(copy.deepcopy(pp))

    # Merge units (contains graphic sub-symbols like polylines, rectangles, text)
    child_units.extend(copy.deepcopy(parent_units))

    # Copy pin_names from parent if child doesn't have them
    if not getattr(child_symbol, "pinNames", None) and getattr(parent_copy, "pinNames", None):
        child_symbol.pinNames = parent_copy.pinNames
    # Copy pinNamesOffset if missing
    if getattr(child_symbol, "pinNamesOffset", None) is None and getattr(parent_copy, "pinNamesOffset", None) is not None:
        child_symbol.pinNamesOffset = parent_copy.pinNamesOffset

    # Copy in_bom and on_board from parent if child doesn't have them
    if not child_symbol.inBom and parent_copy.inBom:
        child_symbol.inBom = parent_copy.inBom
    if not child_symbol.onBoard and parent_copy.onBoard:
        child_symbol.onBoard = parent_copy.onBoard

    # Remove the extends field to make child self-contained
    if hasattr(child_symbol, "extends"):
        del child_symbol.extends

    logger.info(
        "Flattened inheritance: %s (was extends %s), merged %d units + %d pins",
        getattr(child_symbol, "libId", "?"),
        extends,
        len(parent_units),
        len(parent_pins),
    )


def _resolve_library_path(library_name: str, file_path: Any) -> Any | None:
    """Resolve a library name to its .kicad_sym file path via sym-lib-table."""
    from pathlib import Path

    from volta.validation.symbol_resolution import (
        _expand_kiprjmod,
        _find_library_uri,
        _get_sym_table_search_paths,
    )

    schematic_path = Path(file_path) if not isinstance(file_path, Path) else file_path
    search_paths = _get_sym_table_search_paths(schematic_path)
    schematic_dir = schematic_path.resolve().parent

    uri = _find_library_uri(library_name, search_paths, schematic_dir)
    if uri is None:
        return None

    expanded = _expand_kiprjmod(uri, schematic_dir)
    lib_path = Path(expanded)
    if lib_path.exists():
        return lib_path

    # Try relative to schematic dir
    relative = schematic_dir / expanded
    if relative.exists():
        return relative

    return None


def _populate_pin_uuids(
    component: SchematicSymbol,
    library_id: str,
    ir: Any,
) -> None:
    """Generate pin UUID references from the embedded lib_symbol.

    KiCad 10 requires every component instance to have (pin "N" (uuid ...))
    entries linking back to the embedded lib_symbol's pin definitions.
    Without these, kicad-cli ERC fails with "Failed to load schematic".

    kiutils Symbol units use ``unitId`` (integer) to identify sub-symbols.
    For a component with unit=1, match the lib_symbol unit with unitId=1.
    """
    sch = ir._parse_result.kiutils_obj

    # Find the embedded lib_symbol
    lib_symbol = None
    for sym in sch.libSymbols:
        if sym.libId == library_id:
            lib_symbol = sym
            break

    if lib_symbol is None:
        logger.debug("No embedded lib_symbol for %s — cannot populate pin UUIDs", library_id)
        return

    # Determine which unit the component references (default 1)
    unit_num = getattr(component, "unit", 1) or 1

    # Find the pin-bearing unit matching the component's unit number.
    # kiutils Symbol units use unitId (int) not unitName.
    pin_unit = None

    # First: exact unitId match with pins
    for u in lib_symbol.units:
        if getattr(u, "unitId", None) == unit_num and u.pins:
            pin_unit = u
            break

    # Fallback: any unit with pins (for symbols with only one pin unit)
    if pin_unit is None:
        for u in lib_symbol.units:
            if u.pins:
                pin_unit = u
                break

    # Second fallback: root symbol pins
    if pin_unit is None and lib_symbol.pins:
        pin_unit = lib_symbol

    if pin_unit is None:
        logger.debug("No pin-bearing unit found for %s unit %d", library_id, unit_num)
        return

    # Generate fresh UUIDs for each pin and populate the component's pins dict
    for pin in pin_unit.pins:
        pin_uuid = str(uuid.uuid4())
        component.pins[pin.number] = pin_uuid
