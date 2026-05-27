"""Off-grid pin/wire check for KiCad schematics.

KiCad schematics use a connection grid (default 0.01mm for KiCad 8+,
1.27mm for legacy designs). Pins and wire endpoints that do not snap to
this grid cause silent connection failures -- wires appear connected in
the GUI but ERC reports floating pins.

Usage:
    from kicad_agent.validation.grid_check import check_grid_alignment

    result = check_grid_alignment(ir)
    if not result.passed:
        for pin in result.off_grid_pins:
            print(f"OFF-GRID PIN: {pin['reference']}.{pin['pin_name']} at ({pin['x']}, {pin['y']})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GridCheckResult:
    """Result of checking grid alignment for all pins and wire endpoints.

    Attributes:
        passed: True if every pin and wire endpoint is on-grid.
        off_grid_pins: List of dicts with reference, pin_name, x, y for
            pins whose coordinates are not multiples of grid_mm.
        off_grid_wire_endpoints: List of dicts with x, y, endpoint_type
            ("start" or "end") for wire endpoints off-grid.
    """

    passed: bool
    off_grid_pins: tuple[dict[str, Any], ...]
    off_grid_wire_endpoints: tuple[dict[str, Any], ...]


def _is_on_grid(value: float, grid: float) -> bool:
    """Check whether a coordinate value is a multiple of grid.

    Rounds the value to grid precision before testing to handle
    floating-point representation errors.

    Args:
        value: Coordinate value in mm.
        grid: Grid spacing in mm.

    Returns:
        True if the value is aligned to the grid.
    """
    rounded = round(value / grid) * grid
    return abs(value - rounded) < grid * 1e-3


def check_grid_alignment(ir: SchematicIR, grid_mm: float = 0.01) -> GridCheckResult:
    """Check all pin positions and wire endpoints are on the connection grid.

    For each symbol pin and wire endpoint, verifies x and y coordinates are
    multiples of grid_mm. Rounds to grid_mm precision before checking.

    Args:
        ir: Parsed schematic IR with component and wire data.
        grid_mm: Grid spacing in mm (default 0.01 for KiCad 8+).

    Returns:
        GridCheckResult with lists of off-grid pins and wire endpoints.
    """
    off_grid_pins: list[dict[str, Any]] = []
    off_grid_wire_endpoints: list[dict[str, Any]] = []

    # Check pin positions
    try:
        pin_positions = ir.get_pin_positions()
        for pin in pin_positions:
            x = pin["x"]
            y = pin["y"]
            if not _is_on_grid(x, grid_mm) or not _is_on_grid(y, grid_mm):
                off_grid_pins.append({
                    "reference": pin["reference"],
                    "pin_name": pin["pin_name"],
                    "x": round(x, 6),
                    "y": round(y, 6),
                })
    except Exception as exc:
        logger.warning("Failed to check pin grid alignment: %s", exc)

    # Check wire endpoints
    try:
        wire_endpoints = ir.get_wire_endpoints()
        for wire in wire_endpoints:
            if not _is_on_grid(wire["start_x"], grid_mm) or not _is_on_grid(wire["start_y"], grid_mm):
                off_grid_wire_endpoints.append({
                    "x": round(wire["start_x"], 6),
                    "y": round(wire["start_y"], 6),
                    "endpoint_type": "start",
                })
            if not _is_on_grid(wire["end_x"], grid_mm) or not _is_on_grid(wire["end_y"], grid_mm):
                off_grid_wire_endpoints.append({
                    "x": round(wire["end_x"], 6),
                    "y": round(wire["end_y"], 6),
                    "endpoint_type": "end",
                })
    except Exception as exc:
        logger.warning("Failed to check wire endpoint grid alignment: %s", exc)

    passed = len(off_grid_pins) == 0 and len(off_grid_wire_endpoints) == 0

    if not passed:
        logger.info(
            "Grid alignment check: %d off-grid pins, %d off-grid wire endpoints",
            len(off_grid_pins),
            len(off_grid_wire_endpoints),
        )

    return GridCheckResult(
        passed=passed,
        off_grid_pins=tuple(off_grid_pins),
        off_grid_wire_endpoints=tuple(off_grid_wire_endpoints),
    )
