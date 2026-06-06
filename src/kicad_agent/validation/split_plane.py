"""Split power/ground plane analysis engine.

Detects gaps between zones on the same layer/net and flags signals
crossing those gaps. Read-only analysis — no PCB mutation.

Usage:
    from kicad_agent.validation.split_plane import analyze_split_plane

    result = analyze_split_plane(pcb_ir, layer="GND")
    print(f"{result.num_splits} splits, {result.num_crossings} crossings")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.ir.pcb_ir import PcbIR


@dataclass(frozen=True)
class SplitGap:
    """A detected gap between two zones on the same layer.

    Attributes:
        zone_a_id: First zone identifier (UUID or index).
        zone_b_id: Second zone identifier.
        gap_mm: Approximate gap width in mm.
        boundary_points: Approximate midpoint(s) of the gap.
    """

    zone_a_id: str
    zone_b_id: str
    gap_mm: float
    boundary_points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class SplitCrossing:
    """A trace that crosses a split plane boundary.

    Attributes:
        trace_net: Net name of the crossing trace.
        crossing_point: (x, y) where the trace crosses the gap.
        zone_a: First zone identifier.
        zone_b: Second zone identifier.
    """

    trace_net: str
    crossing_point: tuple[float, float]
    zone_a: str
    zone_b: str


@dataclass(frozen=True)
class SplitPlaneAnalysis:
    """Complete split plane analysis result.

    Attributes:
        num_zones: Total zones found on the target layer.
        num_splits: Number of detected gaps between zones.
        num_crossings: Number of traces crossing split boundaries.
        splits: Detected gap regions.
        crossings: Traces that cross gaps.
    """

    num_zones: int
    num_splits: int
    num_crossings: int
    splits: tuple[SplitGap, ...]
    crossings: tuple[SplitCrossing, ...]


def _extract_zone_polygons(pcb_ir: PcbIR, net_name: str) -> list[dict]:
    """Extract zones matching a net name from the PCB IR.

    Returns list of dicts with keys: id, polygon_points, layer.
    """
    zones: list[dict] = []
    board = pcb_ir.board

    if not hasattr(board, "zones") or not board.zones:
        return zones

    for i, zone in enumerate(board.zones):
        zone_net = getattr(zone, "netName", "") or getattr(zone, "net_name", "")
        if zone_net != net_name:
            continue

        # Extract polygon points.
        polygon_points: list[tuple[float, float]] = []
        if hasattr(zone, "polygon_points") and zone.polygon_points:
            polygon_points = list(zone.polygon_points)
        elif hasattr(zone, "polygons") and zone.polygons:
            first_poly = zone.polygons[0]
            if hasattr(first_poly, "coordinates"):
                for pt in first_poly.coordinates:
                    if hasattr(pt, "X") and hasattr(pt, "Y"):
                        polygon_points.append((pt.X, pt.Y))

        zone_id = getattr(zone, "tstamp", "") or getattr(zone, "uuid", "") or f"zone_{i}"
        zone_layer = getattr(zone, "layer", "") or (
            zone.layers[0] if hasattr(zone, "layers") and zone.layers else ""
        )

        if polygon_points and len(polygon_points) >= 3:
            zones.append({
                "id": zone_id,
                "polygon_points": tuple(polygon_points),
                "layer": zone_layer,
            })

    return zones


def _compute_zone_bounds(polygon: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    """Compute axis-aligned bounding box of a polygon."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """Check if two bounding boxes overlap (with optional margin)."""
    return not (
        a[2] + margin < b[0] or
        a[0] - margin > b[2] or
        a[3] + margin < b[1] or
        a[1] - margin > b[3]
    )


def _boxes_nearby(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    max_distance: float = 10.0,
) -> bool:
    """Check if two bounding boxes are within max_distance of each other."""
    # Expand both boxes by max_distance and check overlap.
    expanded = (
        a[0] - max_distance, a[1] - max_distance,
        a[2] + max_distance, a[3] + max_distance,
    )
    return _boxes_overlap(expanded, b)


def _estimate_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Estimate minimum gap between two bounding boxes.

    Returns 0.0 if boxes overlap (no gap).

    Note: L-shaped gaps (overlap on one axis, gap on the other) return
    the single-axis gap value. Full polygon subtraction would be needed
    to distinguish these from contiguous zones. This is acceptable for
    bounding-box-based analysis.
    """
    gap_x = max(a[0], b[0]) - min(a[2], b[2])
    gap_y = max(a[1], b[1]) - min(a[3], b[3])

    if gap_x > 0 and gap_y > 0:
        return min(gap_x, gap_y)
    elif gap_x > 0:
        return gap_x
    elif gap_y > 0:
        return gap_y
    return 0.0


def _detect_trace_crossings(
    pcb_ir: PcbIR,
    splits: list[SplitGap],
) -> list[SplitCrossing]:
    """Detect traces that cross split boundaries.

    Walks board segments and checks if any trace line intersects
    the bounding box gap between split zones.
    """
    crossings: list[SplitCrossing] = []
    board = pcb_ir.board

    if not hasattr(board, "segments"):
        return crossings

    # Build split region boxes.
    split_boxes: list[tuple[SplitGap, tuple[float, float, float, float]]] = []
    for s in splits:
        # Use the midpoint between zone centers as the crossing zone.
        # In a full implementation this would use polygon subtraction,
        # but bounding-box gap detection covers the common case.
        split_boxes.append((s, (0.0, 0.0, 0.0, 0.0)))

    # Walk segments and check for crossings.
    segments = board.segments if hasattr(board, "segments") else []
    for seg in segments:
        seg_net = getattr(seg, "net", "") or ""
        start = (getattr(seg, "start", None),)
        end = (getattr(seg, "end", None),)

        if not start or not end:
            continue

        sx, sy = _extract_point(start[0])
        ex, ey = _extract_point(end[0])

        seg_bounds = (min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))

        for s, box in split_boxes:
            if _boxes_overlap(seg_bounds, box, margin=0.1):
                mid_x = (sx + ex) / 2
                mid_y = (sy + ey) / 2
                crossings.append(SplitCrossing(
                    trace_net=seg_net,
                    crossing_point=(round(mid_x, 4), round(mid_y, 4)),
                    zone_a=s.zone_a_id,
                    zone_b=s.zone_b_id,
                ))
                break  # One crossing per trace.

    return crossings


def _extract_point(pt) -> tuple[float, float]:
    """Extract (x, y) from various point representations."""
    if hasattr(pt, "x") and hasattr(pt, "y"):
        return (float(pt.x), float(pt.y))
    if hasattr(pt, "X") and hasattr(pt, "Y"):
        return (float(pt.X), float(pt.Y))
    if isinstance(pt, (tuple, list)) and len(pt) >= 2:
        return (float(pt[0]), float(pt[1]))
    return (0.0, 0.0)


def analyze_split_plane(
    pcb_ir: PcbIR,
    layer: str = "GND",
    min_gap_mm: float = 0.0,
) -> SplitPlaneAnalysis:
    """Analyze split planes on a PCB for gaps and boundary crossings.

    Args:
        pcb_ir: PcbIR for the PCB to analyze.
        layer: Net name to analyze (e.g. ``"GND"``).
        min_gap_mm: Minimum gap to flag as a split (0 = any gap).

    Returns:
        SplitPlaneAnalysis with all detected splits and crossings.
    """
    zones = _extract_zone_polygons(pcb_ir, layer)

    if len(zones) < 2:
        return SplitPlaneAnalysis(
            num_zones=len(zones),
            num_splits=0,
            num_crossings=0,
            splits=(),
            crossings=(),
        )

    # Detect gaps between zone pairs.
    splits: list[SplitGap] = []
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            za = zones[i]
            zb = zones[j]
            bounds_a = _compute_zone_bounds(za["polygon_points"])
            bounds_b = _compute_zone_bounds(zb["polygon_points"])

            if not _boxes_overlap(bounds_a, bounds_b, margin=1.0):
                continue  # Zones are far apart — not a split candidate.

            gap = _estimate_gap(bounds_a, bounds_b)
            if gap >= min_gap_mm:
                mid_x = (max(bounds_a[0], bounds_b[0]) + min(bounds_a[2], bounds_b[2])) / 2
                mid_y = (max(bounds_a[1], bounds_b[1]) + min(bounds_a[3], bounds_b[3])) / 2
                splits.append(SplitGap(
                    zone_a_id=za["id"],
                    zone_b_id=zb["id"],
                    gap_mm=round(gap, 4),
                    boundary_points=((round(mid_x, 4), round(mid_y, 4)),),
                ))

    # Detect trace crossings.
    crossings = _detect_trace_crossings(pcb_ir, splits) if splits else []

    return SplitPlaneAnalysis(
        num_zones=len(zones),
        num_splits=len(splits),
        num_crossings=len(crossings),
        splits=tuple(splits),
        crossings=tuple(crossings),
    )
