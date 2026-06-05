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
        layers: list[str] | None = None,
        required_nodes: set[tuple[float, float]] | None = None,
    ) -> None:
        """Build routing graph from board bounds, obstacles, and constraints.

        Args:
            board_bounds: (x_min, y_min, x_max, y_max) board outline in mm.
            obstacles: List of SpatialBox objects representing forbidden areas.
            constraints: Routing constraints. Uses defaults if not provided.
            query_engine: Optional pre-built SpatialQueryEngine for proximity
                queries. Built from obstacles if not provided.
            layers: List of copper layer names for multi-layer routing.
                Defaults to ["F.Cu"] for single-layer backward compatibility.
            required_nodes: Set of (x, y) positions (pad locations) that must
                exist as graph nodes even if inside an obstacle. Pads are
                inside footprints but must be routable.

        Raises:
            ValueError: If grid would exceed max_nodes.
        """
        import networkx as nx
        from shapely.geometry import Point as ShapelyPoint

        from kicad_agent.spatial.primitives import SpatialBox

        self.constraints = constraints or RoutingConstraints()
        self._graph = nx.Graph()
        self._node_index_dirty = True  # H-6: lazy spatial index

        active_layers = layers or ["F.Cu"]

        x_min, y_min, x_max, y_max = board_bounds
        grid_res = self.constraints.grid_resolution_mm

        # Build obstacle Shapely geometries for fast containment checks.
        obstacle_geoms = []
        obstacle_ids = []
        for obs in obstacles:
            if isinstance(obs, SpatialBox):
                obstacle_geoms.append(obs.to_shapely())
                obstacle_ids.append(obs.entity_id)

        # Snap required nodes (pad positions) to grid.
        required_grid_nodes: set[tuple[float, float]] = set()
        if required_nodes:
            for px, py in required_nodes:
                gx = round(round(px / grid_res) * grid_res, 6)
                gy = round(round(py / grid_res) * grid_res, 6)
                required_grid_nodes.add((gx, gy))

        # Generate grid nodes. Align to grid resolution so that pads
        # at grid-aligned positions (e.g. 119.0 on a 0.5mm grid) are
        # guaranteed to have nodes.
        grid_x0 = round(round(x_min / grid_res) * grid_res, 6)
        grid_y0 = round(round(y_min / grid_res) * grid_res, 6)

        xs = []
        x = grid_x0
        while x <= x_max + grid_res * 0.01:
            xs.append(round(x, 6))
            x += grid_res

        ys = []
        y = grid_y0
        while y <= y_max + grid_res * 0.01:
            ys.append(round(y, 6))
            y += grid_res

        nodes: list[tuple[float, float, str]] = []
        for layer in active_layers:
            for gx in xs:
                for gy in ys:
                    pt = ShapelyPoint(gx, gy)
                    # Skip nodes inside any obstacle, UNLESS it's a required
                    # node (pad position inside its own footprint courtyard).
                    inside = any(pt.within(geom) for geom in obstacle_geoms)
                    if inside and (gx, gy) not in required_grid_nodes:
                        continue
                    nodes.append((gx, gy, layer))

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

        # Create same-layer edges between adjacent nodes (4-directional).
        clearance_threshold = (
            self.constraints.clearance_mm
            + self.constraints.trace_width_mm / 2.0
        )
        # Relaxed threshold for edges connected to required (pad) nodes.
        # Pads are inside courtyards — traces exiting pads only need trace_width
        # clearance, not the full clearance + trace_width check.
        pad_threshold = self.constraints.trace_width_mm / 2.0

        for gx, gy, layer in nodes:
            is_required = (gx, gy) in required_grid_nodes
            for dx, dy in ((grid_res, 0), (0, grid_res)):
                neighbor = (round(gx + dx, 6), round(gy + dy, 6), layer)
                if neighbor not in node_set:
                    continue

                mid_x = (gx + neighbor[0]) / 2.0
                mid_y = (gy + neighbor[1]) / 2.0
                segment_length = math.hypot(dx, dy)

                # Check clearance at edge midpoint.
                min_distance = self._min_obstacle_distance(mid_x, mid_y)

                # Use relaxed threshold if EITHER endpoint is a pad node.
                neighbor_required = (neighbor[0], neighbor[1]) in required_grid_nodes
                threshold = pad_threshold if (is_required or neighbor_required) else clearance_threshold

                if min_distance is not None and min_distance < threshold:
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
                    (gx, gy, layer), neighbor, weight=cost
                )

        # Add via edges between adjacent layers.
        via_cost = self.constraints.via_cost_mm
        for i in range(len(active_layers) - 1):
            layer_a = active_layers[i]
            layer_b = active_layers[i + 1]
            layer_a_xy = {(gx, gy) for gx, gy, l in nodes if l == layer_a}
            for gx, gy, l in nodes:
                if l == layer_b and (gx, gy) in layer_a_xy:
                    self._graph.add_edge(
                        (gx, gy, layer_a), (gx, gy, layer_b),
                        weight=via_cost,
                    )

        # Add escape edges for isolated required nodes (pads inside courtyards).
        # A pad node that lacks same-layer edges is unreachable on that layer.
        # Via edges (same position, different layer) don't help — search in
        # expanding rings for the nearest same-layer connected node.
        _ESCAPE_COST = 50.0  # Penalty to discourage routing through courtyards.
        _MAX_ESCAPE_RINGS = 10  # Search up to 10 grid steps (~2.5mm at 0.25mm grid).
        if required_grid_nodes:
            for gx, gy in required_grid_nodes:
                for layer in active_layers:
                    node = (gx, gy, layer)
                    if node not in self._graph:
                        continue
                    # Check same-layer degree (ignore via edges to other layers).
                    same_layer_edges = 0
                    for neighbor in self._graph.neighbors(node):
                        if len(neighbor) == 3 and neighbor[2] == layer:
                            same_layer_edges += 1
                    if same_layer_edges > 0:
                        continue  # Already has same-layer connectivity
                    # Search in expanding rings for nearest connected node.
                    best_dist = float("inf")
                    best_neighbor = None
                    for ring in range(1, _MAX_ESCAPE_RINGS + 1):
                        for dx in range(-ring, ring + 1):
                            for dy in range(-ring, ring + 1):
                                if abs(dx) != ring and abs(dy) != ring:
                                    continue  # Only check ring perimeter
                                cx = round(gx + dx * grid_res, 6)
                                cy = round(gy + dy * grid_res, 6)
                                candidate = (cx, cy, layer)
                                if candidate in self._graph:
                                    # Prefer candidates with same-layer edges.
                                    cand_has_layer_edges = any(
                                        len(n) == 3 and n[2] == layer
                                        for n in self._graph.neighbors(candidate)
                                    )
                                    if cand_has_layer_edges:
                                        d = math.hypot(dx * grid_res, dy * grid_res)
                                        if d < best_dist:
                                            best_dist = d
                                            best_neighbor = candidate
                        if best_neighbor is not None:
                            break  # Found in this ring, stop searching
                    if best_neighbor is not None:
                        self._graph.add_edge(
                            node, best_neighbor, weight=_ESCAPE_COST,
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

    def _build_node_index(self) -> None:
        """Build spatial index of nodes per layer for O(log n) snap (H-6)."""
        from shapely.geometry import Point as ShapelyPoint
        from shapely.strtree import STRtree

        layer_nodes: dict[str, list[tuple]] = {}
        other_nodes: list[tuple] = []

        for node in self._graph.nodes:
            if len(node) == 3:
                layer = node[2]
                layer_nodes.setdefault(layer, []).append(node)
            else:
                other_nodes.append(node)

        self._layer_index: dict[str, dict] = {}
        for layer, nodes in layer_nodes.items():
            points = [ShapelyPoint(n[0], n[1]) for n in nodes]
            self._layer_index[layer] = {
                "tree": STRtree(points),
                "nodes": nodes,
                "points": points,
            }

        # Also build a global index for layer=None queries
        all_nodes = list(self._graph.nodes)
        all_points = [ShapelyPoint(n[0], n[1]) for n in all_nodes]
        self._global_index = {
            "tree": STRtree(all_points),
            "nodes": all_nodes,
            "points": all_points,
        }
        self._node_index_dirty = False

    def snap_to_node(
        self, x: float, y: float, layer: str | None = None
    ) -> tuple[float, float, str] | tuple[float, float] | None:
        """Find the nearest grid node to (x, y) within tolerance.

        Tolerance is grid_resolution_mm. Returns None if no node is
        within tolerance. Uses spatial index for O(log n) lookup (H-6).

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.
            layer: Optional copper layer name. If provided, only considers
                nodes on that layer. If None, finds nearest on any layer.

        Returns:
            (x, y, layer) tuple for 3D graphs, or (x, y) for backward
            compat, or None if out of tolerance.
        """
        from shapely.geometry import Point as ShapelyPoint

        if not self._graph.nodes:
            return None

        grid_res = self.constraints.grid_resolution_mm
        tolerance = grid_res

        # Snap to nearest grid point.
        gx = round(round(x / grid_res) * grid_res, 6)
        gy = round(round(y / grid_res) * grid_res, 6)

        if layer is not None:
            # Specific layer snap for 3D graphs.
            candidate = (gx, gy, layer)
            if candidate in self._graph:
                dist = math.hypot(x - gx, y - gy)
                if dist <= tolerance:
                    return candidate

            # Use spatial index for O(log n) nearest-neighbor (H-6).
            if self._node_index_dirty:
                self._build_node_index()
            if hasattr(self, "_layer_index") and layer in self._layer_index:
                idx = self._layer_index[layer]
                query = ShapelyPoint(x, y)
                nearest_idx = idx["tree"].nearest(query)
                nearest_node = idx["nodes"][nearest_idx]
                # H-05: Validate node still exists in graph
                if nearest_node not in self._graph:
                    return None
                d = math.hypot(x - nearest_node[0], y - nearest_node[1])
                if d <= tolerance:
                    return nearest_node
            return None

        # No layer specified -- find nearest on any layer.
        # Try exact grid snap first.
        candidate = (gx, gy)
        if candidate in self._graph:
            dist = math.hypot(x - gx, y - gy)
            if dist <= tolerance:
                return candidate

        # Use global spatial index for nearest-neighbor (H-6).
        if self._node_index_dirty:
            self._build_node_index()
        if hasattr(self, "_global_index"):
            query = ShapelyPoint(x, y)
            nearest_idx = self._global_index["tree"].nearest(query)
            nearest_node = self._global_index["nodes"][nearest_idx]
            # H-05: Validate node still exists in graph
            if nearest_node not in self._graph:
                return None
            d = math.hypot(x - nearest_node[0], y - nearest_node[1])
            if d <= tolerance:
                return nearest_node
        return None

    def mark_path_as_obstacle(
        self,
        path: tuple[tuple[float, float], ...] | tuple[tuple[float, float, str], ...],
        clearance: float = 0.0,
    ) -> None:
        """Remove edges along and near a routed path so subsequent nets avoid it.

        This provides single-layer multi-net routing by progressively blocking
        already-routed paths. Nodes are kept (they may be needed for other
        nets' endpoints) but edges along the path are removed.

        Args:
            path: Ordered tuple of (x, y) or (x, y, layer) waypoints forming
                a routed path.
            clearance: Distance (mm) from path edges to also block. When > 0,
                also removes edges within the clearance corridor (H-10).
        """
        # Remove exact edges along path
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self._graph.has_edge(u, v):
                self._graph.remove_edge(u, v)

        # H-10: Also remove edges within clearance corridor
        if clearance > 0:
            self._mark_clearance_corridor(path, clearance)
        # Mark index dirty after graph mutation
        self._node_index_dirty = True

    def _mark_clearance_corridor(
        self,
        path: tuple[tuple[float, ...], ...],
        clearance: float,
    ) -> None:
        """Remove edges whose segments pass within clearance of any path waypoint.

        Uses STRtree spatial index for O(W * log N) instead of O(W * N) scan.
        """
        from shapely.geometry import Point as ShapelyPoint

        # Ensure spatial index is built
        if self._node_index_dirty:
            self._build_node_index()

        # Determine layer from path nodes
        path_layer = path[0][2] if len(path[0]) >= 3 else None

        # Pick the right index (layer-specific or global)
        if path_layer is not None and hasattr(self, "_layer_index") and path_layer in self._layer_index:
            index_data = self._layer_index[path_layer]
        elif hasattr(self, "_global_index"):
            index_data = self._global_index
        else:
            return

        tree = index_data["tree"]
        nodes = index_data["nodes"]

        for waypoint in path:
            wx, wy = waypoint[0], waypoint[1]
            query = ShapelyPoint(wx, wy)
            # Query tree for nodes within 2x clearance radius
            search_geom = query.buffer(clearance * 2)
            candidate_indices = tree.query(search_geom)

            for idx in candidate_indices:
                node = nodes[idx]
                if node not in self._graph:
                    continue
                # Check all edges from this nearby node
                for neighbor in list(self._graph.neighbors(node)):
                    seg_dist = _point_to_segment_distance(
                        wx, wy, node[0], node[1], neighbor[0], neighbor[1],
                    )
                    if seg_dist <= clearance:
                        if self._graph.has_edge(node, neighbor):
                            self._graph.remove_edge(node, neighbor)


def _point_to_segment_distance(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Minimum distance from point (px, py) to line segment (ax, ay)-(bx, by)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)
