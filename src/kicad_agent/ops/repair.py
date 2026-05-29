"""Schematic ERC repair operations -- auto-fix common ERC errors.

Provides wire snapping, orphaned label removal, shorted net detection,
and no-connect marker placement. These address the most common ERC error
sources identified from real-world KiCad projects.

T-10-09: Snap distance limited to 0.01mm tolerance.
T-10-11: Pin Y-inversion uses (sx+px, sy-py) pattern.

Usage:
    from kicad_agent.ops.repair import repair_wire_snapping

    result = repair_wire_snapping(ir, file_path)
    print(f"Snapped {result['snapped_count']} wires")
"""

import logging
import math
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)

# Maximum distance (mm) to snap a wire endpoint to a pin.
# T-10-09: Bounded to prevent wires from jumping across the board.
SNAP_TOLERANCE = 0.01


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def repair_wire_snapping(ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Snap wire endpoints to the nearest pin position within tolerance.

    For each wire in the schematic, checks if start/end points are within
    SNAP_TOLERANCE of a pin position. If not snapped, adjusts the wire
    endpoint to the nearest pin position.

    Pin positions use the Y-inversion pattern: absolute = (sx+px, sy-py).
    See SchematicIR.get_pin_positions() for rotation handling.

    T-10-09: Snap distance limited to SNAP_TOLERANCE (0.01mm).

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the schematic file (for logging).

    Returns:
        Dict with snapped_count and unchanged_count.
    """
    pin_positions = ir.get_pin_positions()
    if not pin_positions:
        return {"snapped_count": 0, "unchanged_count": 0}

    # Build a list of (x, y) tuples for fast nearest-point lookup
    pins_xy = [(p["x"], p["y"]) for p in pin_positions]

    wire_endpoints = ir.get_wire_endpoints()
    snapped_count = 0
    unchanged_count = 0

    sch = ir.schematic

    # Map wire_index -> wire object from graphicalItems
    for wire_info in wire_endpoints:
        wire_idx = wire_info["wire_index"]
        wire = sch.graphicalItems[wire_idx]

        if not hasattr(wire, "points") or len(wire.points) < 2:
            unchanged_count += 1
            continue

        modified = False

        # Check start point
        sx, sy = wire.points[0].X, wire.points[0].Y
        nearest_pin = _find_nearest_pin(sx, sy, pins_xy, SNAP_TOLERANCE)
        if nearest_pin is not None and _distance(sx, sy, nearest_pin[0], nearest_pin[1]) > 0:
            wire.points[0].X = nearest_pin[0]
            wire.points[0].Y = nearest_pin[1]
            modified = True

        # Check end point
        ex, ey = wire.points[1].X, wire.points[1].Y
        nearest_pin = _find_nearest_pin(ex, ey, pins_xy, SNAP_TOLERANCE)
        if nearest_pin is not None and _distance(ex, ey, nearest_pin[0], nearest_pin[1]) > 0:
            wire.points[1].X = nearest_pin[0]
            wire.points[1].Y = nearest_pin[1]
            modified = True

        if modified:
            snapped_count += 1
            ir._record_mutation("repair_wire_snap", {
                "wire_uuid": wire_info.get("uuid", ""),
            })
        else:
            unchanged_count += 1

    return {"snapped_count": snapped_count, "unchanged_count": unchanged_count}


def remove_orphaned_labels(ir: SchematicIR) -> dict[str, Any]:
    """Remove labels not connected to any wire endpoint or pin.

    An orphaned label has no wire endpoint or pin position within 0.01mm
    of its position.

    Args:
        ir: SchematicIR for the target schematic.

    Returns:
        Dict with removed (list of removed label names) and kept (count).
    """
    wire_endpoints = ir.get_wire_endpoints()
    pin_positions = ir.get_pin_positions()

    # Collect all "connected" positions: wire start/end and pin positions
    connected_positions: list[tuple[float, float]] = []
    for we in wire_endpoints:
        connected_positions.append((we["start_x"], we["start_y"]))
        connected_positions.append((we["end_x"], we["end_y"]))
    for pp in pin_positions:
        connected_positions.append((pp["x"], pp["y"]))

    label_positions = ir.get_label_positions()
    removed_names: list[str] = []
    kept_count = 0

    sch = ir.schematic

    # Check local labels
    labels_to_keep: list = []
    for label in sch.labels:
        if _is_position_connected(label.position.X, label.position.Y, connected_positions):
            labels_to_keep.append(label)
            kept_count += 1
        else:
            removed_names.append(label.text)
            ir._record_mutation("remove_orphaned_label", {
                "name": label.text,
                "position": [label.position.X, label.position.Y],
            })

    sch.labels[:] = labels_to_keep

    # Check global labels
    global_to_keep: list = []
    for label in sch.globalLabels:
        if _is_position_connected(label.position.X, label.position.Y, connected_positions):
            global_to_keep.append(label)
            kept_count += 1
        else:
            removed_names.append(label.text)
            ir._record_mutation("remove_orphaned_label", {
                "name": label.text,
                "position": [label.position.X, label.position.Y],
            })

    sch.globalLabels[:] = global_to_keep

    return {"removed": removed_names, "kept": kept_count}


def detect_shorted_nets(ir: SchematicIR) -> dict[str, Any]:
    """Find junction points where wires from different named nets overlap.

    Detects positions where two wires on different named nets share a
    common coordinate (within 0.01mm tolerance). This indicates a
    short circuit.

    Args:
        ir: SchematicIR for the target schematic.

    Returns:
        Dict with shorts (list of {position, nets}) and clean (bool).
    """
    label_positions = ir.get_label_positions()
    wire_endpoints = ir.get_wire_endpoints()

    # Map positions to net names via labels
    # A wire inherits the net name of any label at its endpoints
    pos_to_nets: dict[tuple[float, float], set[str]] = {}

    for label in label_positions:
        key = _round_pos(label["x"], label["y"])
        pos_to_nets.setdefault(key, set()).add(label["name"])

    # For each wire, propagate net names through connected endpoints
    # Build adjacency: wire endpoints that share coordinates are connected
    endpoint_to_wires: dict[tuple[float, float], list[int]] = {}
    wire_endpoints_map: dict[int, dict] = {}
    for we in wire_endpoints:
        wi = we["wire_index"]
        start_key = _round_pos(we["start_x"], we["start_y"])
        end_key = _round_pos(we["end_x"], we["end_y"])
        endpoint_to_wires.setdefault(start_key, []).append(wi)
        endpoint_to_wires.setdefault(end_key, []).append(wi)
        wire_endpoints_map[wi] = we

    # Propagate net names through wire connectivity using union-find.
    # Build connected components of positions linked by wires, then merge
    # all net names within each connected component.
    # Map each position to a canonical representative (union-find).
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def _find(pos: tuple[float, float]) -> tuple[float, float]:
        while parent.get(pos, pos) != pos:
            parent[pos] = parent.get(parent[pos], parent[pos])
            pos = parent[pos]
        return pos

    def _union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    # Union wire start/end positions (each wire connects its two endpoints)
    for we in wire_endpoints:
        start_key = _round_pos(we["start_x"], we["start_y"])
        end_key = _round_pos(we["end_x"], we["end_y"])
        _union(start_key, end_key)

    # Merge net names across connected positions
    # First, collect all positions that have labels into their components
    component_nets: dict[tuple[float, float], set[str]] = {}
    for pos_key, nets in pos_to_nets.items():
        root = _find(pos_key)
        component_nets.setdefault(root, set()).update(nets)

    # Also propagate: for each label position, find its connected component
    # and check if any other label in the same component has a different name
    for pos_key in pos_to_nets:
        root = _find(pos_key)
        component_nets.setdefault(root, set()).update(pos_to_nets[pos_key])

    # Shorts: components where multiple different net names are connected
    shorts: list[dict[str, Any]] = []

    # 1. Same-position shorts (labels at exact same coordinates)
    for pos_key, nets in pos_to_nets.items():
        if len(nets) > 1:
            net_list = sorted(nets)
            shorts.append({
                "position": (round(pos_key[0], 4), round(pos_key[1], 4)),
                "nets": net_list,
            })

    # 2. Wire-connected shorts (different net labels connected via wire path)
    seen_shorts: set[frozenset[str]] = {
        frozenset(s["nets"]) for s in shorts
    }
    for root, nets in component_nets.items():
        if len(nets) > 1:
            key = frozenset(nets)
            if key not in seen_shorts:
                net_list = sorted(nets)
                shorts.append({
                    "position": (round(root[0], 4), round(root[1], 4)),
                    "nets": net_list,
                })
                seen_shorts.add(key)

    return {"shorts": shorts, "clean": len(shorts) == 0}


def place_no_connects(ir: SchematicIR) -> dict[str, Any]:
    """Place no-connect markers on unconnected pins.

    Finds pins with no wire endpoint or label within 0.01mm and places
    a no-connect marker at each pin position.

    Args:
        ir: SchematicIR for the target schematic.

    Returns:
        Dict with placed (count) and positions (list of (x,y) tuples).
    """
    pin_positions = ir.get_pin_positions()
    wire_endpoints = ir.get_wire_endpoints()
    label_positions_list = ir.get_label_positions()
    sch = ir.schematic

    # Collect connected positions
    connected: list[tuple[float, float]] = []
    for we in wire_endpoints:
        connected.append((we["start_x"], we["start_y"]))
        connected.append((we["end_x"], we["end_y"]))
    for lp in label_positions_list:
        connected.append((lp["x"], lp["y"]))

    # Also check existing no-connect positions to avoid duplicates
    existing_nc: set[tuple[float, float]] = set()
    for nc in sch.noConnects:
        existing_nc.add(_round_pos(nc.position.X, nc.position.Y))

    placed_count = 0
    placed_positions: list[tuple[float, float]] = []

    for pin in pin_positions:
        px, py = pin["x"], pin["y"]
        pos_key = _round_pos(px, py)

        # Skip if already has a no-connect marker
        if pos_key in existing_nc:
            continue

        # Skip if connected to a wire or label
        if _is_position_connected(px, py, connected):
            continue

        # Place no-connect marker
        ir.add_no_connect(x=px, y=py)
        placed_count += 1
        placed_positions.append((round(px, 4), round(py, 4)))

    return {"placed": placed_count, "positions": placed_positions}


def _find_nearest_pin(
    x: float, y: float, pins_xy: list[tuple[float, float]], tolerance: float
) -> tuple[float, float] | None:
    """Find the nearest pin position within tolerance.

    Args:
        x: X coordinate to check.
        y: Y coordinate to check.
        pins_xy: List of (x, y) pin positions.
        tolerance: Maximum distance in mm.

    Returns:
        Nearest (x, y) pin position within tolerance, or None.
    """
    best_dist = tolerance
    best_pin = None

    for px, py in pins_xy:
        d = _distance(x, y, px, py)
        if d < best_dist:
            best_dist = d
            best_pin = (px, py)

    return best_pin


def _is_position_connected(
    x: float, y: float, connected_positions: list[tuple[float, float]],
) -> bool:
    """Check if a position is within SNAP_TOLERANCE of any connected position.

    Args:
        x: X coordinate to check.
        y: Y coordinate to check.
        connected_positions: List of (x, y) positions to check against.

    Returns:
        True if within tolerance of any connected position.
    """
    for cx, cy in connected_positions:
        if _distance(x, y, cx, cy) <= SNAP_TOLERANCE:
            return True
    return False


def _round_pos(x: float, y: float) -> tuple[float, float]:
    """Round position to SNAP_TOLERANCE precision for grouping."""
    precision = 2  # 0.01mm precision
    return (round(x, precision), round(y, precision))


# ---------------------------------------------------------------------------
# ERC-driven repair operations (Phase 23)
# ---------------------------------------------------------------------------


def snap_to_grid(ir: SchematicIR, grid_mm: float = 0.01) -> dict[str, Any]:
    """Snap off-grid wire endpoints to the nearest grid point.

    Groups wire endpoints by proximity first so that co-located endpoints
    (where two wires meet at an off-grid point) all snap to the SAME grid
    point, preserving connectivity.

    SCHREPAIR-05: Grid-snapping for off-grid wire endpoints.

    Args:
        ir: SchematicIR for the target schematic.
        grid_mm: Grid spacing in mm (default 0.01 for KiCad 8+).

    Returns:
        Dict with snapped_count and grid_mm.
    """
    from kicad_agent.validation.grid_check import _is_on_grid

    sch = ir.schematic
    wire_endpoints = ir.get_wire_endpoints()
    if not wire_endpoints:
        return {"snapped_count": 0, "grid_mm": grid_mm}

    # First pass: collect all endpoint positions and their wire/point references
    endpoint_groups: dict[tuple[float, float], list[tuple[int, int]]] = {}
    # key = rounded position, value = list of (wire_index, point_index)

    for wire_info in wire_endpoints:
        wi = wire_info["wire_index"]
        wire = sch.graphicalItems[wi]
        if not hasattr(wire, "points"):
            continue
        for pi, point in enumerate(wire.points):
            key = (round(point.X, 2), round(point.Y, 2))
            endpoint_groups.setdefault(key, []).append((wi, pi))

    # Second pass: for each group, compute shared snap target and apply
    snapped_count = 0
    for key, refs in endpoint_groups.items():
        x, y = key
        if not _is_on_grid(x, grid_mm) or not _is_on_grid(y, grid_mm):
            snap_x = round(x / grid_mm) * grid_mm
            snap_y = round(y / grid_mm) * grid_mm
            for wi, pi in refs:
                wire = sch.graphicalItems[wi]
                wire.points[pi].X = snap_x
                wire.points[pi].Y = snap_y
            snapped_count += 1
            ir._record_mutation("snap_to_grid", {
                "group_at": [x, y],
                "snapped_to": [snap_x, snap_y],
            })

    return {"snapped_count": snapped_count, "grid_mm": grid_mm}


def add_power_flags(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Place PWR_FLAG symbols at power_pin_not_driven ERC violation positions.

    SCHREPAIR-06: ERC-driven power flag placement.

    Args:
        ir: SchematicIR for the target schematic.
        sch_path: Path to the schematic file (for ERC invocation).

    Returns:
        Dict with placed count, positions, skipped count, and net names.
    """
    from kicad_agent.ops.erc_parser import extract_violation_positions

    positions = extract_violation_positions(sch_path, "power_pin_not_driven")
    if not positions:
        return {"placed": 0, "positions": [], "skipped": 0, "net_names": []}

    # Get label positions to determine net names at violation points
    label_positions = ir.get_label_positions()
    placed_count = 0
    skipped_count = 0
    placed_positions: list[tuple[float, float]] = []
    net_names: list[str] = []

    for vp in positions:
        # Find which label is at or near this position
        net_name = _find_net_name_at_position(vp.x, vp.y, label_positions)
        if net_name is None:
            logger.warning(
                "Could not determine net name at (%.2f, %.2f), skipping power flag",
                vp.x, vp.y,
            )
            skipped_count += 1
            continue

        # Place PWR_FLAG offset to the right to avoid overlapping
        offset_x = vp.x + 2.54
        offset_y = vp.y
        ir.add_power_symbol("PWR_FLAG", offset_x, offset_y, 0.0)
        placed_count += 1
        placed_positions.append((round(offset_x, 4), round(offset_y, 4)))
        net_names.append(net_name)
        ir._record_mutation("add_power_flag", {
            "net_name": net_name,
            "position": [offset_x, offset_y],
        })

    return {
        "placed": placed_count,
        "positions": placed_positions,
        "skipped": skipped_count,
        "net_names": net_names,
    }


def place_no_connects_from_erc(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Place no-connect markers at pin_not_connected ERC violation positions.

    SCHREPAIR-07: ERC-driven no-connect placement.

    Args:
        ir: SchematicIR for the target schematic.
        sch_path: Path to the schematic file (for ERC invocation).

    Returns:
        Dict with placed count, skipped duplicates count, and positions.
    """
    from kicad_agent.ops.erc_parser import extract_violation_positions

    positions = extract_violation_positions(sch_path, "pin_not_connected")
    if not positions:
        return {"placed": 0, "skipped_duplicates": 0, "positions": []}

    # Check existing no-connect positions to avoid duplicates
    sch = ir.schematic
    existing_nc: set[tuple[float, float]] = set()
    for nc in sch.noConnects:
        existing_nc.add((round(nc.position.X, 2), round(nc.position.Y, 2)))

    placed_count = 0
    dup_count = 0
    placed_positions: list[tuple[float, float]] = []

    for vp in positions:
        pos_key = (round(vp.x, 2), round(vp.y, 2))
        if pos_key in existing_nc:
            dup_count += 1
            continue

        ir.add_no_connect(x=vp.x, y=vp.y)
        placed_count += 1
        placed_positions.append((round(vp.x, 4), round(vp.y, 4)))
        # Add to existing set to prevent duplicates within this batch
        existing_nc.add(pos_key)

    return {
        "placed": placed_count,
        "skipped_duplicates": dup_count,
        "positions": placed_positions,
    }


def _find_net_name_at_position(
    x: float,
    y: float,
    label_positions: list[dict[str, Any]],
    tolerance: float = 0.01,
) -> str | None:
    """Find the net label name at or near a given position.

    Args:
        x: X coordinate to search.
        y: Y coordinate to search.
        label_positions: List of label position dicts from get_label_positions().
        tolerance: Maximum distance in mm for a match.

    Returns:
        Net name string if found, None otherwise.
    """
    for lp in label_positions:
        if _distance(x, y, lp["x"], lp["y"]) <= tolerance:
            return lp["name"]
    return None
