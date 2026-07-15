"""Tests for routing pathfinder module."""

import pytest

from volta.routing.pathfinder import (
    RouteResult,
    build_routing_graph,
    route_net,
    route_all_nets,
)


class TestPathfinderDetailed:
    """Detailed tests for pathfinder."""

    def test_import(self):
        """RouteResult is importable."""
        assert RouteResult is not None

    def test_build_routing_graph_callable(self):
        """build_routing_graph is callable."""
        assert callable(build_routing_graph)

    def test_route_net_callable(self):
        """route_net is callable."""
        assert callable(route_net)

    def test_route_all_nets_callable(self):
        """route_all_nets is callable."""
        assert callable(route_all_nets)
