"""Board outline extraction from KiCad Edge.Cuts graphic items.

SI-06: Extracts board outline from Edge.Cuts layer graphic items
(line segments, arcs, circles) and returns a Shapely Polygon.

Handles:
  - GrLine: straight line segments -> LineString
  - GrArc: arc segments defined by start, mid, end -> approximate with LineString
  - GrCircle: circles defined by center and end (point on circumference) -> Polygon
  - Multiple disjoint outlines (panelized boards) -> MultiPolygon

All coordinates in millimeters.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.ops import linemerge, polygonize, unary_union

logger = logging.getLogger(__name__)

# Number of segments used to approximate each arc
_ARC_SEGMENTS: int = 32


def _arc_to_linestring(
    start_x: float,
    start_y: float,
    mid_x: float,
    mid_y: float,
    end_x: float,
    end_y: float,
    num_segments: int = _ARC_SEGMENTS,
) -> LineString:
    """Approximate a circular arc defined by start, mid, end points.

    Computes the arc center via perpendicular bisector intersection,
    then interpolates points along the arc.

    Args:
        start_x, start_y: Arc start point.
        mid_x, mid_y: Arc midpoint (point on the arc).
        end_x, end_y: Arc end point.
        num_segments: Number of line segments to approximate the arc.

    Returns:
        LineString approximating the arc. Falls back to a simple
        3-point LineString if center computation fails (collinear points).
    """
    # Compute perpendicular bisector of (start, mid)
    sm_mx = (start_x + mid_x) / 2.0
    sm_my = (start_y + mid_y) / 2.0
    dx_sm = mid_x - start_x
    dy_sm = mid_y - start_y

    # Compute perpendicular bisector of (mid, end)
    me_mx = (mid_x + end_x) / 2.0
    me_my = (mid_y + end_y) / 2.0
    dx_me = end_x - mid_x
    dy_me = end_y - mid_y

    # Direction vectors for the bisectors (perpendicular to chord)
    # Bisector 1 direction: (-dy_sm, dx_sm)
    # Bisector 2 direction: (-dy_me, dx_me)
    # Solve: sm_origin + t * bisector1_dir == me_origin + s * bisector2_dir
    # => sm_mx + t * (-dy_sm) = me_mx + s * (-dy_me)
    # => sm_my + t * dx_sm = me_my + s * dx_me
    # Matrix: [[-dy_sm, dy_me], [dx_sm, -dx_me]] * [t, s]^T = [me_mx - sm_mx, me_my - sm_my]^T

    det = (-dy_sm) * (-dx_me) - (dy_me) * (dx_sm)

    if abs(det) < 1e-10:
        # Collinear or near-collinear points: fall back to simple line
        return LineString(
            [(start_x, start_y), (mid_x, mid_y), (end_x, end_y)]
        )

    rhs_x = me_mx - sm_mx
    rhs_y = me_my - sm_my

    t = (rhs_x * (-dx_me) - rhs_y * (dy_me)) / det

    center_x = sm_mx + t * (-dy_sm)
    center_y = sm_my + t * dx_sm

    radius = math.hypot(start_x - center_x, start_y - center_y)

    if radius < 1e-10:
        return LineString(
            [(start_x, start_y), (mid_x, mid_y), (end_x, end_y)]
        )

    # Compute angles
    start_angle = math.atan2(start_y - center_y, start_x - center_x)
    mid_angle = math.atan2(mid_y - center_y, mid_x - center_x)
    end_angle = math.atan2(end_y - center_y, end_x - center_x)

    # Determine arc direction: check if mid point is on the shorter arc
    # going from start_angle to end_angle in the positive (CCW) direction
    def _angle_diff(a: float, b: float) -> float:
        """Signed angle from a to b in [-pi, pi]."""
        d = b - a
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        return d

    ccw_to_end = _angle_diff(start_angle, end_angle)
    ccw_to_mid = _angle_diff(start_angle, mid_angle)

    # If mid is between start and end in CCW direction, arc is CCW
    # Otherwise, arc is CW
    if ccw_to_end > 0:
        # CCW arc from start to end
        arc_is_ccw = (0 < ccw_to_mid < ccw_to_end)
    else:
        # CW arc from start to end (which is CCW the long way)
        arc_is_ccw = not (ccw_to_end < ccw_to_mid < 0)

    # Generate interpolated points
    points: list[tuple[float, float]] = []
    for i in range(num_segments + 1):
        frac = i / num_segments
        if arc_is_ccw:
            angle = start_angle + frac * ccw_to_end
        else:
            angle = start_angle + frac * (ccw_to_end - 2 * math.pi)
        px = center_x + radius * math.cos(angle)
        py = center_y + radius * math.sin(angle)
        points.append((px, py))

    return LineString(points)


def _is_gr_line(item: Any) -> bool:
    """Check if item is a GrLine (has start and end, no mid, no center)."""
    return (
        hasattr(item, "start")
        and hasattr(item, "end")
        and not hasattr(item, "mid")
        and not hasattr(item, "center")
    )


def _is_gr_arc(item: Any) -> bool:
    """Check if item is a GrArc (has start, mid, end)."""
    return hasattr(item, "start") and hasattr(item, "mid") and hasattr(item, "end")


def _is_gr_circle(item: Any) -> bool:
    """Check if item is a GrCircle (has center and end, no start)."""
    return (
        hasattr(item, "center")
        and hasattr(item, "end")
        and not hasattr(item, "start")
    )


def _is_gr_rect(item: Any) -> bool:
    """Check if item is a GrRect (has start and end, layer, no mid, no center).

    GrRect has start/end like GrLine but also has a 'layer' attribute
    and lacks 'mid'. Distinguished from GrLine by checking for an
    additional 'filled' or 'stroke' attribute that GrLine lacks, or
    simply by process of elimination after other types are checked.
    """
    return (
        hasattr(item, "start")
        and hasattr(item, "end")
        and not hasattr(item, "mid")
        and not hasattr(item, "center")
        and hasattr(item, "filled")
    )


def extract_board_outline(
    board: Any,
) -> Polygon | MultiPolygon | None:
    """Extract board outline from Edge.Cuts graphic items.

    Filters board.graphicItems for Edge.Cuts layer, converts each
    to Shapely geometry, merges line segments, and polygonizes to
    produce the board outline.

    Args:
        board: kiutils Board object with graphicItems list.

    Returns:
        Polygon for a single connected outline, MultiPolygon for
        disjoint outlines (panelized boards), or None if no Edge.Cuts
        items exist or polygonization fails.
    """
    graphic_items = getattr(board, "graphicItems", [])
    if not graphic_items:
        return None

    # Filter for Edge.Cuts items
    edge_items = [
        item for item in graphic_items
        if getattr(item, "layer", None) == "Edge.Cuts"
    ]

    if not edge_items:
        return None

    line_geometries: list[LineString] = []
    circle_geometries: list[Polygon] = []

    for item in edge_items:
        layer = getattr(item, "layer", "")
        if layer != "Edge.Cuts":
            continue

        if _is_gr_circle(item):
            # Circle: center + end point on circumference
            cx = float(item.center.X)
            cy = float(item.center.Y)
            ex = float(item.end.X)
            ey = float(item.end.Y)
            radius = math.hypot(ex - cx, ey - cy)
            circle_poly = Point(cx, cy).buffer(radius)
            circle_geometries.append(circle_poly)

        elif _is_gr_arc(item):
            # Arc: start, mid, end -> approximate with LineString
            sx = float(item.start.X)
            sy = float(item.start.Y)
            mx = float(item.mid.X)
            my = float(item.mid.Y)
            ex = float(item.end.X)
            ey = float(item.end.Y)
            line_geometries.append(
                _arc_to_linestring(sx, sy, mx, my, ex, ey)
            )

        elif _is_gr_rect(item):
            # GrRect on Edge.Cuts: convert to 4 corner LineString
            sx = float(item.start.X)
            sy = float(item.start.Y)
            ex = float(item.end.X)
            ey = float(item.end.Y)
            corners = [
                (sx, sy), (ex, sy), (ex, ey), (sx, ey), (sx, sy)
            ]
            line_geometries.append(LineString(corners))

        elif _is_gr_line(item):
            # Line: start, end
            sx = float(item.start.X)
            sy = float(item.start.Y)
            ex = float(item.end.X)
            ey = float(item.end.Y)
            line_geometries.append(
                LineString([(sx, sy), (ex, ey)])
            )

    # Merge line segments and polygonize
    polygons: list[Polygon] = []

    if line_geometries:
        merged = linemerge(MultiLineString(line_geometries))

        # Snap nearly-closed linestrings to ensure polygonize can close them.
        # Arc interpolation introduces sub-nanometer floating-point gaps that
        # prevent polygonize from detecting a closed ring.
        _SNAP_TOLERANCE = 1e-6  # 1 nanometer -- well below manufacturing tolerance
        if merged.geom_type == "LineString":
            coords = list(merged.coords)
            if len(coords) >= 3:
                first = coords[0]
                last = coords[-1]
                dist = math.hypot(last[0] - first[0], last[1] - first[1])
                if 0 < dist < _SNAP_TOLERANCE:
                    # Snap last point to first to close the ring
                    coords[-1] = first
                    merged = LineString(coords)
        elif merged.geom_type == "MultiLineString":
            # Snap each sub-line that is nearly closed
            snapped_lines: list[LineString] = []
            for geom in merged.geoms:
                coords = list(geom.coords)
                if len(coords) >= 3:
                    first = coords[0]
                    last = coords[-1]
                    dist = math.hypot(last[0] - first[0], last[1] - first[1])
                    if 0 < dist < _SNAP_TOLERANCE:
                        coords[-1] = first
                        snapped_lines.append(LineString(coords))
                    else:
                        snapped_lines.append(geom)
                else:
                    snapped_lines.append(geom)
            merged = MultiLineString(snapped_lines)

        polygonized = list(polygonize([merged]))
        polygons.extend(polygonized)

    if circle_geometries:
        circle_union = unary_union(circle_geometries)
        if circle_union.geom_type == "Polygon":
            polygons.append(circle_union)
        elif circle_union.geom_type == "MultiPolygon":
            for geom in circle_union.geoms:
                polygons.append(geom)

    if not polygons:
        if line_geometries:
            logger.warning(
                "Edge.Cuts lines do not form a closed polygon; "
                "outline extraction returned no polygons"
            )
        return None

    # Combine line-derived polygons with circle polygons
    if polygons and circle_geometries:
        combined = unary_union(polygons)
        if combined.geom_type == "Polygon":
            return combined
        elif combined.geom_type == "MultiPolygon":
            return combined
        return None

    if len(polygons) == 1:
        return polygons[0]

    return MultiPolygon(polygons)
