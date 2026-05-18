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

    # Record mutation for audit trail
    ir._record_mutation(
        "add_component",
        {
            "reference": op.reference,
            "library_id": op.library_id,
            "uuid": str(new_uuid),
        },
    )

    return {
        "reference": op.reference,
        "library_id": op.library_id,
        "uuid": str(new_uuid),
        "position": {"x": op.position.x, "y": op.position.y, "angle": op.position.angle},
    }
