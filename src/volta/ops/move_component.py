"""Move component operation handler.

Moves a SchematicSymbol to a new position with correct decimal precision
(4 for schematics, 6 for PCB). Records mutation with old and new positions.

Security (threat model):
- T-04-15: Precision rounding prevents accumulated floating-point drift
- T-04-14: Out-of-bounds coordinates are KiCad's concern, not ours

Usage:
    from volta.ops.move_component import move_component, MoveComponentError

    op = MoveComponentOp(
        target_file="schematic.kicad_sch",
        reference="J1",
        position=PositionSpec(x=100.0, y=75.0),
    )
    result = move_component(op, ir)
"""

from typing import Any

from volta.ops.schema import MoveComponentOp


# Coordinate precision constants (T-04-15)
SCHEMATIC_DECIMALS = 4
PCB_DECIMALS = 6


class MoveComponentError(Exception):
    """Error raised when move_component operation fails."""


def move_component(
    op: MoveComponentOp,
    ir: Any,
    file_type: str = "schematic",
) -> dict[str, Any]:
    """Move a component to a new position with correct decimal precision.

    T-04-15: Coordinates are rounded to the correct number of decimal
    places (4 for schematics, 6 for PCB) to prevent floating-point drift.

    Args:
        op: MoveComponentOp with reference and target position.
        ir: SchematicIR wrapping the parsed schematic.
        file_type: File type for precision selection ("schematic" or "pcb").

    Returns:
        Dict with reference, old_position, and new_position.

    Raises:
        MoveComponentError: If component with given reference is not found.
    """
    # Find component by reference
    component = ir.get_component_by_ref(op.reference)
    if component is None:
        raise MoveComponentError(
            f"Component not found: {op.reference!r}"
        )

    # Determine decimal precision based on file type
    precision = SCHEMATIC_DECIMALS if file_type == "schematic" else PCB_DECIMALS

    # Record old position before mutation
    old_position = {
        "x": component.position.X,
        "y": component.position.Y,
        "angle": component.position.angle,
    }

    # Compute new position with precision rounding (T-04-15)
    new_x = round(op.position.x, precision)
    new_y = round(op.position.y, precision)
    # KiCad convention: angle=None when 0.0 (omits angle token in S-expression)
    new_angle = op.position.angle if op.position.angle != 0.0 else None

    # Mutate position on the component
    component.position.X = new_x
    component.position.Y = new_y
    component.position.angle = new_angle

    new_position = {"x": new_x, "y": new_y, "angle": new_angle}

    # Record mutation for audit trail
    ir._record_mutation(
        "move_component",
        {
            "reference": op.reference,
            "old_position": old_position,
            "new_position": new_position,
        },
    )

    return {
        "reference": op.reference,
        "old_position": old_position,
        "new_position": new_position,
    }
