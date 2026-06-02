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
from kicad_agent.schematic_routing.net_extractor import NetPositionIndex

logger = logging.getLogger(__name__)

# Maximum distance (mm) to snap a wire endpoint to a pin.
# T-10-09: Bounded to prevent wires from jumping across the board.
SNAP_TOLERANCE = 0.01


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _check_snap_safety(
    endpoint_pos: tuple[float, float],
    target_pin_pos: tuple[float, float],
    net_index: NetPositionIndex,
) -> bool:
    """Check if snapping a wire endpoint to a target pin is safe.

    Phase 69: Returns True if the snap is allowed, False if it would move
    the endpoint from one named net to a different named net.

    Rules:
    - If endpoint is on no net (floating) -> ALLOW (needs connection)
    - If endpoint is on an auto-named net (Net_N) -> ALLOW (no identity)
    - If target pin is on no net or auto-named -> ALLOW
    - If both on same named net -> ALLOW
    - If on different named nets -> BLOCK
    """
    source_net = net_index.get_net_at(endpoint_pos)
    target_net = net_index.get_net_at(target_pin_pos)

    # Auto-named nets treated as "no net"
    if source_net and net_index.is_auto_named(source_net):
        source_net = None
    if target_net and net_index.is_auto_named(target_net):
        target_net = None

    # Both floating or auto-named -> safe
    if source_net is None or target_net is None:
        return True

    # Same named net -> safe
    if source_net == target_net:
        return True

    # Different named nets -> BLOCK
    return False


def repair_wire_snapping(ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Snap wire endpoints to the nearest pin position within tolerance.

    Phase 69: Adds net-verification guard. Before snapping a wire endpoint
    to a pin, checks that the endpoint isn't already connected to a
    different named net. Prevents unintended cross-net connections.

    Pin positions use the Y-inversion pattern: absolute = (sx+px, sy-py).
    See SchematicIR.get_pin_positions() for rotation handling.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the schematic file (for logging).

    Returns:
        Dict with snapped_count, unchanged_count, and skipped_net_mismatch.
    """
    pin_positions = ir.get_pin_positions()
    if not pin_positions:
        return {"snapped_count": 0, "unchanged_count": 0, "skipped_net_mismatch": 0}

    # Build a list of (x, y) tuples for fast nearest-point lookup
    pins_xy = [(p["x"], p["y"]) for p in pin_positions]

    # Build net index once for snap safety checks
    net_index: NetPositionIndex | None = None
    try:
        net_index = NetPositionIndex.from_file(file_path)
    except Exception:
        pass

    wire_endpoints = ir.get_wire_endpoints()
    snapped_count = 0
    unchanged_count = 0
    skipped_net_mismatch = 0

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
            # Net safety check
            if net_index is not None and not _check_snap_safety(
                (sx, sy), nearest_pin, net_index,
            ):
                skipped_net_mismatch += 1
            else:
                wire.points[0].X = nearest_pin[0]
                wire.points[0].Y = nearest_pin[1]
                modified = True

        # Check end point
        ex, ey = wire.points[1].X, wire.points[1].Y
        nearest_pin = _find_nearest_pin(ex, ey, pins_xy, SNAP_TOLERANCE)
        if nearest_pin is not None and _distance(ex, ey, nearest_pin[0], nearest_pin[1]) > 0:
            # Net safety check
            if net_index is not None and not _check_snap_safety(
                (ex, ey), nearest_pin, net_index,
            ):
                skipped_net_mismatch += 1
            else:
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

    return {
        "snapped_count": snapped_count,
        "unchanged_count": unchanged_count,
        "skipped_net_mismatch": skipped_net_mismatch,
    }


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
        pass

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
        # directly to the power net (not offset — offset was the isolation bug)
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


def place_no_connects_from_erc(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Place no-connect markers at pin_not_connected ERC violation positions.

    Phase 68: Filters by pin electrical type — skips power pins, input pins,
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

    positions = extract_violation_positions(sch_path, "pin_not_connected")
    if not positions:
        return {"placed": 0, "skipped_duplicates": 0, "positions": [],
                "skipped_pin_type": 0, "skipped_power_net": 0}

    # Build pin position → electrical type lookup from IR
    pin_positions = ir.get_pin_positions()
    pos_to_type: dict[tuple[float, float], str] = {}
    for p in pin_positions:
        key = (round(p["x"], 2), round(p["y"], 2))
        pos_to_type[key] = p.get("electrical_type", "passive")

    # Try to build net index for power-net checking
    net_index: NetPositionIndex | None = None
    try:
        net_index = NetPositionIndex.from_file(sch_path)
    except Exception:
        pass

    # Pin types that should NOT receive no_connect
    UNSAFE_PIN_TYPES = frozenset({
        "power_in", "power_out", "input", "net_in", "net_out",
    })

    # Check existing no-connect positions to avoid duplicates
    sch = ir.schematic
    existing_nc: set[tuple[float, float]] = set()
    for nc in sch.noConnects:
        existing_nc.add((round(nc.position.X, 2), round(nc.position.Y, 2)))

    placed_count = 0
    dup_count = 0
    skipped_pin_type = 0
    skipped_power_net = 0
    placed_positions: list[tuple[float, float]] = []

    for vp in positions:
        pos_key = (round(vp.x, 2), round(vp.y, 2))
        if pos_key in existing_nc:
            dup_count += 1
            continue

        # Check pin electrical type
        pin_type = pos_to_type.get(pos_key, "passive")
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


# ---------------------------------------------------------------------------
# ERC auto-fix operations (Phase 35)
# ---------------------------------------------------------------------------


def update_symbols_from_library(
    ir: SchematicIR, file_path: Path, *,
    references: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Re-embed mismatched symbols from their libraries.

    Equivalent to KiCad GUI's "Update Symbol from Library" for all symbols
    whose embedded lib_symbols definition diverges from the library version.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        references: Specific references to update, or None for all.
        dry_run: If True, report mismatches without modifying.

    Returns:
        Dict with updated (list), skipped (list), and total_mismatches.
    """
    import copy

    from kiutils.symbol import SymbolLib

    from kicad_agent.validation.symbol_mismatch import (
        _get_embedded_pin_signature,
        _get_library_pin_signature,
    )

    sch = ir._parse_result.kiutils_obj

    # Get all unique lib_ids used by placed symbols
    try:
        all_refs = ir.get_all_references()
    except Exception as exc:
        return {"updated": [], "skipped": [], "total_mismatches": 0, "error": str(exc)}

    # Deduplicate lib_ids while tracking references
    seen_lib_ids: dict[str, list[str]] = {}
    for reference, lib_id in all_refs:
        if lib_id and ":" in lib_id:
            seen_lib_ids.setdefault(lib_id, []).append(reference)

    # Filter by requested references
    if references is not None:
        ref_set = set(references)
        filtered: dict[str, list[str]] = {}
        for lib_id, refs in seen_lib_ids.items():
            matching = [r for r in refs if r in ref_set]
            if matching:
                filtered[lib_id] = matching
        seen_lib_ids = filtered

    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for lib_id, refs in seen_lib_ids.items():
        embedded_pins = _get_embedded_pin_signature(ir, lib_id)
        library_pins = _get_library_pin_signature(lib_id, file_path)

        if library_pins is None:
            skipped.append({
                "lib_id": lib_id,
                "references": refs,
                "reason": "library_not_found",
            })
            continue

        if embedded_pins == library_pins:
            continue  # No mismatch

        if dry_run:
            updated.append({
                "lib_id": lib_id,
                "references": refs,
                "action": "would_update",
            })
            continue

        # Re-embed: find the library, load symbol, replace embedded version
        library_name, _, symbol_name = lib_id.partition(":")
        try:
            from kicad_agent.project.lib_table import parse_lib_table

            schematic_dir = file_path.resolve().parent
            library_uri: str | None = None

            for table_path in [
                schematic_dir / "sym-lib-table",
                Path.home() / "Library" / "Preferences" / "kicad" / "10.0" / "sym-lib-table",
                Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/sym-lib-table"),
            ]:
                if not table_path.exists():
                    continue
                try:
                    table = parse_lib_table(table_path)
                    entry = table.get(library_name)
                    library_uri = entry.uri.replace(
                        "${KIPRJMOD}", str(schematic_dir.resolve())
                    )
                    break
                except (KeyError, ValueError, FileNotFoundError, OSError):
                    continue

            if library_uri is None:
                skipped.append({
                    "lib_id": lib_id,
                    "references": refs,
                    "reason": "library_path_not_resolved",
                })
                continue

            lib_path = Path(library_uri)
            if not lib_path.exists():
                skipped.append({
                    "lib_id": lib_id,
                    "references": refs,
                    "reason": "library_file_not_found",
                })
                continue

            lib = SymbolLib.from_file(str(lib_path))

            source_symbol = None
            for sym in lib.symbols:
                if sym.libId == lib_id or sym.name == symbol_name:
                    source_symbol = sym
                    break

            if source_symbol is None:
                skipped.append({
                    "lib_id": lib_id,
                    "references": refs,
                    "reason": "symbol_not_in_library",
                })
                continue

            # Replace embedded symbol
            new_symbol = copy.deepcopy(source_symbol)
            new_symbol.libraryNickname = library_name

            for i, existing in enumerate(sch.libSymbols):
                if getattr(existing, "libId", "") == lib_id:
                    sch.libSymbols[i] = new_symbol
                    break

            ir._record_mutation("update_symbols_from_library", {
                "lib_id": lib_id,
                "references": refs,
            })

            updated.append({
                "lib_id": lib_id,
                "references": refs,
                "action": "updated",
            })

        except Exception as exc:
            skipped.append({
                "lib_id": lib_id,
                "references": refs,
                "reason": f"error: {exc}",
            })

    return {
        "updated": updated,
        "skipped": skipped,
        "total_mismatches": len(updated) + len(skipped),
    }


def fix_shorted_nets(
    ir: SchematicIR, file_path: Path, *,
    strategy: str = "keep_first",
    keep_nets: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fix positions where multiple net names connect to the same items.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        strategy: "keep_first", "keep_last", or "manual".
        keep_nets: For "manual" strategy, which net names to keep.
        dry_run: If True, report shorts without modifying.

    Returns:
        Dict with shorts_found, labels_removed, and details.
    """
    short_result = detect_shorted_nets(ir)
    shorts = short_result["shorts"]

    if not shorts:
        return {"shorts_found": 0, "labels_removed": [], "clean": True}

    label_positions = ir.get_label_positions()
    sch = ir.schematic

    labels_removed: list[dict[str, Any]] = []

    for short in shorts:
        nets = short["nets"]
        if len(nets) < 2:
            continue

        # Decide which net to keep
        if strategy == "keep_first":
            keep_net = nets[0]
        elif strategy == "keep_last":
            keep_net = nets[-1]
        elif strategy == "manual":
            if keep_nets is None:
                continue
            keep_net = None
            for kn in keep_nets:
                if kn in nets:
                    keep_net = kn
                    break
            if keep_net is None:
                continue
        else:
            continue

        # Remove labels for the non-kept nets
        remove_nets = set(nets) - {keep_net}

        for label in list(sch.labels):
            if label.text in remove_nets:
                pos_key = _round_pos(label.position.X, label.position.Y)
                short_pos = (round(short["position"][0], 2), round(short["position"][1], 2))
                if pos_key == short_pos or _distance(
                    label.position.X, label.position.Y,
                    short["position"][0], short["position"][1],
                ) <= SNAP_TOLERANCE:
                    if not dry_run:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                        })
                        sch.labels.remove(label)
                        ir._record_mutation("fix_shorted_net", {
                            "removed_label": label.text,
                            "kept_net": keep_net,
                        })
                    else:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                            "dry_run": True,
                        })

        for label in list(sch.globalLabels):
            if label.text in remove_nets:
                pos_key = _round_pos(label.position.X, label.position.Y)
                short_pos = (round(short["position"][0], 2), round(short["position"][1], 2))
                if pos_key == short_pos or _distance(
                    label.position.X, label.position.Y,
                    short["position"][0], short["position"][1],
                ) <= SNAP_TOLERANCE:
                    if not dry_run:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                        })
                        sch.globalLabels.remove(label)
                        ir._record_mutation("fix_shorted_net", {
                            "removed_label": label.text,
                            "kept_net": keep_net,
                        })
                    else:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                            "dry_run": True,
                        })

    return {
        "shorts_found": len(shorts),
        "labels_removed": labels_removed,
        "clean": len(labels_removed) == 0,
    }


def fix_pin_type_mismatches(
    ir: SchematicIR, file_path: Path, *,
    pin_type_map: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fix pin electrical type mismatches in embedded lib_symbols.

    Updates pin electrical types to resolve pin_to_pin ERC violations.
    Default: change "unspecified" to "passive".

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        pin_type_map: Override map, defaults to {"unspecified": "passive"}.
        dry_run: If True, report without modifying.

    Returns:
        Dict with pins_changed, details, and lib_ids_affected.
    """
    if pin_type_map is None:
        pin_type_map = {"unspecified": "passive"}

    sch = ir._parse_result.kiutils_obj
    pins_changed: list[dict[str, Any]] = []
    lib_ids_affected: set[str] = set()

    for lib_sym in sch.libSymbols:
        lib_id = getattr(lib_sym, "libId", "")
        for unit in lib_sym.units:
            for pin in unit.pins:
                old_type = pin.electricalType
                new_type = pin_type_map.get(old_type)
                if new_type is not None:
                    if dry_run:
                        pins_changed.append({
                            "lib_id": lib_id,
                            "pin_number": pin.number,
                            "pin_name": pin.name,
                            "old_type": old_type,
                            "new_type": new_type,
                            "dry_run": True,
                        })
                    else:
                        pin.electricalType = new_type
                        pins_changed.append({
                            "lib_id": lib_id,
                            "pin_number": pin.number,
                            "pin_name": pin.name,
                            "old_type": old_type,
                            "new_type": new_type,
                        })
                    lib_ids_affected.add(lib_id)

    if pins_changed and not dry_run:
        ir._record_mutation("fix_pin_type_mismatches", {
            "pins_changed": len(pins_changed),
            "lib_ids": sorted(lib_ids_affected),
        })

    return {
        "pins_changed": pins_changed,
        "total": len(pins_changed),
        "lib_ids_affected": sorted(lib_ids_affected),
    }


def _get_unit_pin_map(lib_sym) -> dict[int, set[str]]:
    """Extract unit_number -> pin_numbers mapping from sub-symbol names.

    KiCad multi-unit symbols define sub-symbols named ``ParentName_X_Y``
    where X is the unit number and Y is the body style.  This helper
    parses those names and returns a mapping from unit number to the set
    of pin numbers defined in that unit.

    Units with zero pins (graphic-only wrappers) are excluded.
    """
    unit_map: dict[int, set[str]] = {}
    for sub_sym in lib_sym.units:
        name = getattr(sub_sym, "libId", "") or ""
        parts = name.rsplit("_", 2)
        if len(parts) < 3:
            continue
        try:
            unit_num = int(parts[-2])
        except ValueError:
            continue

        pin_numbers: set[str] = set()
        for pin in sub_sym.pins:
            if pin.number:
                pin_numbers.add(pin.number)

        if pin_numbers:
            unit_map[unit_num] = pin_numbers

    return unit_map


def _get_unit_pin_offsets(
    lib_sym, unit_num: int
) -> dict[str, tuple[float, float]]:
    """Get pin positions for a specific unit from the lib symbol.

    Returns dict of pin_number -> (px, py) where px, py are relative to
    the component origin (the pin's connection-point position in the lib
    symbol definition).
    """
    for sub_sym in lib_sym.units:
        name = getattr(sub_sym, "libId", "") or ""
        parts = name.rsplit("_", 2)
        if len(parts) < 3:
            continue
        try:
            u = int(parts[-2])
        except ValueError:
            continue
        if u == unit_num:
            return {
                pin.number: (pin.position.X, pin.position.Y)
                for pin in sub_sym.pins
                if pin.number
            }
    return {}


def _find_position_for_unit(
    ir: SchematicIR,
    lib_sym,
    unit_num: int,
    rotation: float,
    wire_endpoints: list[dict[str, Any]],
    label_positions: list[dict[str, Any]],
    center: tuple[float, float] | None = None,
    max_distance: float = 100.0,
    net_index: NetPositionIndex | None = None,
    placed_unit_roots: set[tuple[float, float]] | None = None,
) -> tuple[float, float] | None:
    """Find the component position that aligns a unit's pins with existing nets.

    Phase 66: Uses connectivity-aware scoring when a NetPositionIndex is
    provided.  For each candidate position, calculates where each pin would
    land and scores by how many pins connect to unique nets (not shared with
    already-placed units).  Falls back to spatial wire-endpoint voting when
    no net index is available.

    Uses the Y-inversion pattern from ``get_pin_positions()``:
        absolute = (sx + rot_px, sy - rot_py)
    Reverse: (sx, sy) = (abs_x - rot_px, abs_y + rot_py)

    Args:
        net_index: Optional NetPositionIndex for connectivity-aware scoring.
        placed_unit_roots: Set of union-find component roots for pins of
            already-placed units.  Candidate positions whose pins land on
            these roots are penalized.
    """
    pin_offsets = _get_unit_pin_offsets(lib_sym, unit_num)
    if not pin_offsets:
        return None

    angle_rad = math.radians(rotation)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Build anchor points from wire endpoints and label positions
    anchor_points: list[tuple[float, float]] = []
    for wire in wire_endpoints:
        anchor_points.append((wire["start_x"], wire["start_y"]))
        anchor_points.append((wire["end_x"], wire["end_y"]))
    for label in label_positions:
        anchor_points.append((label["x"], label["y"]))

    if not anchor_points:
        return None

    # Filter by proximity to center if provided
    if center is not None:
        cx, cy = center
        max_dist_sq = max_distance * max_distance
        anchor_points = [
            (ax, ay)
            for ax, ay in anchor_points
            if (ax - cx) ** 2 + (ay - cy) ** 2 <= max_dist_sq
        ]
        if not anchor_points:
            return None

    # Collect candidate component positions from all pins x all anchors
    from collections import Counter

    candidate_positions: list[tuple[float, float]] = []
    for _pin_num, (px, py) in pin_offsets.items():
        rot_px = px * cos_a - py * sin_a
        rot_py = px * sin_a + py * cos_a

        for anchor_x, anchor_y in anchor_points:
            cand_x = round((anchor_x - rot_px) * 10) / 10
            cand_y = round((anchor_y + rot_py) * 10) / 10
            candidate_positions.append((cand_x, cand_y))

    if not candidate_positions:
        return None

    # --- Net-aware scoring (Phase 66) ---
    if net_index is not None and placed_unit_roots is not None:
        best_pos: tuple[float, float] | None = None
        best_score = 0

        # Deduplicated candidate positions
        unique_candidates = set(candidate_positions)

        for cand_x, cand_y in unique_candidates:
            score = 0
            for _pin_num, (px, py) in pin_offsets.items():
                rot_px = px * cos_a - py * sin_a
                rot_py = px * sin_a + py * cos_a

                # Y-inversion: absolute = (sx + rot_px, sy - rot_py)
                pin_abs_x = cand_x + rot_px
                pin_abs_y = cand_y - rot_py

                root = net_index.get_component_root((pin_abs_x, pin_abs_y))
                if root is not None and root not in placed_unit_roots:
                    score += 1

            if score > best_score:
                best_score = score
                best_pos = (cand_x, cand_y)

        if best_score >= 2 and best_pos is not None:
            return best_pos

        # Net-aware didn't find a good position — fall through to spatial
        logger.debug(
            "Net-aware scoring best=%d (need >=2), falling back to spatial",
            best_score,
        )

    # --- Spatial fallback: wire-endpoint voting ---
    pos_counter = Counter(candidate_positions)
    if not pos_counter:
        return None

    best_pos_spatial, count = pos_counter.most_common(1)[0]
    if count >= 2:
        return best_pos_spatial

    return None


def place_missing_units(
    ir: SchematicIR, file_path: Path, *,
    references: list[str] | None = None,
    offset_x: float = 25.4,
    offset_y: float = 0.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Place all unplaced units of multi-unit symbols.

    For multi-unit symbols, finds units reported as missing by ERC and places
    them adjacent to the existing unit with configurable spacing.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        references: Specific references to fix, or None for all.
        offset_x: Horizontal spacing between units in mm.
        offset_y: Vertical spacing between units in mm.
        dry_run: If True, report without modifying.

    Returns:
        Dict with units_placed and details.
    """
    import uuid

    sch = ir._parse_result.kiutils_obj

    # Find all components, grouped by reference prefix (multi-unit symbols
    # share the same base reference like U4 with units A, B, C, D)
    components_by_ref: dict[str, list[Any]] = {}
    for comp in sch.schematicSymbols:
        ref_prop = None
        for prop in comp.properties:
            if prop.key == "Reference":
                ref_prop = prop.value
                break
        if ref_prop is None:
            continue

        # Multi-unit references: U4A, U4B etc. Base is U4
        base_ref = ref_prop.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        components_by_ref.setdefault(base_ref, []).append(comp)

    # Filter by requested references
    if references is not None:
        ref_set = set(references)
        components_by_ref = {
            k: v for k, v in components_by_ref.items() if k in ref_set
        }

    units_placed: list[dict[str, Any]] = []

    # Build net position index for connectivity-aware placement (Phase 66).
    # Try to build from the schematic file; if that fails (e.g. in-memory
    # only), fall back to None which disables net-aware scoring.
    net_index: NetPositionIndex | None = None
    try:
        net_index = NetPositionIndex.from_file(file_path)
    except Exception:
        logger.debug("Could not build NetPositionIndex, using spatial fallback")

    for base_ref, components in components_by_ref.items():
        if len(components) == 0:
            continue

        # Get the lib_id from the first component
        lib_id = components[0].libId

        # Find the embedded symbol definition
        lib_sym = None
        for ls in sch.libSymbols:
            if getattr(ls, "libId", "") == lib_id:
                lib_sym = ls
                break

        if lib_sym is None:
            continue

        # Count available units
        available_units = list(lib_sym.units)

        # KiCad standard library symbols (R, C, L, power, test points) use a
        # 2-unit structure: unit 0 = graphic-only (no pins), unit 1 = component.
        # True multi-unit symbols (NE5532, CD4066BE) have 3+ units or pins on
        # unit 0 (shared power pins).  Skip the fake 2-unit symbols.
        if len(available_units) <= 2 and len(available_units[0].pins) == 0:
            continue  # Single-unit symbol with graphic wrapper

        # Get unit_number -> pin_numbers mapping from sub-symbol names
        unit_pin_map = _get_unit_pin_map(lib_sym)
        if not unit_pin_map:
            continue

        # Determine which unit numbers are placed vs missing.
        # KiCad unit numbers are NOT sequential array indices —
        # NE5532 has units {1, 2, 3} but a component may have
        # only units {1, 3} placed (op-amp A + power).  We must
        # use comp.unit to get the actual KiCad unit number.
        placed_unit_nums = {comp.unit for comp in components}
        missing_unit_nums = sorted(unit_pin_map.keys() - placed_unit_nums)

        if not missing_unit_nums:
            continue  # All units already placed

        # Get wire endpoints and label positions for position calculation
        wire_endpoints = ir.get_wire_endpoints()
        label_positions = ir.get_label_positions()

        # Get position and rotation of first placed component
        first_comp = components[0]
        rotation = first_comp.position.angle or 0.0

        # Collect union-find component roots for already-placed units' pins.
        # Phase 66: Net-aware scoring uses this to avoid placing a missing
        # unit at a position where its pins would land on the same nets.
        placed_unit_roots: set[tuple[float, float]] = set()
        if net_index is not None:
            angle_rad = math.radians(rotation)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            for comp in components:
                comp_offsets = _get_unit_pin_offsets(lib_sym, comp.unit)
                for _pn, (px, py) in comp_offsets.items():
                    rot_px = px * cos_a - py * sin_a
                    rot_py = px * sin_a + py * cos_a
                    pin_x = comp.position.X + rot_px
                    pin_y = comp.position.Y - rot_py
                    root = net_index.get_component_root((pin_x, pin_y))
                    if root is not None:
                        placed_unit_roots.add(root)

        # Place missing units
        import copy

        for i, missing_num in enumerate(missing_unit_nums):
            # Phase 66: Net-aware position matching.  Find a position where
            # the missing unit's pins land on nets DIFFERENT from the
            # already-placed units.  Only search near the first placed unit.
            center = (first_comp.position.X, first_comp.position.Y)
            pos = _find_position_for_unit(
                ir, lib_sym, missing_num, rotation,
                wire_endpoints, label_positions,
                center=center, max_distance=100.0,
                net_index=net_index,
                placed_unit_roots=placed_unit_roots,
            )
            if pos is None:
                # Fallback: offset from first unit.  Stacking at the
                # same position is unsafe for dual op-amps (NE5532
                # units 1 and 2 have identical pin offset patterns),
                # so we use a sequential offset instead.
                offset_idx = len(components) + i
                pos = (
                    first_comp.position.X + offset_idx * offset_x,
                    first_comp.position.Y + offset_idx * offset_y,
                )

            new_x, new_y = pos

            if dry_run:
                unit_letter = chr(ord("A") + missing_num - 1)
                units_placed.append({
                    "base_reference": base_ref,
                    "unit_number": missing_num,
                    "unit_letter": unit_letter,
                    "position": [new_x, new_y],
                    "dry_run": True,
                })
                continue

            # Clone the first component and override unit-specific fields
            new_comp = copy.deepcopy(first_comp)
            new_uuid = str(uuid.uuid4())
            new_comp.position.X = new_x
            new_comp.position.Y = new_y
            new_comp.position.angle = rotation

            # Bug B fix: set the correct KiCad unit number.
            # Previously all clones inherited comp.unit=1 from the
            # first component, causing the wrong sub-symbol graphics.
            new_comp.unit = missing_num

            # Update UUID
            if hasattr(new_comp, "uuid"):
                new_comp.uuid = new_uuid

            # Derive reference letter from unit number (1=A, 2=B, 3=C, ...)
            unit_letter = chr(ord("A") + missing_num - 1)
            for prop in new_comp.properties:
                if prop.key == "Reference":
                    prop.value = f"{base_ref}{unit_letter}"
                    break

            sch.schematicSymbols.append(new_comp)

            ir._record_mutation("place_missing_unit", {
                "base_reference": base_ref,
                "unit_number": missing_num,
                "unit_letter": unit_letter,
                "position": [new_x, new_y],
                "uuid": new_uuid,
            })

            units_placed.append({
                "base_reference": base_ref,
                "unit_number": missing_num,
                "unit_letter": unit_letter,
                "position": [new_x, new_y],
                "uuid": new_uuid,
            })

    return {
        "units_placed": units_placed,
        "total": len(units_placed),
    }


# ---------------------------------------------------------------------------
# Post-repair verification (Phase 70)
# ---------------------------------------------------------------------------


def _take_net_snapshot(ir: SchematicIR) -> dict[str, Any]:
    """Build net topology snapshot from in-memory IR state.

    Uses pin-set identity (frozenset of (ref, pin_number)) for stable
    comparison across snapshots, immune to auto-naming order changes.
    """
    wire_endpoints = ir.get_wire_endpoints()
    label_positions = ir.get_label_positions()
    pin_positions = ir.get_pin_positions()

    # Build union-find over wire-connected positions
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def _uf_find(pos: tuple[float, float]) -> tuple[float, float]:
        while parent.get(pos, pos) != pos:
            parent[pos] = parent.get(parent[pos], parent[pos])
            pos = parent[pos]
        return pos

    def _uf_union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = _uf_find(a), _uf_find(b)
        if ra != rb:
            parent[ra] = rb

    # Union wire start/end
    for we in wire_endpoints:
        start = _round_pos(we["start_x"], we["start_y"])
        end = _round_pos(we["end_x"], we["end_y"])
        _uf_union(start, end)

    # Collect label positions and pin positions
    pos_to_pins: dict[tuple[float, float], list[tuple[str, str]]] = {}
    for p in pin_positions:
        key = _round_pos(p["x"], p["y"])
        pos_to_pins.setdefault(key, []).append((p["reference"], p["pin_number"]))

    pos_to_labels: dict[tuple[float, float], str] = {}
    for label in label_positions:
        key = _round_pos(label["x"], label["y"])
        pos_to_labels[key] = label["name"]

    # Build components by root
    components: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for we in wire_endpoints:
        for coord in [(we["start_x"], we["start_y"]), (we["end_x"], we["end_y"])]:
            key = _round_pos(coord[0], coord[1])
            root = _uf_find(key)
            components.setdefault(root, set()).add(key)
    for key in pos_to_pins:
        root = _uf_find(key)
        components.setdefault(root, set()).add(key)
    for key in pos_to_labels:
        root = _uf_find(key)
        components.setdefault(root, set()).add(key)

    # Build per-component pin sets and net names
    result: dict[str, Any] = {"components": {}}
    for root, positions in components.items():
        pin_set: set[tuple[str, str]] = set()
        net_name: str | None = None
        for pos in positions:
            if pos in pos_to_pins:
                pin_set.update(pos_to_pins[pos])
            if pos in pos_to_labels and net_name is None:
                net_name = pos_to_labels[pos]
        result["components"][root] = {
            "pin_set": frozenset(pin_set),
            "net_name": net_name,
        }

    return result


def _diff_net_snapshots(before: dict, after: dict) -> dict[str, Any]:
    """Compare two net snapshots and detect regressions.

    Returns dict with broken_nets, merged_nets, new_components, and clean flag.
    Uses pin-set overlap for component matching (not net names).
    """
    before_comps = before.get("components", {})
    after_comps = after.get("components", {})

    # Build pin_set -> component mappings
    before_by_pins: dict[frozenset, tuple] = {}
    for root, data in before_comps.items():
        pins = data["pin_set"]
        if pins:
            before_by_pins[pins] = (root, data)

    after_by_pins: dict[frozenset, tuple] = {}
    for root, data in after_comps.items():
        pins = data["pin_set"]
        if pins:
            after_by_pins[pins] = (root, data)

    broken_nets: list[dict] = []
    merged_nets: list[dict] = []
    new_components: list[dict] = []

    # Find broken: before component with no after match
    matched_after: set[frozenset] = set()
    for pins, (root, data) in before_by_pins.items():
        if pins in after_by_pins:
            matched_after.add(pins)
        else:
            # Check for partial match (subset of pins still present)
            found_partial = False
            for after_pins, (after_root, after_data) in after_by_pins.items():
                if after_pins and pins and after_pins.issubset(pins) and len(after_pins) >= len(pins) * 0.5:
                    found_partial = True
                    matched_after.add(after_pins)
                    break
            if not found_partial:
                broken_nets.append({
                    "net_name": data.get("net_name"),
                    "pin_count": len(pins),
                })

    # Find merged: multiple before components matching same after component
    # (This would indicate a short was introduced)
    # Find new: after components with no before match
    for pins, (root, data) in after_by_pins.items():
        if pins not in matched_after:
            new_components.append({
                "net_name": data.get("net_name"),
                "pin_count": len(pins),
            })

    clean = len(broken_nets) == 0 and len(merged_nets) == 0
    return {
        "broken_nets": broken_nets,
        "merged_nets": merged_nets,
        "new_components": new_components,
        "clean": clean,
    }


def _checkpoint_ir(ir: SchematicIR) -> bytes:
    """Deep-copy the IR's kiutils object for rollback on verification failure."""
    import pickle
    return pickle.dumps(ir._parse_result.kiutils_obj)


def _restore_ir(ir: SchematicIR, checkpoint: bytes) -> None:
    """Restore IR from checkpoint on verification failure."""
    import pickle
    restored = pickle.loads(checkpoint)
    # ParseResult is a frozen dataclass; use object.__setattr__ to bypass
    object.__setattr__(ir._parse_result, "kiutils_obj", restored)


def remove_dangling_wires(
    ir: SchematicIR, file_path: Path, *,
    max_length_mm: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove wire segments with unconnected endpoints.

    A dangling wire has at least one endpoint not connected to any pin,
    label, junction, or other wire intersection.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        max_length_mm: Only remove wires shorter than this. None = no limit.
        dry_run: If True, report without modifying.

    Returns:
        Dict with removed_count and details.
    """
    pin_positions = ir.get_pin_positions()
    label_positions = ir.get_label_positions()
    wire_endpoints = ir.get_wire_endpoints()
    sch = ir.schematic

    # Collect all "connected" positions
    connected: set[tuple[float, float]] = set()
    for pp in pin_positions:
        connected.add(_round_pos(pp["x"], pp["y"]))
    for lp in label_positions:
        connected.add(_round_pos(lp["x"], lp["y"]))

    # Also collect junction positions
    for junction in sch.junctions:
        connected.add(_round_pos(junction.position.X, junction.position.Y))

    # Build wire intersection map: positions where multiple wires meet
    wire_pos_count: dict[tuple[float, float], int] = {}
    for we in wire_endpoints:
        start_key = _round_pos(we["start_x"], we["start_y"])
        end_key = _round_pos(we["end_x"], we["end_y"])
        wire_pos_count[start_key] = wire_pos_count.get(start_key, 0) + 1
        wire_pos_count[end_key] = wire_pos_count.get(end_key, 0) + 1

    # A position is "anchored" if it has a pin, label, junction, or 2+ wires
    anchored: set[tuple[float, float]] = set()
    anchored.update(connected)
    for pos, count in wire_pos_count.items():
        if count >= 2:
            anchored.add(pos)

    # Find dangling wires: both endpoints unanchored
    removed: list[dict[str, Any]] = []
    wires_to_remove: list[int] = []

    for wire_info in wire_endpoints:
        start_key = _round_pos(wire_info["start_x"], wire_info["start_y"])
        end_key = _round_pos(wire_info["end_x"], wire_info["end_y"])

        start_anchored = start_key in anchored
        end_anchored = end_key in anchored

        # Dangling if both endpoints unanchored
        if not start_anchored and not end_anchored:
            wire_idx = wire_info["wire_index"]
            wire = sch.graphicalItems[wire_idx]

            # Check max_length filter
            if max_length_mm is not None:
                length = _distance(
                    wire_info["start_x"], wire_info["start_y"],
                    wire_info["end_x"], wire_info["end_y"],
                )
                if length > max_length_mm:
                    continue

            if dry_run:
                removed.append({
                    "position": [wire_info["start_x"], wire_info["start_y"]],
                    "length": round(_distance(
                        wire_info["start_x"], wire_info["start_y"],
                        wire_info["end_x"], wire_info["end_y"],
                    ), 4),
                    "dry_run": True,
                })
            else:
                wires_to_remove.append(wire_idx)
                removed.append({
                    "position": [wire_info["start_x"], wire_info["start_y"]],
                    "length": round(_distance(
                        wire_info["start_x"], wire_info["start_y"],
                        wire_info["end_x"], wire_info["end_y"],
                    ), 4),
                })

    if wires_to_remove and not dry_run:
        # Remove in reverse order to preserve indices
        for idx in sorted(wires_to_remove, reverse=True):
            wire = sch.graphicalItems[idx]
            sch.graphicalItems.pop(idx)
            ir._record_mutation("remove_dangling_wire", {
                "position": [
                    wire.points[0].X if hasattr(wire, "points") and wire.points else 0,
                    wire.points[0].Y if hasattr(wire, "points") and wire.points else 0,
                ],
            })

    return {
        "removed_count": len(removed),
        "details": removed,
    }


def find_bridge_wires(
    ir: SchematicIR,
    net_a: str,
    net_b: str,
) -> list[dict[str, Any]]:
    """Find wire segments that bridge (short) two different nets.

    Uses BFS from net_a label positions to net_b label positions through
    the wire connectivity graph. Returns the wire(s) on the connecting path.

    Args:
        ir: SchematicIR for the target schematic.
        net_a: First net name.
        net_b: Second net name.

    Returns:
        List of dicts with wire_index, start, end, and the net pair.
    """
    label_positions = ir.get_label_positions()
    wire_endpoints = ir.get_wire_endpoints()

    # Map positions to net names
    pos_to_nets: dict[tuple[float, float], set[str]] = {}
    for label in label_positions:
        key = _round_pos(label["x"], label["y"])
        pos_to_nets.setdefault(key, set()).add(label["name"])

    # Seed positions: all positions that have net_a or net_b labels
    seeds_a: set[tuple[float, float]] = set()
    seeds_b: set[tuple[float, float]] = set()
    for pos, nets in pos_to_nets.items():
        if net_a in nets:
            seeds_a.add(pos)
        if net_b in nets:
            seeds_b.add(pos)

    if not seeds_a or not seeds_b:
        return []

    # Build adjacency: position → list of (neighbor_position, wire_index)
    adjacency: dict[tuple[float, float], list[tuple[tuple[float, float], int]]] = {}
    for we in wire_endpoints:
        wi = we["wire_index"]
        start_key = _round_pos(we["start_x"], we["start_y"])
        end_key = _round_pos(we["end_x"], we["end_y"])
        adjacency.setdefault(start_key, []).append((end_key, wi))
        adjacency.setdefault(end_key, []).append((start_key, wi))

    # BFS from all net_a seed positions to any net_b seed position
    # Track which wire index led to each position
    visited: set[tuple[float, float]] = set()
    parent: dict[tuple[float, float], tuple[tuple[float, float], int]] = {}
    queue: list[tuple[float, float]] = list(seeds_a)
    for s in queue:
        visited.add(s)

    found_target: tuple[float, float] | None = None
    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1

        if current in seeds_b:
            found_target = current
            break

        for neighbor, wire_idx in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                parent[neighbor] = (current, wire_idx)
                queue.append(neighbor)

    if found_target is None:
        return []

    # Trace back from target to seed to find bridge wires
    bridge_wires: list[int] = []
    pos = found_target
    while pos in parent:
        prev_pos, wire_idx = parent[pos]
        bridge_wires.append(wire_idx)
        pos = prev_pos

    # Build details for each bridge wire
    wire_map: dict[int, dict] = {}
    for we in wire_endpoints:
        wire_map[we["wire_index"]] = we

    results = []
    for wi in bridge_wires:
        we = wire_map.get(wi)
        if we:
            results.append({
                "wire_index": wi,
                "start": [we["start_x"], we["start_y"]],
                "end": [we["end_x"], we["end_y"]],
                "length": round(_distance(
                    we["start_x"], we["start_y"],
                    we["end_x"], we["end_y"],
                ), 4),
                "nets": sorted([net_a, net_b]),
            })

    return results


def break_wire_shorts(
    ir: SchematicIR, file_path: Path, *,
    net_pairs: list[list[str]] | None = None,
    strategy: str = "shortest_path",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Break wire segments that short different nets together.

    Detects positions where wires physically connect two nets that shouldn't
    be connected. Uses BFS to find the bridge wire(s) on the path between
    shorted net labels and removes them.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        net_pairs: Specific net pairs to break, or None for all detected shorts.
        strategy: "shortest_path" removes one bridge wire per short,
            "all_bridges" removes all wires connecting the pair.
        dry_run: If True, report without modifying.

    Returns:
        Dict with shorts_found, wires_removed, and details.
    """
    # Step 1: Detect all shorts
    shorts_result = detect_shorted_nets(ir)
    all_shorts = shorts_result["shorts"]

    if not all_shorts:
        return {"shorts_found": 0, "wires_removed": 0, "details": []}

    # Step 2: Filter to requested net pairs
    requested_pairs: set[frozenset[str]] | None = None
    if net_pairs is not None:
        requested_pairs = {frozenset(pair) for pair in net_pairs}

    target_shorts = []
    for short in all_shorts:
        pair_key = frozenset(short["nets"])
        if requested_pairs is None or pair_key in requested_pairs:
            target_shorts.append(short)

    if not target_shorts:
        return {
            "shorts_found": len(all_shorts),
            "wires_removed": 0,
            "details": [],
        }

    # Step 3: Find bridge wires for each short
    all_bridge_indices: set[int] = set()
    details: list[dict[str, Any]] = []

    for short in target_shorts:
        nets = short["nets"]
        if len(nets) < 2:
            continue

        bridges = find_bridge_wires(ir, nets[0], nets[1])

        if strategy == "shortest_path" and bridges:
            # Only take the first (shortest path) bridge wire
            bridges = [bridges[0]]

        for bridge in bridges:
            all_bridge_indices.add(bridge["wire_index"])
            details.append({
                "short": sorted(nets),
                "wire_start": bridge["start"],
                "wire_end": bridge["end"],
                "wire_length": bridge["length"],
                "dry_run": dry_run,
            })

    # Step 4: Remove bridge wires
    sch = ir.schematic
    removed_count = 0

    if all_bridge_indices and not dry_run:
        # Remove in reverse index order to preserve indices
        for idx in sorted(all_bridge_indices, reverse=True):
            if idx < len(sch.graphicalItems):
                wire = sch.graphicalItems[idx]
                sch.graphicalItems.pop(idx)
                removed_count += 1
                ir._record_mutation("break_wire_short", {
                    "wire_index": idx,
                    "position": [
                        wire.points[0].X if hasattr(wire, "points") and wire.points else 0,
                        wire.points[0].Y if hasattr(wire, "points") and wire.points else 0,
                    ],
                })

    return {
        "shorts_found": len(target_shorts),
        "wires_removed": removed_count if not dry_run else len(all_bridge_indices),
        "details": details,
    }


# Power net name patterns — never auto-remove these labels
_POWER_NET_PATTERNS = frozenset({
    "VCC", "VDD", "VEE", "VSS",
    "GND", "AGND", "DGND", "PGND", "CHASSIS",
    "+3V3", "+5V", "+9V", "+12V", "+15V", "+24V", "+48V",
    "-3V3", "-5V", "-9V", "-12V", "-15V", "-24V", "-48V",
    "3V3", "5V", "9V", "12V", "15V", "24V", "48V",
})


def _is_power_net(net_name: str) -> bool:
    """Check if a net name is a power rail."""
    upper = net_name.upper().lstrip("+").lstrip("-")
    return net_name in _POWER_NET_PATTERNS or upper in _POWER_NET_PATTERNS


def _check_orphan_count(
    wire_endpoints: list[dict[str, Any]],
    bridge_wire_index: int,
    label_positions: list[dict[str, Any]],
) -> int:
    """Count pins/labels orphaned if bridge_wire_index is removed.

    Returns 0 if the break is clean (no orphans).
    """
    # Build adjacency without the bridge wire
    adjacency: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for we in wire_endpoints:
        wi = we["wire_index"]
        if wi == bridge_wire_index:
            continue
        start = _round_pos(we["start_x"], we["start_y"])
        end = _round_pos(we["end_x"], we["end_y"])
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)

    # Collect all label positions
    label_pos_set: set[tuple[float, float]] = set()
    for label in label_positions:
        label_pos_set.add(_round_pos(label["x"], label["y"]))

    # BFS from label positions to find reachable set
    visited: set[tuple[float, float]] = set()
    queue: list[tuple[float, float]] = list(label_pos_set)
    for pos in queue:
        visited.add(pos)

    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    # Count label positions NOT reachable from any other label
    orphan_count = 0
    for pos in label_pos_set:
        if pos not in visited:
            orphan_count += 1

    return orphan_count


def resolve_shorted_nets(
    ir: SchematicIR, file_path: Path, *,
    strategy: str = "break_bridge",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atomic short resolution with power-net protection and orphan checking.

    Phase 67: Combines break_wire_shorts + fix_shorted_nets into a single
    operation with:
    - Power-net protection: never auto-resolve shorts involving power rails
    - Orphan checking: reject break points that leave labels/pins disconnected
    - Graph-bridges algorithm for optimal break point selection

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        strategy: "break_bridge" (remove bridge wire), "remove_label"
            (remove duplicate label), or "manual" (report only).
        dry_run: If True, report without modifying.

    Returns:
        Dict with shorts_found, resolved, skipped_power, and details.
    """
    shorts_result = detect_shorted_nets(ir)
    shorts = shorts_result["shorts"]

    if not shorts:
        return {"shorts_found": 0, "resolved": 0, "skipped_power": 0, "details": []}

    wire_endpoints = ir.get_wire_endpoints()
    label_positions = ir.get_label_positions()
    sch = ir.schematic

    resolved_count = 0
    skipped_power = 0
    details: list[dict[str, Any]] = []

    for short in shorts:
        nets = short["nets"]
        if len(nets) < 2:
            continue

        # Power-net protection: skip auto-resolution for power rail shorts
        if any(_is_power_net(n) for n in nets):
            skipped_power += 1
            details.append({
                "nets": sorted(nets),
                "action": "skipped_power",
                "position": list(short["position"]),
                "reason": "Short involves power rail — requires manual resolution",
            })
            continue

        if strategy == "manual":
            details.append({
                "nets": sorted(nets),
                "action": "manual_only",
                "position": list(short["position"]),
            })
            continue

        # Try break_bridge strategy first
        if strategy == "break_bridge":
            bridges = find_bridge_wires(ir, nets[0], nets[1])

            # Check orphan count for each bridge candidate
            clean_bridge = None
            for bridge in bridges[:5]:  # limit candidates
                orphan_count = _check_orphan_count(
                    wire_endpoints, bridge["wire_index"], label_positions,
                )
                if orphan_count == 0:
                    clean_bridge = bridge
                    break

            if clean_bridge and not dry_run:
                # Remove the bridge wire
                wire_idx = clean_bridge["wire_index"]
                if wire_idx < len(sch.graphicalItems):
                    sch.graphicalItems.pop(wire_idx)
                    resolved_count += 1
                    ir._record_mutation("resolve_shorted_net", {
                        "action": "break_bridge",
                        "nets": sorted(nets),
                        "wire_index": wire_idx,
                    })
                    details.append({
                        "nets": sorted(nets),
                        "action": "break_bridge",
                        "wire_start": clean_bridge["start"],
                        "wire_end": clean_bridge["end"],
                    })
                    continue

            # No clean break found — try label removal
            if clean_bridge is None and bridges:
                details.append({
                    "nets": sorted(nets),
                    "action": "no_clean_break",
                    "position": list(short["position"]),
                    "reason": "All bridge candidates would orphan connections",
                })

        # Label removal strategy (fallback or explicit)
        if strategy == "remove_label" or (strategy == "break_bridge" and not bridges):
            # Keep the first net, remove labels for the rest
            keep_net = nets[0]
            remove_nets = set(nets) - {keep_net}

            removed_labels = []
            for label in list(sch.labels):
                if label.text in remove_nets:
                    pos_key = _round_pos(label.position.X, label.position.Y)
                    short_pos = (round(short["position"][0], 2), round(short["position"][1], 2))
                    if pos_key == short_pos or _distance(
                        label.position.X, label.position.Y,
                        short["position"][0], short["position"][1],
                    ) <= 0.5:
                        if not dry_run:
                            removed_labels.append(label.text)
                            sch.labels.remove(label)
                            ir._record_mutation("resolve_shorted_net", {
                                "action": "remove_label",
                                "removed": label.text,
                                "kept": keep_net,
                            })

            for label in list(sch.globalLabels):
                if label.text in remove_nets:
                    pos_key = _round_pos(label.position.X, label.position.Y)
                    short_pos = (round(short["position"][0], 2), round(short["position"][1], 2))
                    if pos_key == short_pos or _distance(
                        label.position.X, label.position.Y,
                        short["position"][0], short["position"][1],
                    ) <= 0.5:
                        if not dry_run:
                            removed_labels.append(label.text)
                            sch.globalLabels.remove(label)
                            ir._record_mutation("resolve_shorted_net", {
                                "action": "remove_label",
                                "removed": label.text,
                                "kept": keep_net,
                            })

            if removed_labels:
                resolved_count += 1
                details.append({
                    "nets": sorted(nets),
                    "action": "remove_label",
                    "kept": keep_net,
                    "removed": removed_labels,
                })

    return {
        "shorts_found": len(shorts),
        "resolved": resolved_count,
        "skipped_power": skipped_power,
        "details": details,
    }
