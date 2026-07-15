"""Shared geometry utilities for routing operations.

Provides path interpolation, direction computation, and length calculation
used by both differential pair routing and multi-layer pathfinding.

These helpers operate on paths represented as tuples of (x, y) coordinate
pairs. They are extracted here to avoid duplication across modules.

Usage:
    from volta.routing.geometry import _interpolate_path, _direction_at, _path_length
"""

from __future__ import annotations

import math


def _path_length(path: tuple[tuple[float, float], ...]) -> float:
    """Compute total Euclidean length of a path.

    Args:
        path: Ordered tuple of (x, y) waypoints.

    Returns:
        Sum of Euclidean distances between consecutive points.
    """
    total = 0.0
    for i in range(len(path) - 1):
        total += math.hypot(
            path[i + 1][0] - path[i][0],
            path[i + 1][1] - path[i][1],
        )
    return total


def _interpolate_path(
    path: tuple[tuple[float, float], ...],
    distances: list[float],
) -> list[tuple[float, float]]:
    """Return points at given arc-length distances along the path.

    If a distance exceeds the total path length, the last point is
    returned.

    Precondition:
        - ``path`` must contain at least 2 waypoints (len(path) >= 2).
        - ``distances`` must be sorted in non-decreasing order and all
          values must be non-negative. Violating this will not raise an
          error but may produce incorrect interpolation results.

    Args:
        path: Ordered tuple of (x, y) waypoints.
        distances: Sorted list of arc-length distances along the path.

    Returns:
        List of (x, y) points at the requested distances.
    """
    points: list[tuple[float, float]] = []
    seg_idx = 0
    cumulative = 0.0

    for d in distances:
        # Advance to the segment containing distance d.
        while seg_idx < len(path) - 1:
            seg_len = math.hypot(
                path[seg_idx + 1][0] - path[seg_idx][0],
                path[seg_idx + 1][1] - path[seg_idx][1],
            )
            if cumulative + seg_len >= d - 1e-9:
                break
            cumulative += seg_len
            seg_idx += 1

        if seg_idx >= len(path) - 1:
            points.append(path[-1])
            continue

        p0 = path[seg_idx]
        p1 = path[seg_idx + 1]
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])

        if seg_len < 1e-9:
            points.append(p0)
            continue

        t = max(0.0, min(1.0, (d - cumulative) / seg_len))
        points.append((
            round(p0[0] + t * (p1[0] - p0[0]), 6),
            round(p0[1] + t * (p1[1] - p0[1]), 6),
        ))

    return points


def _direction_at(
    path: tuple[tuple[float, float], ...],
    distance: float,
) -> tuple[float, float, float, float]:
    """Return (ux, uy, px, py) at a given arc-length distance.

    ux, uy = unit direction along the path.
    px, py = perpendicular direction (rotated 90 degrees CCW).

    Args:
        path: Ordered tuple of (x, y) waypoints.
        distance: Arc-length distance along the path.

    Returns:
        Tuple of (ux, uy, px, py) direction components.
    """
    cumulative = 0.0
    for i in range(len(path) - 1):
        seg_len = math.hypot(
            path[i + 1][0] - path[i][0],
            path[i + 1][1] - path[i][1],
        )
        if cumulative + seg_len >= distance - 1e-9 or i == len(path) - 2:
            if seg_len < 1e-9:
                continue
            ux = (path[i + 1][0] - path[i][0]) / seg_len
            uy = (path[i + 1][1] - path[i][1]) / seg_len
            return ux, uy, -uy, ux
        cumulative += seg_len

    # Fallback: use last segment direction.
    if len(path) >= 2:
        p0 = path[-2]
        p1 = path[-1]
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if seg_len > 1e-9:
            ux = (p1[0] - p0[0]) / seg_len
            uy = (p1[1] - p0[1]) / seg_len
            return ux, uy, -uy, ux

    return 1.0, 0.0, 0.0, 1.0
