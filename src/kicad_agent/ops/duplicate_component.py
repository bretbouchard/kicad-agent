"""Duplicate component operation handler.

Creates a copy of an existing component with a fresh UUID, incremented
reference designator, and optional position offset. Supports creating
multiple copies in a single operation.

Security (threat model):
- T-04-08: _increment_reference scans all existing references -- no collision possible
- T-04-10: Fresh UUIDs generated via uuid.uuid4() for symbol and pins

Usage:
    from kicad_agent.ops.duplicate_component import duplicate_component, DuplicateComponentError

    op = DuplicateComponentOp(
        target_file="schematic.kicad_sch",
        source_reference="R1",
        offset=PositionSpec(x=10.0, y=5.0),
        count=2,
    )
    result = duplicate_component(op, ir)
"""

import re
import uuid
from typing import Any

from kiutils.items.common import Position, Property
from kiutils.items.schitems import SchematicSymbol

from kicad_agent.ops.schema import DuplicateComponentOp


class DuplicateComponentError(Exception):
    """Error raised when duplicate_component operation fails."""


def _parse_reference(reference: str) -> tuple[str, int | None]:
    """Parse a reference designator into prefix and numeric suffix.

    Examples:
        "R1" -> ("R", 1)
        "U10" -> ("U", 10)
        "R?" -> ("R", None)

    Args:
        reference: Reference designator string.

    Returns:
        Tuple of (prefix, number) where number is None for unannotated refs.
    """
    match = re.match(r"^([A-Za-z]+)(\d*)$", reference)
    if not match:
        return reference, None
    prefix = match.group(1)
    number_str = match.group(2)
    if not number_str:
        return prefix, None
    return prefix, int(number_str)


def _collect_all_references(ir: Any) -> set[str]:
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


def _increment_reference(
    source_reference: str,
    all_references: set[str],
) -> str:
    """Generate the next available incremented reference.

    Parses the source reference into prefix and number, then finds
    the next available number for that prefix.

    T-04-08: Scans all existing references to prevent collisions.

    Args:
        source_reference: The source component's reference (e.g. "R1").
        all_references: Set of all existing references for collision check.

    Returns:
        The next available reference string (e.g. "R2").
    """
    prefix, source_number = _parse_reference(source_reference)

    # Collect all numbers used by this prefix
    used_numbers = set()
    for ref in all_references:
        ref_prefix, ref_number = _parse_reference(ref)
        if ref_prefix == prefix and ref_number is not None:
            used_numbers.add(ref_number)

    # Start from source_number + 1 (or 1 if source has no number)
    start = (source_number or 0) + 1
    candidate = start
    while candidate in used_numbers:
        candidate += 1

    return f"{prefix}{candidate}"


def _deep_copy_symbol(
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
    # Generate fresh UUID for the symbol itself
    new_uuid = str(uuid.uuid4())

    # Copy pins with fresh UUIDs
    new_pins = {}
    for pin_name, pin_uuid in symbol.pins.items():
        new_pins[pin_name] = str(uuid.uuid4())

    # Copy properties with updated Reference
    new_properties = []
    for prop in symbol.properties:
        if prop.key == "Reference":
            # Create new Reference property with updated value
            new_prop = Property(
                key=prop.key,
                value=new_reference,
                id=prop.id,
                position=Position(
                    X=prop.position.X,
                    Y=prop.position.Y,
                    angle=prop.position.angle,
                ),
                effects=prop.effects,
                showName=prop.showName,
            )
            new_properties.append(new_prop)
        else:
            # Copy other properties as-is
            new_prop = Property(
                key=prop.key,
                value=prop.value,
                id=prop.id,
                position=Position(
                    X=prop.position.X,
                    Y=prop.position.Y,
                    angle=prop.position.angle,
                ),
                effects=prop.effects,
                showName=prop.showName,
            )
            new_properties.append(new_prop)

    # Determine position
    pos = new_position if new_position is not None else Position(
        X=symbol.position.X,
        Y=symbol.position.Y,
        angle=symbol.position.angle,
    )

    # Create new instances list with fresh reference
    new_instances = []
    for inst in symbol.instances:
        new_paths = []
        for path in inst.paths:
            from kiutils.items.schitems import SymbolProjectPath
            new_paths.append(SymbolProjectPath(
                sheetInstancePath=path.sheetInstancePath,
                reference=new_reference,
                unit=path.unit,
            ))
        from kiutils.items.schitems import SymbolProjectInstance
        new_instances.append(SymbolProjectInstance(
            name=inst.name,
            paths=new_paths,
        ))

    # Create new SchematicSymbol with all copied fields
    new_symbol = SchematicSymbol(
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

    return new_symbol


def duplicate_component(
    op: DuplicateComponentOp,
    ir: Any,
) -> dict[str, Any]:
    """Duplicate a component with fresh UUIDs and incremented reference.

    Finds the source component, creates copies with fresh UUIDs and
    incremented references, applies position offsets, and appends to
    the schematic.

    Args:
        op: DuplicateComponentOp with source_reference, offset, and count.
        ir: SchematicIR wrapping the parsed schematic.

    Returns:
        Dict with list of created components (each with reference and uuid).

    Raises:
        DuplicateComponentError: If source component is not found.
    """
    # Find source component
    source = ir.get_component_by_ref(op.source_reference)
    if source is None:
        raise DuplicateComponentError(
            f"Component not found: {op.source_reference!r}"
        )

    # Collect all existing references for collision avoidance
    all_references = _collect_all_references(ir)

    created = []
    for i in range(op.count):
        # Compute new reference
        new_ref = _increment_reference(op.source_reference, all_references)
        all_references.add(new_ref)

        # Compute position with offset
        if op.offset is not None:
            offset_multiplier = i + 1
            new_position = Position(
                X=source.position.X + op.offset.x * offset_multiplier,
                Y=source.position.Y + op.offset.y * offset_multiplier,
                angle=source.position.angle,
            )
        else:
            new_position = None

        # Create deep copy with fresh UUIDs
        new_symbol = _deep_copy_symbol(source, new_ref, new_position)

        # Append to schematicSymbols list
        ir._parse_result.kiutils_obj.schematicSymbols.append(new_symbol)

        created.append({
            "reference": new_ref,
            "uuid": new_symbol.uuid,
        })

    # Record mutation for audit trail
    ir._record_mutation(
        "duplicate_component",
        {
            "source_reference": op.source_reference,
            "count": op.count,
            "created_references": [c["reference"] for c in created],
        },
    )

    return {
        "source_reference": op.source_reference,
        "created": created,
    }
