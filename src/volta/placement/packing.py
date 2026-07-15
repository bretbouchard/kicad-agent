"""Shelf-based bin packing for overlap-free component placement.

Produces provably overlap-free initial positions using a Next-Fit
Decreasing Height (NFDH) shelf packing strategy with clearance
expansion. All component bounding boxes are expanded by min_clearance
before packing, ensuring that adjacent placements maintain the required
gap.

Also provides a push-apart resolver for resolving residual overlaps
that may result from SA refinement or external modifications.

Usage::

    from volta.placement.packing import (
        pack_components_no_overlap,
        resolve_overlaps,
        PackResult,
    )

    result = pack_components_no_overlap(
        component_sizes={"R1": (3.0, 1.5), "C1": (2.0, 2.0)},
        board_width=100.0,
        board_height=80.0,
        min_clearance=1.0,
    )
    print(result.positions)  # {"R1": (x, y, 0.0), "C1": (x, y, 0.0)}
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PackResult:
    """Result of overlap-free shelf packing initialization.

    Attributes:
        positions: Mapping of ref to (x_center, y_center, rotation_degrees).
        packed_count: Number of components successfully placed.
        unpacked_refs: Components that could not fit on the board.
        utilization: Fraction of board area used (0.0 to 1.0).
    """

    positions: dict[str, tuple[float, float, float]]
    packed_count: int
    unpacked_refs: tuple[str, ...]
    utilization: float


def pack_components_no_overlap(
    component_sizes: dict[str, tuple[float, float]],
    board_width: float,
    board_height: float,
    min_clearance: float = 1.0,
    fixed_positions: dict[str, tuple[float, float, float]] | None = None,
    keepout_zones: list[tuple[float, float, float, float]] | None = None,
) -> PackResult:
    """Pack components onto board using shelf-based bin packing.

    Algorithm (Next-Fit Decreasing Height):
    1. Clearance-expand all bounding boxes by min_clearance.
    2. Convert fixed_positions and keepout_zones to obstacle rectangles.
    3. Sort free components by area (largest first).
    4. Place onto shelves (y-stacked rows), checking obstacle overlap.

    Args:
        component_sizes: Mapping of ref to (width_mm, height_mm).
        board_width: Board width in mm.
        board_height: Board height in mm.
        min_clearance: Minimum clearance between components in mm.
        fixed_positions: Components already placed (treated as obstacles).
        keepout_zones: Forbidden rectangular regions.

    Returns:
        PackResult with provably overlap-free positions.
    """
    fixed_positions = fixed_positions or {}
    keepout_zones = keepout_zones or []
    margin = min_clearance

    # Build obstacle rectangles: (x1, y1, x2, y2)
    obstacles: list[tuple[float, float, float, float]] = list(keepout_zones)

    for ref, (fx, fy, _frot) in fixed_positions.items():
        if ref in component_sizes:
            w, h = component_sizes[ref]
        else:
            w = h = 2.0
        half_w = w / 2.0 + margin
        half_h = h / 2.0 + margin
        obstacles.append((fx - half_w, fy - half_h, fx + half_w, fy + half_h))

    # Build free component list with effective (clearance-expanded) sizes
    free_entries: list[tuple[str, float, float, float]] = []
    for ref, (w, h) in component_sizes.items():
        if ref in fixed_positions:
            continue
        eff_w = w + min_clearance
        eff_h = h + min_clearance
        area = eff_w * eff_h
        free_entries.append((ref, eff_w, eff_h, area))

    # Sort by area descending (largest first — standard bin packing heuristic)
    free_entries.sort(key=lambda e: e[3], reverse=True)

    # Shelf packing
    positions: dict[str, tuple[float, float, float]] = {}
    unpacked: list[str] = []

    # Shelf state
    shelf_y = margin
    shelf_height = 0.0
    shelf_x = margin
    board_area_used = 0.0

    for ref, eff_w, eff_h, _area in free_entries:
        placed = False

        # Try current shelf first
        if shelf_x + eff_w <= board_width - margin and shelf_y + eff_h <= board_height - margin:
            cx = shelf_x + eff_w / 2.0
            cy = shelf_y + eff_h / 2.0
            if not _overlaps_any_obstacle(cx, cy, eff_w, eff_h, obstacles):
                positions[ref] = (cx, cy, 0.0)
                board_area_used += eff_w * eff_h
                shelf_x += eff_w
                shelf_height = max(shelf_height, eff_h)
                placed = True

        # Try next shelf if current shelf is full or obstacle blocked
        if not placed:
            new_shelf_y = shelf_y + shelf_height + margin
            if margin + eff_w <= board_width - margin and new_shelf_y + eff_h <= board_height - margin:
                # Scan across new shelf, skipping obstacles
                scan_x = margin
                while scan_x + eff_w <= board_width - margin:
                    cx = scan_x + eff_w / 2.0
                    cy = new_shelf_y + eff_h / 2.0
                    if not _overlaps_any_obstacle(cx, cy, eff_w, eff_h, obstacles):
                        positions[ref] = (cx, cy, 0.0)
                        board_area_used += eff_w * eff_h
                        # Start a new shelf row
                        shelf_y = new_shelf_y
                        shelf_x = scan_x + eff_w
                        shelf_height = eff_h
                        placed = True
                        break
                    scan_x += eff_w * 0.1  # Fine-grained scanning past obstacles

        if not placed:
            unpacked.append(ref)

    total_board_area = board_width * board_height
    utilization = board_area_used / total_board_area if total_board_area > 0 else 0.0

    return PackResult(
        positions=positions,
        packed_count=len(positions),
        unpacked_refs=tuple(unpacked),
        utilization=utilization,
    )


def resolve_overlaps(
    positions: dict[str, tuple[float, float, float]],
    component_sizes: dict[str, float],
    board_width: float,
    board_height: float,
    min_clearance: float = 1.0,
    max_iterations: int = 100,
) -> dict[str, tuple[float, float, float]]:
    """Resolve overlapping components by iteratively pushing them apart.

    For each overlapping pair, compute the overlap vector and push each
    component away by half. Clamp to board bounds after each iteration.

    Args:
        positions: Current placement positions.
        component_sizes: Component bounding box sizes (diameter in mm).
        board_width: Board width in mm.
        board_height: Board height in mm.
        min_clearance: Minimum clearance in mm.
        max_iterations: Maximum push iterations.

    Returns:
        Updated positions with overlaps resolved (best-effort).
    """
    margin = min_clearance
    current = dict(positions)
    refs = list(current.keys())
    n = len(refs)

    for _iteration in range(max_iterations):
        overlap_found = False

        for i in range(n):
            ri = refs[i]
            xi, yi, roti = current[ri]
            si = component_sizes.get(ri, 2.0) / 2.0 + margin

            for j in range(i + 1, n):
                rj = refs[j]
                xj, yj, rotj = current[rj]
                sj = component_sizes.get(rj, 2.0) / 2.0 + margin

                dx = xi - xj
                dy = yi - yj
                dist = math.hypot(dx, dy)
                min_dist = si + sj

                if dist < min_dist and dist > 1e-9:
                    overlap_found = True
                    # Push apart: move each component by half the overlap
                    push = (min_dist - dist) / 2.0 + 0.01  # small extra gap
                    nx = dx / dist
                    ny = dy / dist

                    new_xi = xi + nx * push
                    new_yi = yi + ny * push
                    new_xj = xj - nx * push
                    new_yj = yj - ny * push

                    # Clamp to board bounds
                    new_xi = max(margin, min(board_width - margin, new_xi))
                    new_yi = max(margin, min(board_height - margin, new_yi))
                    new_xj = max(margin, min(board_width - margin, new_xj))
                    new_yj = max(margin, min(board_height - margin, new_yj))

                    current[ri] = (new_xi, new_yi, roti)
                    current[rj] = (new_xj, new_yj, rotj)
                    # Update xi, yi for subsequent j checks
                    xi, yi = new_xi, new_yi

                elif dist < 1e-9:
                    # Components at exact same position — push apart arbitrarily
                    overlap_found = True
                    current[ri] = (xi + min_dist, yi, roti)
                    current[rj] = (xj - min_dist, yj, rotj)

        if not overlap_found:
            break

    return current


def _overlaps_any_obstacle(
    cx: float,
    cy: float,
    w: float,
    h: float,
    obstacles: list[tuple[float, float, float, float]],
) -> bool:
    """Check if a rectangle centered at (cx, cy) with size (w, h) overlaps any obstacle."""
    x1 = cx - w / 2.0
    y1 = cy - h / 2.0
    x2 = cx + w / 2.0
    y2 = cy + h / 2.0

    for ox1, oy1, ox2, oy2 in obstacles:
        if x1 < ox2 and x2 > ox1 and y1 < oy2 and y2 > oy1:
            return True
    return False
