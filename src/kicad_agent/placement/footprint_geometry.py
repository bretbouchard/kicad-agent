"""Footprint geometry extraction for layout-aware placement.

Extracts real component bounding boxes from PcbIR, replacing the
scalar 2.0mm estimated_size heuristic with actual footprint dimensions.

Usage::

    from kicad_agent.placement.footprint_geometry import (
        ComponentGeometry,
        extract_footprint_geometry,
    )

    geometry = extract_footprint_geometry(pcb_ir)
    for ref, geo in geometry.items():
        print(f"{ref}: {geo.width_mm:.1f} x {geo.height_mm:.1f} mm")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_WIDTH = 2.0
"""Default width in mm when footprint has no pads."""

_DEFAULT_HEIGHT = 2.0
"""Default height in mm when footprint has no pads."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentGeometry:
    """Real footprint bounding box and geometry data.

    Attributes:
        reference: Component reference designator (e.g., "U1").
        width_mm: Bounding box width in mm.
        height_mm: Bounding box height in mm.
        pad_positions: Pad (x, y) positions relative to footprint origin.
        thermal_area_mm2: Conservative thermal area estimate (width * height).
        centroid_offset: Offset from footprint origin to bounding box center.
    """

    reference: str
    width_mm: float
    height_mm: float
    pad_positions: tuple[tuple[float, float], ...]
    thermal_area_mm2: float
    centroid_offset: tuple[float, float]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_footprint_geometry(
    pcb_ir: PcbIR | None = None,
) -> dict[str, ComponentGeometry]:
    """Extract real footprint geometry from PcbIR.

    For each footprint in the PCB, computes bounding box from pad positions
    and sizes. Falls back to 2.0x2.0mm default for footprints without pads.

    Args:
        pcb_ir: PcbIR instance with footprints, or None for empty result.

    Returns:
        Dict mapping component reference to ComponentGeometry.
    """
    if pcb_ir is None:
        return {}

    result: dict[str, ComponentGeometry] = {}

    for fp in pcb_ir.footprints:
        ref = fp.reference
        if not ref:
            continue

        pads = fp.pads if hasattr(fp, "pads") else []
        if not pads:
            # No pads -- use default dimensions
            result[ref] = ComponentGeometry(
                reference=ref,
                width_mm=_DEFAULT_WIDTH,
                height_mm=_DEFAULT_HEIGHT,
                pad_positions=(),
                thermal_area_mm2=0.0,
                centroid_offset=(0.0, 0.0),
            )
            continue

        # Collect pad extents accounting for pad size
        pad_positions: list[tuple[float, float]] = []
        x_extents: list[float] = []
        y_extents: list[float] = []

        for pad in pads:
            # Pad position (x, y, angle)
            pad_x = pad.at[0]
            pad_y = pad.at[1]
            pad_positions.append((pad_x, pad_y))

            # Pad size (width, height)
            pad_size = pad.size if hasattr(pad, "size") else None
            if pad_size and len(pad_size) >= 2:
                half_w = pad_size[0] / 2.0
                half_h = pad_size[1] / 2.0
            else:
                half_w = 0.0
                half_h = 0.0

            x_extents.append(pad_x - half_w)
            x_extents.append(pad_x + half_w)
            y_extents.append(pad_y - half_h)
            y_extents.append(pad_y + half_h)

        min_x = min(x_extents)
        max_x = max(x_extents)
        min_y = min(y_extents)
        max_y = max(y_extents)

        width = max_x - min_x
        height = max_y - min_y

        # Ensure non-zero dimensions
        if width <= 0:
            width = _DEFAULT_WIDTH
        if height <= 0:
            height = _DEFAULT_HEIGHT

        centroid_x = (min_x + max_x) / 2.0
        centroid_y = (min_y + max_y) / 2.0

        result[ref] = ComponentGeometry(
            reference=ref,
            width_mm=width,
            height_mm=height,
            pad_positions=tuple(pad_positions),
            thermal_area_mm2=width * height,
            centroid_offset=(centroid_x, centroid_y),
        )

    return result
