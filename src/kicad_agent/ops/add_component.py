"""Add component operation handler.

Creates a SchematicSymbol with correct library reference, properties,
position, and UUID. Appends to SchematicIR.components and records mutation.

Security (threat model):
- T-04-01: UUID v4 generated server-side, never from LLM input
- T-04-02: library_id validated for single-colon format

Usage:
    from kicad_agent.ops.add_component import add_component, AddComponentError

    op = AddComponentOp(
        target_file="schematic.kicad_sch",
        library_id="Device:R_Small_US",
        reference="R1",
        value="10k",
        position=PositionSpec(x=50.0, y=30.0),
    )
    result = add_component(op, ir, file_path)
"""

import uuid
from typing import Any

from kiutils.items.common import Effects, Font, Position, Property
from kiutils.items.schitems import SchematicSymbol

from kicad_agent.ops.schema import AddComponentOp


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
    symbol = SchematicSymbol(
        libraryNickname=library_nickname,
        entryName=entry_name,
        libName=op.library_id,
        position=pos,
        uuid=str(new_uuid),
        properties=properties,
        inBom=True,
        onBoard=True,
    )

    # Append to schematicSymbols list
    ir._parse_result.kiutils_obj.schematicSymbols.append(symbol)

    # Auto-embed lib_symbol definition so the component has pins
    embed_result = _auto_embed_lib_symbol(
        op.library_id, library_nickname, entry_name,
        ir, file_path,
    )

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

    logger.info("Auto-embedded symbol %s from %s", library_id, lib_path.name)
    return "embedded"


def _resolve_library_path(library_name: str, file_path: Any) -> Any | None:
    """Resolve a library name to its .kicad_sym file path via sym-lib-table."""
    from pathlib import Path

    from kicad_agent.validation.symbol_resolution import (
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
