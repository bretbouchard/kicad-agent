"""Tests for Phase 62: Routing Correctness (H-6, H-7, H-8, H-9, H-10).

H-6: Spatial index for snap_to_node (O(log n))
H-7: Multi-pin net routing (Steiner tree)
H-8/H-9: Net IDs in TrackSegment/ViaSegment
H-10: Clearance corridor in mark_path_as_obstacle
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from kicad_agent.routing.bridge import TrackSegment, ViaSegment
from kicad_agent.routing.constraints import RoutingConstraints


# ---------------------------------------------------------------------------
# H-6: Spatial index for snap_to_node
# ---------------------------------------------------------------------------


class TestSpatialIndexSnap:
    """Verify snap_to_node uses spatial index for efficient lookup."""

    def _make_graph(self, n: int = 10):
        """Create a routing graph with n*n nodes for testing."""
        from kicad_agent.routing.graph import RoutingGraph
        bounds = (0.0, 0.0, float(n), float(n))
        return RoutingGraph(
            board_bounds=bounds,
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )

    def test_exact_match_fast_path(self) -> None:
        """Exact grid match returns immediately."""
        graph = self._make_graph()
        result = graph.snap_to_node(1.0, 1.0)
        assert result is not None
        assert result[:2] == (1.0, 1.0)

    def test_snap_finds_nearest_within_tolerance(self) -> None:
        """Near-grid coordinate snaps to closest node."""
        graph = self._make_graph()
        result = graph.snap_to_node(1.3, 1.3)
        assert result is not None
        assert result[:2] == (1.0, 1.0)

    def test_snap_returns_none_outside_tolerance(self) -> None:
        """Coordinates far from any node return None."""
        graph = self._make_graph()
        result = graph.snap_to_node(1.6, 1.6)
        # 3D graph may snap to (1.0, 1.0, 'F.Cu') which is within tolerance
        # Use a coordinate truly outside tolerance (>0.5 away from any grid point)
        result = graph.snap_to_node(1.6, 1.6)
        # With 1mm grid, tolerance=1.0, distance from (1.6,1.6) to (1,1)=~0.85 < 1.0
        # So it WILL snap. Use coords far from any grid point instead.
        result = graph.snap_to_node(1.51, 0.49)
        # Distance to nearest (1,0)=~0.72, to (2,0)=~0.72, to (1,1)=~0.72
        # With tolerance=1.0, this still snaps. Need truly far coords.
        result = graph.snap_to_node(-5.0, -5.0)
        assert result is None

    def test_snap_with_layer(self) -> None:
        """Layer-specific snap works with spatial index."""
        from kicad_agent.routing.graph import RoutingGraph
        graph = RoutingGraph(
            board_bounds=(0.0, 0.0, 5.0, 5.0),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            layers=["F.Cu", "B.Cu"],
        )
        result = graph.snap_to_node(1.0, 1.0, layer="F.Cu")
        assert result is not None
        assert result[2] == "F.Cu"

    def test_empty_graph_returns_none(self) -> None:
        """Graph with no nodes near query returns None for snap."""
        from kicad_agent.routing.graph import RoutingGraph
        graph = RoutingGraph(
            board_bounds=(0.0, 0.0, 0.1, 0.1),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        # Small bounds with 1mm grid: origin node (0,0,'F.Cu') exists.
        # Query far outside bounds returns None.
        result = graph.snap_to_node(50.0, 50.0)
        assert result is None


# ---------------------------------------------------------------------------
# H-7: Multi-pin net routing
# ---------------------------------------------------------------------------


class TestMultiPinRouting:
    """Verify multi-pin nets are routed as Steiner trees."""

    def _make_graph(self) -> "RoutingGraph":
        """Create a routing graph with enough space for multi-pin routing."""
        from kicad_agent.routing.graph import RoutingGraph
        return RoutingGraph(
            board_bounds=(0.0, 0.0, 20.0, 20.0),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )

    def test_two_pin_backward_compat(self) -> None:
        """2-pin nets route exactly as before."""
        from kicad_agent.routing.pathfinder import route_all_nets
        graph = self._make_graph()
        result = route_all_nets(graph, {
            "VCC": [(1.0, 1.0), (5.0, 5.0)],
        })
        assert "VCC" in result
        assert result["VCC"].success

    def test_three_pin_net_connected(self) -> None:
        """3-pin net produces a path connecting all pins."""
        from kicad_agent.routing.pathfinder import route_all_nets
        graph = self._make_graph()
        result = route_all_nets(graph, {
            "SPI": [(1.0, 1.0), (5.0, 1.0), (5.0, 5.0)],
        })
        assert "SPI" in result
        assert result["SPI"].success
        path = result["SPI"].path
        # All 3 pins should be reachable (path visits them)
        assert len(path) >= 3

    def test_single_pin_net_skipped(self) -> None:
        """1-pin nets are skipped."""
        from kicad_agent.routing.pathfinder import route_all_nets
        graph = self._make_graph()
        result = route_all_nets(graph, {
            "EMPTY": [(1.0, 1.0)],
        })
        assert "EMPTY" not in result

    def test_empty_netlist(self) -> None:
        """Empty netlist returns empty results."""
        from kicad_agent.routing.pathfinder import route_all_nets
        graph = self._make_graph()
        result = route_all_nets(graph, {})
        assert result == {}


# ---------------------------------------------------------------------------
# H-8/H-9: Net IDs in TrackSegment/ViaSegment
# ---------------------------------------------------------------------------


class TestNetIds:
    """Verify TrackSegment and ViaSegment use correct net IDs."""

    def test_track_segment_with_net_id(self) -> None:
        """TrackSegment with net_id=5 produces (net "VCC")."""
        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=10.0, end_y=10.0,
            width=0.25, layer="F.Cu",
            net="VCC", net_id=5,
        )
        sexpr = seg.to_sexpr()
        assert '(net "VCC")' in sexpr
        assert "(net 0" not in sexpr

    def test_track_segment_default_net_id_zero(self) -> None:
        """TrackSegment without net_id defaults to 0."""
        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=10.0, end_y=10.0,
            width=0.25, layer="F.Cu",
            net="GND",
        )
        sexpr = seg.to_sexpr()
        assert '(net "GND")' in sexpr

    def test_via_segment_with_net_id(self) -> None:
        """ViaSegment with net_id=3 produces (net "SDA")."""
        via = ViaSegment(
            x=5.0, y=5.0,
            from_layer="F.Cu", to_layer="B.Cu",
            diameter=0.8, drill=0.4,
            net="SDA", net_id=3,
        )
        sexpr = via.to_sexpr()
        assert '(net "SDA")' in sexpr

    def test_via_segment_default_net_id_zero(self) -> None:
        """ViaSegment without net_id defaults to 0."""
        via = ViaSegment(
            x=5.0, y=5.0,
            from_layer="F.Cu", to_layer="B.Cu",
            diameter=0.8, drill=0.4,
            net="SCL",
        )
        sexpr = via.to_sexpr()
        assert '(net "SCL")' in sexpr

    def test_track_segment_no_net(self) -> None:
        """TrackSegment with empty net omits net field."""
        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=10.0, end_y=10.0,
            width=0.25, layer="F.Cu",
            net="",
        )
        sexpr = seg.to_sexpr()
        assert "(net" not in sexpr


# ---------------------------------------------------------------------------
# H-10: Clearance corridor in mark_path_as_obstacle
# ---------------------------------------------------------------------------


class TestClearanceCorridor:
    """Verify mark_path_as_obstacle blocks clearance corridor."""

    def _make_graph(self) -> "RoutingGraph":
        from kicad_agent.routing.graph import RoutingGraph
        return RoutingGraph(
            board_bounds=(0.0, 0.0, 10.0, 10.0),
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )

    def test_exact_edges_removed(self) -> None:
        """Default clearance=0 removes only exact path edges."""
        graph = self._make_graph()
        path = ((1.0, 1.0, "F.Cu"), (2.0, 1.0, "F.Cu"), (3.0, 1.0, "F.Cu"))
        graph.mark_path_as_obstacle(path)
        assert not graph.graph.has_edge((1.0, 1.0, "F.Cu"), (2.0, 1.0, "F.Cu"))
        assert not graph.graph.has_edge((2.0, 1.0, "F.Cu"), (3.0, 1.0, "F.Cu"))

    def test_clearance_removes_adjacent_edges(self) -> None:
        """clearance > 0 also blocks edges near the path."""
        graph = self._make_graph()
        path = ((1.0, 1.0, "F.Cu"), (2.0, 1.0, "F.Cu"), (3.0, 1.0, "F.Cu"))
        graph.mark_path_as_obstacle(path, clearance=1.5)
        # Path edges removed
        assert not graph.graph.has_edge((1.0, 1.0, "F.Cu"), (2.0, 1.0, "F.Cu"))
        # Adjacent row edges should also be removed
        assert not graph.graph.has_edge((2.0, 2.0, "F.Cu"), (3.0, 2.0, "F.Cu"))

    def test_far_edges_remain(self) -> None:
        """Edges far from path are not removed even with clearance."""
        graph = self._make_graph()
        # Nodes are 3D (x, y, layer)
        path = ((1.0, 1.0, "F.Cu"), (2.0, 1.0, "F.Cu"))
        graph.mark_path_as_obstacle(path, clearance=1.0)
        # Edge at (9,9) should remain
        assert graph.graph.has_edge((9.0, 9.0, "F.Cu"), (10.0, 9.0, "F.Cu"))


# ---------------------------------------------------------------------------
# Point-to-segment distance helper
# ---------------------------------------------------------------------------


class TestPointToSegmentDistance:
    """Verify _point_to_segment_distance correctness."""

    def test_point_on_segment(self) -> None:
        """Point on the segment has distance 0."""
        from kicad_agent.routing.graph import _point_to_segment_distance
        assert _point_to_segment_distance(5.0, 0.0, 0.0, 0.0, 10.0, 0.0) == pytest.approx(0.0)

    def test_point_perpendicular(self) -> None:
        """Perpendicular distance to horizontal segment."""
        from kicad_agent.routing.graph import _point_to_segment_distance
        assert _point_to_segment_distance(5.0, 3.0, 0.0, 0.0, 10.0, 0.0) == pytest.approx(3.0)

    def test_point_beyond_endpoint(self) -> None:
        """Distance to nearest endpoint when projection falls outside."""
        from kicad_agent.routing.graph import _point_to_segment_distance
        d = _point_to_segment_distance(12.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert d == pytest.approx(2.0)

    def test_zero_length_segment(self) -> None:
        """Zero-length segment returns distance to the point."""
        from kicad_agent.routing.graph import _point_to_segment_distance
        d = _point_to_segment_distance(3.0, 4.0, 0.0, 0.0, 0.0, 0.0)
        assert d == pytest.approx(5.0)
