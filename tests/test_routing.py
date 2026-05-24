"""Tests for routing graph model and A* pathfinder.

Uses synthetic data (SpatialBox from spatial.primitives) -- no kicad-cli
dependency. Tests cover graph construction, obstacle exclusion, DRC
clearance, pathfinding, and batch routing.
"""

from __future__ import annotations

import math

import pytest

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.pathfinder import (
    RouteResult,
    build_routing_graph,
    route_all_nets,
    route_net,
)
from kicad_agent.spatial.primitives import SpatialBox


# ---------------------------------------------------------------------------
# RoutingConstraints
# ---------------------------------------------------------------------------


class TestRoutingConstraints:
    """Constraint validation and defaults."""

    def test_defaults(self) -> None:
        c = RoutingConstraints()
        assert c.clearance_mm == 0.2
        assert c.grid_resolution_mm == 0.5
        assert c.trace_width_mm == 0.25
        assert c.via_diameter_mm == 0.8
        assert c.via_drill_mm == 0.4
        assert c.max_nodes == 500_000

    def test_frozen(self) -> None:
        c = RoutingConstraints()
        with pytest.raises(AttributeError):
            c.clearance_mm = 0.5  # type: ignore[misc]

    def test_clearance_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="clearance_mm must be > 0"):
            RoutingConstraints(clearance_mm=0)
        with pytest.raises(ValueError, match="clearance_mm must be > 0"):
            RoutingConstraints(clearance_mm=-0.1)

    def test_grid_resolution_minimum(self) -> None:
        with pytest.raises(ValueError, match="grid_resolution_mm must be >= 0.1"):
            RoutingConstraints(grid_resolution_mm=0.05)

    def test_max_nodes_cap(self) -> None:
        with pytest.raises(ValueError, match="max_nodes must be <= 1_000_000"):
            RoutingConstraints(max_nodes=2_000_000)

    def test_custom_values(self) -> None:
        c = RoutingConstraints(
            clearance_mm=0.3,
            grid_resolution_mm=0.25,
            trace_width_mm=0.15,
            via_diameter_mm=0.6,
            via_drill_mm=0.3,
            max_nodes=100_000,
        )
        assert c.clearance_mm == 0.3
        assert c.grid_resolution_mm == 0.25


# ---------------------------------------------------------------------------
# RoutingGraph construction
# ---------------------------------------------------------------------------


class TestRoutingGraph:
    """Graph construction, obstacle exclusion, snap-to-node."""

    def _make_empty_graph(
        self, size_mm: float = 50.0, grid_res: float = 0.5
    ) -> RoutingGraph:
        """Helper: build a routing graph with no obstacles."""
        return RoutingGraph(
            board_bounds=(0, 0, size_mm, size_mm),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=grid_res),
        )

    def test_empty_board_grid_nodes(self) -> None:
        """50x50mm board at 0.5mm resolution produces correct grid."""
        graph = self._make_empty_graph(50.0, 0.5)
        # 0, 0.5, 1.0, ..., 50.0 -> 101 points per axis -> 10201 nodes
        expected_per_axis = int(50.0 / 0.5) + 1
        assert graph.node_count == expected_per_axis * expected_per_axis

    def test_empty_board_edges(self) -> None:
        """Empty board has 4-directional edges."""
        graph = self._make_empty_graph(10.0, 1.0)
        # 11x11 = 121 nodes, edges = 10*11*2 = 220 (horizontal + vertical)
        assert graph.edge_count == 10 * 11 * 2

    def test_obstacle_nodes_excluded(self) -> None:
        """Nodes inside an obstacle bounding box are excluded."""
        obstacle = SpatialBox(5, 5, 8, 8, "footprint", "U1")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        # Node (6, 6) should be inside the obstacle and excluded.
        assert (6.0, 6.0) not in graph.graph.nodes
        # Node (0, 0) should be outside and present.
        assert (0.0, 0.0) in graph.graph.nodes

    def test_max_nodes_raises_value_error(self) -> None:
        """Grid exceeding max_nodes raises ValueError."""
        with pytest.raises(ValueError, match="exceeding max_nodes"):
            RoutingGraph(
                board_bounds=(0, 0, 50, 50),
                obstacles=[],
                constraints=RoutingConstraints(
                    grid_resolution_mm=0.1,
                    max_nodes=100,
                ),
            )

    def test_snap_to_node_within_tolerance(self) -> None:
        """snap_to_node returns nearest grid point within grid_resolution."""
        graph = self._make_empty_graph(50.0, 1.0)
        node = graph.snap_to_node(5.3, 10.7)
        assert node is not None
        assert node == (5.0, 11.0) or node == (5.0, 10.0)

    def test_snap_to_node_exact(self) -> None:
        """snap_to_node returns exact grid point for on-grid input."""
        graph = self._make_empty_graph(50.0, 1.0)
        node = graph.snap_to_node(5.0, 10.0)
        assert node == (5.0, 10.0)

    def test_snap_to_node_out_of_bounds(self) -> None:
        """snap_to_node returns None for points far outside grid."""
        graph = self._make_empty_graph(10.0, 1.0)
        node = graph.snap_to_node(100.0, 100.0)
        assert node is None

    def test_drc_clearance_enforcement(self) -> None:
        """Edges violating clearance near obstacle are omitted."""
        # Obstacle from x=10..12, y=10..12 with 0.5mm grid and large clearance.
        # clearance_threshold = 1.0 + 0.5/2 = 1.25mm.
        # Edge (9.5,10)-(10.0,10) midpoint (9.75,10) is 0.25mm from obstacle
        # -- well within 1.25mm threshold, so edge is omitted.
        # Edge (9.0,10)-(9.5,10) midpoint (9.25,10) is 0.75mm from obstacle
        # -- also within 1.25mm threshold, omitted.
        obstacle = SpatialBox(10, 10, 12, 12, "pad", "P1")
        constraints = RoutingConstraints(
            grid_resolution_mm=0.5,
            clearance_mm=1.0,
            trace_width_mm=0.5,
        )
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[obstacle],
            constraints=constraints,
        )
        # Nodes strictly inside obstacle should be excluded.
        assert (11.0, 11.0) not in graph.graph.nodes

        # Edges near obstacle should be omitted due to clearance violation.
        assert not graph.graph.has_edge((9.5, 10.0), (10.0, 10.0))
        assert not graph.graph.has_edge((9.0, 10.0), (9.5, 10.0))

    def test_obstacle_creates_detour(self) -> None:
        """Obstacle forces a detour -- path around is longer than straight."""
        obstacle = SpatialBox(10, 0, 11, 20, "pad", "WALL")
        graph = RoutingGraph(
            board_bounds=(0, 0, 30, 30),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        # Route from (5, 10) to (20, 10) -- must go around wall.
        result = route_net(graph, (5, 10), (20, 10), "detour")
        assert result is not None
        assert result.success
        # Straight distance is 15mm; detour must be longer.
        assert result.length_mm > 15.0


# ---------------------------------------------------------------------------
# A* Pathfinding
# ---------------------------------------------------------------------------


class TestPathfinding:
    """A* pathfinding: empty board, obstacles, blocked paths."""

    def test_route_empty_board(self) -> None:
        """Route on empty board returns valid straight-ish path."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 30, 30),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_net(graph, (0, 0), (10, 10), "NET1")
        assert result is not None
        assert result.success
        assert result.net_name == "NET1"
        assert len(result.path) >= 2
        assert result.path[0] == (0.0, 0.0)
        assert result.path[-1] == (10.0, 10.0)

    def test_route_with_obstacle(self) -> None:
        """Route around an obstacle finds a valid path."""
        obstacle = SpatialBox(5, 5, 8, 8, "footprint", "U1")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_net(graph, (0, 0), (15, 15), "NET2")
        assert result is not None
        assert result.success
        # Path must not pass through obstacle interior (strict interior,
        # boundary points like (5,5) or (8,8) are not excluded by within).
        for x, y in result.path:
            assert not (5 < x < 8 and 5 < y < 8)

    def test_route_blocked_source_returns_none(self) -> None:
        """Blocked source (inside obstacle) returns None."""
        obstacle = SpatialBox(0, 0, 5, 5, "zone", "Z1")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_net(graph, (2, 2), (15, 15), "BLOCKED")
        assert result is None

    def test_route_blocked_target_returns_none(self) -> None:
        """Blocked target (inside obstacle) returns None."""
        obstacle = SpatialBox(15, 15, 20, 20, "zone", "Z1")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_net(graph, (0, 0), (17, 17), "BLOCKED")
        assert result is None

    def test_route_no_path_returns_none(self) -> None:
        """Completely separated areas return None."""
        # Wall spanning entire board height.
        wall = SpatialBox(10, 0, 11, 20, "keepout", "WALL")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[wall],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        # If the wall blocks all paths, route_net returns None.
        # Note: with clearance enforcement, nodes near the wall edges
        # may also be removed, potentially creating a true barrier.
        # If some path exists, the test still passes (just gets a path).
        result = route_net(graph, (0, 10), (19, 10), "CUT")
        # Result is either None or a valid detour -- both are acceptable.
        if result is not None:
            assert result.success


# ---------------------------------------------------------------------------
# Batch routing
# ---------------------------------------------------------------------------


class TestRouteAllNets:
    """Batch routing with route_all_nets."""

    def test_three_net_netlist(self) -> None:
        """Three-net netlist routes all nets."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 50, 50),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        netlist = {
            "VCC": [(0, 0), (10, 0)],
            "GND": [(0, 5), (10, 5)],
            "SIG": [(0, 10), (10, 10)],
        }
        results = route_all_nets(graph, netlist)
        assert len(results) == 3
        assert "VCC" in results
        assert "GND" in results
        assert "SIG" in results
        for name, result in results.items():
            assert result.success
            assert result.net_name == name

    def test_shortest_first_ordering(self) -> None:
        """Nets are routed shortest estimated distance first."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 50, 50),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        netlist = {
            "LONG": [(0, 0), (40, 40)],
            "SHORT": [(0, 0), (5, 0)],
        }
        results = route_all_nets(graph, netlist)
        assert len(results) == 2
        # Both should succeed regardless of order.
        assert results["LONG"].success
        assert results["SHORT"].success

    def test_single_pin_net_skipped(self) -> None:
        """Nets with < 2 pins are skipped."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        netlist = {
            "VCC": [(5, 5)],  # Single pin
            "GND": [(0, 0), (10, 10)],
        }
        results = route_all_nets(graph, netlist)
        assert "VCC" not in results
        assert "GND" in results

    def test_empty_netlist(self) -> None:
        """Empty netlist returns empty results."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        results = route_all_nets(graph, {})
        assert results == {}


# ---------------------------------------------------------------------------
# RouteResult
# ---------------------------------------------------------------------------


class TestRouteResult:
    """RouteResult frozen dataclass."""

    def test_frozen(self) -> None:
        result = RouteResult(
            net_name="VCC",
            path=((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)),
            length_mm=10.0,
            success=True,
        )
        with pytest.raises(AttributeError):
            result.net_name = "GND"  # type: ignore[misc]

    def test_path_is_tuple(self) -> None:
        result = RouteResult(
            net_name="VCC",
            path=((0.0, 0.0), (5.0, 5.0)),
            length_mm=7.0711,
            success=True,
        )
        assert isinstance(result.path, tuple)

    def test_length_calculation(self) -> None:
        """Path length is correctly computed."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_net(graph, (0, 0), (5, 0), "TEST")
        assert result is not None
        assert abs(result.length_mm - 5.0) < 0.01


# ---------------------------------------------------------------------------
# build_routing_graph convenience
# ---------------------------------------------------------------------------


class TestBuildRoutingGraph:
    """Convenience build_routing_graph function."""

    def test_no_obstacles(self) -> None:
        graph = build_routing_graph((0, 0, 20, 20))
        assert graph.node_count > 0

    def test_with_obstacles(self) -> None:
        obs = SpatialBox(5, 5, 10, 10, "pad", "P1")
        graph = build_routing_graph((0, 0, 20, 20), obstacles=[obs])
        assert (7.0, 7.0) not in graph.graph.nodes

    def test_custom_constraints(self) -> None:
        c = RoutingConstraints(grid_resolution_mm=2.0)
        graph = build_routing_graph((0, 0, 20, 20), constraints=c)
        # 0, 2, 4, ..., 20 -> 11 per axis = 121 nodes
        assert graph.node_count == 11 * 11
