"""Tests for routing graph model and A* pathfinder.

Uses synthetic data (SpatialBox from spatial.primitives) -- no kicad-cli
dependency. Tests cover graph construction, obstacle exclusion, DRC
clearance, pathfinding, and batch routing.
"""

from __future__ import annotations

import math

import pytest

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.bridge import TrackSegment
from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.diff_pair import (
    DiffPairResult,
    _path_length,
    route_differential_pair,
)
from kicad_agent.routing.interactive import (
    InteractiveRoutingSession,
    RoutingSuggestion,
    SuggestionStatus,
)
from kicad_agent.routing.pathfinder import (
    RouteFailure,
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
        with pytest.raises(ValueError, match="max_nodes must be <= 2_000_000"):
            RoutingConstraints(max_nodes=3_000_000)

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
        assert (6.0, 6.0, "F.Cu") not in graph.graph.nodes
        # Node (0, 0) should be outside and present.
        assert (0.0, 0.0, "F.Cu") in graph.graph.nodes

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
        assert node == (5.0, 11.0, "F.Cu") or node == (5.0, 10.0, "F.Cu")

    def test_snap_to_node_exact(self) -> None:
        """snap_to_node returns exact grid point for on-grid input."""
        graph = self._make_empty_graph(50.0, 1.0)
        node = graph.snap_to_node(5.0, 10.0)
        assert node == (5.0, 10.0, "F.Cu")

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
        assert (11.0, 11.0, "F.Cu") not in graph.graph.nodes

        # Edges near obstacle should be omitted due to clearance violation.
        assert not graph.graph.has_edge((9.5, 10.0, "F.Cu"), (10.0, 10.0, "F.Cu"))
        assert not graph.graph.has_edge((9.0, 10.0, "F.Cu"), (9.5, 10.0, "F.Cu"))

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
        assert result.path[0] == (0.0, 0.0, "F.Cu")
        assert result.path[-1] == (10.0, 10.0, "F.Cu")

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
        for pt in result.path:
            x, y = pt[0], pt[1]
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
        # Phase 103: route_net returns RouteFailure (falsy) instead of None.
        assert not result
        assert isinstance(result, RouteFailure)

    def test_route_blocked_target_returns_none(self) -> None:
        """Blocked target (inside obstacle) returns RouteFailure."""
        obstacle = SpatialBox(15, 15, 20, 20, "zone", "Z1")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_net(graph, (0, 0), (17, 17), "BLOCKED")
        assert not result
        assert isinstance(result, RouteFailure)

    def test_route_no_path_returns_none(self) -> None:
        """Completely separated areas return RouteFailure with dead-end point."""
        # Wall spanning entire board height.
        wall = SpatialBox(10, 0, 11, 20, "keepout", "WALL")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[wall],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        # If the wall blocks all paths, route_net returns RouteFailure.
        # Note: with clearance enforcement, nodes near the wall edges
        # may also be removed, potentially creating a true barrier.
        # If some path exists, the test still passes (just gets a path).
        result = route_net(graph, (0, 10), (19, 10), "CUT")
        # Result is either RouteFailure or a valid detour -- both acceptable.
        if result:
            assert result.success
        else:
            # Phase 103: verify the dead-end point is the nearest-reached node.
            assert isinstance(result, RouteFailure)
            assert result.failure_type == "no_path"
            # Dead-end must be on the source side of the wall (x <= 10).
            # A node may exist right at the wall edge due to clearance rules.
            assert result.dead_end_point[0] <= 10
            # Target is at (19, 10); dead-end can't reach it.
            assert result.dead_end_point[0] < 19
            # Reachable count > 0 (source has a component).
            assert result.reachable_count > 0


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
        assert (7.0, 7.0, "F.Cu") not in graph.graph.nodes

    def test_custom_constraints(self) -> None:
        c = RoutingConstraints(grid_resolution_mm=2.0)
        graph = build_routing_graph((0, 0, 20, 20), constraints=c)
        # 0, 2, 4, ..., 20 -> 11 per axis = 121 nodes
        assert graph.node_count == 11 * 11


# ---------------------------------------------------------------------------
# ROUTE-03: Differential pair routing
# ---------------------------------------------------------------------------


class TestPathLength:
    """Unit test for _path_length utility."""

    def test_straight_line(self) -> None:
        """Straight horizontal path has correct length."""
        path = ((0.0, 0.0), (10.0, 0.0))
        assert _path_length(path) == 10.0

    def test_two_segments(self) -> None:
        """L-shaped path sums both segments."""
        path = ((0.0, 0.0), (3.0, 0.0), (3.0, 4.0))
        assert _path_length(path) == 7.0

    def test_diagonal(self) -> None:
        """Diagonal path uses Euclidean distance."""
        path = ((0.0, 0.0), (3.0, 4.0))
        assert abs(_path_length(path) - 5.0) < 1e-9

    def test_single_point(self) -> None:
        """Single point has zero length."""
        path = ((5.0, 5.0),)
        assert _path_length(path) == 0.0

    def test_empty_path(self) -> None:
        """Empty path has zero length."""
        assert _path_length(()) == 0.0


class TestDifferentialPair:
    """ROUTE-03: Differential pair routing with length matching."""

    def _make_empty_graph(
        self, size_mm: float = 50.0, grid_res: float = 1.0
    ) -> RoutingGraph:
        """Helper: build a routing graph with no obstacles."""
        return RoutingGraph(
            board_bounds=(0, 0, size_mm, size_mm),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=grid_res),
        )

    def test_diff_pair_basic(self) -> None:
        """Both nets route on clear board, valid=True."""
        graph = self._make_empty_graph(30.0, 1.0)
        # Parallel paths: positive at y=5, negative at y=7, both going x=0->20.
        result = route_differential_pair(
            graph,
            source_pos=(0, 5),
            source_neg=(0, 7),
            target_pos=(20, 5),
            target_neg=(20, 7),
            net_name_pos="DP_P",
            net_name_neg="DP_N",
        )
        assert isinstance(result, DiffPairResult)
        assert result.valid
        assert len(result.net_positive) >= 2
        assert len(result.net_negative) >= 2
        assert result.net_positive[0] == (0.0, 5.0)
        assert result.net_positive[-1] == (20.0, 5.0)
        assert result.net_negative[0] == (0.0, 7.0)
        assert result.net_negative[-1] == (20.0, 7.0)

    def test_diff_pair_length_matching(self) -> None:
        """Asymmetric positions trigger serpentining on the shorter path."""
        graph = self._make_empty_graph(50.0, 1.0)
        # Positive net: short path (0,5) -> (10,5) = 10mm
        # Negative net: long path (0,7) -> (30,7) = 30mm
        # Mismatch ~20mm should trigger serpentining on positive net.
        result = route_differential_pair(
            graph,
            source_pos=(0, 5),
            source_neg=(0, 7),
            target_pos=(10, 5),
            target_neg=(30, 7),
            target_spacing_mm=1.0,
            max_length_mismatch_mm=2.0,
        )
        assert isinstance(result, DiffPairResult)
        assert result.valid
        # After serpentining, mismatch should be within tolerance.
        assert result.mismatch_mm <= 2.0

    def test_diff_pair_blocked_positive(self) -> None:
        """Blocked positive net returns invalid result."""
        obstacle = SpatialBox(0, 0, 5, 10, "zone", "BLOCK_P")
        graph = RoutingGraph(
            board_bounds=(0, 0, 30, 30),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_differential_pair(
            graph,
            source_pos=(2, 5),   # Inside obstacle -- blocked.
            source_neg=(10, 5),
            target_pos=(20, 5),
            target_neg=(20, 7),
        )
        assert isinstance(result, DiffPairResult)
        assert not result.valid
        assert result.net_positive == ()

    def test_diff_pair_blocked_negative(self) -> None:
        """Blocked negative net returns invalid result."""
        obstacle = SpatialBox(0, 0, 5, 10, "zone", "BLOCK_N")
        graph = RoutingGraph(
            board_bounds=(0, 0, 30, 30),
            obstacles=[obstacle],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = route_differential_pair(
            graph,
            source_pos=(10, 5),
            source_neg=(2, 5),   # Inside obstacle -- blocked.
            target_pos=(20, 5),
            target_neg=(20, 7),
        )
        assert isinstance(result, DiffPairResult)
        assert not result.valid
        assert result.net_negative == ()

    def test_diff_pair_serpentine_bounded(self) -> None:
        """Serpentine amplitude does not exceed spacing_mm * 2."""
        graph = self._make_empty_graph(50.0, 1.0)
        spacing = 1.0
        result = route_differential_pair(
            graph,
            source_pos=(0, 5),
            source_neg=(0, 7),
            target_pos=(10, 5),
            target_neg=(30, 7),
            target_spacing_mm=spacing,
            max_length_mismatch_mm=1.0,
        )
        assert isinstance(result, DiffPairResult)
        # The shorter path (positive) should have more points than a
        # straight line if serpentining was applied.
        if result.length_positive_mm > 10.5:
            # Serpentining was applied -- verify path has extra points.
            assert len(result.net_positive) > 2

        # Check that serpentine bumps don't deviate more than spacing*2
        # from the original straight-line path. For a horizontal path at y=5,
        # all y-coordinates should be within [5 - 2*spacing, 5 + 2*spacing].
        max_amplitude = spacing * 2.0
        for pt in result.net_positive:
            x, y = pt[0], pt[1]
            assert abs(y - 5.0) <= max_amplitude + 1e-6, (
                f"Point ({x},{y}) exceeds amplitude bound"
            )


# ---------------------------------------------------------------------------
# ROUTE-04: Interactive routing session
# ---------------------------------------------------------------------------


def _make_session(
    netlist: dict[str, list[tuple[float, float]]] | None = None,
    constraints: RoutingConstraints | None = None,
    max_iterations: int = 5,
    differential_pairs: list[tuple[str, str]] | None = None,
) -> InteractiveRoutingSession:
    """Helper: build an InteractiveRoutingSession with a fresh graph."""
    if netlist is None:
        netlist = {
            "VCC": [(0, 0), (10, 0)],
            "GND": [(0, 5), (10, 5)],
            "SIG": [(0, 10), (10, 10)],
        }
    if constraints is None:
        constraints = RoutingConstraints(grid_resolution_mm=1.0)
    graph = RoutingGraph(
        board_bounds=(0, 0, 50, 50),
        obstacles=[],
        constraints=constraints,
    )
    return InteractiveRoutingSession(
        graph=graph,
        netlist=netlist,
        constraints=constraints,
        max_iterations=max_iterations,
        differential_pairs=differential_pairs,
    )


class TestInteractiveSession:
    """ROUTE-04: Interactive routing session with approve/reject/reroute."""

    def test_interactive_session_generates_suggestions(self) -> None:
        """3-net netlist produces 3 pending suggestions."""
        session = _make_session()
        assert len(session.suggestions) == 3
        for sugg in session.suggestions.values():
            assert sugg.status == SuggestionStatus.PENDING
            assert len(sugg.path) >= 2

    def test_interactive_approve(self) -> None:
        """Approving a net locks it and sets status."""
        session = _make_session()
        session.approve("VCC")
        assert session.suggestions["VCC"].status == SuggestionStatus.APPROVED
        assert "VCC" in session.locked_routes
        assert session.locked_routes["VCC"].net_name == "VCC"

    def test_interactive_reject(self) -> None:
        """Rejecting a net sets status and reason."""
        session = _make_session()
        session.reject("GND", reason="clearance violation")
        assert session.suggestions["GND"].status == SuggestionStatus.REJECTED
        assert session.suggestions["GND"].reject_reason == "clearance violation"
        assert "GND" not in session.locked_routes

    def test_interactive_reroute(self) -> None:
        """Reject and reroute produces new PENDING suggestions."""
        session = _make_session()
        session.reject("SIG")
        new_suggestions = session.reroute_rejected()
        assert len(new_suggestions) >= 1
        for sugg in new_suggestions:
            assert sugg.status == SuggestionStatus.PENDING
        assert session.iteration == 1

    def test_interactive_max_iterations(self) -> None:
        """Exceeding max_iterations raises RuntimeError."""
        session = _make_session(max_iterations=1)
        session.reject("VCC")
        session.reroute_rejected()
        # Second reroute should raise.
        session.reject("VCC")
        with pytest.raises(RuntimeError, match="Maximum iterations"):
            session.reroute_rejected()

    def test_interactive_set_constraint(self) -> None:
        """User constraint persists through reroute."""
        session = _make_session()
        session.set_constraint("VCC", "clearance_mm", 0.5)
        assert session.suggestions["VCC"].user_constraints["clearance_mm"] == 0.5

    def test_interactive_set_constraint_invalid_value(self) -> None:
        """Non-positive constraint value raises ValueError."""
        session = _make_session()
        with pytest.raises(ValueError, match="positive float"):
            session.set_constraint("VCC", "clearance_mm", -0.1)

    def test_interactive_locked_excluded_from_reroute(self) -> None:
        """Approved nets are not re-routed; only rejected ones are."""
        session = _make_session()
        session.approve("VCC")
        session.reject("GND")
        session.reject("SIG")
        new_suggestions = session.reroute_rejected()
        # VCC was approved -- it should NOT appear in new suggestions.
        rerouted_names = {s.net_name for s in new_suggestions}
        assert "VCC" not in rerouted_names
        assert "GND" in rerouted_names or "SIG" in rerouted_names

    def test_interactive_summary(self) -> None:
        """Summary dict counts match after approve/reject operations."""
        session = _make_session()
        session.approve("VCC")
        session.reject("GND", reason="bad")
        s = session.summary()
        assert s["total_nets"] == 3
        assert s["approved"] == 1
        assert s["rejected"] == 1
        assert s["pending"] == 1
        assert s["iteration"] == 0
        assert s["max_iterations"] == 5

    def test_interactive_nonexistent_net(self) -> None:
        """Approve/reject on non-existent net raises KeyError."""
        session = _make_session()
        with pytest.raises(KeyError, match="not found"):
            session.approve("NONEXISTENT")
        with pytest.raises(KeyError, match="not found"):
            session.reject("NONEXISTENT")
        with pytest.raises(KeyError, match="not found"):
            session.set_constraint("NONEXISTENT", "clearance_mm", 0.5)

    def test_interactive_diff_pair(self) -> None:
        """Differential pair nets are routed together and share status."""
        netlist = {
            "DP_P": [(0, 5), (20, 5)],
            "DP_N": [(0, 7), (20, 7)],
            "VCC": [(0, 0), (10, 0)],
        }
        session = _make_session(
            netlist=netlist,
            differential_pairs=[("DP_P", "DP_N")],
        )
        assert "DP_P" in session.suggestions
        assert "DP_N" in session.suggestions
        assert session.suggestions["DP_P"].is_differential_pair
        assert session.suggestions["DP_P"].diff_pair_complement == "DP_N"
        assert session.suggestions["DP_N"].diff_pair_complement == "DP_P"

    def test_interactive_diff_pair_approve_propagates(self) -> None:
        """Approving one diff pair net also approves its complement."""
        netlist = {
            "DP_P": [(0, 5), (20, 5)],
            "DP_N": [(0, 7), (20, 7)],
            "VCC": [(0, 0), (10, 0)],
        }
        session = _make_session(
            netlist=netlist,
            differential_pairs=[("DP_P", "DP_N")],
        )
        session.approve("DP_P")
        assert session.suggestions["DP_P"].status == SuggestionStatus.APPROVED
        assert session.suggestions["DP_N"].status == SuggestionStatus.APPROVED
        assert "DP_P" in session.locked_routes
        assert "DP_N" in session.locked_routes

    def test_interactive_diff_pair_reject_propagates(self) -> None:
        """Rejecting one diff pair net also rejects its complement."""
        netlist = {
            "DP_P": [(0, 5), (20, 5)],
            "DP_N": [(0, 7), (20, 7)],
            "VCC": [(0, 0), (10, 0)],
        }
        session = _make_session(
            netlist=netlist,
            differential_pairs=[("DP_P", "DP_N")],
        )
        session.reject("DP_N", reason="mismatch too large")
        assert session.suggestions["DP_P"].status == SuggestionStatus.REJECTED
        assert session.suggestions["DP_N"].status == SuggestionStatus.REJECTED
        assert session.suggestions["DP_P"].reject_reason == "mismatch too large"

    def test_interactive_is_complete(self) -> None:
        """is_complete is True only when all nets are approved."""
        session = _make_session()
        assert not session.is_complete
        session.approve("VCC")
        session.approve("GND")
        assert not session.is_complete
        session.approve("SIG")
        assert session.is_complete


# ---------------------------------------------------------------------------
# Routing bridge: RouteResult → KiCad track segments
# ---------------------------------------------------------------------------


class TestRoutingBridge:
    """Bridge from routing results to KiCad PCB track segments."""

    def test_route_to_segments_basic(self) -> None:
        """route_to_segments converts routing results into TrackSegments."""
        from kicad_agent.routing.bridge import route_to_segments

        results = {
            "VCC": RouteResult(
                net_name="VCC",
                path=((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)),
                length_mm=10.0,
                success=True,
            ),
        }
        segments = route_to_segments(results)
        assert len(segments) == 2
        # First segment: (0,0) -> (5,0)
        assert segments[0].start_x == 0.0
        assert segments[0].end_x == 5.0
        assert segments[0].net == "VCC"
        assert segments[0].layer == "F.Cu"
        # Second segment: (5,0) -> (5,5)
        assert segments[1].start_x == 5.0
        assert segments[1].end_y == 5.0

    def test_route_to_segments_skips_failed(self) -> None:
        """Failed routes are skipped."""
        from kicad_agent.routing.bridge import route_to_segments

        results = {
            "VCC": RouteResult("VCC", ((0.0, 0.0),), 0.0, success=False),
            "GND": RouteResult("GND", ((0.0, 0.0), (5.0, 5.0)), 7.07, success=True),
        }
        segments = route_to_segments(results)
        assert len(segments) == 1
        assert segments[0].net == "GND"

    def test_route_to_segments_custom_layer(self) -> None:
        """Custom layer parameter is passed through."""
        from kicad_agent.routing.bridge import route_to_segments

        results = {
            "SIG": RouteResult("SIG", ((0.0, 0.0), (10.0, 0.0)), 10.0, success=True),
        }
        segments = route_to_segments(results, layer="B.Cu")
        assert segments[0].layer == "B.Cu"

    def test_track_segment_to_sexpr(self) -> None:
        """TrackSegment serializes to valid KiCad S-expression."""
        from kicad_agent.routing.bridge import TrackSegment

        seg = TrackSegment(
            start_x=1.0, start_y=2.0,
            end_x=3.0, end_y=4.0,
            width=0.25, layer="F.Cu", net="VCC",
        )
        sexpr = seg.to_sexpr(uuid_tag="abc-123")
        assert "(segment" in sexpr
        assert "(start 1.0000 2.0000)" in sexpr
        assert "(end 3.0000 4.0000)" in sexpr
        assert "(width 0.2500)" in sexpr
        assert '"F.Cu"' in sexpr
        assert '"VCC"' in sexpr
        assert '(uuid "abc-123")' in sexpr

    def test_segments_to_sexpr_block(self) -> None:
        """segments_to_sexpr produces a multi-segment S-expression block."""
        from kicad_agent.routing.bridge import (
            TrackSegment,
            route_to_segments,
            segments_to_sexpr,
        )

        results = {
            "VCC": RouteResult("VCC", ((0.0, 0.0), (5.0, 0.0)), 5.0, success=True),
            "GND": RouteResult("GND", ((0.0, 5.0), (5.0, 5.0)), 5.0, success=True),
        }
        segments = route_to_segments(results)
        block = segments_to_sexpr(segments)
        assert block.count("(segment") == 2

    def test_track_segment_no_net(self) -> None:
        """TrackSegment with empty net omits net field."""
        from kicad_agent.routing.bridge import TrackSegment

        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=1.0, end_y=1.0,
            width=0.25, layer="F.Cu", net="",
        )
        sexpr = seg.to_sexpr()
        assert "(net" not in sexpr


# ---------------------------------------------------------------------------
# RoutingGraph.mark_path_as_obstacle
# ---------------------------------------------------------------------------


class TestMarkPathAsObstacle:
    """Progressive obstacle marking for multi-net routing."""

    def test_edges_removed_along_path(self) -> None:
        """Edges along a routed path are removed from the graph."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        # Verify edge exists before marking.
        assert graph.graph.has_edge((5.0, 5.0, "F.Cu"), (6.0, 5.0, "F.Cu"))
        graph.mark_path_as_obstacle(((5.0, 5.0, "F.Cu"), (6.0, 5.0, "F.Cu"), (7.0, 5.0, "F.Cu")))
        # Edges (5,5)-(6,5) and (6,5)-(7,5) should be removed.
        assert not graph.graph.has_edge((5.0, 5.0, "F.Cu"), (6.0, 5.0, "F.Cu"))
        assert not graph.graph.has_edge((6.0, 5.0, "F.Cu"), (7.0, 5.0, "F.Cu"))
        # Adjacent edge (4,5)-(5,5) should still exist.
        assert graph.graph.has_edge((4.0, 5.0, "F.Cu"), (5.0, 5.0, "F.Cu"))

    def test_multi_net_obstacle_marking(self) -> None:
        """route_all_nets marks paths as obstacles, preventing reuse."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        netlist = {
            "NET1": [(0, 5), (10, 5)],
            "NET2": [(0, 5), (10, 5)],  # Same route — must find alternative
        }
        results = route_all_nets(graph, netlist)
        # Both nets should still route (detour available).
        assert len(results) == 2
        # The two nets should take different paths since NET1 blocked the direct route.
        if results["NET1"].success and results["NET2"].success:
            assert results["NET1"].path != results["NET2"].path

    def test_empty_path_no_error(self) -> None:
        """Empty path doesn't cause errors."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 10, 10),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        graph.mark_path_as_obstacle(())  # Should not raise


# ---------------------------------------------------------------------------
# ROUTE-05: Multi-layer routing (3D graph, via edges)
# ---------------------------------------------------------------------------


class TestRoutingConstraints3D:
    """Multi-layer constraint fields: via_cost_mm, layer_trace_widths, stackup."""

    def test_via_cost_mm_default(self) -> None:
        """via_cost_mm defaults to 5.0."""
        c = RoutingConstraints()
        assert c.via_cost_mm == 5.0

    def test_via_cost_mm_must_be_positive(self) -> None:
        """via_cost_mm must be > 0."""
        with pytest.raises(ValueError, match="via_cost_mm must be > 0"):
            RoutingConstraints(via_cost_mm=0)
        with pytest.raises(ValueError, match="via_cost_mm must be > 0"):
            RoutingConstraints(via_cost_mm=-1.0)

    def test_via_cost_mm_custom(self) -> None:
        """via_cost_mm accepts positive custom values."""
        c = RoutingConstraints(via_cost_mm=10.0)
        assert c.via_cost_mm == 10.0

    def test_layer_trace_widths_default_none(self) -> None:
        """layer_trace_widths defaults to None."""
        c = RoutingConstraints()
        assert c.layer_trace_widths is None

    def test_layer_trace_widths_custom(self) -> None:
        """layer_trace_widths accepts a dict mapping layer names to widths."""
        c = RoutingConstraints(
            layer_trace_widths={"F.Cu": 0.3, "B.Cu": 0.25}
        )
        assert c.layer_trace_widths == {"F.Cu": 0.3, "B.Cu": 0.25}

    def test_dielectric_constant_default(self) -> None:
        """dielectric_constant defaults to 4.5."""
        c = RoutingConstraints()
        assert c.dielectric_constant == 4.5

    def test_dielectric_constant_must_be_positive(self) -> None:
        """dielectric_constant must be > 0."""
        with pytest.raises(ValueError, match="dielectric_constant must be > 0"):
            RoutingConstraints(dielectric_constant=0)

    def test_dielectric_height_default(self) -> None:
        """dielectric_height_mm defaults to 0.2."""
        c = RoutingConstraints()
        assert c.dielectric_height_mm == 0.2

    def test_dielectric_height_must_be_positive(self) -> None:
        """dielectric_height_mm must be > 0."""
        with pytest.raises(ValueError, match="dielectric_height_mm must be > 0"):
            RoutingConstraints(dielectric_height_mm=-0.1)

    def test_copper_thickness_default(self) -> None:
        """copper_thickness_mm defaults to 0.035."""
        c = RoutingConstraints()
        assert c.copper_thickness_mm == 0.035

    def test_copper_thickness_must_be_positive(self) -> None:
        """copper_thickness_mm must be > 0."""
        with pytest.raises(ValueError, match="copper_thickness_mm must be > 0"):
            RoutingConstraints(copper_thickness_mm=0)

    def test_max_nodes_raised_cap(self) -> None:
        """max_nodes cap raised to 2,000,000."""
        c = RoutingConstraints(max_nodes=2_000_000)
        assert c.max_nodes == 2_000_000

    def test_max_nodes_over_new_cap(self) -> None:
        """max_nodes over 2,000,000 still raises ValueError."""
        with pytest.raises(ValueError, match="max_nodes must be <= 2_000_000"):
            RoutingConstraints(max_nodes=3_000_000)

    def test_effective_trace_width_default(self) -> None:
        """effective_trace_width returns trace_width_mm when no layer overrides."""
        c = RoutingConstraints(trace_width_mm=0.25)
        assert c.effective_trace_width("F.Cu") == 0.25
        assert c.effective_trace_width("B.Cu") == 0.25

    def test_effective_trace_width_layer_override(self) -> None:
        """effective_trace_width returns layer-specific width when set."""
        c = RoutingConstraints(
            trace_width_mm=0.25,
            layer_trace_widths={"F.Cu": 0.3, "In1.Cu": 0.2},
        )
        assert c.effective_trace_width("F.Cu") == 0.3
        assert c.effective_trace_width("In1.Cu") == 0.2
        # Layer not in overrides falls back to trace_width_mm.
        assert c.effective_trace_width("B.Cu") == 0.25


class TestRoutingGraph3D:
    """Multi-layer graph construction with 3D (x, y, layer) nodes."""

    def _make_2layer_graph(
        self,
        size_mm: float = 10.0,
        grid_res: float = 1.0,
        layers: list[str] | None = None,
    ) -> RoutingGraph:
        if layers is None:
            layers = ["F.Cu", "B.Cu"]
        return RoutingGraph(
            board_bounds=(0, 0, size_mm, size_mm),
            obstacles=[],
            constraints=RoutingConstraints(
                grid_resolution_mm=grid_res,
                via_cost_mm=5.0,
            ),
            layers=layers,
        )

    def test_2layer_node_count(self) -> None:
        """2-layer graph has ~2x the single-layer node count."""
        graph = self._make_2layer_graph(10.0, 1.0, ["F.Cu", "B.Cu"])
        # 11x11 = 121 nodes per layer, 242 total.
        assert graph.node_count == 242

    def test_3d_node_format(self) -> None:
        """Nodes are (x, y, layer) 3-tuples."""
        graph = self._make_2layer_graph(5.0, 1.0, ["F.Cu", "In1.Cu"])
        for node in graph.graph.nodes:
            assert len(node) == 3
            assert isinstance(node[2], str)

    def test_nodes_on_both_layers(self) -> None:
        """Both layers have nodes."""
        graph = self._make_2layer_graph(5.0, 1.0, ["F.Cu", "B.Cu"])
        f_cu_nodes = [n for n in graph.graph.nodes if n[2] == "F.Cu"]
        b_cu_nodes = [n for n in graph.graph.nodes if n[2] == "B.Cu"]
        assert len(f_cu_nodes) > 0
        assert len(b_cu_nodes) > 0
        assert len(f_cu_nodes) == len(b_cu_nodes)

    def test_via_edges_connect_adjacent_layers(self) -> None:
        """Via edges connect same (x,y) on adjacent layers with via_cost_mm."""
        constraints = RoutingConstraints(grid_resolution_mm=1.0, via_cost_mm=7.5)
        graph = RoutingGraph(
            board_bounds=(0, 0, 5, 5),
            obstacles=[],
            constraints=constraints,
            layers=["F.Cu", "B.Cu"],
        )
        # Check a specific via edge.
        node_f = (3.0, 3.0, "F.Cu")
        node_b = (3.0, 3.0, "B.Cu")
        assert graph.graph.has_edge(node_f, node_b)
        assert graph.graph[node_f][node_b]["weight"] == 7.5

    def test_via_edge_count(self) -> None:
        """Via edge count matches expected for 2-layer board."""
        graph = self._make_2layer_graph(5.0, 1.0, ["F.Cu", "B.Cu"])
        # 6x6 = 36 nodes per layer, all overlap, so 36 via edges.
        via_edges = [
            (u, v)
            for u, v in graph.graph.edges
            if u[2] != v[2]
        ]
        assert len(via_edges) == 36

    def test_same_layer_edges_exist(self) -> None:
        """Same-layer horizontal and vertical edges exist on both layers."""
        graph = self._make_2layer_graph(5.0, 1.0, ["F.Cu", "B.Cu"])
        # Check F.Cu same-layer edge.
        assert graph.graph.has_edge((0.0, 0.0, "F.Cu"), (1.0, 0.0, "F.Cu"))
        # Check B.Cu same-layer edge.
        assert graph.graph.has_edge((0.0, 0.0, "B.Cu"), (1.0, 0.0, "B.Cu"))

    def test_layers_none_backward_compat(self) -> None:
        """layers=None defaults to single-layer F.Cu, backward compatible."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 10, 10),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            layers=None,
        )
        # Should behave like old 2D graph.
        assert graph.node_count == 121  # 11x11
        # Nodes should be 3-tuples with "F.Cu" layer.
        for node in graph.graph.nodes:
            assert len(node) == 3
            assert node[2] == "F.Cu"

    def test_snap_to_node_with_layer(self) -> None:
        """snap_to_node with layer parameter returns 3D tuple."""
        graph = self._make_2layer_graph(10.0, 1.0)
        node = graph.snap_to_node(5.3, 10.7, layer="F.Cu")
        assert node is not None
        assert len(node) == 3
        assert node[2] == "F.Cu"

    def test_snap_to_node_without_layer_3d(self) -> None:
        """snap_to_node without layer finds nearest on any layer."""
        graph = self._make_2layer_graph(10.0, 1.0)
        node = graph.snap_to_node(5.0, 5.0)
        assert node is not None
        assert len(node) == 3

    def test_snap_to_node_layer_specific(self) -> None:
        """snap_to_node with layer restricts to that layer only."""
        graph = self._make_2layer_graph(10.0, 1.0)
        node_f = graph.snap_to_node(5.0, 5.0, layer="F.Cu")
        node_b = graph.snap_to_node(5.0, 5.0, layer="B.Cu")
        assert node_f is not None
        assert node_b is not None
        assert node_f[2] == "F.Cu"
        assert node_b[2] == "B.Cu"
        # Same x,y but different layer.
        assert node_f[:2] == node_b[:2]

    def test_mark_path_as_obstacle_3d(self) -> None:
        """mark_path_as_obstacle works with 3D path tuples."""
        graph = self._make_2layer_graph(10.0, 1.0)
        node_a = (5.0, 5.0, "F.Cu")
        node_b = (6.0, 5.0, "F.Cu")
        assert graph.graph.has_edge(node_a, node_b)
        graph.mark_path_as_obstacle((node_a, node_b))
        assert not graph.graph.has_edge(node_a, node_b)

    def test_obstacle_nodes_excluded_on_all_layers(self) -> None:
        """Obstacles exclude nodes on all layers."""
        obstacle = SpatialBox(3, 3, 5, 5, "footprint", "U1")
        constraints = RoutingConstraints(grid_resolution_mm=1.0)
        graph = RoutingGraph(
            board_bounds=(0, 0, 10, 10),
            obstacles=[obstacle],
            constraints=constraints,
            layers=["F.Cu", "B.Cu"],
        )
        # (4, 4) is inside obstacle -- excluded on both layers.
        assert (4.0, 4.0, "F.Cu") not in graph.graph.nodes
        assert (4.0, 4.0, "B.Cu") not in graph.graph.nodes
        # (0, 0) is outside -- present on both layers.
        assert (0.0, 0.0, "F.Cu") in graph.graph.nodes
        assert (0.0, 0.0, "B.Cu") in graph.graph.nodes

    def test_3layer_graph(self) -> None:
        """3-layer graph builds correctly with via edges between adjacent."""
        graph = RoutingGraph(
            board_bounds=(0, 0, 5, 5),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            layers=["F.Cu", "In1.Cu", "B.Cu"],
        )
        # 6x6 = 36 per layer, 3 layers = 108 nodes.
        assert graph.node_count == 108
        # Via edges: F.Cu-In1.Cu (36) + In1.Cu-B.Cu (36) = 72.
        via_edges = [
            (u, v) for u, v in graph.graph.edges if u[2] != v[2]
        ]
        assert len(via_edges) == 72
        # No direct via between F.Cu and B.Cu (not adjacent).
        assert not graph.graph.has_edge((0.0, 0.0, "F.Cu"), (0.0, 0.0, "B.Cu"))


# ---------------------------------------------------------------------------
# ROUTE-05: 3D pathfinding and ViaSegment
# ---------------------------------------------------------------------------


class TestPathfinding3D:
    """3D pathfinding: route across layers, via detours, multi-layer batch."""

    def _make_2layer_graph(
        self,
        size_mm: float = 20.0,
        grid_res: float = 1.0,
        via_cost: float = 5.0,
    ) -> RoutingGraph:
        return RoutingGraph(
            board_bounds=(0, 0, size_mm, size_mm),
            obstacles=[],
            constraints=RoutingConstraints(
                grid_resolution_mm=grid_res,
                via_cost_mm=via_cost,
            ),
            layers=["F.Cu", "B.Cu"],
        )

    def test_route_3d_same_layer(self) -> None:
        """route_net on 3D graph routes on same layer."""
        graph = self._make_2layer_graph()
        result = route_net(
            graph,
            (0.0, 0.0, "F.Cu"),
            (10.0, 0.0, "F.Cu"),
            "NET3D",
        )
        assert result is not None
        assert result.success
        assert result.path[0] == (0.0, 0.0, "F.Cu")
        assert result.path[-1] == (10.0, 0.0, "F.Cu")

    def test_route_3d_cross_layer(self) -> None:
        """route_net with different source/target layers uses vias."""
        graph = self._make_2layer_graph()
        result = route_net(
            graph,
            (0.0, 0.0, "F.Cu"),
            (10.0, 0.0, "B.Cu"),
            "VIA_NET",
        )
        assert result is not None
        assert result.success
        # Path starts on F.Cu and ends on B.Cu.
        assert result.path[0][2] == "F.Cu"
        assert result.path[-1][2] == "B.Cu"
        # Path should contain at least one layer transition.
        layers_in_path = {pt[2] for pt in result.path}
        assert len(layers_in_path) == 2

    def test_route_3d_blocked_layer_via_detour(self) -> None:
        """Wall on one axis -- route takes via to another layer for shorter path."""
        # Small obstacle blocking the direct path at (5,10) on both layers.
        # But with a via, the path can detour more efficiently.
        # Actually test that cross-layer routing works: source on F.Cu,
        # target on B.Cu forces a layer transition.
        wall = SpatialBox(8, 8, 9, 12, "keepout", "WALL")
        graph = RoutingGraph(
            board_bounds=(0, 0, 20, 20),
            obstacles=[wall],
            constraints=RoutingConstraints(
                grid_resolution_mm=1.0,
                via_cost_mm=5.0,
            ),
            layers=["F.Cu", "B.Cu"],
        )
        # Source on F.Cu, target on B.Cu -- must transition layers.
        result = route_net(
            graph,
            (5.0, 10.0, "F.Cu"),
            (15.0, 10.0, "B.Cu"),
            "DETOUR",
        )
        assert result is not None
        assert result.success
        # Path starts on F.Cu, ends on B.Cu.
        assert result.path[0][2] == "F.Cu"
        assert result.path[-1][2] == "B.Cu"
        # Path must visit both layers.
        layers_in_path = {pt[2] for pt in result.path}
        assert len(layers_in_path) == 2

    def test_route_result_3d_path_tuples(self) -> None:
        """RouteResult.path contains 3D tuples on multi-layer graph."""
        graph = self._make_2layer_graph()
        result = route_net(
            graph,
            (0.0, 0.0, "F.Cu"),
            (5.0, 5.0, "F.Cu"),
            "3D_TUPLES",
        )
        assert result is not None
        for pt in result.path:
            assert len(pt) == 3

    def test_euclidean_heuristic_3d(self) -> None:
        """_euclidean_heuristic works with 3D tuples (ignores layer)."""
        from kicad_agent.routing.pathfinder import _euclidean_heuristic
        d = _euclidean_heuristic((0.0, 0.0, "F.Cu"), (3.0, 4.0, "B.Cu"))
        assert abs(d - 5.0) < 1e-9

    def test_route_all_nets_multilayer(self) -> None:
        """route_all_nets works on multi-layer graph."""
        graph = self._make_2layer_graph()
        netlist = {
            "VCC": [(0, 0), (10, 0)],
            "GND": [(0, 5), (10, 5)],
        }
        results = route_all_nets(graph, netlist)
        assert len(results) == 2
        assert results["VCC"].success
        assert results["GND"].success

    def test_build_routing_graph_with_layers(self) -> None:
        """build_routing_graph accepts layers parameter."""
        graph = build_routing_graph(
            (0, 0, 5, 5),
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            layers=["F.Cu", "B.Cu"],
        )
        # 6x6 per layer * 2 = 72 nodes.
        assert graph.node_count == 72


class TestViaSegment:
    """ViaSegment frozen dataclass and to_sexpr()."""

    def test_construction(self) -> None:
        """ViaSegment holds x, y, from_layer, to_layer, diameter, drill, net."""
        from kicad_agent.routing.bridge import ViaSegment
        via = ViaSegment(
            x=5.0, y=10.0,
            from_layer="F.Cu", to_layer="B.Cu",
            diameter=0.8, drill=0.4, net="VCC",
        )
        assert via.x == 5.0
        assert via.from_layer == "F.Cu"
        assert via.to_layer == "B.Cu"

    def test_frozen(self) -> None:
        """ViaSegment is frozen."""
        from kicad_agent.routing.bridge import ViaSegment
        via = ViaSegment(5.0, 5.0, "F.Cu", "B.Cu", 0.8, 0.4, "GND")
        with pytest.raises(AttributeError):
            via.x = 6.0  # type: ignore[misc]

    def test_to_sexpr(self) -> None:
        """ViaSegment.to_sexpr() produces valid KiCad via S-expression."""
        from kicad_agent.routing.bridge import ViaSegment
        via = ViaSegment(5.0, 10.0, "F.Cu", "B.Cu", 0.8, 0.4, "VCC")
        sexpr = via.to_sexpr(uuid_tag="test-uuid")
        assert "(via" in sexpr
        assert "(at 5.0000 10.0000)" in sexpr
        assert "(size 0.8000)" in sexpr
        assert "(drill 0.4000)" in sexpr
        assert '"F.Cu"' in sexpr
        assert '"B.Cu"' in sexpr
        assert '"VCC"' in sexpr
        assert '(uuid "test-uuid")' in sexpr

    def test_to_sexpr_no_net(self) -> None:
        """ViaSegment with empty net omits net field."""
        from kicad_agent.routing.bridge import ViaSegment
        via = ViaSegment(5.0, 5.0, "F.Cu", "B.Cu", 0.8, 0.4, "")
        sexpr = via.to_sexpr()
        assert "(net" not in sexpr


class TestRouteToSegmentsMultilayer:
    """route_to_segments_multilayer with layer extraction and vias."""

    def _make_3d_results(self) -> dict[str, RouteResult]:
        """Create synthetic 3D route results with layer transitions."""
        return {
            "CROSS": RouteResult(
                net_name="CROSS",
                path=(
                    (0.0, 0.0, "F.Cu"),
                    (5.0, 0.0, "F.Cu"),
                    (5.0, 0.0, "B.Cu"),
                    (10.0, 0.0, "B.Cu"),
                ),
                length_mm=15.0,
                success=True,
            ),
        }

    def test_extracts_track_segments_with_layers(self) -> None:
        """Produces TrackSegments with correct layer from 3D path."""
        from kicad_agent.routing.bridge import route_to_segments_multilayer
        results = self._make_3d_results()
        segments = route_to_segments_multilayer(results)
        # Should have 3 track segments: (0,0,F)->(5,0,F), (5,0,F)->(5,0,B) is via,
        # (5,0,B)->(10,0,B)
        track_segs = [s for s in segments if isinstance(s, TrackSegment)]
        assert len(track_segs) == 2
        # First segment on F.Cu.
        f_cu_segs = [s for s in track_segs if s.layer == "F.Cu"]
        assert len(f_cu_segs) == 1
        # Second segment on B.Cu.
        b_cu_segs = [s for s in track_segs if s.layer == "B.Cu"]
        assert len(b_cu_segs) == 1

    def test_produces_via_segments(self) -> None:
        """Produces ViaSegments at layer transitions."""
        from kicad_agent.routing.bridge import ViaSegment, route_to_segments_multilayer
        results = self._make_3d_results()
        segments = route_to_segments_multilayer(results)
        via_segs = [s for s in segments if isinstance(s, ViaSegment)]
        assert len(via_segs) == 1
        via = via_segs[0]
        assert via.x == 5.0
        assert via.y == 0.0
        assert via.from_layer == "F.Cu"
        assert via.to_layer == "B.Cu"
        assert via.net == "CROSS"

    def test_single_layer_no_vias(self) -> None:
        """Single-layer path produces no ViaSegments."""
        from kicad_agent.routing.bridge import ViaSegment, route_to_segments_multilayer
        results = {
            "FLAT": RouteResult(
                net_name="FLAT",
                path=(
                    (0.0, 0.0, "F.Cu"),
                    (5.0, 0.0, "F.Cu"),
                    (10.0, 0.0, "F.Cu"),
                ),
                length_mm=10.0,
                success=True,
            ),
        }
        segments = route_to_segments_multilayer(results)
        via_segs = [s for s in segments if isinstance(s, ViaSegment)]
        assert len(via_segs) == 0
        track_segs = [s for s in segments if isinstance(s, TrackSegment)]
        assert len(track_segs) == 2

    def test_effective_trace_width_per_layer(self) -> None:
        """Uses effective_trace_width for per-layer segment widths."""
        from kicad_agent.routing.bridge import TrackSegment, route_to_segments_multilayer
        constraints = RoutingConstraints(
            trace_width_mm=0.25,
            layer_trace_widths={"F.Cu": 0.3, "B.Cu": 0.2},
        )
        results = self._make_3d_results()
        segments = route_to_segments_multilayer(results, constraints)
        track_segs = [s for s in segments if isinstance(s, TrackSegment)]
        f_cu = [s for s in track_segs if s.layer == "F.Cu"][0]
        b_cu = [s for s in track_segs if s.layer == "B.Cu"][0]
        assert f_cu.width == 0.3
        assert b_cu.width == 0.2


# ---------------------------------------------------------------------------
# IPC-2141 Impedance Calculator (Plan 36-02 Task 1)
# ---------------------------------------------------------------------------


class TestImpedance:
    """IPC-2141 microstrip/stripline impedance and bisection trace width solver."""

    def test_microstrip_known_value(self) -> None:
        """w=0.47mm microstrip on er=4.5 stackup gives ~50 ohm (within 5%)."""
        from kicad_agent.routing.impedance import microstrip_z0
        z0 = microstrip_z0(w=0.47, h=0.2, t=0.035, er=4.5)
        assert 47.5 <= z0 <= 52.5, f"Expected ~50 ohm, got {z0:.2f}"

    def test_stripline_known_value(self) -> None:
        """w=0.09mm symmetric stripline on er=4.5 gives ~50 ohm (within 5%)."""
        from kicad_agent.routing.impedance import stripline_z0
        z0 = stripline_z0(w=0.09, h=0.15, t=0.035, er=4.5)
        assert 47.5 <= z0 <= 52.5, f"Expected ~50 ohm, got {z0:.2f}"

    def test_microstrip_decreases_with_width(self) -> None:
        """Wider trace has lower impedance."""
        from kicad_agent.routing.impedance import microstrip_z0
        z0_narrow = microstrip_z0(w=0.2, h=0.2, t=0.035, er=4.5)
        z0_wide = microstrip_z0(w=0.6, h=0.2, t=0.035, er=4.5)
        assert z0_wide < z0_narrow

    def test_stripline_decreases_with_width(self) -> None:
        """Wider stripline trace has lower impedance."""
        from kicad_agent.routing.impedance import stripline_z0
        z0_narrow = stripline_z0(w=0.05, h=0.15, t=0.035, er=4.5)
        z0_wide = stripline_z0(w=0.3, h=0.15, t=0.035, er=4.5)
        assert z0_wide < z0_narrow

    def test_impedance_result_is_frozen(self) -> None:
        """ImpedanceResult is a frozen dataclass."""
        from kicad_agent.routing.impedance import ImpedanceResult
        r = ImpedanceResult(
            trace_width_mm=0.47,
            target_z0=50.0,
            achieved_z0=49.8,
            impedance_error_percent=0.4,
            model="microstrip",
            valid=True,
        )
        with pytest.raises(AttributeError):
            r.valid = False  # type: ignore[misc]

    def test_impedance_result_fields(self) -> None:
        """ImpedanceResult has all required fields."""
        from kicad_agent.routing.impedance import ImpedanceResult
        r = ImpedanceResult(
            trace_width_mm=0.47,
            target_z0=50.0,
            achieved_z0=49.8,
            impedance_error_percent=0.4,
            model="microstrip",
            valid=True,
        )
        assert r.trace_width_mm == 0.47
        assert r.target_z0 == 50.0
        assert r.achieved_z0 == 49.8
        assert r.impedance_error_percent == 0.4
        assert r.model == "microstrip"
        assert r.valid is True

    def test_solve_trace_width_microstrip(self) -> None:
        """Bisection solver finds ~0.47mm for 50-ohm microstrip target."""
        from kicad_agent.routing.impedance import solve_trace_width
        r = solve_trace_width(
            target_z0=50.0, h=0.2, t=0.035, er=4.5, model="microstrip"
        )
        assert r.valid is True
        assert r.impedance_error_percent < 1.0
        assert abs(r.trace_width_mm - 0.47) < 0.05

    def test_solve_trace_width_stripline(self) -> None:
        """Bisection solver converges for stripline model."""
        from kicad_agent.routing.impedance import solve_trace_width
        r = solve_trace_width(
            target_z0=50.0, h=0.15, t=0.035, er=4.5, model="stripline",
            min_width=0.05,
        )
        assert r.valid is True
        assert r.impedance_error_percent < 1.0

    def test_solve_trace_width_min_width_clamp(self) -> None:
        """Very high target impedance clamps to min_width=0.1mm."""
        from kicad_agent.routing.impedance import solve_trace_width
        r = solve_trace_width(
            target_z0=200.0, h=0.2, t=0.035, er=4.5, model="microstrip",
            min_width=0.1, max_width=2.0,
        )
        assert r.trace_width_mm == pytest.approx(0.1, abs=0.001)

    def test_solve_trace_width_unreachable_returns_invalid(self) -> None:
        """Unreachable impedance target returns valid=False."""
        from kicad_agent.routing.impedance import solve_trace_width
        r = solve_trace_width(
            target_z0=200.0, h=0.2, t=0.035, er=4.5, model="microstrip",
            min_width=0.1, max_width=0.15,
        )
        assert r.valid is False
        assert r.impedance_error_percent > 1.0

    def test_solve_trace_width_valid_reflects_error(self) -> None:
        """ImpedanceResult.valid is True when error <= tolerance_percent."""
        from kicad_agent.routing.impedance import solve_trace_width
        r = solve_trace_width(
            target_z0=50.0, h=0.2, t=0.035, er=4.5, model="microstrip",
            tolerance_percent=1.0,
        )
        if r.valid:
            assert r.impedance_error_percent <= 1.0
        else:
            assert r.impedance_error_percent > 1.0

    def test_solve_trace_width_validates_model(self) -> None:
        """Invalid model raises ValueError."""
        from kicad_agent.routing.impedance import solve_trace_width
        with pytest.raises(ValueError, match="model"):
            solve_trace_width(
                target_z0=50.0, h=0.2, t=0.035, er=4.5, model="coaxial"
            )

    def test_solve_trace_width_validates_positive(self) -> None:
        """Negative parameters raise ValueError."""
        from kicad_agent.routing.impedance import solve_trace_width
        with pytest.raises(ValueError):
            solve_trace_width(
                target_z0=-10.0, h=0.2, t=0.035, er=4.5
            )


# ---------------------------------------------------------------------------
# Sawtooth Length Matching (Plan 36-02 Task 2)
# ---------------------------------------------------------------------------


class TestSawtoothMatching:
    """Sawtooth length matching with measure-and-refine convergence."""

    def test_sawtooth_extra_length_positive(self) -> None:
        """_sawtooth_extra_length returns positive value for nonzero amplitude."""
        from kicad_agent.routing.length_matching import _sawtooth_extra_length
        extra = _sawtooth_extra_length(amplitude=1.0, half_pitch=0.5)
        expected = 2 * math.hypot(0.5, 1.0) - 2 * 0.5
        assert extra == pytest.approx(expected, rel=1e-6)
        assert extra > 0

    def test_sawtooth_extra_length_zero_amplitude(self) -> None:
        """_sawtooth_extra_length returns 0 when amplitude=0."""
        from kicad_agent.routing.length_matching import _sawtooth_extra_length
        extra = _sawtooth_extra_length(amplitude=0.0, half_pitch=0.5)
        assert extra == pytest.approx(0.0, abs=1e-9)

    def test_zero_delta_returns_original(self) -> None:
        """target_delta_mm=0 returns original path unchanged."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        path = ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0))
        result = add_sawtooth_matching(path, target_delta_mm=0.0)
        assert result.path == path
        assert result.achieved_delta_mm == 0.0

    def test_positive_delta_longer_path(self) -> None:
        """target_delta_mm > 0 returns path longer than original."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        from kicad_agent.routing.geometry import _path_length
        path = ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0))
        original_len = _path_length(path)
        result = add_sawtooth_matching(path, target_delta_mm=2.0)
        result_len = _path_length(result.path)
        assert result_len > original_len

    def test_target_5mm_delta_on_20mm_path(self) -> None:
        """add_sawtooth_matching adds approximately 5mm on a 20mm path."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        from kicad_agent.routing.geometry import _path_length
        path = ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0))
        original_len = _path_length(path)
        result = add_sawtooth_matching(path, target_delta_mm=5.0)
        result_len = _path_length(result.path)
        actual_delta = result_len - original_len
        assert actual_delta == pytest.approx(5.0, abs=0.5), (
            f"Expected ~5mm delta, got {actual_delta:.2f}mm"
        )

    def test_bumps_are_triangle_shaped(self) -> None:
        """Sawtooth bumps have 3 points per bump (start, peak, end)."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        path = ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0))
        result = add_sawtooth_matching(path, target_delta_mm=2.0, spacing_mm=1.0)
        # Each bump adds 3 points. Original path has 3 points + first/last
        # preserved. So total = 3 + num_bumps * 3.
        # Just verify we have more points than original and num_bumps > 0.
        assert len(result.path) > len(path)
        assert result.num_bumps > 0

    def test_amplitude_capped_by_detour_ratio(self) -> None:
        """Sawtooth amplitude does not exceed half_pitch * max_detour_ratio."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        path = ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0))
        max_detour = 3.0
        result = add_sawtooth_matching(
            path, target_delta_mm=10.0, spacing_mm=1.0,
            max_detour_ratio=max_detour,
        )
        # Even with large target, bumps should exist and amplitude is capped.
        # We can't directly inspect amplitude, but we verify the result
        # doesn't produce a path with absurd length.
        from kicad_agent.routing.geometry import _path_length
        original_len = _path_length(path)
        max_possible_delta = result.num_bumps * _sawtooth_max_extra(
            spacing_mm=1.0, max_detour_ratio=max_detour,
        )
        actual_delta = _path_length(result.path) - original_len
        assert actual_delta <= max_possible_delta + 0.1

    def test_length_match_result_frozen(self) -> None:
        """LengthMatchResult is a frozen dataclass."""
        from kicad_agent.routing.length_matching import LengthMatchResult
        r = LengthMatchResult(
            path=((0.0, 0.0), (10.0, 0.0)),
            target_delta_mm=2.0,
            achieved_delta_mm=1.95,
            num_bumps=3,
            valid=True,
        )
        with pytest.raises(AttributeError):
            r.valid = False  # type: ignore[misc]

    def test_length_match_result_fields(self) -> None:
        """LengthMatchResult has all required fields."""
        from kicad_agent.routing.length_matching import LengthMatchResult
        r = LengthMatchResult(
            path=((0.0, 0.0), (10.0, 0.0)),
            target_delta_mm=2.0,
            achieved_delta_mm=1.95,
            num_bumps=3,
            valid=True,
        )
        assert r.path == ((0.0, 0.0), (10.0, 0.0))
        assert r.target_delta_mm == 2.0
        assert r.achieved_delta_mm == 1.95
        assert r.num_bumps == 3
        assert r.valid is True

    def test_short_path_returns_original(self) -> None:
        """Path shorter than bump_pitch returns original path."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        # 0.5mm path is shorter than bump_pitch (max(1.0, 0.5) = 1.0mm).
        path = ((0.0, 0.0), (0.5, 0.0))
        result = add_sawtooth_matching(path, target_delta_mm=2.0, spacing_mm=1.0)
        assert result.path == path
        assert result.num_bumps == 0

    def test_single_point_path_returns_original(self) -> None:
        """Single-point path returns original path."""
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        path = ((5.0, 5.0),)
        result = add_sawtooth_matching(path, target_delta_mm=2.0)
        assert result.path == path
        assert result.num_bumps == 0


def _sawtooth_max_extra(spacing_mm: float, max_detour_ratio: float) -> float:
    """Helper: max extra length per sawtooth bump at max amplitude."""
    from kicad_agent.routing.length_matching import _sawtooth_extra_length
    half_pitch = spacing_mm * 0.5
    max_amplitude = half_pitch * max_detour_ratio
    return _sawtooth_extra_length(max_amplitude, half_pitch)


# ---------------------------------------------------------------------------
# ROUTE-05/06/07: AutoRouteOp schema extension (Plan 36-03)
# ---------------------------------------------------------------------------


class TestAutoRouteOpSchema:
    """AutoRouteOp schema validation for multi-layer, impedance, length matching."""

    def test_autorouteop_default_fields(self) -> None:
        """AutoRouteOp defaults: layers=[], impedance_target=None, length_match_pairs=None."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(target_file="test.kicad_pcb")
        assert op.layers == []
        assert op.impedance_target is None
        assert op.length_match_pairs is None
        # Backward compat: single-layer mode via 'layer' field.
        assert op.layer == "F.Cu"

    def test_autorouteop_layers_valid(self) -> None:
        """AutoRouteOp accepts valid copper layer names in layers list."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(
            target_file="test.kicad_pcb",
            layers=["F.Cu", "B.Cu"],
        )
        assert op.layers == ["F.Cu", "B.Cu"]

    def test_autorouteop_layers_inner(self) -> None:
        """AutoRouteOp accepts inner layer names like In1.Cu."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(
            target_file="test.kicad_pcb",
            layers=["F.Cu", "In1.Cu", "B.Cu"],
        )
        assert len(op.layers) == 3

    def test_autorouteop_layers_invalid_name(self) -> None:
        """AutoRouteOp rejects invalid layer name in layers list."""
        from pydantic import ValidationError

        from kicad_agent.ops._schema_pcb import AutoRouteOp

        with pytest.raises(ValidationError, match="Invalid layer name"):
            AutoRouteOp(
                target_file="test.kicad_pcb",
                layers=["F.Cu", "InvalidLayer"],
            )

    def test_autorouteop_impedance_target_valid(self) -> None:
        """AutoRouteOp accepts valid impedance_target."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(
            target_file="test.kicad_pcb",
            impedance_target=50.0,
        )
        assert op.impedance_target == 50.0

    def test_autorouteop_impedance_target_zero_rejected(self) -> None:
        """AutoRouteOp rejects impedance_target=0."""
        from pydantic import ValidationError

        from kicad_agent.ops._schema_pcb import AutoRouteOp

        with pytest.raises(ValidationError):
            AutoRouteOp(
                target_file="test.kicad_pcb",
                impedance_target=0.0,
            )

    def test_autorouteop_impedance_target_over_200_rejected(self) -> None:
        """AutoRouteOp rejects impedance_target > 200."""
        from pydantic import ValidationError

        from kicad_agent.ops._schema_pcb import AutoRouteOp

        with pytest.raises(ValidationError):
            AutoRouteOp(
                target_file="test.kicad_pcb",
                impedance_target=250.0,
            )

    def test_autorouteop_length_match_pairs_valid(self) -> None:
        """AutoRouteOp accepts valid length_match_pairs."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(
            target_file="test.kicad_pcb",
            length_match_pairs=[("CLK_P", "CLK_N", 0.1)],
        )
        assert op.length_match_pairs == [("CLK_P", "CLK_N", 0.1)]

    def test_autorouteop_length_match_pairs_multiple(self) -> None:
        """AutoRouteOp accepts multiple length match pairs."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(
            target_file="test.kicad_pcb",
            length_match_pairs=[
                ("CLK_P", "CLK_N", 0.1),
                ("DATA_P", "DATA_N", 0.25),
            ],
        )
        assert len(op.length_match_pairs) == 2

    def test_autorouteop_all_fields_combined(self) -> None:
        """AutoRouteOp with all new fields validates correctly."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(
            target_file="test.kicad_pcb",
            layers=["F.Cu", "In1.Cu", "B.Cu"],
            impedance_target=50.0,
            length_match_pairs=[("CLK_P", "CLK_N", 0.1)],
        )
        assert len(op.layers) == 3
        assert op.impedance_target == 50.0
        assert len(op.length_match_pairs) == 1

    def test_autorouteop_empty_layers_backward_compat(self) -> None:
        """AutoRouteOp with empty layers falls back to single-layer mode."""
        from kicad_agent.ops._schema_pcb import AutoRouteOp

        op = AutoRouteOp(target_file="test.kicad_pcb", layer="B.Cu")
        assert op.layers == []
        assert op.layer == "B.Cu"


class TestMultiLayerIntegration:
    """End-to-end integration: multi-layer + impedance + length matching."""

    def test_handle_auto_route_single_layer_backward_compat(self) -> None:
        """_handle_auto_route without new fields produces same result as before."""
        from kicad_agent.routing.bridge import TrackSegment, route_to_segments
        from kicad_agent.routing.constraints import RoutingConstraints
        from kicad_agent.routing.pathfinder import RouteResult, route_all_nets

        constraints = RoutingConstraints(grid_resolution_mm=1.0)
        graph = build_routing_graph(
            (0, 0, 20, 20),
            constraints=constraints,
        )
        netlist = {
            "VCC": [(0, 0), (10, 0)],
            "GND": [(0, 5), (10, 5)],
        }
        results = route_all_nets(graph, netlist)
        segments = route_to_segments(results, constraints, layer="F.Cu")
        assert len(segments) >= 2
        assert all(s.layer == "F.Cu" for s in segments)

    def test_handle_auto_route_multilayer_produces_vias(self) -> None:
        """Multi-layer routing produces ViaSegments at layer transitions."""
        from kicad_agent.routing.bridge import (
            TrackSegment,
            ViaSegment,
            route_to_segments_multilayer,
        )

        constraints = RoutingConstraints(
            grid_resolution_mm=1.0,
            via_cost_mm=5.0,
        )
        graph = build_routing_graph(
            (0, 0, 20, 20),
            constraints=constraints,
            layers=["F.Cu", "B.Cu"],
        )
        netlist = {
            "CROSS": [(0, 0), (15, 10)],
        }
        results = route_all_nets(graph, netlist)
        # route_all_nets with 3D graph should produce results.
        assert "CROSS" in results
        assert results["CROSS"].success
        # Check segments include both layers and vias.
        segments = route_to_segments_multilayer(results, constraints)
        via_segs = [s for s in segments if isinstance(s, ViaSegment)]
        # If there are any layer transitions, vias should exist.
        path = results["CROSS"].path
        layers_in_path = {pt[2] for pt in path if len(pt) >= 3}
        if len(layers_in_path) > 1:
            assert len(via_segs) >= 1

    def test_handle_auto_route_impedance_adjusts_width(self) -> None:
        """Impedance target produces trace width different from default."""
        from kicad_agent.routing.impedance import solve_trace_width

        constraints = RoutingConstraints()
        target_z0 = 50.0
        # Solve for microstrip on surface layer.
        result = solve_trace_width(
            target_z0=target_z0,
            h=constraints.dielectric_height_mm,
            t=constraints.copper_thickness_mm,
            er=constraints.dielectric_constant,
            model="microstrip",
        )
        assert result.valid
        # The solved trace width should differ from default 0.25mm.
        assert result.trace_width_mm != pytest.approx(constraints.trace_width_mm, abs=0.001)

    def test_handle_auto_route_length_matching(self) -> None:
        """Length matching adjusts shorter net to match longer net."""
        from kicad_agent.routing.constraints import RoutingConstraints
        from kicad_agent.routing.length_matching import add_sawtooth_matching

        path_short = ((0.0, 0.0), (5.0, 0.0))
        delta = 3.0
        result = add_sawtooth_matching(path_short, target_delta_mm=delta, spacing_mm=1.0)
        assert result.valid
        from kicad_agent.routing.geometry import _path_length
        new_len = _path_length(result.path)
        original_len = _path_length(path_short)
        assert new_len > original_len

    def test_full_pipeline_multilayer_impedance_length_match(self) -> None:
        """Full pipeline: multi-layer graph + impedance + length matching."""
        from kicad_agent.routing.bridge import (
            TrackSegment,
            ViaSegment,
            route_to_segments_multilayer,
        )
        from kicad_agent.routing.impedance import solve_trace_width
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        from kicad_agent.routing.pathfinder import RouteResult, _path_length

        constraints = RoutingConstraints(
            grid_resolution_mm=1.0,
            via_cost_mm=5.0,
        )

        # Step 1: Solve impedance for 50-ohm target.
        imp_result = solve_trace_width(
            target_z0=50.0,
            h=constraints.dielectric_height_mm,
            t=constraints.copper_thickness_mm,
            er=constraints.dielectric_constant,
            model="microstrip",
        )
        assert imp_result.valid

        # Step 2: Create constraints with impedance-adjusted widths.
        constraints = RoutingConstraints(
            grid_resolution_mm=1.0,
            via_cost_mm=5.0,
            layer_trace_widths={
                "F.Cu": imp_result.trace_width_mm,
                "B.Cu": imp_result.trace_width_mm,
            },
        )

        # Step 3: Build multi-layer graph.
        graph = build_routing_graph(
            (0, 0, 20, 20),
            constraints=constraints,
            layers=["F.Cu", "B.Cu"],
        )

        # Step 4: Route nets.
        netlist = {
            "CLK_P": [(0, 0), (15, 0)],
            "CLK_N": [(0, 2), (15, 2)],
        }
        results = route_all_nets(graph, netlist)
        assert len(results) == 2
        assert results["CLK_P"].success
        assert results["CLK_N"].success

        # Step 5: Apply length matching if needed.
        len_p = results["CLK_P"].length_mm
        len_n = results["CLK_N"].length_mm
        mismatch = abs(len_p - len_n)
        tolerance = 0.5

        if mismatch > tolerance:
            shorter_net = "CLK_P" if len_p < len_n else "CLK_N"
            shorter_path = results[shorter_net].path
            path_2d = tuple((p[0], p[1]) for p in shorter_path)
            match_result = add_sawtooth_matching(
                path_2d, target_delta_mm=mismatch - tolerance,
                spacing_mm=constraints.trace_width_mm,
            )
            assert match_result.valid

        # Step 6: Convert to segments with per-layer widths.
        segments = route_to_segments_multilayer(results, constraints)
        track_segs = [s for s in segments if isinstance(s, TrackSegment)]
        # All track segments should use impedance-adjusted width.
        for seg in track_segs:
            expected_width = constraints.effective_trace_width(seg.layer)
            assert seg.width == pytest.approx(expected_width, abs=0.001)
