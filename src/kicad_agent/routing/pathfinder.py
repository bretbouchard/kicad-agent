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


def _path_length(path: list[tuple[float, ...]] | tuple[tuple[float, ...], ...]) -> float:
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
        # Collect available layers from graph nodes.
        _graph_layers = sorted({n[2] for n in graph.graph.nodes if len(n) == 3})
        default_layer = _graph_layers[0] if _graph_layers else None
        src_layer = source[2] if len(source) == 3 else default_layer
        tgt_layer = target[2] if len(target) == 3 else default_layer
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

    For 2-pin nets, routes first pin to last pin (existing behavior).
    For multi-pin nets (3+ pins), uses sequential nearest-neighbor heuristic
    to build a Steiner-tree approximation connecting all pins (H-7).

    Nets are sorted by estimated Euclidean distance (shortest first)
    to maximize routability.

    Args:
        graph: Routing graph with DRC-aware edge weights.
        netlist: Dict mapping net names to lists of (x, y) pin positions.

    Returns:
        Dict mapping net names to RouteResult objects. Only includes nets
        that were successfully routed (or attempted but failed).
    """
    # Filter to nets with >= 2 pins and compute estimated distance.
    routable: list[tuple[str, float, list[tuple[float, float]]]] = []
    for net_name, pins in netlist.items():
        if len(pins) < 2:
            continue
        if len(pins) == 2:
            est_distance = _euclidean_heuristic(pins[0], pins[-1])
        else:
            # Multi-pin: estimate total Steiner tree length
            est_distance = sum(
                _euclidean_heuristic(pins[i], pins[i + 1])
                for i in range(len(pins) - 1)
            )
        routable.append((net_name, est_distance, pins))

    # Sort by estimated distance (shortest first).
    routable.sort(key=lambda x: x[1])

    results: dict[str, RouteResult] = {}
    for net_name, _, pins in routable:
        if len(pins) == 2:
            # Two-pin net: existing fast path
            result = route_net(graph, pins[0], pins[-1], net_name)
            if result is not None:
                results[net_name] = result
                graph.mark_path_as_obstacle(result.path)
        else:
            # Multi-pin net: sequential nearest-neighbor Steiner tree (H-7)
            multi_result = _route_multi_pin_net(graph, net_name, pins)
            if multi_result is not None:
                results[net_name] = multi_result

    return results


def _nearest_routed_position(
    pin: tuple[float, float],
    routed_positions: set[tuple[float, float]],
) -> tuple[float, float]:
    """Find the nearest already-routed position to a target pin.

    Uses brute-force Euclidean distance for small sets (typical pin counts)
    avoiding Shapely overhead. Falls back to first routed position for
    degenerate single-element sets.
    """
    nearest = min(routed_positions, key=lambda r: _euclidean_heuristic(r, pin))
    return nearest


def _route_multi_pin_net(
    graph: RoutingGraph,
    net_name: str,
    pins: list[tuple[float, float]],
) -> RouteResult | None:
    """Route a multi-pin net using nearest-neighbor heuristic (H-7).

    For each unrouted pin, finds the single nearest already-routed position
    using Euclidean distance (O(k) per pin) and attempts one A* route.
    This reduces from O(k^2) A* calls to O(k) A* calls, preventing OOM
    on boards with many pins per net (BUG-004).
    """
    routed_positions = {pins[0]}
    unrouted = set(pins[1:])
    all_paths: list[tuple] = []

    while unrouted:
        # Find the unrouted pin closest to any routed position
        best_pin = min(
            unrouted,
            key=lambda p: min(
                _euclidean_heuristic(p, r) for r in routed_positions
            ),
        )
        # Route from only the nearest routed position (1 A* call, not k)
        nearest = _nearest_routed_position(best_pin, routed_positions)
        result = route_net(graph, nearest, best_pin, net_name)

        if result is None or not result.success:
            # Fallback: try all routed positions (rare, for blocked paths)
            found = False
            for alt_routed in sorted(
                routed_positions,
                key=lambda r: _euclidean_heuristic(r, best_pin),
            ):
                if alt_routed == nearest:
                    continue
                result = route_net(graph, alt_routed, best_pin, net_name)
                if result is not None and result.success:
                    found = True
                    break
            if not found:
                break  # Cannot reach this pin

        all_paths.append(result.path)
        routed_positions.add(best_pin)
        unrouted.discard(best_pin)
        graph.mark_path_as_obstacle(result.path)

    if not all_paths:
        return None

    # Merge sub-paths into a single path for the result
    merged = list(all_paths[0])
    for extra_path in all_paths[1:]:
        merged.extend(extra_path[1:])  # Skip first node (already in merged)

    total_length = sum(_path_length(p) for p in all_paths)
    return RouteResult(
        net_name=net_name,
        success=len(routed_positions) == len(pins),  # False if partial
        path=tuple(merged),
        length_mm=round(total_length, 4),
    )


def build_routing_graph(
    board_bounds: tuple[float, float, float, float],
    obstacles: list | None = None,
    constraints: RoutingConstraints | None = None,
    layers: list[str] | None = None,
    required_nodes: set[tuple[float, float]] | None = None,
    forbidden_zones: list[dict] | None = None,
) -> RoutingGraph:
    """Convenience function to build a routing graph.

    Args:
        board_bounds: (x_min, y_min, x_max, y_max) board outline in mm.
        obstacles: List of SpatialBox obstacles. Defaults to empty.
        constraints: Routing constraints. Uses defaults if not provided.
        layers: List of copper layer names for multi-layer routing.
            Defaults to ["F.Cu"] for single-layer.
        required_nodes: Set of (x, y) pad positions that must be routable.
        forbidden_zones: Phase 99 Gap 2 — per-layer impassable zones.
            Each dict: {layer, x1, y1, x2, y2}.

    Returns:
        Constructed RoutingGraph.
    """
    from kicad_agent.routing.constraints import RoutingConstraints as RC

    return RoutingGraph(
        board_bounds=board_bounds,
        obstacles=obstacles or [],
        constraints=constraints or RC(),
        layers=layers,
        required_nodes=required_nodes,
        forbidden_zones=forbidden_zones,
    )
