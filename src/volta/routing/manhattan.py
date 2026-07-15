"""Manhattan-style L-shaped routing for KiCad PCBs.

Generates simple L-shaped track segments between pads on the same net.
For each net with 2+ pads, pads are sorted by (x, y) and consecutive
pads connected via horizontal-then-vertical L-segments.

This is a fallback router when Freerouting is unavailable or produces
incomplete results. It does NOT account for component body obstacles,
perform clearance checking, or support differential pairs. DRC must
be run after.

Usage:
    from volta.routing.manhattan import route_manhattan
    segments = route_manhattan(netlist, default_layer="F.Cu")
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from volta.routing.bridge import TrackSegment


@dataclass(frozen=True)
class NetOverride:
    """Per-net routing override for layer and width."""

    layer: str = "F.Cu"
    width: float = 0.15


def route_manhattan(
    netlist: dict[str, list[tuple[float, float]]],
    *,
    default_layer: str = "F.Cu",
    default_width: float = 0.15,
    net_overrides: dict[str, NetOverride | dict[str, Any]] | None = None,
) -> list[TrackSegment]:
    """Generate Manhattan L-shaped routing segments.

    For each net with 2+ pads, sorts pads by (x, y) and generates
    horizontal-then-vertical L-segments between consecutive pads.
    Zero-length segments (where start == end within tolerance) are skipped.

    Args:
        netlist: Dict mapping net names to lists of (x, y) pad positions.
        default_layer: Default copper layer for segments.
        default_width: Default trace width in mm.
        net_overrides: Optional per-net overrides as dict mapping net name
            to NetOverride or dict with 'layer' and 'width' keys.

    Returns:
        List of TrackSegment objects ready for S-expression serialization.
    """
    overrides: dict[str, NetOverride] = {}
    if net_overrides:
        for name, override in net_overrides.items():
            if isinstance(override, NetOverride):
                overrides[name] = override
            elif isinstance(override, dict):
                overrides[name] = NetOverride(
                    layer=override.get("layer", default_layer),
                    width=override.get("width", default_width),
                )

    segments: list[TrackSegment] = []

    for net_name, pads in netlist.items():
        if len(pads) < 2:
            continue

        override = overrides.get(net_name)
        layer = override.layer if override else default_layer
        width = override.width if override else default_width

        # Sort pads by (x, y) for deterministic routing order
        sorted_pads = sorted(pads, key=lambda p: (p[0], p[1]))

        for i in range(len(sorted_pads) - 1):
            x1, y1 = sorted_pads[i]
            x2, y2 = sorted_pads[i + 1]

            # Horizontal segment: (x1, y1) -> (x2, y1)
            if abs(x2 - x1) > 0.01:
                segments.append(TrackSegment(
                    start_x=x1,
                    start_y=y1,
                    end_x=x2,
                    end_y=y1,
                    width=width,
                    layer=layer,
                    net=net_name,
                ))

            # Vertical segment: (x2, y1) -> (x2, y2)
            if abs(y2 - y1) > 0.01:
                segments.append(TrackSegment(
                    start_x=x2,
                    start_y=y1,
                    end_x=x2,
                    end_y=y2,
                    width=width,
                    layer=layer,
                    net=net_name,
                ))

    return segments


def segments_to_sexpr(segments: list[TrackSegment]) -> str:
    """Convert TrackSegment list to KiCad S-expression string.

    Args:
        segments: List of TrackSegment objects.

    Returns:
        S-expression string with (segment ...) blocks, ready for insertion.
    """
    lines = []
    for seg in segments:
        lines.append(seg.to_sexpr(uuid_tag=str(uuid.uuid4())))
    return "\n".join(lines) + "\n"
