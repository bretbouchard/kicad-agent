"""Routing graph construction with DRC-aware edge costs.

Builds a grid-based routing graph over a PCB board area, excluding nodes
inside obstacles and penalizing edges that violate design-rule clearances.

Uses lazy networkx and shapely imports so the module loads without them
installed (graceful degradation for environments that only need constraints).

Usage:
    from kicad_agent.routing.graph import RoutingGraph
    from kicad_agent.routing.constraints import RoutingConstraints

    graph = RoutingGraph(
        board_bounds=(0, 0, 50, 50),
        obstacles=[],
        constraints=RoutingConstraints(),
    )
    node = graph.snap_to_node(10.3, 20.7)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from kicad_agent.routing.constraints import RoutingConstraints

if TYPE_CHECKING:
    from kicad_agent.spatial.query import SpatialQueryEngine


# DRC penalty multiplier for edges near obstacles.
_DRC_PENALTY = 100.0


class RoutingGraph:
    """Grid-based routing graph with DRC-aware edge costs.

    Wraps a ``networkx.Graph`` where nodes are (x, y) grid coordinates
    and edges carry a ``weight`` attribute reflecting distance plus
    any DRC penalty.

    Attributes:
        graph: The underlying networkx Graph.
        constraints: Routing constraints used during construction.
    """

    def __init__(
        self,
        board_bounds: tuple[float, float, float, float],
        obstacles: list,
        constraints: RoutingConstraints | None = None,
        query_engine: SpatialQueryEngine | None = None,
    ) -> None:
        """Build routing graph from board bounds, obstacles, and constraints.

        Args:
            board_bounds: (x_min, y_min, x_max, y_max) board outline in mm.
            obstacles: List of SpatialBox objects representing forbidden areas.
            constraints: Routing constraints. Uses defaults if not provided.
            query_engine: Optional pre-built SpatialQueryEngine for proximity
                queries. Built from obstacles if not provided.

        Raises:
            ValueError: If grid would exceed max_nodes.
        """
        import networkx as nx
        from shapely.geometry import Point as ShapelyPoint

        from kicad_agent.spatial.primitives import SpatialBox

        self.constraints = constraints or RoutingConstraints()
        self._graph = nx.Graph()

        x_min, y_min, x_max, y_max = board_bounds
        grid_res = self.constraints.grid_resolution_mm

        # Build obstacle Shapely geometries for fast containment checks.
        obstacle_geoms = []
        obstacle_ids = []
        for obs in obstacles:
            if isinstance(obs, SpatialBox):
                obstacle_geoms.append(obs.to_shapely())
                obstacle_ids.append(obs.entity_id)

        # Generate grid nodes.
        xs = []
        x = x_min
        while x <= x_max + grid_res * 0.01:
            xs.append(round(x, 6))
            x += grid_res

        ys = []
        y = y_min
        while y <= y_max + grid_res * 0.01:
            ys.append(round(y, 6))
            y += grid_res

        nodes: list[tuple[float, float]] = []
        for gx in xs:
            for gy in ys:
                pt = ShapelyPoint(gx, gy)
                # Skip nodes inside any obstacle.
                inside = False
                for geom in obstacle_geoms:
                    if pt.within(geom):
                        inside = True
                        break
                if not inside:
                    nodes.append((gx, gy))

        if len(nodes) > self.constraints.max_nodes:
            raise ValueError(
                f"Grid would have {len(nodes)} nodes, "
                f"exceeding max_nodes={self.constraints.max_nodes}. "
                f"Increase grid_resolution_mm or max_nodes."
            )

        # Add nodes to graph.
        self._graph.add_nodes_from(nodes)

        # Build lookup for fast node existence check.
        node_set = set(nodes)

        # Build a spatial index of obstacles for edge DRC checks.
        if query_engine is not None:
            self._query_engine = query_engine
        elif obstacles:
            self._query_engine = self._build_query_engine(obstacles)
        else:
            self._query_engine = None

        # Create edges between adjacent nodes (4-directional).
        clearance_threshold = (
            self.constraints.clearance_mm
            + self.constraints.trace_width_mm / 2.0
        )

        for gx, gy in nodes:
            for dx, dy in ((grid_res, 0), (0, grid_res)):
                neighbor = (round(gx + dx, 6), round(gy + dy, 6))
                if neighbor not in node_set:
                    continue

                mid_x = (gx + neighbor[0]) / 2.0
                mid_y = (gy + neighbor[1]) / 2.0
                segment_length = math.hypot(dx, dy)

                # Check clearance at edge midpoint.
                min_distance = self._min_obstacle_distance(mid_x, mid_y)

                if min_distance is not None and min_distance < clearance_threshold:
                    # Edge violates clearance -- omit it.
                    continue

                cost = segment_length
                if (
                    min_distance is not None
                    and min_distance < self.constraints.clearance_mm
                ):
                    # Edge is legal but within clearance zone -- add penalty.
                    cost += _DRC_PENALTY

                self._graph.add_edge(
                    (gx, gy), neighbor, weight=cost
                )

    @staticmethod
    def _build_query_engine(obstacles: list) -> SpatialQueryEngine:
        """Build a SpatialQueryEngine from obstacle list."""
        from kicad_agent.spatial.query import SpatialQueryEngine

        return SpatialQueryEngine(obstacles)

    def _min_obstacle_distance(
        self, x: float, y: float
    ) -> float | None:
        """Compute minimum distance from (x,y) to any obstacle.

        Returns None if no obstacles exist.
        """
        if self._query_engine is None:
            return None

        # Search within a generous radius.
        search_radius = max(
            self.constraints.clearance_mm
            + self.constraints.trace_width_mm
            + 1.0,
            10.0,
        )
        nearby = self._query_engine.proximity(x, y, search_radius)
        if not nearby:
            return None

        from shapely.geometry import Point as ShapelyPoint

        query_pt = ShapelyPoint(x, y)
        min_dist = float("inf")
        for prim in nearby:
            geom = prim.to_shapely()
            dist = query_pt.distance(geom)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    @property
    def graph(self):
        """The underlying networkx Graph."""
        return self._graph

    @property
    def node_count(self) -> int:
        """Number of grid nodes in the graph."""
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        """Number of edges in the graph."""
        return self._graph.number_of_edges()

    def snap_to_node(
        self, x: float, y: float
    ) -> tuple[float, float] | None:
        """Find the nearest grid node to (x, y) within tolerance.

        Tolerance is grid_resolution_mm. Returns None if no node is
        within tolerance.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.

        Returns:
            (x, y) tuple of the nearest node, or None if out of tolerance.
        """
        if not self._graph.nodes:
            return None

        grid_res = self.constraints.grid_resolution_mm
        tolerance = grid_res

        # Snap to nearest grid point.
        gx = round(round(x / grid_res) * grid_res, 6)
        gy = round(round(y / grid_res) * grid_res, 6)

        if (gx, gy) in self._graph:
            dist = math.hypot(x - gx, y - gy)
            if dist <= tolerance:
                return (gx, gy)

        # Fall back to nearest neighbor search.
        best_node = None
        best_dist = float("inf")
        for node in self._graph.nodes:
            d = math.hypot(x - node[0], y - node[1])
            if d < best_dist:
                best_dist = d
                best_node = node

        if best_node is not None and best_dist <= tolerance:
            return best_node
        return None

    def mark_path_as_obstacle(self, path: tuple[tuple[float, float], ...]) -> None:
        """Remove edges along a routed path so subsequent nets avoid it.

        This provides single-layer multi-net routing by progressively blocking
        already-routed paths. Nodes are kept (they may be needed for other
        nets' endpoints) but edges along the path are removed.

        Args:
            path: Ordered tuple of (x, y) waypoints forming a routed path.
        """
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self._graph.has_edge(u, v):
                self._graph.remove_edge(u, v)
