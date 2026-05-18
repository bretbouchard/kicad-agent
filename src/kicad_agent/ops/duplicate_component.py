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

from typing import Any

from kiutils.items.common import Position

from kicad_agent.ops._symbol_utils import (
    collect_all_references,
    deep_copy_symbol,
    increment_reference,
)
from kicad_agent.ops.schema import DuplicateComponentOp


class DuplicateComponentError(Exception):
    """Error raised when duplicate_component operation fails."""


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
    all_references = collect_all_references(ir)

    created = []
    for i in range(op.count):
        # Compute new reference
        new_ref = increment_reference(op.source_reference, all_references)
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
        new_symbol = deep_copy_symbol(source, new_ref, new_position)

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
