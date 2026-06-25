"""Wire repair operations -- snapping, grid alignment, dangling removal, bridges, shorts.

Provides wire-level repair functions for schematic ERC auto-fix:
- Wire endpoint snapping to pin positions
- Grid alignment with connectivity preservation
- Dangling wire removal
- Bridge wire detection and breaking
- Wire short resolution

T-10-09: Snap distance limited to 0.01mm tolerance.
T-10-11: Pin Y-inversion uses (sx+px, sy-py) pattern.
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
    except Exception as e:
        # D-11: Log failure at WARNING instead of debug
        logger.warning(
            "Could not build NetPositionIndex for wire snapping, "
            "skipping net safety checks: %s", e,
        )

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


def _point_on_wire_segment(
    px: float,
    py: float,
    wire_endpoints: list[dict[str, Any]],
    tolerance: float = SNAP_TOLERANCE,
) -> bool:
    """Check if a point lies on any wire segment (not just endpoints).

    KiCad wires are axis-aligned (horizontal or vertical). A pin at (10, 25)
    on a wire from (10, 20) to (10, 30) is connected even though no endpoint
    is at (10, 25). This function detects mid-wire connections.

    Args:
        px: Point X coordinate.
        py: Point Y coordinate.
        wire_endpoints: List of wire endpoint dicts with start_x/y, end_x/y.
        tolerance: Maximum distance from the wire line to count as connected.

    Returns:
        True if the point lies on any wire segment within tolerance.
    """
    for we in wire_endpoints:
        sx, sy = we["start_x"], we["start_y"]
        ex, ey = we["end_x"], we["end_y"]

        # Horizontal wire: same Y, different X
        if abs(sy - ey) <= tolerance and abs(py - sy) <= tolerance:
            min_x, max_x = min(sx, ex), max(sx, ex)
            if min_x - tolerance <= px <= max_x + tolerance:
                return True

        # Vertical wire: same X, different Y
        if abs(sx - ex) <= tolerance and abs(px - sx) <= tolerance:
            min_y, max_y = min(sy, ey), max(sy, ey)
            if min_y - tolerance <= py <= max_y + tolerance:
                return True

    return False


def _near_anchor(
    x: float,
    y: float,
    anchor_positions: set[tuple[float, float]],
    tolerance: float = SNAP_TOLERANCE,
) -> bool:
    """Check if a position is within tolerance of any anchor position.

    Replaces exact set membership (``key in anchor_positions``) with a
    distance-based check. Two positions within SNAP_TOLERANCE can round to
    different 2-decimal keys, causing false negatives with set membership.

    Args:
        x: X coordinate to check.
        y: Y coordinate to check.
        anchor_positions: Set of (x, y) anchor positions.
        tolerance: Maximum distance to count as near.

    Returns:
        True if within tolerance of any anchor.
    """
    for ax, ay in anchor_positions:
        if _distance(x, y, ax, ay) <= tolerance:
            return True
    return False


def _round_pos(x: float, y: float) -> tuple[float, float]:
    """Round position to SNAP_TOLERANCE precision for grouping."""
    precision = 2  # 0.01mm precision
    return (round(x, precision), round(y, precision))


# ---------------------------------------------------------------------------
# ERC-driven repair operations (Phase 23)
# ---------------------------------------------------------------------------


def snap_to_grid(ir: SchematicIR, file_path: Any = None, *, grid_mm: float = 0.01) -> dict[str, Any]:
    """Snap off-grid wire endpoints to the nearest grid point.

    Issue #5/#1: Uses tolerance-based clustering (union-find) instead of
    rounding-based grouping. This ensures that co-located endpoints within
    SNAP_TOLERANCE always snap to the SAME target, even when their rounded
    keys differ (e.g., 10.004 vs 10.006 rounding to 10.00 vs 10.01).

    Before snapping, checks that the snapped position won't break existing
    connections to pins, labels, or junctions. Skips snaps that would
    disconnect an anchor. Also skips floating-point noise (< 0.001mm).

    SCHREPAIR-05: Grid-snapping for off-grid wire endpoints.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to schematic file (accepted for erc_auto_fix compatibility,
                   not used by this function).
        grid_mm: Grid spacing in mm (default 0.01 for KiCad 8+).

    Returns:
        Dict with snapped_count, skipped_connectivity, and grid_mm.
    """
    from kicad_agent.validation.grid_check import _is_on_grid

    sch = ir.schematic
    wire_endpoints = ir.get_wire_endpoints()
    if not wire_endpoints:
        return {"snapped_count": 0, "skipped_connectivity": 0, "grid_mm": grid_mm}

    # Build anchor positions: pins, labels, junctions that wires connect to
    pin_positions = ir.get_pin_positions()
    label_positions_list = ir.get_label_positions()
    anchor_positions: set[tuple[float, float]] = set()
    for p in pin_positions:
        anchor_positions.add((round(p["x"], 2), round(p["y"], 2)))
    for lp in label_positions_list:
        anchor_positions.add((round(lp["x"], 2), round(lp["y"], 2)))
    for junction in sch.junctions:
        anchor_positions.add((round(junction.position.X, 2), round(junction.position.Y, 2)))

    # Minimum snap distance -- skip floating-point noise
    MIN_SNAP_DELTA = 0.001

    # Collect all endpoint positions as (exact_x, exact_y, wire_index, point_index)
    endpoints: list[tuple[float, float, int, int]] = []
    for wire_info in wire_endpoints:
        wi = wire_info["wire_index"]
        wire = sch.graphicalItems[wi]
        if not hasattr(wire, "points"):
            continue
        for pi, point in enumerate(wire.points):
            endpoints.append((point.X, point.Y, wi, pi))

    if not endpoints:
        return {"snapped_count": 0, "skipped_connectivity": 0, "grid_mm": grid_mm}

    # Issue #5/#1: Tolerance-based clustering via union-find.
    # Rounding-based grouping (round(x, 2)) can split nearby endpoints
    # into different groups (e.g., 10.004->10.00, 10.006->10.01), causing
    # them to snap to different targets and break connectivity.
    parent = list(range(len(endpoints)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    # Merge endpoints within SNAP_TOLERANCE of each other
    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            if _distance(endpoints[i][0], endpoints[i][1],
                         endpoints[j][0], endpoints[j][1]) <= SNAP_TOLERANCE:
                union(i, j)

    # Build clusters: root -> list of endpoint indices
    clusters: dict[int, list[int]] = {}
    for i in range(len(endpoints)):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    # For each cluster, compute shared snap target and apply
    snapped_count = 0
    skipped_connectivity = 0
    for indices in clusters.values():
        # Use centroid of cluster as the representative position
        cx = sum(endpoints[i][0] for i in indices) / len(indices)
        cy = sum(endpoints[i][1] for i in indices) / len(indices)

        if _is_on_grid(cx, grid_mm) and _is_on_grid(cy, grid_mm):
            continue

        snap_x = round(cx / grid_mm) * grid_mm
        snap_y = round(cy / grid_mm) * grid_mm

        # Skip negligible snaps (floating-point noise)
        if _distance(cx, cy, snap_x, snap_y) < MIN_SNAP_DELTA:
            continue

        # Connectivity check: if ANY endpoint in the cluster is near an
        # anchor, the snap target must also be near an anchor.
        cluster_near_anchor = any(
            _near_anchor(endpoints[i][0], endpoints[i][1], anchor_positions)
            for i in indices
        )
        if cluster_near_anchor and not _near_anchor(snap_x, snap_y, anchor_positions):
            skipped_connectivity += 1
            logger.debug(
                "Skipping snap (%.4f, %.4f) -> (%.4f, %.4f): "
                "would break connection to anchor (cluster of %d endpoints)",
                cx, cy, snap_x, snap_y, len(indices),
            )
            continue

        for i in indices:
            _, _, wi, pi = endpoints[i]
            wire = sch.graphicalItems[wi]
            wire.points[pi].X = snap_x
            wire.points[pi].Y = snap_y
        snapped_count += 1
        ir._record_mutation("snap_to_grid", {
            "group_at": [cx, cy],
            "snapped_to": [snap_x, snap_y],
        })

    return {"snapped_count": snapped_count, "skipped_connectivity": skipped_connectivity, "grid_mm": grid_mm}


def remove_dangling_wires(
    ir: SchematicIR, file_path: Path, *,
    max_length_mm: float | None = None,
    dry_run: bool = False,
    trust_erc: bool = True,
) -> dict[str, Any]:
    """Remove wire segments with unconnected endpoints.

    A dangling wire has at least one endpoint not connected to any pin,
    label, junction, or other wire intersection.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        max_length_mm: Only remove wires shorter than this. None = no limit.
        dry_run: If True, report without modifying.
        trust_erc: If True (default), also remove wires at ERC wire_dangling
            violation positions even if geometric criteria don't flag them.
            This aligns the op with KiCad ERC's electrical definition of
            "dangling" (which includes wires ending at wrong-type labels,
            crossing wires without junctions, etc.). When ERC reports no
            wire_dangling violations, falls back to geometric criteria only.
            [P0-005 fix] See BUGS/P0-005-remove-dangling-wires-criteria-mismatch.md

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
    # LO-02 fix: Track flagged indices in BOTH dry_run and mutate paths so
    # the ERC passthrough doesn't double-count wires that match both
    # geometric and ERC criteria. Previously dry_run skipped the
    # wires_to_remove append, leaving already_flagged empty.
    flagged_indices: set[int] = set()

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

            # LO-01 fix: Normalize geometric entries to include source key
            # so downstream consumers can read d["source"] without KeyError.
            # LO-02 fix: Track flagged index in both branches.
            if dry_run:
                removed.append({
                    "position": [wire_info["start_x"], wire_info["start_y"]],
                    "length": round(_distance(
                        wire_info["start_x"], wire_info["start_y"],
                        wire_info["end_x"], wire_info["end_y"],
                    ), 4),
                    "dry_run": True,
                    "source": "geometric",
                })
            else:
                wires_to_remove.append(wire_idx)
                removed.append({
                    "position": [wire_info["start_x"], wire_info["start_y"]],
                    "length": round(_distance(
                        wire_info["start_x"], wire_info["start_y"],
                        wire_info["end_x"], wire_info["end_y"],
                    ), 4),
                    "source": "geometric",
                })
            flagged_indices.add(wire_idx)

    # P0-005 fix: ERC position passthrough. KiCad ERC uses an electrical
    # definition of "dangling" (includes wrong-type labels, crossing
    # without junction) that is broader than our geometric heuristic.
    # When trust_erc=True, augment the geometric results with any wire
    # whose endpoint matches an ERC wire_dangling violation position.
    erc_removed: list[dict[str, Any]] = []
    # LO-03 fix: Surface ERC lookup failures so callers can distinguish
    # "ERC found nothing" from "ERC failed to run". Previously this fell
    # back silently at DEBUG level.
    erc_fallback_used = False
    if trust_erc:
        try:
            from kicad_agent.ops.erc_parser import extract_violation_positions
            erc_positions = extract_violation_positions(file_path, "wire_dangling")
            erc_pos_set = {_round_pos(p.x, p.y) for p in erc_positions}

            # Check wires not already flagged by geometric criteria.
            # LO-02 fix: Use flagged_indices (populated in both dry_run and
            # mutate paths) instead of set(wires_to_remove) which was empty
            # in dry_run mode.
            already_flagged = flagged_indices
            for wire_info in wire_endpoints:
                wire_idx = wire_info["wire_index"]
                if wire_idx in already_flagged:
                    continue
                start_key = _round_pos(wire_info["start_x"], wire_info["start_y"])
                end_key = _round_pos(wire_info["end_x"], wire_info["end_y"])
                if start_key in erc_pos_set or end_key in erc_pos_set:
                    length = round(_distance(
                        wire_info["start_x"], wire_info["start_y"],
                        wire_info["end_x"], wire_info["end_y"],
                    ), 4)
                    # LO-01 fix: Include dry_run key on ERC entries for
                    # schema consistency with geometric entries.
                    if dry_run:
                        erc_removed.append({
                            "position": [wire_info["start_x"], wire_info["start_y"]],
                            "length": length,
                            "dry_run": True,
                            "source": "erc_passthrough",
                        })
                    else:
                        wires_to_remove.append(wire_idx)
                        erc_removed.append({
                            "position": [wire_info["start_x"], wire_info["start_y"]],
                            "length": length,
                            "dry_run": False,
                            "source": "erc_passthrough",
                        })
        except Exception as exc:
            # LO-03 fix: Elevate to WARNING and signal fallback in return dict.
            logger.warning(
                "trust_erc lookup failed for %s, using geometric only: %s",
                file_path, exc,
            )
            erc_fallback_used = True

    # Merge ERC-passthrough removals into the main removed list so the
    # return value includes both geometric and ERC-sourced removals.
    removed.extend(erc_removed)

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

    result: dict[str, Any] = {
        "removed_count": len(removed),
        "details": removed,
    }
    # LO-03 fix: Surface ERC fallback so callers can distinguish "ERC found
    # nothing" from "ERC failed to run". Only included when trust_erc=True.
    if trust_erc and erc_fallback_used:
        result["erc_fallback_used"] = True
    return result


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

    # Build adjacency: position -> list of (neighbor_position, wire_index)
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
    from kicad_agent.ops.repair_nets import detect_shorted_nets

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
