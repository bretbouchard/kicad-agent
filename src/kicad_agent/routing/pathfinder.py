"""A* pathfinding engine for PCB trace routing.

Provides route_net (single net) and route_all_nets (batch) functions
using networkx.astar_path with a Euclidean distance heuristic.

Results are immutable RouteResult frozen dataclasses.

Usage:
    from kicad_agent.routing.pathfinder import route_net, route_all_nets

    result = route_net(graph, (0, 0), (10, 10), "VCC")
    results = route_all_nets(graph, {"VCC": [(0,0), (10,10)], "GND": [(5,5), (15,15)]})
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kicad_agent.routing.graph import RoutingGraph


@dataclass(frozen=True)
class RouteResult:
    """Immutable result of routing a single net.

    Attributes:
        net_name: Name of the routed net.
        path: Ordered tuple of (x, y) or (x, y, layer) waypoints.
        length_mm: Total path length in mm.
        success: True if a valid path was found.
    """

    net_name: str
    path: tuple[tuple[float, float], ...] | tuple[tuple[float, float, str], ...]
    length_mm: float
    success: bool


def _euclidean_heuristic(u: tuple[float, ...], v: tuple[float, ...]) -> float:
    """Euclidean distance heuristic for A* search.

    Works with both 2D (x, y) and 3D (x, y, layer) tuples by only
    using the first two elements.
    """
    return math.hypot(u[0] - v[0], u[1] - v[1])


def _path_length(path: list[tuple[float, ...]]) -> float:
    """Compute total Euclidean length of a path.

    Works with both 2D and 3D tuples by only using x, y coordinates.
    """
    total = 0.0
    for i in range(len(path) - 1):
        total += math.hypot(
            path[i + 1][0] - path[i][0],
            path[i + 1][1] - path[i][1],
        )
    return total


def route_net(
    graph: RoutingGraph,
    source: tuple[float, float] | tuple[float, float, str],
    target: tuple[float, float] | tuple[float, float, str],
    net_name: str,
) -> RouteResult | None:
    """Route a single net from source to target using A* pathfinding.

    Args:
        graph: Routing graph with DRC-aware edge weights.
        source: (x, y) or (x, y, layer) start coordinate in mm.
        target: (x, y) or (x, y, layer) end coordinate in mm.
        net_name: Name of the net being routed.

    Returns:
        RouteResult with the path, or None if no path exists (blocked
        source or target, or no route found).
    """
    import networkx as nx

    # Detect whether graph has 3D nodes.
    is_3d = any(len(n) == 3 for n in graph.graph.nodes)

    if is_3d:
        src_layer = source[2] if len(source) == 3 else None
        tgt_layer = target[2] if len(target) == 3 else None
        src_node = graph.snap_to_node(source[0], source[1], src_layer)
        tgt_node = graph.snap_to_node(target[0], target[1], tgt_layer)
    else:
        src_node = graph.snap_to_node(source[0], source[1])
        tgt_node = graph.snap_to_node(target[0], target[1])

    if src_node is None or tgt_node is None:
        return None

    try:
        path = nx.astar_path(
            graph.graph,
            src_node,
            tgt_node,
            heuristic=_euclidean_heuristic,
            weight="weight",
        )
    except nx.NetworkXNoPath:
        return None

    length = _path_length(path)
    return RouteResult(
        net_name=net_name,
        path=tuple(path),
        length_mm=round(length, 4),
        success=True,
    )


def route_all_nets(
    graph: RoutingGraph,
    netlist: dict[str, list[tuple[float, float]]],
) -> dict[str, RouteResult]:
    """Route all nets in the netlist, shortest first.

    For each net with >= 2 pins, routes from the first pin to the last
    pin. Nets are sorted by estimated Euclidean distance (shortest first)
    to maximize routability.

    Args:
        graph: Routing graph with DRC-aware edge weights.
        netlist: Dict mapping net names to lists of (x, y) pin positions.

    Returns:
        Dict mapping net names to RouteResult objects. Only includes nets
        that were successfully routed (or attempted but failed).
    """
    # Filter to nets with >= 2 pins and compute estimated distance.
    routable: list[tuple[str, float, tuple[float, float], tuple[float, float]]] = []
    for net_name, pins in netlist.items():
        if len(pins) < 2:
            continue
        first_pin = pins[0]
        last_pin = pins[-1]
        est_distance = _euclidean_heuristic(first_pin, last_pin)
        routable.append((net_name, est_distance, first_pin, last_pin))

    # Sort by estimated distance (shortest first).
    routable.sort(key=lambda x: x[1])

    results: dict[str, RouteResult] = {}
    for net_name, _, first_pin, last_pin in routable:
        result = route_net(graph, first_pin, last_pin, net_name)
        if result is not None:
            results[net_name] = result
            # Mark routed path as obstacle for subsequent nets.
            graph.mark_path_as_obstacle(result.path)

    return results


def build_routing_graph(
    board_bounds: tuple[float, float, float, float],
    obstacles: list | None = None,
    constraints: RoutingConstraints | None = None,
    layers: list[str] | None = None,
) -> RoutingGraph:
    """Convenience function to build a routing graph.

    Args:
        board_bounds: (x_min, y_min, x_max, y_max) board outline in mm.
        obstacles: List of SpatialBox obstacles. Defaults to empty.
        constraints: Routing constraints. Uses defaults if not provided.
        layers: List of copper layer names for multi-layer routing.
            Defaults to ["F.Cu"] for single-layer.

    Returns:
        Constructed RoutingGraph.
    """
    from kicad_agent.routing.constraints import RoutingConstraints as RC

    return RoutingGraph(
        board_bounds=board_bounds,
        obstacles=obstacles or [],
        constraints=constraints or RC(),
        layers=layers,
    )
