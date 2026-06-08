"""Tests for routing module: RoutingConstraints, graph, impedance, length matching."""

import pytest

from kicad_agent.routing import (
    DiffPairResult,
    ImpedanceResult,
    InteractiveRoutingSession,
    LengthMatchResult,
    RouteResult,
    RoutingConstraints,
    RoutingGraph,
    RoutingSuggestion,
    SuggestionStatus,
    TrackSegment,
    ViaSegment,
    add_sawtooth_matching,
    build_routing_graph,
    route_all_nets,
    route_differential_pair,
    route_net,
    solve_trace_width,
)


class TestRoutingConstraints:
    """Tests for RoutingConstraints frozen dataclass."""

    def test_default_values(self):
        """RoutingConstraints with defaults has expected values."""
        rc = RoutingConstraints()
        assert rc.clearance_mm == 0.2
        assert rc.grid_resolution_mm == 0.5
        assert rc.trace_width_mm == 0.25
        assert rc.via_diameter_mm == 0.8
        assert rc.via_drill_mm == 0.4
        assert rc.max_nodes == 500_000
        assert rc.via_cost_mm == 5.0

    def test_custom_values(self):
        """RoutingConstraints accepts custom values."""
        rc = RoutingConstraints(
            clearance_mm=0.3,
            trace_width_mm=0.15,
            via_diameter_mm=0.6,
        )
        assert rc.clearance_mm == 0.3
        assert rc.trace_width_mm == 0.15

    def test_zero_clearance_rejected(self):
        """RoutingConstraints rejects zero clearance."""
        with pytest.raises(ValueError, match="clearance_mm"):
            RoutingConstraints(clearance_mm=0)

    def test_negative_trace_width_rejected(self):
        """RoutingConstraints rejects negative trace width."""
        with pytest.raises(ValueError, match="trace_width_mm"):
            RoutingConstraints(trace_width_mm=-0.1)

    def test_zero_via_diameter_rejected(self):
        """RoutingConstraints rejects zero via diameter."""
        with pytest.raises(ValueError, match="via_diameter_mm"):
            RoutingConstraints(via_diameter_mm=0)

    def test_zero_via_drill_rejected(self):
        """RoutingConstraints rejects zero via drill."""
        with pytest.raises(ValueError, match="via_drill_mm"):
            RoutingConstraints(via_drill_mm=0)

    def test_too_small_grid_rejected(self):
        """RoutingConstraints rejects grid < 0.1mm."""
        with pytest.raises(ValueError, match="grid_resolution_mm"):
            RoutingConstraints(grid_resolution_mm=0.05)

    def test_too_many_nodes_rejected(self):
        """RoutingConstraints rejects max_nodes > 2M."""
        with pytest.raises(ValueError, match="max_nodes"):
            RoutingConstraints(max_nodes=3_000_000)

    def test_zero_via_cost_rejected(self):
        """RoutingConstraints rejects zero via cost."""
        with pytest.raises(ValueError, match="via_cost_mm"):
            RoutingConstraints(via_cost_mm=0)

    def test_frozen(self):
        """RoutingConstraints is frozen (immutable)."""
        rc = RoutingConstraints()
        with pytest.raises(AttributeError):
            rc.clearance_mm = 0.5

    def test_effective_trace_width_default(self):
        """effective_trace_width returns trace_width_mm when no layer overrides."""
        rc = RoutingConstraints(trace_width_mm=0.25)
        assert rc.effective_trace_width("F.Cu") == 0.25

    def test_effective_trace_width_with_overrides(self):
        """effective_trace_width returns layer-specific width when set."""
        rc = RoutingConstraints(
            trace_width_mm=0.25,
            layer_trace_widths={"F.Cu": 0.15, "B.Cu": 0.20},
        )
        assert rc.effective_trace_width("F.Cu") == 0.15
        assert rc.effective_trace_width("B.Cu") == 0.20
        assert rc.effective_trace_width("In1.Cu") == 0.25  # fallback


class TestTrackSegment:
    """Tests for TrackSegment dataclass."""

    def test_creation(self):
        """TrackSegment can be created."""
        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=10.0, end_y=5.0,
            width=0.25,
            layer="F.Cu",
            net="NET1",
        )
        assert seg.layer == "F.Cu"
        assert seg.start_x == 0.0

    def test_to_sexpr(self):
        """TrackSegment serializes to S-expression."""
        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=10.0, end_y=5.0,
            width=0.25,
            layer="F.Cu",
            net="NET1",
        )
        sexpr = seg.to_sexpr()
        assert "segment" in sexpr
        assert "NET1" in sexpr


class TestViaSegment:
    """Tests for ViaSegment dataclass."""

    def test_creation(self):
        """ViaSegment can be created."""
        via = ViaSegment(
            x=5.0, y=3.0,
            from_layer="F.Cu", to_layer="B.Cu",
            diameter=0.8,
            drill=0.4,
            net="NET1",
        )
        assert via.diameter == 0.8
        assert via.from_layer == "F.Cu"

    def test_to_sexpr(self):
        """ViaSegment serializes to S-expression."""
        via = ViaSegment(
            x=5.0, y=3.0,
            from_layer="F.Cu", to_layer="B.Cu",
            diameter=0.8,
            drill=0.4,
            net="NET1",
        )
        sexpr = via.to_sexpr()
        assert "via" in sexpr
        assert "NET1" in sexpr


class TestRouteResult:
    """Tests for RouteResult dataclass."""

    def test_creation(self):
        """RouteResult can be created."""
        result = RouteResult(
            net_name="NET1",
            path=((0, 0), (1, 0), (1, 1)),
            length_mm=3.0,
            success=True,
        )
        assert result.success is True
        assert result.net_name == "NET1"


class TestRoutingImports:
    """Verify all routing module exports."""

    def test_all_exports_importable(self):
        """All __all__ exports can be imported."""
        from kicad_agent import routing
        for name in routing.__all__:
            assert hasattr(routing, name), f"Missing export: {name}"


class TestSuggestionStatus:
    """Tests for SuggestionStatus enum."""

    def test_known_values(self):
        """SuggestionStatus has expected values."""
        values = [v for v in SuggestionStatus]
        assert len(values) >= 3
