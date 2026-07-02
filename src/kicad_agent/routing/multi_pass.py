"""Multi-pass routing strategy with 3 passes (#42).

Council C-03 compliance: Maximum 3 passes. Differential pair and power
zone routing are deferred to separate phases.

Pass strategy:
  1. Pass 1: A* shortest path on original graph — routes clear paths,
     marks routed paths as obstacles for subsequent nets in this pass.
  2. Pass 2: A* on fresh graph (no progressive obstacle blocking) — routes
     failed nets without interference from other nets' paths.
  3. Pass 3: A* on fresh graph with relaxed grid resolution — coarser grid
     provides more routing freedom for dense areas.

Usage:
    from kicad_agent.routing.multi_pass import MultiPassRouter

    router = MultiPassRouter(graph, netlist)
    results = router.route_all()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.pathfinder import (
    RouteFailure,
    RouteResult,
    build_routing_graph,
    route_all_nets,
)

logger = logging.getLogger(__name__)


@dataclass
class NetPassHistory:
    """Tracks per-net routing attempts across passes."""

    net_name: str
    attempts: list[dict[str, Any]] = field(default_factory=list)
    best_result: RouteResult | None = None
    routed: bool = False

    def record_attempt(
        self, pass_num: int, result: RouteResult | RouteFailure | None, strategy: str
    ) -> None:
        """Record a routing attempt for this net.

        Phase 103: result can now be RouteFailure (falsy) instead of None.
        Both falsy outcomes are treated as unsuccessful attempts.
        """
        is_success = result is not None and result
        self.attempts.append({
            "pass": pass_num,
            "strategy": strategy,
            "success": is_success,
            "length_mm": result.length_mm if result else None,
        })
        if is_success:
            if self.best_result is None or result.length_mm < self.best_result.length_mm:
                self.best_result = result
            self.routed = True


class MultiPassRouter:
    """Multi-pass router with fallback strategies.

    Implements 3-pass routing strategy (Council C-03):
    - Pass 1: Standard A* shortest path, progressive obstacle blocking
    - Pass 2: Fresh graph, no progressive obstacle blocking
    - Pass 3: Fresh graph with relaxed grid resolution (finer granularity)
    """

    def __init__(
        self,
        graph: RoutingGraph,
        netlist: dict[str, list[tuple[float, float]]],
    ) -> None:
        """Initialize the multi-pass router.

        Args:
            graph: Routing graph with board bounds and constraints.
            netlist: Dict mapping net names to lists of (x, y) pin positions.
        """
        self._graph = graph
        self._netlist = netlist
        self._history: dict[str, NetPassHistory] = {
            name: NetPassHistory(net_name=name) for name in netlist
        }

    def route_all(self) -> dict[str, RouteResult]:
        """Execute all 3 routing passes.

        Each pass only attempts nets that were not routed in previous passes.
        Failed nets are retried with progressively different strategies.

        Returns:
            Dict mapping net names to the best RouteResult for each net.
        """
        # Pass 1: Standard A* with progressive obstacle blocking
        pass1_results = route_all_nets(self._graph, self._netlist)
        self._record_results(1, "astar_obstacle_blocking", pass1_results)

        failed_nets = self._get_failed_netlist()
        if not failed_nets:
            return self._best_results()

        # Pass 2: Fresh graph, no progressive obstacle blocking
        # Rebuild graph from original constraints — routes without marking
        # other nets' paths as obstacles.
        pass2_graph = self._rebuild_graph()
        if pass2_graph is not None:
            pass2_results = self._route_without_obstacles(pass2_graph, failed_nets)
            self._record_results(2, "astar_no_obstacles", pass2_results)
        else:
            logger.warning("Pass 2: Could not rebuild graph, skipping")

        failed_nets = self._get_failed_netlist()
        if not failed_nets:
            return self._best_results()

        # Pass 3: Relaxed grid resolution for more routing freedom
        pass3_graph = self._rebuild_graph_relaxed()
        if pass3_graph is not None:
            pass3_results = self._route_without_obstacles(pass3_graph, failed_nets)
            self._record_results(3, "astar_relaxed_grid", pass3_results)
        else:
            logger.warning("Pass 3: Could not build relaxed graph, skipping")

        return self._best_results()

    def _route_without_obstacles(
        self,
        graph: RoutingGraph,
        netlist: dict[str, list[tuple[float, float]]],
    ) -> dict[str, RouteResult]:
        """Route nets on a fresh graph without marking paths as obstacles.

        This allows nets to share routing space, useful when the progressive
        obstacle blocking in pass 1 was too aggressive.
        """
        from kicad_agent.routing.pathfinder import route_net

        results: dict[str, RouteResult] = {}
        for net_name, pins in netlist.items():
            if len(pins) < 2:
                continue
            result = route_net(graph, pins[0], pins[-1], net_name)
            if result:
                results[net_name] = result
        return results

    def _rebuild_graph(self) -> RoutingGraph | None:
        """Rebuild the routing graph with the same constraints.

        Returns a fresh graph without any progressive obstacle markings.
        Returns None if the original graph's board bounds are not available.
        """
        bounds = self._get_board_bounds()
        if bounds is None:
            return None
        try:
            return build_routing_graph(
                board_bounds=bounds,
                obstacles=[],
                constraints=self._graph.constraints,
            )
        except (ValueError, ImportError):
            logger.exception("Failed to rebuild routing graph")
            return None

    def _rebuild_graph_relaxed(self) -> RoutingGraph | None:
        """Rebuild the routing graph with relaxed constraints.

        Uses 50% finer grid resolution for more routing options.
        Returns None if bounds are not available or constraints cannot be relaxed.
        """
        bounds = self._get_board_bounds()
        if bounds is None:
            return None
        try:
            from kicad_agent.routing.constraints import RoutingConstraints

            base = self._graph.constraints
            relaxed = RoutingConstraints(
                clearance_mm=base.clearance_mm * 0.75,
                grid_resolution_mm=max(0.1, base.grid_resolution_mm * 0.5),
                trace_width_mm=base.trace_width_mm,
                via_diameter_mm=base.via_diameter_mm,
                via_drill_mm=base.via_drill_mm,
                max_nodes=base.max_nodes,
                via_cost_mm=base.via_cost_mm,
                layer_trace_widths=base.layer_trace_widths,
                dielectric_constant=base.dielectric_constant,
                dielectric_height_mm=base.dielectric_height_mm,
                copper_thickness_mm=base.copper_thickness_mm,
            )
            return build_routing_graph(
                board_bounds=bounds,
                obstacles=[],
                constraints=relaxed,
            )
        except (ValueError, ImportError):
            logger.exception("Failed to build relaxed routing graph")
            return None

    def _get_board_bounds(self) -> tuple[float, float, float, float] | None:
        """Extract board bounds from the routing graph.

        Scans graph nodes to find bounding box.
        """
        import networkx as nx

        nodes = list(self._graph._graph.nodes)
        if not nodes:
            return None

        xs = [n[0] for n in nodes]
        ys = [n[1] for n in nodes]
        return (min(xs), min(ys), max(xs), max(ys))

    def _record_results(
        self,
        pass_num: int,
        strategy: str,
        results: dict[str, RouteResult],
    ) -> None:
        """Record results from a pass into net histories."""
        for net_name, result in results.items():
            if net_name in self._history:
                self._history[net_name].record_attempt(
                    pass_num, result, strategy
                )

    def _get_failed_netlist(self) -> dict[str, list[tuple[float, float]]]:
        """Get netlist of nets not yet successfully routed."""
        return {
            name: pins
            for name, pins in self._netlist.items()
            if name in self._history and not self._history[name].routed
        }

    def _best_results(self) -> dict[str, RouteResult]:
        """Get the best result for each net across all passes."""
        results: dict[str, RouteResult] = {}
        for net_name, history in self._history.items():
            if history.best_result is not None:
                results[net_name] = history.best_result
        return results

    @property
    def pass_history(self) -> dict[str, NetPassHistory]:
        """Access to per-net pass history for analysis."""
        return dict(self._history)

    @property
    def summary(self) -> dict[str, Any]:
        """Summary of routing results across all passes."""
        total = len(self._netlist)
        routed = sum(1 for h in self._history.values() if h.routed)
        return {
            "total_nets": total,
            "routed_nets": routed,
            "failed_nets": total - routed,
            "pass1_routed": sum(
                1 for h in self._history.values()
                if h.attempts and h.attempts[0].get("success")
            ),
            "pass2_routed": sum(
                1 for h in self._history.values()
                if len(h.attempts) > 1 and h.attempts[1].get("success")
            ),
            "pass3_routed": sum(
                1 for h in self._history.values()
                if len(h.attempts) > 2 and h.attempts[2].get("success")
            ),
        }
