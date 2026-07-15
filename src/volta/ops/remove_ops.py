"""Remove operation handlers -- remove_wire, remove_label, remove_junction, remove_no_connect.

Provides list-filter removal with dangling-endpoint safety checks for wires.
Follows the pattern established in remove_component.py.

Security (threat model):
- T-04-03: UUID must match existing element exactly -- no wildcard or pattern deletion.
- Wire adjacency: refuses removal that would leave an endpoint dangling
  (no pin, junction, label, or remaining wire at that position).

Usage:
    from volta.ops.remove_ops import remove_wire, remove_label, remove_junction, remove_no_connect

    result = remove_wire(op, ir, file_path, base_dir)
"""

from pathlib import Path
from typing import Any

# Coordinate tolerance for endpoint matching (mm)
_ENDPOINT_TOLERANCE = 0.0001


class RemoveOpError(Exception):
    """Error raised when a remove operation fails."""


def remove_wire(
    op: Any,
    ir: Any,
    file_path: Path,
    base_dir: Path,
) -> dict[str, Any]:
    """Remove a wire segment by UUID with dangling-endpoint safety check.

    Checks both endpoints before removal. If an endpoint would have no
    remaining wire, pin, junction, or label connection after removal,
    raises RemoveOpError to prevent creating a dangling endpoint.

    Args:
        op: RemoveWireOp with target UUID.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Resolved path to the target schematic file.
        base_dir: Base directory for the project.

    Returns:
        Dict with success status, UUID, and op_type.

    Raises:
        RemoveOpError: If wire not found or removal would create dangling endpoint.
    """
    wire = ir.get_wire_by_uuid(op.uuid)
    if wire is None:
        raise RemoveOpError(f"Wire not found: {op.uuid!r}")

    if len(wire.points) < 2:
        raise RemoveOpError(f"Wire {op.uuid!r} has fewer than 2 points")

    start_x, start_y = wire.points[0].X, wire.points[0].Y
    end_x, end_y = wire.points[1].X, wire.points[1].Y

    # Check both endpoints for dangling connections AFTER removal
    for ep_x, ep_y, ep_name in [
        (start_x, start_y, "start"),
        (end_x, end_y, "end"),
    ]:
        if not _has_remaining_connection(ir, wire, ep_x, ep_y):
            raise RemoveOpError(
                f"Removing wire {op.uuid!r} would leave {ep_name} endpoint "
                f"({ep_x}, {ep_y}) dangling -- no pin, junction, label, "
                f"or remaining wire at that position"
            )

    # Remove from graphicalItems using identity check
    sch = ir._parse_result.kiutils_obj
    sch.graphicalItems = [
        item for item in sch.graphicalItems if item is not wire
    ]

    ir._record_mutation("remove_wire", {"uuid": op.uuid})

    return {"success": True, "uuid": op.uuid, "op_type": op.op_type}


def remove_label(
    op: Any,
    ir: Any,
    file_path: Path,
    base_dir: Path,
) -> dict[str, Any]:
    """Remove a net label by UUID and label_type.

    Dispatches to the correct label list (labels, globalLabels,
    hierarchicalLabels) based on the label_type field.

    Args:
        op: RemoveLabelOp with target UUID and label_type.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Resolved path to the target schematic file.
        base_dir: Base directory for the project.

    Returns:
        Dict with success status, UUID, and op_type.

    Raises:
        RemoveOpError: If label not found in the specified list.
    """
    sch = ir._parse_result.kiutils_obj

    label = ir.get_label_by_uuid(op.uuid)
    if label is None:
        raise RemoveOpError(f"Label not found: {op.uuid!r}")

    # Determine which list to filter based on label_type
    if op.label_type == "global":
        target_list = sch.globalLabels
    elif op.label_type == "hierarchical":
        target_list = sch.hierarchicalLabels
    else:
        target_list = sch.labels

    # Remove using identity check
    if op.label_type == "global":
        sch.globalLabels = [l for l in sch.globalLabels if l is not label]
    elif op.label_type == "hierarchical":
        sch.hierarchicalLabels = [l for l in sch.hierarchicalLabels if l is not label]
    else:
        sch.labels = [l for l in sch.labels if l is not label]

    ir._record_mutation(
        "remove_label",
        {"uuid": op.uuid, "label_type": op.label_type},
    )

    return {"success": True, "uuid": op.uuid, "op_type": op.op_type}


def remove_junction(
    op: Any,
    ir: Any,
    file_path: Path,
    base_dir: Path,
) -> dict[str, Any]:
    """Remove a junction dot by UUID.

    Args:
        op: RemoveJunctionOp with target UUID.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Resolved path to the target schematic file.
        base_dir: Base directory for the project.

    Returns:
        Dict with success status, UUID, and op_type.

    Raises:
        RemoveOpError: If junction not found.
    """
    junction = ir.get_junction_by_uuid(op.uuid)
    if junction is None:
        raise RemoveOpError(f"Junction not found: {op.uuid!r}")

    sch = ir._parse_result.kiutils_obj
    sch.junctions = [j for j in sch.junctions if j is not junction]

    ir._record_mutation("remove_junction", {"uuid": op.uuid})

    return {"success": True, "uuid": op.uuid, "op_type": op.op_type}


def remove_no_connect(
    op: Any,
    ir: Any,
    file_path: Path,
    base_dir: Path,
) -> dict[str, Any]:
    """Remove a no-connect flag by UUID.

    Args:
        op: RemoveNoConnectOp with target UUID.
        ir: SchematicIR wrapping the parsed schematic.
        file_path: Resolved path to the target schematic file.
        base_dir: Base directory for the project.

    Returns:
        Dict with success status, UUID, and op_type.

    Raises:
        RemoveOpError: If no-connect not found.
    """
    no_connect = ir.get_no_connect_by_uuid(op.uuid)
    if no_connect is None:
        raise RemoveOpError(f"No-connect not found: {op.uuid!r}")

    sch = ir._parse_result.kiutils_obj
    sch.noConnects = [nc for nc in sch.noConnects if nc is not no_connect]

    ir._record_mutation("remove_no_connect", {"uuid": op.uuid})

    return {"success": True, "uuid": op.uuid, "op_type": op.op_type}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _has_remaining_connection(
    ir: Any,
    wire_to_remove: Any,
    x: float,
    y: float,
) -> bool:
    """Check if a position has a remaining connection after wire removal.

    A connection exists if any of the following are at (x, y) within tolerance:
    - A component pin
    - A junction
    - A label (local, global, or hierarchical)
    - A remaining wire (other than wire_to_remove)

    Args:
        ir: SchematicIR wrapping the parsed schematic.
        wire_to_remove: The wire being removed (excluded from adjacency check).
        x: X coordinate of the endpoint.
        y: Y coordinate of the endpoint.

    Returns:
        True if at least one connection remains at the position.
    """
    tol = _ENDPOINT_TOLERANCE

    # Check pins
    for pin in ir.get_pin_positions():
        if abs(pin["x"] - x) <= tol and abs(pin["y"] - y) <= tol:
            return True

    # Check junctions
    for jct in ir._parse_result.kiutils_obj.junctions:
        if abs(jct.position.X - x) <= tol and abs(jct.position.Y - y) <= tol:
            return True

    # Check labels (local, global, hierarchical)
    for label in ir._parse_result.kiutils_obj.labels:
        if abs(label.position.X - x) <= tol and abs(label.position.Y - y) <= tol:
            return True

    for label in ir._parse_result.kiutils_obj.globalLabels:
        if abs(label.position.X - x) <= tol and abs(label.position.Y - y) <= tol:
            return True

    for label in ir._parse_result.kiutils_obj.hierarchicalLabels:
        if abs(label.position.X - x) <= tol and abs(label.position.Y - y) <= tol:
            return True

    # Check remaining wires (excluding the one being removed)
    from kiutils.items.schitems import Connection

    for item in ir._parse_result.kiutils_obj.graphicalItems:
        if not isinstance(item, Connection) or item.type != "wire":
            continue
        if item is wire_to_remove:
            continue
        if len(item.points) < 2:
            continue
        for pt in item.points:
            if abs(pt.X - x) <= tol and abs(pt.Y - y) <= tol:
                return True

    return False
