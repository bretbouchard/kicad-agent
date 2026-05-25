"""Bridge from routing results to KiCad PCB track segments.

Converts RouteResult waypoints into KiCad (segment ...) S-expressions
that can be inserted into a .kicad_pcb file via the PcbIR layer.

This is the critical missing link between the routing engine and
the IR/serializer pipeline (Council C6 fix).

Usage:
    from kicad_agent.routing.bridge import route_to_segments
    from kicad_agent.routing.constraints import RoutingConstraints

    segments = route_to_segments(route_results, constraints)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.pathfinder import RouteResult


@dataclass(frozen=True)
class TrackSegment:
    """A single KiCad PCB track segment.

    Attributes:
        start_x: Start X coordinate in mm.
        start_y: Start Y coordinate in mm.
        end_x: End X coordinate in mm.
        end_y: End Y coordinate in mm.
        width: Trace width in mm.
        layer: Copper layer name (e.g., "F.Cu").
        net: Net name (may be "" for unconnected).
    """

    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float
    layer: str
    net: str

    def to_sexpr(self, uuid_tag: str = "") -> str:
        """Serialize to KiCad S-expression format.

        Args:
            uuid_tag: Optional UUID for the segment.

        Returns:
            S-expression string like (segment (start ...) ...).
        """
        parts = [
            f"  (segment",
            f"    (start {self.start_x:.4f} {self.start_y:.4f})",
            f"    (end {self.end_x:.4f} {self.end_y:.4f})",
            f"    (width {self.width:.4f})",
            f"    (layer \"{self.layer}\")",
        ]
        if self.net:
            parts.append(f"    (net 0 \"{self.net}\")")
        if uuid_tag:
            parts.append(f"    (uuid {uuid_tag})")
        parts.append("  )")
        return "\n".join(parts)


def route_to_segments(
    results: dict[str, RouteResult],
    constraints: RoutingConstraints | None = None,
    layer: str = "F.Cu",
) -> list[TrackSegment]:
    """Convert routing results into KiCad track segments.

    For each RouteResult, converts the waypoint path into individual
    track segments between consecutive waypoints.

    Args:
        results: Dict mapping net names to RouteResult objects.
        constraints: Routing constraints for trace width. Uses defaults if None.
        layer: Copper layer for all segments. Default F.Cu (top copper).

    Returns:
        List of TrackSegment objects ready for IR insertion.
    """
    constraints = constraints or RoutingConstraints()
    segments: list[TrackSegment] = []

    for net_name, result in results.items():
        if not result.success or len(result.path) < 2:
            continue

        for i in range(len(result.path) - 1):
            sx, sy = result.path[i]
            ex, ey = result.path[i + 1]
            segments.append(TrackSegment(
                start_x=round(sx, 4),
                start_y=round(sy, 4),
                end_x=round(ex, 4),
                end_y=round(ey, 4),
                width=constraints.trace_width_mm,
                layer=layer,
                net=net_name,
            ))

    return segments


def segments_to_sexpr(segments: list[TrackSegment]) -> str:
    """Convert track segments to a block of KiCad S-expressions.

    Args:
        segments: List of TrackSegment objects.

    Returns:
        S-expression string block suitable for insertion into a .kicad_pcb file.
    """
    return "\n".join(seg.to_sexpr() for seg in segments)
