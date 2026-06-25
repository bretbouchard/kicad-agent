"""ERC repair operations -- no-connects, power flags, labels, junctions, checkpoints.

Provides ERC-driven repair functions for schematic auto-fix:
- Orphaned label removal
- No-connect marker placement (general and ERC-driven)
- Power flag placement
- Junction placement at label intersections
- IR checkpoint/restore for atomic operations
"""

import logging
import math
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.schematic_routing.net_extractor import NetPositionIndex

logger = logging.getLogger(__name__)


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _lookup_pin_type_with_tolerance(
    x: float,
    y: float,
    pin_positions: list[dict[str, Any]],
    tolerance: float,
) -> str:
    """Find pin electrical type at (x, y) within tolerance. Default "passive".

    Replaces exact dict-key lookup which fails when ERC violation positions
    and pin positions differ by sub-micron precision that rounds to different
    2-decimal keys. Uses the same SNAP_TOLERANCE pattern as _near_anchor.

    P0-004 fix: see BUGS/P0-004-place-no-connects-from-erc-wrong-positions.md.
    The previous code built pos_to_type with round(p["x"], 2) keys; a pin at
    x=127.015 (key 127.02) and violation at x=127.014 (key 127.01) missed,
    defaulting to "passive" and placing a no_connect on power_in pins.

    Args:
        x: X coordinate of the ERC violation position.
        y: Y coordinate of the ERC violation position.
        pin_positions: List of pin position dicts from ir.get_pin_positions().
        tolerance: Maximum per-axis distance in mm for a match
                   (use SNAP_TOLERANCE = 0.01).

    Returns:
        The pin's electrical_type if a match is found, else "passive"
        (same default as the old dict .get() for backward compatibility).
    """
    for p in pin_positions:
        if abs(x - p["x"]) <= tolerance and abs(y - p["y"]) <= tolerance:
            return p.get("electrical_type", "passive")
    return "passive"


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
    from kicad_agent.ops.repair_wires import SNAP_TOLERANCE

    for cx, cy in connected_positions:
        if _distance(x, y, cx, cy) <= SNAP_TOLERANCE:
            return True
    return False


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


def place_no_connects(ir: SchematicIR) -> dict[str, Any]:
    """Place no-connect markers on unconnected pins.

    Finds pins with no wire endpoint or label within 0.01mm and places
    a no-connect marker at each pin position.

    Args:
        ir: SchematicIR for the target schematic.

    Returns:
        Dict with placed (count) and positions (list of (x,y) tuples).
    """
    from kicad_agent.ops.repair_wires import (
        SNAP_TOLERANCE,
        _point_on_wire_segment,
        _round_pos,
    )

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

    # Issue #13: Also consider pin-to-pin co-location as "connected".
    # Power symbols (power:+5V, power:GND, etc.) connect to component pins
    # by sharing the same position -- no wire required. Without this check,
    # place_no_connects marks power pins as unconnected and corrupts the file.
    other_pin_positions: list[tuple[float, float]] = []
    for p in pin_positions:
        other_pin_positions.append((p["x"], p["y"]))

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

        # Skip if connected to a wire endpoint or label
        if _is_position_connected(px, py, connected):
            continue

        # Issue #4: Also skip if pin lies on a wire segment (mid-wire
        # connection). KiCad considers pins on wire midpoints connected
        # even without a wire endpoint at that position.
        if _point_on_wire_segment(px, py, wire_endpoints):
            continue

        # Issue #13: Skip if another symbol's pin is co-located at this
        # position. Power symbols (power:+5V, power:GND) connect to
        # component pins implicitly by sharing coordinates -- no wire needed.
        # Count how many pins occupy this position; if >1, it's connected.
        colocated = sum(
            1 for opx, opy in other_pin_positions
            if abs(px - opx) <= SNAP_TOLERANCE and abs(py - opy) <= SNAP_TOLERANCE
        )
        if colocated > 1:
            continue

        # Place no-connect marker
        ir.add_no_connect(x=px, y=py)
        placed_count += 1
        placed_positions.append((round(px, 4), round(py, 4)))

    return {"placed": placed_count, "positions": placed_positions}


def place_no_connects_from_erc(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Place no-connect markers at pin_not_connected ERC violation positions.

    Phase 68: Filters by pin electrical type -- skips power pins, input pins,
    and pins on power nets. Only places no_connect on safe pin types.

    Pin type safety table:
    - Always skip: power_in, power_out, input, net_in, net_out
    - Safe to no-connect: output, bidirectional, open_collector, open_emitter,
      free, passive

    Args:
        ir: SchematicIR for the target schematic.
        sch_path: Path to the schematic file (for ERC invocation).

    Returns:
        Dict with placed count, skipped counts, and positions.
    """
    from kicad_agent.ops.erc_parser import extract_violation_positions
    from kicad_agent.ops.repair_nets import _is_power_net
    from kicad_agent.ops.repair_wires import (
        SNAP_TOLERANCE,
        _near_anchor,
        _point_on_wire_segment,
        _round_pos,
    )

    positions = extract_violation_positions(sch_path, "pin_not_connected")
    if not positions:
        return {"placed": 0, "skipped_duplicates": 0, "positions": [],
                "skipped_pin_type": 0, "skipped_power_net": 0,
                "skipped_connected": 0}

    # Build pin position list from IR. Pin electrical type is looked up
    # per-violation via _lookup_pin_type_with_tolerance (P0-004 fix) — the
    # previous pos_to_type dict used round(x, 2) keys that missed sub-micron
    # precision offsets between ERC violation positions and pin positions.
    pin_positions = ir.get_pin_positions()

    # Issue #13: Build pin position list for co-location detection.
    # Power symbols connect to component pins by sharing coordinates.
    # Use tolerance-based matching (not rounding) to avoid edge cases
    # where positions 0.002mm apart round to different keys (Council HIGH-1).
    all_pin_xy: list[tuple[float, float]] = [
        (p["x"], p["y"]) for p in pin_positions
    ]

    # Try to build net index for power-net checking
    net_index: NetPositionIndex | None = None
    try:
        net_index = NetPositionIndex.from_file(sch_path)
    except Exception:
        logger.debug("Could not build NetPositionIndex for no-connect placement, skipping power-net checks")

    # Pin types that should NOT receive no_connect
    UNSAFE_PIN_TYPES = frozenset({
        "power_in", "power_out", "input", "net_in", "net_out",
    })

    # Check existing no-connect positions to avoid duplicates
    sch = ir.schematic
    existing_nc: set[tuple[float, float]] = set()
    for nc in sch.noConnects:
        existing_nc.add((round(nc.position.X, 2), round(nc.position.Y, 2)))

    # Issue #4: Build wire/label connectivity sets to avoid placing no_connects
    # on already-connected pins. A no_connect on a connected pin creates
    # no_connect_connected violations.
    wire_endpoints = ir.get_wire_endpoints()
    label_positions_list = ir.get_label_positions()
    connected_positions: set[tuple[float, float]] = set()
    for we in wire_endpoints:
        connected_positions.add((round(we["start_x"], 2), round(we["start_y"], 2)))
        connected_positions.add((round(we["end_x"], 2), round(we["end_y"], 2)))
    for lp in label_positions_list:
        connected_positions.add((round(lp["x"], 2), round(lp["y"], 2)))

    placed_count = 0
    dup_count = 0
    skipped_pin_type = 0
    skipped_power_net = 0
    skipped_connected = 0
    placed_positions: list[tuple[float, float]] = []

    for vp in positions:
        pos_key = (round(vp.x, 2), round(vp.y, 2))
        if pos_key in existing_nc:
            dup_count += 1
            continue

        # Issue #4: Skip if pin already has a wire or label connection.
        # Use tolerance-based check instead of exact set membership --
        # positions within SNAP_TOLERANCE can round to different keys.
        if _near_anchor(vp.x, vp.y, connected_positions):
            skipped_connected += 1
            logger.debug(
                "Skipping no_connect at (%.2f, %.2f): already connected",
                vp.x, vp.y,
            )
            continue

        # Issue #4: Also skip if pin lies on a wire segment (mid-wire
        # connection). KiCad considers pins on wire midpoints connected.
        if _point_on_wire_segment(vp.x, vp.y, wire_endpoints):
            skipped_connected += 1
            logger.debug(
                "Skipping no_connect at (%.2f, %.2f): on wire segment",
                vp.x, vp.y,
            )
            continue

        # Issue #13: Skip if multiple pins share this position (pin-to-pin
        # co-location). Power symbols connect implicitly by sharing coords.
        # Use SNAP_TOLERANCE-based count for consistent semantics (Council HIGH-1).
        colocated = sum(
            1 for px, py in all_pin_xy
            if abs(vp.x - px) <= SNAP_TOLERANCE and abs(vp.y - py) <= SNAP_TOLERANCE
        )
        if colocated > 1:
            skipped_connected += 1
            logger.debug(
                "Skipping no_connect at (%.2f, %.2f): pin co-located with another pin",
                vp.x, vp.y,
            )
            continue

        # Check pin electrical type
        # P0-004 fix: tolerance-based lookup replaces exact dict key.
        # ERC violation positions can differ from pin positions by sub-micron
        # precision, causing round(x, 2) to produce different keys
        # (e.g., pin 127.015 -> key 127.02, violation 127.014 -> key 127.01).
        # The tolerance helper reads directly from pin_positions (the source
        # list), matching within SNAP_TOLERANCE per axis.
        pin_type = _lookup_pin_type_with_tolerance(
            vp.x, vp.y, pin_positions, SNAP_TOLERANCE,
        )
        if pin_type in UNSAFE_PIN_TYPES:
            skipped_pin_type += 1
            logger.debug(
                "Skipping no_connect at (%.2f, %.2f): unsafe pin type '%s'",
                vp.x, vp.y, pin_type,
            )
            continue

        # Check if pin is on a power net
        if net_index is not None:
            net_name = net_index.get_net_at((vp.x, vp.y))
            if net_name and _is_power_net(net_name):
                skipped_power_net += 1
                logger.debug(
                    "Skipping no_connect at (%.2f, %.2f): on power net '%s'",
                    vp.x, vp.y, net_name,
                )
                continue

        ir.add_no_connect(x=vp.x, y=vp.y)
        placed_count += 1
        placed_positions.append((round(vp.x, 4), round(vp.y, 4)))
        # Add to existing set to prevent duplicates within this batch
        existing_nc.add(pos_key)

    return {
        "placed": placed_count,
        "skipped_duplicates": dup_count,
        "skipped_pin_type": skipped_pin_type,
        "skipped_power_net": skipped_power_net,
        "skipped_connected": skipped_connected,
        "positions": placed_positions,
    }


def add_power_flags(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Place PWR_FLAG symbols at power_pin_not_driven ERC violation positions.

    Phase 68: Places PWR_FLAG directly at the violation position so its pin
    overlaps with the power net connection. Uses NetPositionIndex for net
    name resolution when available. Deduplicates per net name.

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

    # Try to use NetPositionIndex for connectivity-aware net resolution
    net_index: NetPositionIndex | None = None
    try:
        net_index = NetPositionIndex.from_file(sch_path)
    except Exception:
        logger.debug("Could not build NetPositionIndex for label placement, using spatial fallback")

    label_positions = ir.get_label_positions()
    placed_count = 0
    skipped_count = 0
    placed_positions: list[tuple[float, float]] = []
    net_names: list[str] = []
    placed_nets: set[str] = set()  # dedup per invocation

    for vp in positions:
        # Resolve net name: prefer NetPositionIndex, fall back to labels
        net_name = None
        if net_index is not None:
            net_name = net_index.get_net_at((vp.x, vp.y))
        if net_name is None:
            net_name = _find_net_name_at_position(vp.x, vp.y, label_positions)

        if net_name is None:
            logger.warning(
                "Could not determine net name at (%.2f, %.2f), skipping power flag",
                vp.x, vp.y,
            )
            skipped_count += 1
            continue

        # Dedup: one PWR_FLAG per net per invocation
        if net_name in placed_nets:
            skipped_count += 1
            continue
        placed_nets.add(net_name)

        # Place PWR_FLAG at the violation position so its pin connects
        # directly to the power net (not offset -- offset was the isolation bug)
        ir.add_power_symbol("PWR_FLAG", vp.x, vp.y, 0.0)
        placed_count += 1
        placed_positions.append((round(vp.x, 4), round(vp.y, 4)))
        net_names.append(net_name)
        ir._record_mutation("add_power_flag", {
            "net_name": net_name,
            "position": [vp.x, vp.y],
        })

    return {
        "placed": placed_count,
        "positions": placed_positions,
        "skipped": skipped_count,
        "net_names": net_names,
    }


def _find_net_name_at_position(
    x: float,
    y: float,
    label_positions: list[dict[str, Any]],
    tolerance: float = 2.54,
) -> str | None:
    """Find the net label name at or near a given position.

    Args:
        x: X coordinate to search.
        y: Y coordinate to search.
        label_positions: List of label position dicts from get_label_positions().
        tolerance: Maximum distance in mm for a match (default 2.54mm = 1 grid space).

    Returns:
        Net name string if found, None otherwise.
    """
    best_match: str | None = None
    best_dist = tolerance
    for lp in label_positions:
        d = _distance(x, y, lp["x"], lp["y"])
        if d <= best_dist:
            best_dist = d
            best_match = lp["name"]
    return best_match


def add_junctions_at_labels(
    ir: SchematicIR, sch_path: Any = None,
) -> dict[str, Any]:
    """Add junctions at label positions where multiple wires meet.

    Fixes label_multiple_wires ERC violations by placing junction dots at
    label positions that have 2+ wire endpoints within tolerance.

    Args:
        ir: SchematicIR for the target schematic.
        sch_path: Path to schematic (accepted for erc_auto_fix compatibility).

    Returns:
        Dict with added count and positions.
    """
    label_positions = ir.get_label_positions()
    wire_endpoints = ir.get_wire_endpoints()
    if not label_positions or not wire_endpoints:
        return {"added": 0, "positions": []}

    # Build a map of position -> count of wire endpoints nearby
    TOLERANCE = 0.5  # mm
    added = 0
    positions: list[tuple[float, float]] = []

    for lp in label_positions:
        lx, ly = lp["x"], lp["y"]
        nearby_count = sum(
            1 for ep in wire_endpoints
            if _distance(lx, ly, ep["x"], ep["y"]) <= TOLERANCE
        )
        if nearby_count >= 2:
            ir.add_junction(lx, ly)
            added += 1
            positions.append((round(lx, 4), round(ly, 4)))

    return {"added": added, "positions": positions}


# ---------------------------------------------------------------------------
# IR checkpoint/restore for atomic operations
# ---------------------------------------------------------------------------


def _checkpoint_ir(ir: SchematicIR) -> object:
    """Deep-copy the IR's kiutils object for rollback on verification failure."""
    from copy import deepcopy
    return deepcopy(ir._parse_result.kiutils_obj)


def _restore_ir(ir: SchematicIR, checkpoint: object) -> None:
    """Restore IR from checkpoint on verification failure."""
    # ParseResult is a frozen dataclass; use object.__setattr__ to bypass
    object.__setattr__(ir._parse_result, "kiutils_obj", checkpoint)
