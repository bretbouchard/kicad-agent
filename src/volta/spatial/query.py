"""Spatial query engine backed by Shapely STRtree.

VP-06: Fast proximity, containment, and clearance queries over spatial
primitives extracted from PCB data.

Uses a two-phase query pattern:
  1. STRtree.query() for coarse bounding-box filter (O(log n))
  2. Exact Shapely intersection/contains/distance check on candidates

All query methods return the original primitive objects (not copies).
The engine holds references to the input primitives list.

Usage:
    from volta.spatial.query import SpatialQueryEngine
    from volta.spatial.primitives import SpatialPoint

    points = [SpatialPoint(10, 10, "via", "v1")]
    engine = SpatialQueryEngine(points)
    nearby = engine.proximity(10.5, 10.5, 5.0)
"""

from __future__ import annotations

import math
from typing import Any

from shapely import STRtree


# Maximum query radius in mm. Larger than any realistic PCB (10 meters).
# Prevents DoS via unreasonably large spatial queries (T-08-08, T-08-09).
_MAX_RADIUS_MM = 10000.0


def _validate_finite(value: float, name: str) -> None:
    """Raise ValueError if value is NaN or Inf."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value}")


class SpatialQueryEngine:
    """Spatial query engine backed by Shapely STRtree.

    Builds a spatial index over extracted primitives for fast proximity,
    containment, and clearance queries.
    """

    def __init__(self, primitives: list) -> None:
        """Build spatial index from a list of spatial primitives.

        Args:
            primitives: List of SpatialPoint/SpatialBox/SpatialPath/SpatialRegion
                objects. Each must have a ``to_shapely()`` method. Empty list
                creates an empty engine (all queries return empty results).
        """
        self._primitives: list = list(primitives)
        if primitives:
            geometries = [p.to_shapely() for p in primitives]
            self._tree: STRtree | None = STRtree(geometries)
        else:
            self._tree = None

    @property
    def primitive_count(self) -> int:
        """Number of primitives indexed by this engine."""
        return len(self._primitives)

    def proximity(self, x: float, y: float, radius_mm: float) -> list:
        """Find all primitives within radius_mm of point (x, y).

        Two-phase query: STRtree bounding-box filter then exact
        Shapely intersection check.

        Args:
            x: Query point X coordinate (mm).
            y: Query point Y coordinate (mm).
            radius_mm: Search radius in mm. Must be > 0 and <= 10000.

        Returns:
            List of primitives whose geometry intersects the query buffer.

        Raises:
            ValueError: If radius_mm is out of range or coordinates are not finite.
        """
        _validate_finite(x, "x")
        _validate_finite(y, "y")
        if radius_mm <= 0:
            raise ValueError(f"radius_mm must be > 0, got {radius_mm}")
        if radius_mm > _MAX_RADIUS_MM:
            raise ValueError(
                f"radius_mm must be <= {_MAX_RADIUS_MM}, got {radius_mm}"
            )

        if self._tree is None:
            return []

        from shapely.geometry import Point

        query_point = Point(x, y)
        buffer = query_point.buffer(radius_mm)
        candidates = self._tree.query(buffer)
        return [
            self._primitives[i]
            for i in candidates
            if self._primitives[i].to_shapely().intersects(buffer)
        ]

    def containment(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> list:
        """Find all primitives fully contained within bounding box (x1,y1)-(x2,y2).

        Two-phase query: STRtree bounding-box filter then exact
        Shapely ``contains`` check.

        Args:
            x1: Min X of query box (mm).
            y1: Min Y of query box (mm).
            x2: Max X of query box (mm).
            y2: Max Y of query box (mm).

        Returns:
            List of primitives fully contained within the query box.

        Raises:
            ValueError: If box coordinates are invalid or not finite.
        """
        _validate_finite(x1, "x1")
        _validate_finite(y1, "y1")
        _validate_finite(x2, "x2")
        _validate_finite(y2, "y2")
        if x1 >= x2:
            raise ValueError(f"x1 must be < x2, got {x1} >= {x2}")
        if y1 >= y2:
            raise ValueError(f"y1 must be < y2, got {y1} >= {y2}")

        if self._tree is None:
            return []

        from shapely.geometry import box

        query_box = box(x1, y1, x2, y2)
        candidates = self._tree.query(query_box)
        return [
            self._primitives[i]
            for i in candidates
            if query_box.contains(self._primitives[i].to_shapely())
        ]

    def clearance(
        self, entity_id: str, search_radius_mm: float = 10.0
    ) -> list[tuple[Any, float]]:
        """Find all primitives near a given entity and compute distances.

        Uses a two-phase approach:
        1. Linear scan to find the target primitive by entity_id
        2. STRtree query within search_radius_mm, then exact distance computation

        Args:
            entity_id: The entity_id of the target primitive.
            search_radius_mm: How far to search around the target (mm).
                Must be > 0 and <= 10000. Defaults to 10.0.

        Returns:
            List of (primitive, distance) tuples sorted by distance ascending.
            The target itself is excluded. Returns [] if entity_id not found.
        """
        if search_radius_mm <= 0:
            raise ValueError(
                f"search_radius_mm must be > 0, got {search_radius_mm}"
            )
        if search_radius_mm > _MAX_RADIUS_MM:
            raise ValueError(
                f"search_radius_mm must be <= {_MAX_RADIUS_MM}, "
                f"got {search_radius_mm}"
            )

        # Linear scan for target (entity_id is not indexed)
        target_idx: int | None = None
        for i, p in enumerate(self._primitives):
            if p.entity_id == entity_id:
                target_idx = i
                break

        if target_idx is None or self._tree is None:
            return []

        target_geom = self._primitives[target_idx].to_shapely()
        buffer = target_geom.buffer(search_radius_mm)
        candidates = self._tree.query(buffer)

        results: list[tuple[Any, float]] = []
        for i in candidates:
            if i != target_idx:
                candidate_geom = self._primitives[i].to_shapely()
                dist = target_geom.distance(candidate_geom)
                results.append((self._primitives[i], dist))

        return sorted(results, key=lambda x: x[1])

    def find_by_entity_id(self, entity_id: str) -> list:
        """Find all primitives with matching entity_id.

        Linear scan since entity_id is not spatially indexed.

        Args:
            entity_id: The entity_id to search for.

        Returns:
            List of primitives with matching entity_id (may be empty or
            have multiple matches if different primitive types share the
            same entity_id).
        """
        return [p for p in self._primitives if p.entity_id == entity_id]

    def find_by_net(self, net_name: str) -> list:
        """Find all primitives belonging to the named net.

        Checks for a ``net`` attribute on each primitive and compares
        equality with net_name.

        Args:
            net_name: Net name to filter by.

        Returns:
            List of primitives on the specified net.
        """
        return [
            p
            for p in self._primitives
            if hasattr(p, "net") and p.net == net_name
        ]

    def find_by_layer(self, layer_name: str) -> list:
        """Find all primitives on the specified layer.

        Checks for a ``layer`` attribute on each primitive and compares
        equality with layer_name.

        Args:
            layer_name: Layer name to filter by.

        Returns:
            List of primitives on the specified layer.
        """
        return [
            p
            for p in self._primitives
            if hasattr(p, "layer") and p.layer == layer_name
        ]
