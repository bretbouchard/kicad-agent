"""Shared utilities for schematic symbol operations.

Consolidates _deep_copy_symbol, _increment_reference, and _collect_all_references
to eliminate duplication between operation handlers.

Security (threat model):
- T-04-08: _increment_reference scans all existing references for collision avoidance
- T-04-10: Fresh UUIDs generated via uuid.uuid4() for symbol and pins
"""

import re
import uuid
from typing import Any

from kiutils.items.common import Position, Property
from kiutils.items.schitems import SchematicSymbol, SymbolProjectInstance, SymbolProjectPath


def collect_all_references(ir: Any) -> set[str]:
    """Collect all existing reference designators from the schematic.

    Args:
        ir: SchematicIR wrapping the parsed schematic.

    Returns:
        Set of all reference designator strings.
    """
    refs = set()
    for sym in ir._parse_result.kiutils_obj.schematicSymbols:
        for prop in sym.properties:
            if prop.key == "Reference":
                refs.add(prop.value)
    return refs


def increment_reference(
    source_reference: str,
    all_references: set[str],
) -> str:
    """Generate the next available incremented reference.

    T-04-08: Scans all existing references to prevent collisions.

    Args:
        source_reference: The source component's reference (e.g. "R1").
        all_references: Set of all existing references for collision check.

    Returns:
        The next available reference string (e.g. "R2").

    Raises:
        ValueError: If source_reference doesn't match expected pattern.
    """
    match = re.match(r"^([A-Za-z]+)(\d*)$", source_reference)
    if not match:
        raise ValueError(
            f"Invalid reference format: {source_reference!r}. "
            "Expected format like 'R1', 'U10', 'FB3'."
        )

    prefix = match.group(1)
    number_str = match.group(2)
    source_number = int(number_str) if number_str else None

    used_numbers = set()
    for ref in all_references:
        ref_match = re.match(r"^([A-Za-z]+)(\d+)$", ref)
        if ref_match and ref_match.group(1) == prefix:
            used_numbers.add(int(ref_match.group(2)))

    start = (source_number or 0) + 1
    candidate = start
    while candidate in used_numbers:
        candidate += 1

    return f"{prefix}{candidate}"


def deep_copy_symbol(
    symbol: SchematicSymbol,
    new_reference: str,
    new_position: Position | None = None,
) -> SchematicSymbol:
    """Create a deep copy of a SchematicSymbol with fresh UUIDs.

    T-04-10: Generates fresh UUIDs for the symbol and all pins.

    Args:
        symbol: Source SchematicSymbol to copy.
        new_reference: New reference designator for the copy.
        new_position: New position for the copy (None = keep source position).

    Returns:
        New SchematicSymbol with fresh UUIDs and updated reference.
    """
    new_uuid = str(uuid.uuid4())

    # Copy pins with fresh UUIDs
    new_pins = {name: str(uuid.uuid4()) for name in symbol.pins}

    # Copy properties with updated Reference
    new_properties = []
    for prop in symbol.properties:
        new_properties.append(Property(
            key=prop.key,
            value=new_reference if prop.key == "Reference" else prop.value,
            id=prop.id,
            position=Position(
                X=prop.position.X,
                Y=prop.position.Y,
                angle=prop.position.angle,
            ),
            effects=prop.effects,
            showName=prop.showName,
        ))

    # Determine position
    pos = new_position if new_position is not None else Position(
        X=symbol.position.X,
        Y=symbol.position.Y,
        angle=symbol.position.angle,
    )

    # Copy instances with updated reference
    new_instances = []
    for inst in symbol.instances:
        new_paths = [
            SymbolProjectPath(
                sheetInstancePath=path.sheetInstancePath,
                reference=new_reference,
                unit=path.unit,
            )
            for path in inst.paths
        ]
        new_instances.append(SymbolProjectInstance(
            name=inst.name,
            paths=new_paths,
        ))

    return SchematicSymbol(
        libraryNickname=symbol.libraryNickname,
        entryName=symbol.entryName,
        libName=symbol.libName,
        position=pos,
        unit=symbol.unit,
        inBom=symbol.inBom,
        onBoard=symbol.onBoard,
        dnp=symbol.dnp,
        fieldsAutoplaced=symbol.fieldsAutoplaced,
        uuid=new_uuid,
        properties=new_properties,
        pins=new_pins,
        mirror=symbol.mirror,
        instances=new_instances,
    )
