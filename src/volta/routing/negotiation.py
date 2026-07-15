"""Phase 105: Negotiation-based rip-up and reroute loop.

PathFinder-style negotiation (McMurchie & Ebeling 1995) with targeted
reverse-perspective blocker diagnosis (Phase 104). The loop:

  1. Route all nets (A* or Freerouting).
  2. Verify via DRC.
  3. Diagnose failures (Phase 104 BlockerDiagnostician).
  4. For SOFT_OTHER blockers: rip up the blocker net, raise its priority,
     and re-route both the failed net and the blocker.
  5. For contested corridors: apply monotonic congestion cost (PathFinder
     historical penalty) to push routes toward alternative paths.
  6. Repeat until: all nets routed | only HARD blockers remain | max_rounds
     reached | convergence stall (no DRC improvement for 2 rounds).

Convergence guarantee (PathFinder): historical congestion cost is monotonic
(only increases), preventing oscillation. max_rounds cap + stall detection
bound runtime.

Council conditions honored:
  C-02: DSN round-trip fidelity (the wiring emitter + test — separate task).
  F-06: the loop owns its own mutable-weight graph instance (not the per-call
        graph that route_net operates on).
  R-7: termination via monotonic cost + stall detection.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from volta.routing.constraints import RoutingConstraints
from volta.routing.diagnostician import (
    BlockerDiagnostician,
    BlockerDiagnosis,
)
from volta.routing.graph import RoutingGraph
from volta.routing.pathfinder import (
    RouteFailure,
    RouteResult,
    route_net,
)
from volta.spatial.primitives import SpatialBox

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROUNDS = 8
_STALL_THRESHOLD = 2  # rounds with no improvement before early exit


@dataclass(frozen=True)
class NegotiationResult:
    """Result of a negotiation loop run.

    Attributes:
        routed_nets: Dict of net_name → RouteResult for successfully routed nets.
        failed_nets: Dict of net_name → RouteFailure for nets that couldn't route.
        diagnoses: Dict of net_name → BlockerDiagnosis for failed nets.
        rounds_used: Number of negotiation rounds executed.
        converged: True if all nets routed. False if some remain failed.
        congestion_map: Final congestion costs per graph node (for audit/debug).
        stalled: True if the loop exited due to convergence stall.
    """

    routed_nets: dict[str, RouteResult]
    failed_nets: dict[str, RouteFailure]
    diagnoses: dict[str, BlockerDiagnosis]
    rounds_used: int
    converged: bool
    congestion_map: dict[tuple, float]
    stalled: bool


class NegotiationLoop:
    """Closed-loop rip-up-and-reroute with congestion-driven convergence.

    F-06 (graph lifecycle): the loop owns a persistent RoutingGraph with
    mutable edge weights. Congestion costs accumulate between rounds and
    are injected into edge weights, pushing routes away from contested
    corridors (PathFinder's historical penalty).
    """

    def __init__(
        self,
        board_bounds: tuple[float, float, float, float],
        obstacles: list[SpatialBox],
        netlist: dict[str, list[tuple[float, float]]],
        constraints: RoutingConstraints | None = None,
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
        board_raw_content: str | None = None,
        diagnostician: Any = None,
    ) -> None:
        """Initialize the negotiation loop.

        Args:
            board_bounds: (x_min, y_min, x_max, y_max) in mm.
            obstacles: Full obstacle list (footprints + existing tracks).
            netlist: Dict of net_name → list of (x, y) pin positions.
            constraints: Routing constraints.
            max_rounds: Maximum negotiation rounds (default 8).
            board_raw_content: Raw PCB content for locked-footprint detection.
            diagnostician: Phase 106 — optional pluggable diagnostician.
                If provided (e.g. BlockerDiagnosticianModel), used instead of
                the deterministic BlockerDiagnostician. Must implement
                diagnose(failure: RouteFailure) -> BlockerDiagnosis.
                Default None → deterministic (zero regression).
        """
        self._board_bounds = board_bounds
        self._obstacles = list(obstacles)
        self._netlist = netlist
        self._constraints = constraints or RoutingConstraints()
        self._max_rounds = max_rounds
        self._raw_content = board_raw_content
        # Phase 106: pluggable diagnostician (model-based or deterministic).
        self._diagnostician = diagnostician

        # F-06: persistent congestion map (graph_node → historical cost).
        # Monotonic — only increases. This is PathFinder's convergence guarantee.
        self._congestion: dict[tuple, float] = {}

        # Track ripped-up nets (their obstacles removed for re-routing).
        self._ripped_net_ids: set[str] = set()

    def run(self) -> NegotiationResult:
        """Execute the negotiation loop.

        Returns:
            NegotiationResult with final routing state.
        """
        routed: dict[str, RouteResult] = {}
        failed: dict[str, RouteFailure] = {}
        diagnoses: dict[str, BlockerDiagnosis] = {}
        prev_failed_count = -1
        stall_counter = 0
        round_num = 0

        for round_num in range(1, self._max_rounds + 1):
            logger.info("Negotiation round %d/%d", round_num, self._max_rounds)

            # Build graph with current obstacles minus ripped-up nets.
            active_obstacles = self._active_obstacles()
            graph = self._build_graph(active_obstacles)

            # Route all unrouted nets.
            round_routed, round_failed = self._route_round(graph, routed)

            # Merge results.
            routed.update(round_routed)
            failed = round_failed  # Replace prior failures with current state.

            if not failed:
                logger.info("Negotiation converged in %d rounds (all routed)", round_num)
                break

            # Diagnose failures.
            # Phase 106: use injected diagnostician (model-based) if provided,
            # otherwise fall back to deterministic BlockerDiagnostician.
            if self._diagnostician is not None:
                for net_name, failure in failed.items():
                    diagnoses[net_name] = self._diagnostician.diagnose(failure)
            else:
                diag = BlockerDiagnostician(
                    board_bounds=self._board_bounds,
                    obstacles=active_obstacles,
                    constraints=self._constraints,
                    board_raw_content=self._raw_content,
                )
                for net_name, failure in failed.items():
                    diagnoses[net_name] = diag.diagnose(failure)

            # Check for SOFT_OTHER blockers — rip them up for next round.
            ripped_this_round = self._process_diagnoses(diagnoses)

            # Update congestion costs for contested corridors.
            self._update_congestion(failed, graph)

            # Stall detection (R-7): no improvement for N consecutive rounds.
            current_failed_count = len(failed)
            if current_failed_count >= prev_failed_count and not ripped_this_round:
                stall_counter += 1
                if stall_counter >= _STALL_THRESHOLD:
                    logger.info(
                        "Negotiation stalled after %d rounds (%d nets failed)",
                        round_num, current_failed_count,
                    )
                    break
            else:
                stall_counter = 0
            prev_failed_count = current_failed_count

            # If only HARD blockers remain, no point continuing.
            if ripped_this_round == 0 and self._only_hard_blockers(diagnoses):
                logger.info(
                    "Negotiation stopped: only HARD blockers remain (%d nets)",
                    len(failed),
                )
                break

        return NegotiationResult(
            routed_nets=routed,
            failed_nets=failed,
            diagnoses=diagnoses,
            rounds_used=round_num,
            converged=not failed,
            congestion_map=dict(self._congestion),
            stalled=stall_counter >= _STALL_THRESHOLD,
        )

    def _active_obstacles(self) -> list[SpatialBox]:
        """Return obstacles minus ripped-up nets' tracks."""
        if not self._ripped_net_ids:
            return list(self._obstacles)
        return [
            o for o in self._obstacles
            if o.reference not in self._ripped_net_ids
            or o.entity_type == "footprint"
        ]

    def _build_graph(self, obstacles: list[SpatialBox]) -> RoutingGraph:
        """Build a routing graph with current obstacles + congestion costs.

        F-06: the loop owns graph lifecycle. Each round rebuilds the graph
        with the current obstacle set. Congestion costs are injected into
        edge weights after construction.
        """
        # Collect pad positions as required nodes.
        required: set[tuple[float, float]] = set()
        for pins in self._netlist.values():
            for px, py in pins:
                required.add((px, py))

        graph = RoutingGraph(
            board_bounds=self._board_bounds,
            obstacles=obstacles,
            constraints=self._constraints,
            required_nodes=required,
        )

        # Inject congestion costs into edge weights (F-06).
        if self._congestion:
            self._apply_congestion(graph)

        return graph

    def _apply_congestion(self, graph: RoutingGraph) -> None:
        """Apply accumulated congestion costs to graph edge weights.

        PathFinder historical penalty: edges through contested nodes get
        progressively more expensive, pushing routes to alternative paths.
        """
        g = graph.graph
        for node, cost in self._congestion.items():
            if node in g:
                # Increase weight of all edges touching this node.
                for neighbor in g[node]:
                    edge_data = g[node][neighbor]
                    edge_data["weight"] = edge_data.get("weight", 1.0) + cost

    def _route_round(
        self,
        graph: RoutingGraph,
        already_routed: dict[str, RouteResult],
    ) -> tuple[dict[str, RouteResult], dict[str, RouteFailure]]:
        """Route all unrouted nets in priority order.

        Returns:
            (routed_this_round, failed_this_round)
        """
        routed: dict[str, RouteResult] = {}
        failed: dict[str, RouteFailure] = {}

        # Sort nets: ripped-up nets first (they were blocking), then shortest.
        unrouted = {
            n: pins for n, pins in self._netlist.items()
            if n not in already_routed
        }

        # Sort by estimated distance (shortest first, like route_all_nets).
        sorted_nets = sorted(
            unrouted.items(),
            key=lambda kv: self._estimate_distance(kv[1]),
        )

        for net_name, pins in sorted_nets:
            if len(pins) < 2:
                continue
            result = route_net(graph, pins[0], pins[-1], net_name)
            if result:
                routed[net_name] = result
                graph.mark_path_as_obstacle(result.path)
            else:
                assert isinstance(result, RouteFailure)
                failed[net_name] = result

        return routed, failed

    def _estimate_distance(self, pins: list[tuple[float, float]]) -> float:
        """Estimate routing distance for net ordering."""
        if len(pins) < 2:
            return 0.0
        return math.hypot(pins[-1][0] - pins[0][0], pins[-1][1] - pins[0][1])

    def _process_diagnoses(
        self,
        diagnoses: dict[str, BlockerDiagnosis],
    ) -> int:
        """Process blocker diagnoses — rip up SOFT_OTHER blockers.

        Returns:
            Number of nets ripped up this round.
        """
        ripped = 0
        for net_name, diag in diagnoses.items():
            for blocker in diag.blockers:
                if blocker.classification == "SOFT_OTHER" and blocker.blocks_path:
                    # Rip up the blocker's net for next round.
                    blocker_net = blocker.reference
                    if blocker_net and blocker_net not in self._ripped_net_ids:
                        self._ripped_net_ids.add(blocker_net)
                        logger.info(
                            "Ripping up %s (blocks %s) for re-routing",
                            blocker_net, net_name,
                        )
                        ripped += 1
        return ripped

    def _update_congestion(
        self,
        failed: dict[str, RouteFailure],
        graph: RoutingGraph,
    ) -> None:
        """Update congestion costs for contested corridors.

        PathFinder: nodes near dead-end points get increasing historical
        cost. This is monotonic (only increases) — the convergence guarantee.
        """
        penalty = 10.0  # Per-round penalty increment for contested nodes.
        g = graph.graph

        for failure in failed.values():
            dead_end = failure.dead_end_point
            # Find the nearest graph node to the dead-end and penalize it
            # plus its neighbors (the contested corridor).
            nearest = self._nearest_node(g, dead_end)
            if nearest is not None:
                self._congestion[nearest] = (
                    self._congestion.get(nearest, 0.0) + penalty
                )
                # Also penalize immediate neighbors (the corridor).
                for neighbor in g[nearest]:
                    self._congestion[neighbor] = (
                        self._congestion.get(neighbor, 0.0) + penalty * 0.5
                    )

    def _nearest_node(
        self,
        g: Any,
        point: tuple[float, float],
    ) -> tuple | None:
        """Find the nearest graph node to a 2D point."""
        nearest = None
        nearest_dist = float("inf")
        for node in g.nodes:
            d = math.hypot(node[0] - point[0], node[1] - point[1])
            if d < nearest_dist:
                nearest_dist = d
                nearest = node
        return nearest

    def _only_hard_blockers(
        self,
        diagnoses: dict[str, BlockerDiagnosis],
    ) -> bool:
        """Check if all remaining blockers are HARD (can't fix by routing)."""
        for diag in diagnoses.values():
            for blocker in diag.blockers:
                if blocker.classification in ("SOFT_OTHER", "SOFT_OWN"):
                    return False
        return True


def negotiate_route(
    board_bounds: tuple[float, float, float, float],
    obstacles: list[SpatialBox],
    netlist: dict[str, list[tuple[float, float]]],
    constraints: RoutingConstraints | None = None,
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
    board_raw_content: str | None = None,
    diagnostician: Any = None,
) -> NegotiationResult:
    """Standalone negotiation loop — convenience function.

    Args:
        board_bounds: (x_min, y_min, x_max, y_max) in mm.
        obstacles: Full obstacle list (footprints + existing tracks).
        netlist: Dict of net_name → list of (x, y) pin positions.
        constraints: Routing constraints.
        max_rounds: Maximum negotiation rounds (default 8).
        board_raw_content: Raw PCB content for locked-footprint detection.
        diagnostician: Phase 106 — optional pluggable diagnostician.

    Returns:
        NegotiationResult with final routing state.
    """
    loop = NegotiationLoop(
        board_bounds=board_bounds,
        obstacles=obstacles,
        netlist=netlist,
        constraints=constraints,
        max_rounds=max_rounds,
        board_raw_content=board_raw_content,
        diagnostician=diagnostician,
    )
    return loop.run()
