"""Array replicate operation handler.

Replicates a component in linear, circular, or matrix array patterns.
Each replica gets fresh UUIDs and incremented references.

Security (threat model):
- T-04-07: count constrained to max 100 via Pydantic Field (DoS mitigation)
- T-04-10: Fresh UUIDs generated via uuid.uuid4() for symbol and pins
- T-04-09: Floating-point precision in cos/sin is acceptable for placement

Usage:
    from kicad_agent.ops.array_replicate import array_replicate, ArrayReplicateError

    op = ArrayReplicateOp(
        target_file="schematic.kicad_sch",
        source_reference="R1",
        pattern="linear",
        count=5,
        spacing=PositionSpec(x=10.0, y=0.0),
    )
    result = array_replicate(op, ir)
"""

import math
import uuid
from typing import Any

from kiutils.items.common import Position
from kiutils.items.schitems import SchematicSymbol

from kicad_agent.ops.schema import ArrayReplicateOp


class ArrayReplicateError(Exception):
    """Error raised when array_replicate operation fails."""


def _linear_positions(
    source_pos: Position,
    count: int,
    spacing_x: float,
    spacing_y: float,
) -> list[Position]:
    """Generate positions for linear array.

    Each position is source + spacing * (i + 1) for i in range(count).

    Args:
        source_pos: Source component position.
        count: Number of replicas.
        spacing_x: X spacing between replicas.
        spacing_y: Y spacing between replicas.

    Returns:
        List of Position objects for each replica.
    """
    positions = []
    for i in range(1, count + 1):
        positions.append(Position(
            X=source_pos.X + spacing_x * i,
            Y=source_pos.Y + spacing_y * i,
            angle=source_pos.angle,
        ))
    return positions


def _circular_positions(
    source_pos: Position,
    count: int,
    center_x: float,
    center_y: float,
    angle_step: float,
) -> list[Position]:
    """Generate positions for circular array.

    Rotates the source position around the center point by angle_step
    for each replica.

    Args:
        source_pos: Source component position.
        count: Number of replicas.
        center_x: Center point X coordinate.
        center_y: Center point Y coordinate.
        angle_step: Degrees per step.

    Returns:
        List of Position objects for each replica.
    """
    dx = source_pos.X - center_x
    dy = source_pos.Y - center_y

    positions = []
    for i in range(1, count + 1):
        angle_rad = math.radians(angle_step * i)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        new_x = center_x + dx * cos_a - dy * sin_a
        new_y = center_y + dx * sin_a + dy * cos_a
        positions.append(Position(
            X=new_x,
            Y=new_y,
            angle=source_pos.angle,
        ))
    return positions


def _matrix_positions(
    source_pos: Position,
    rows: int,
    cols: int,
    spacing_x: float,
    spacing_y: float,
) -> list[Position]:
    """Generate positions for matrix array.

    Creates a rows x cols grid starting from source position.
    The source occupies (0, 0), so only non-origin positions are returned.

    Args:
        source_pos: Source component position.
        rows: Number of rows.
        cols: Number of columns.
        spacing_x: Column spacing (x direction).
        spacing_y: Row spacing (y direction).

    Returns:
        List of Position objects for each replica (excluding source).
    """
    positions = []
    for row in range(rows):
        for col in range(cols):
            # Skip the source position (0, 0)
            if row == 0 and col == 0:
                continue
            positions.append(Position(
                X=source_pos.X + col * spacing_x,
                Y=source_pos.Y + row * spacing_y,
                angle=source_pos.angle,
            ))
    return positions


def _deep_copy_symbol(
    symbol: SchematicSymbol,
    new_reference: str,
    new_position: Position,
) -> SchematicSymbol:
    """Create a deep copy of a SchematicSymbol with fresh UUIDs.

    T-04-10: Generates fresh UUIDs for the symbol and all pins.

    Args:
        symbol: Source SchematicSymbol to copy.
        new_reference: New reference designator.
        new_position: New position for the copy.

    Returns:
        New SchematicSymbol with fresh UUIDs and updated reference/position.
    """
    from kiutils.items.common import Property
    from kiutils.items.schitems import SymbolProjectInstance, SymbolProjectPath

    # Generate fresh UUID for the symbol
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
        position=new_position,
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

    Args:
        source_reference: The source component's reference.
        all_references: Set of all existing references.

    Returns:
        The next available reference string.
    """
    import re

    match = re.match(r"^([A-Za-z]+)(\d*)$", source_reference)
    if not match:
        return source_reference

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


def array_replicate(
    op: ArrayReplicateOp,
    ir: Any,
) -> dict[str, Any]:
    """Replicate a component in a linear, circular, or matrix array pattern.

    Validates pattern-specific parameters, generates positions, and creates
    deep copies of the source component at each position.

    Args:
        op: ArrayReplicateOp with pattern, count, spacing, and pattern-specific params.
        ir: SchematicIR wrapping the parsed schematic.

    Returns:
        Dict with pattern type, list of created components (each with reference and uuid).

    Raises:
        ArrayReplicateError: If source not found or pattern parameters are invalid.
    """
    # Find source component
    source = ir.get_component_by_ref(op.source_reference)
    if source is None:
        raise ArrayReplicateError(
            f"Component not found: {op.source_reference!r}"
        )

    # Validate pattern-specific parameters and generate positions
    if op.pattern == "linear":
        positions = _linear_positions(
            source.position, op.count, op.spacing.x, op.spacing.y,
        )
    elif op.pattern == "circular":
        if op.center is None:
            raise ArrayReplicateError(
                "Circular pattern requires 'center' parameter"
            )
        if op.angle_step is None:
            raise ArrayReplicateError(
                "Circular pattern requires 'angle_step' parameter"
            )
        positions = _circular_positions(
            source.position, op.count,
            op.center.x, op.center.y, op.angle_step,
        )
    elif op.pattern == "matrix":
        if op.rows is None:
            raise ArrayReplicateError(
                "Matrix pattern requires 'rows' parameter"
            )
        if op.cols is None:
            raise ArrayReplicateError(
                "Matrix pattern requires 'cols' parameter"
            )
        positions = _matrix_positions(
            source.position, op.rows, op.cols,
            op.spacing.x, op.spacing.y,
        )
    else:
        raise ArrayReplicateError(
            f"Unknown pattern: {op.pattern!r}"
        )

    # Collect all existing references for collision avoidance
    all_references = _collect_all_references(ir)

    created = []
    for position in positions:
        # Generate unique reference
        new_ref = _increment_reference(op.source_reference, all_references)
        all_references.add(new_ref)

        # Create deep copy with fresh UUIDs
        new_symbol = _deep_copy_symbol(source, new_ref, position)

        # Append to schematicSymbols list
        ir._parse_result.kiutils_obj.schematicSymbols.append(new_symbol)

        created.append({
            "reference": new_ref,
            "uuid": new_symbol.uuid,
        })

    # Record mutation for audit trail
    ir._record_mutation(
        "array_replicate",
        {
            "source_reference": op.source_reference,
            "pattern": op.pattern,
            "count": len(created),
            "created_references": [c["reference"] for c in created],
        },
    )

    return {
        "source_reference": op.source_reference,
        "pattern": op.pattern,
        "created": created,
    }
