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
    net_id: int = 0

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
            parts.append(f'    (net "{self.net}")')
        if uuid_tag:
            parts.append(f"    (uuid {uuid_tag})")
        parts.append("  )")
        return "\n".join(parts)


def route_to_segments(
    results: dict[str, RouteResult],
    constraints: RoutingConstraints | None = None,
    layer: str = "F.Cu",
    net_id_map: dict[str, int] | None = None,
) -> list[TrackSegment]:
    """Convert routing results into KiCad track segments.

    For each RouteResult, converts the waypoint path into individual
    track segments between consecutive waypoints.

    Args:
        results: Dict mapping net names to RouteResult objects.
        constraints: Routing constraints for trace width. Uses defaults if None.
        layer: Copper layer for all segments. Default F.Cu (top copper).
        net_id_map: Optional mapping from net name to KiCad net ID.
            When provided, segments get correct net IDs for output.

    Returns:
        List of TrackSegment objects ready for IR insertion.
    """
    constraints = constraints or RoutingConstraints()
    segments: list[TrackSegment] = []

    for net_name, result in results.items():
        if not result.success or len(result.path) < 2:
            continue

        net_id = net_id_map.get(net_name, 0) if net_id_map else 0

        for i in range(len(result.path) - 1):
            p0 = result.path[i]
            p1 = result.path[i + 1]
            sx, sy = p0[0], p0[1]
            ex, ey = p1[0], p1[1]
            segments.append(TrackSegment(
                start_x=round(sx, 4),
                start_y=round(sy, 4),
                end_x=round(ex, 4),
                end_y=round(ey, 4),
                width=constraints.trace_width_mm,
                layer=layer,
                net=net_name,
                net_id=net_id,
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


@dataclass(frozen=True)
class ViaSegment:
    """A KiCad via connecting two copper layers.

    Attributes:
        x: X coordinate in mm.
        y: Y coordinate in mm.
        from_layer: Starting copper layer name.
        to_layer: Ending copper layer name.
        diameter: Via pad diameter in mm.
        drill: Via drill hole diameter in mm.
        net: Net name (may be "" for unconnected).
    """

    x: float
    y: float
    from_layer: str
    to_layer: str
    diameter: float
    drill: float
    net: str
    net_id: int = 0

    def to_sexpr(self, uuid_tag: str = "") -> str:
        """Serialize to KiCad via S-expression format.

        Args:
            uuid_tag: Optional UUID for the via.

        Returns:
            S-expression string like (via (at ...) ...).
        """
        parts = [
            "  (via",
            f"    (at {self.x:.4f} {self.y:.4f})",
            f"    (size {self.diameter:.4f})",
            f"    (drill {self.drill:.4f})",
            f'    (layers "{self.from_layer}" "{self.to_layer}")',
        ]
        if self.net:
            parts.append(f'    (net "{self.net}")')
        if uuid_tag:
            parts.append(f"    (uuid {uuid_tag})")
        parts.append("  )")
        return "\n".join(parts)


def route_to_segments_multilayer(
    results: dict[str, RouteResult],
    constraints: RoutingConstraints | None = None,
    net_id_map: dict[str, int] | None = None,
) -> list[TrackSegment | ViaSegment]:
    """Convert 3D routing results into track segments and vias.

    For each RouteResult with 3D (x, y, layer) path waypoints, produces:
    - TrackSegment for consecutive same-layer points
    - ViaSegment at layer transitions

    Uses constraints.effective_trace_width(layer) for per-layer trace widths
    and constraints.via_diameter_mm / via_drill_mm for via dimensions.

    Args:
        results: Dict mapping net names to RouteResult objects with 3D paths.
        constraints: Routing constraints for trace/via dimensions.
            Uses defaults if None.
        net_id_map: Optional mapping from net name to KiCad net ID.
            When provided, segments/vias get correct net IDs for output.

    Returns:
        List of TrackSegment and ViaSegment objects.
    """
    constraints = constraints or RoutingConstraints()
    segments: list[TrackSegment | ViaSegment] = []

    for net_name, result in results.items():
        if not result.success or len(result.path) < 2:
            continue

        net_id = net_id_map.get(net_name, 0) if net_id_map else 0

        for i in range(len(result.path) - 1):
            p0 = result.path[i]
            p1 = result.path[i + 1]

            # Check for layer transition.
            if len(p0) >= 3 and len(p1) >= 3 and p0[2] != p1[2]:
                # Layer transition -- create a via at midpoint.
                via_x = round((p0[0] + p1[0]) / 2.0, 4)
                via_y = round((p0[1] + p1[1]) / 2.0, 4)
                segments.append(ViaSegment(
                    x=via_x,
                    y=via_y,
                    from_layer=p0[2],
                    to_layer=p1[2],
                    diameter=constraints.via_diameter_mm,
                    drill=constraints.via_drill_mm,
                    net=net_name,
                    net_id=net_id,
                ))
            else:
                # Same-layer segment.
                sx, sy = p0[0], p0[1]
                ex, ey = p1[0], p1[1]
                layer = p0[2] if len(p0) >= 3 else "F.Cu"
                segments.append(TrackSegment(
                    start_x=round(sx, 4),
                    start_y=round(sy, 4),
                    end_x=round(ex, 4),
                    end_y=round(ey, 4),
                    width=constraints.effective_trace_width(layer),
                    layer=layer,
                    net=net_name,
                    net_id=net_id,
                ))

    return segments
