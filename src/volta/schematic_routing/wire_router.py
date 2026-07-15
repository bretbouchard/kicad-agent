"""Generate wire modifications from routing targets.

For each RoutingTarget, produces either:
  - same_axis: modify existing wire endpoint coordinate
  - l_shape: keep existing wire, add new wire segment(s)

All coordinates snapped to 2.54mm grid.

Usage:
    from volta.schematic_routing.wire_router import generate_fixes

    fixes = generate_fixes(targets, grid=2.54)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from volta.schematic_routing.target_finder import RoutingTarget


@dataclass
class WireFix:
    """A wire modification to apply."""
    file: str
    fix_type: str  # "extend" (modify existing wire) or "new_segment" (add wire)
    old_endpoint: tuple[float, float]  # Original endpoint to change (from file, not ERC)
    new_endpoint: tuple[float, float]  # New endpoint (same_axis only)
    new_wire_points: Optional[list[tuple[float, float]]] = None  # For L-shaped routing
    net_name: str = ""
    target_ref: str = ""
    target_pin: str = ""
    distance: float = 0.0
    sheet: str = ""
    wire_endpoints: Optional[tuple[tuple[float, float], tuple[float, float]]] = None  # Actual wire coords from file


def _snap_to_grid(value: float, grid: float) -> float:
    """Snap a coordinate value to the nearest grid point.

    Args:
        value: Coordinate value in mm.
        grid: Grid spacing in mm (typically 2.54 for KiCad default).

    Returns:
        Value snapped to the nearest grid point, rounded to 2 decimal places.
    """
    snapped = round(round(value / grid) * grid, 2)
    return snapped


def generate_fixes(
    targets: list[RoutingTarget],
    grid: float = 2.54,
) -> list[WireFix]:
    """Generate wire fixes from routing targets.

    Args:
        targets: Routing targets from target_finder.
        grid: Grid spacing in mm for coordinate snapping.

    Returns:
        List of WireFix objects ready to apply.
    """
    fixes = []

    for target in targets:
        # Snap coordinates to grid to avoid endpoint_off_grid ERC violations
        # R-BUG-004 fix: use grid snapping instead of just rounding to 2 decimals
        target_pos = (_snap_to_grid(target.target_x, grid), _snap_to_grid(target.target_y, grid))
        violation_pos = (_snap_to_grid(target.violation_x, grid), _snap_to_grid(target.violation_y, grid))

        # Pass actual wire endpoints from the file for safe replacement
        wire_eps = None
        if target.wire_start and target.wire_end:
            wire_eps = (target.wire_start, target.wire_end)

        if target.routing_type == "same_axis":
            # Extend the DANGLING wire endpoint to the target position.
            # The violation is at the pin body (connection point). The wire
            # connects the pin to a dangling endpoint. We extend the dangling
            # end, NOT the pin end — extending the pin end would disconnect it.
            dangling_ep = _find_dangling_endpoint(
                violation_pos, target.wire_start, target.wire_end,
            )
            fixes.append(WireFix(
                file=target.file,
                fix_type="extend",
                old_endpoint=dangling_ep,
                new_endpoint=target_pos,
                net_name=target.net_name,
                target_ref=target.target_ref,
                target_pin=target.target_pin,
                distance=target.distance,
                sheet=target.sheet,
                wire_endpoints=wire_eps,
            ))

        elif target.routing_type == "l_shape":
            # R-BUG-008 fix: implement L-shaped routing with grid-snapped corners.
            # Route from dangling endpoint to corner, then corner to target pin.
            # Two fix entries: extend existing wire to corner + new wire segment.
            dangling_ep = _find_dangling_endpoint(
                violation_pos, target.wire_start, target.wire_end,
            )

            # Choose L-shape direction: prefer the axis with shorter total travel
            # Option A: horizontal-first (dangling_x, target_y) -> target
            corner_a = (_snap_to_grid(dangling_ep[0], grid), _snap_to_grid(target_pos[1], grid))
            dist_a = abs(corner_a[0] - dangling_ep[0]) + abs(corner_a[1] - dangling_ep[1]) + \
                     abs(target_pos[0] - corner_a[0]) + abs(target_pos[1] - corner_a[1])

            # Option B: vertical-first (target_x, dangling_y) -> target
            corner_b = (_snap_to_grid(target_pos[0], grid), _snap_to_grid(dangling_ep[1], grid))
            dist_b = abs(corner_b[0] - dangling_ep[0]) + abs(corner_b[1] - dangling_ep[1]) + \
                     abs(target_pos[0] - corner_b[0]) + abs(target_pos[1] - corner_b[1])

            # Use shorter path, fall back to option A if equal
            corner = corner_a if dist_a <= dist_b else corner_b

            # Skip degenerate L-shapes that are actually same-axis
            if corner == dangling_ep or corner == target_pos:
                continue

            # Fix 1: extend existing wire endpoint to the corner
            fixes.append(WireFix(
                file=target.file,
                fix_type="extend",
                old_endpoint=dangling_ep,
                new_endpoint=corner,
                net_name=target.net_name,
                target_ref=target.target_ref,
                target_pin=target.target_pin,
                distance=target.distance,
                sheet=target.sheet,
                wire_endpoints=wire_eps,
            ))

            # Fix 2: add new wire segment from corner to target pin
            fixes.append(WireFix(
                file=target.file,
                fix_type="new_segment",
                old_endpoint=(0, 0),  # unused for new_segment
                new_endpoint=(0, 0),  # unused for new_segment
                new_wire_points=[corner, target_pos],
                net_name=target.net_name,
                target_ref=target.target_ref,
                target_pin=target.target_pin,
                distance=target.distance,
                sheet=target.sheet,
                wire_endpoints=None,
            ))

    return fixes


def _find_dangling_endpoint(
    violation_pos: tuple[float, float],
    wire_start: Optional[tuple[float, float]],
    wire_end: Optional[tuple[float, float]],
) -> tuple[float, float]:
    """Find the dangling endpoint of the wire (not at the violation/pin position).

    The violation is at the pin body (connection point). The wire has two
    endpoints: one at the pin and one dangling. We return the dangling one.
    """
    if wire_start and wire_end:
        ws = _round_pos(wire_start)
        we = _round_pos(wire_end)
        vp = _round_pos(violation_pos)
        if ws == vp:
            return we
        elif we == vp:
            return ws
    # Fallback: return violation position (shouldn't happen with valid data)
    return violation_pos


def _round_pos(pos: tuple[float, float]) -> tuple[float, float]:
    """Round position for comparison."""
    return (round(pos[0], 2), round(pos[1], 2))
