"""Tests for routing sub-modules: diff_pair, impedance, length_matching, geometry, graph."""

from pathlib import Path

import pytest


class TestDiffPair:
    """Tests for differential pair routing."""

    def test_import(self):
        """DiffPairResult is importable."""
        from volta.routing.diff_pair import DiffPairResult, route_differential_pair
        assert DiffPairResult is not None
        assert callable(route_differential_pair)


class TestImpedance:
    """Tests for impedance calculation."""

    def test_import(self):
        """ImpedanceResult and solve_trace_width are importable."""
        from volta.routing.impedance import ImpedanceResult, solve_trace_width
        assert ImpedanceResult is not None
        assert callable(solve_trace_width)


class TestLengthMatching:
    """Tests for length matching."""

    def test_import(self):
        """LengthMatchResult and add_sawtooth_matching are importable."""
        from volta.routing.length_matching import (
            LengthMatchResult,
            add_sawtooth_matching,
        )
        assert LengthMatchResult is not None
        assert callable(add_sawtooth_matching)


class TestRoutingGeometry:
    """Tests for routing geometry utilities."""

    def test_import(self):
        """Geometry module is importable."""
        from volta.routing import geometry
        assert geometry is not None


class TestRoutingGraph:
    """Tests for routing graph module."""

    def test_import(self):
        """RoutingGraph is importable."""
        from volta.routing.graph import RoutingGraph
        assert RoutingGraph is not None

    def test_build_routing_graph_callable(self):
        """build_routing_graph is callable."""
        from volta.routing.pathfinder import build_routing_graph
        assert callable(build_routing_graph)


class TestRoutingBridge:
    """Tests for bridge module with TrackSegment and ViaSegment."""

    def test_import(self):
        """Bridge module is importable."""
        from volta.routing import bridge
        assert hasattr(bridge, "TrackSegment")
        assert hasattr(bridge, "ViaSegment")


class TestFreerouting:
    """Tests for freerouting integration module."""

    def test_import(self):
        """Freerouting module is importable."""
        from volta.routing import freerouting
        assert freerouting is not None


class TestInteractiveRouting:
    """Tests for interactive routing session."""

    def test_import(self):
        """Interactive routing types are importable."""
        from volta.routing.interactive import (
            InteractiveRoutingSession,
            RoutingSuggestion,
            SuggestionStatus,
        )
        assert SuggestionStatus is not None
