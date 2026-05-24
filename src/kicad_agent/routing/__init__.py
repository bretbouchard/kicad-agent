"""Routing graph model and A* pathfinding with DRC constraints.

Provides:
    - RoutingConstraints: Frozen dataclass of design-rule parameters.
    - RoutingGraph: Grid-based routing graph with DRC-aware edge costs.
    - RouteResult: Frozen dataclass for a routed net path.
    - build_routing_graph: Convenience function for graph construction.
    - route_net: A* pathfinding for a single net.
    - route_all_nets: Batch routing for multiple nets (shortest first).
"""

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.pathfinder import (
    RouteResult,
    build_routing_graph,
    route_all_nets,
    route_net,
)

__all__ = [
    "RoutingConstraints",
    "RoutingGraph",
    "RouteResult",
    "build_routing_graph",
    "route_net",
    "route_all_nets",
]
