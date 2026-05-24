"""Interactive routing session with suggestion/approval and constraint adaptation.

Provides an InteractiveRoutingSession that generates routing suggestions for
all nets, then allows approve/reject/modify cycles with automatic rerouting
of rejected paths. Supports differential pair coupling and user constraint
overrides per net.

Usage:
    from kicad_agent.routing.interactive import InteractiveRoutingSession

    session = InteractiveRoutingSession(graph, netlist, constraints)
    session.approve("VCC")
    session.reject("SIG", reason="too close to GND")
    new_suggestions = session.reroute_rejected()
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.pathfinder import route_all_nets, route_net

if TYPE_CHECKING:
    from kicad_agent.routing.diff_pair import DiffPairResult


class SuggestionStatus(str, Enum):
    """Status of a routing suggestion.

    PENDING: Awaiting user review.
    APPROVED: User accepted the route; added to locked routes.
    REJECTED: User rejected the route; eligible for reroute.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class RoutingSuggestion:
    """A single routing suggestion for a net.

    Unlike RouteResult, this is mutable -- status changes as the user
    approves or rejects suggestions.

    Attributes:
        net_name: Name of the net.
        path: Ordered list of (x, y) waypoints forming the route.
        length_mm: Total path length in mm.
        clearance_violations: List of DRC violation descriptions.
        status: Current suggestion status.
        reject_reason: Reason for rejection, if any.
        user_constraints: Per-net constraint overrides from the user.
        is_differential_pair: True if this net is part of a diff pair.
        diff_pair_complement: Name of the complementary net in the pair.
    """

    net_name: str
    path: list[tuple[float, float]]
    length_mm: float
    clearance_violations: list[str] = field(default_factory=list)
    status: SuggestionStatus = SuggestionStatus.PENDING
    reject_reason: str = ""
    user_constraints: dict[str, float] = field(default_factory=dict)
    is_differential_pair: bool = False
    diff_pair_complement: str = ""


class InteractiveRoutingSession:
    """Interactive routing session with approve/reject/reroute cycles.

    Generates routing suggestions for all nets on construction, then
    supports iterative review: approve good routes, reject bad ones,
    adjust constraints, and reroute only the rejected nets.

    Locked (approved) routes are treated as obstacles during reroute,
    ensuring approved paths are preserved.

    Args:
        graph: Routing graph with DRC-aware edge weights.
        netlist: Dict mapping net names to lists of (x, y) pin positions.
        constraints: Routing constraints governing clearance, grid, etc.
        max_iterations: Maximum number of reroute cycles allowed.
        differential_pairs: List of (positive_net, negative_net) tuples
            for differential pair routing.
    """

    def __init__(
        self,
        graph: RoutingGraph,
        netlist: dict[str, list[tuple[float, float]]],
        constraints: RoutingConstraints,
        max_iterations: int = 5,
        differential_pairs: list[tuple[str, str]] | None = None,
    ) -> None:
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")
        if differential_pairs is None:
            differential_pairs = []

        self._graph = graph
        self._netlist = netlist
        self._constraints = constraints
        self._max_iterations = max_iterations
        self._differential_pairs = list(differential_pairs)

        # Build a lookup: net_name -> complement net_name (if diff pair).
        self._diff_pair_map: dict[str, str] = {}
        for pos_net, neg_net in self._differential_pairs:
            self._diff_pair_map[pos_net] = neg_net
            self._diff_pair_map[neg_net] = pos_net

        # Collect diff pair net names for exclusion from batch routing.
        diff_pair_nets: set[str] = set()
        for pos_net, neg_net in self._differential_pairs:
            diff_pair_nets.add(pos_net)
            diff_pair_nets.add(neg_net)

        self._suggestions: dict[str, RoutingSuggestion] = {}
        self._locked_routes: dict[str, RoutingSuggestion] = {}
        self._iteration: int = 0
        self._board_bounds: tuple[float, float, float, float] = (
            0.0, 0.0, 0.0, 0.0,
        )

        self._generate_suggestions(diff_pair_nets)

    def _generate_suggestions(
        self, diff_pair_nets: set[str],
    ) -> None:
        """Route all nets and create RoutingSuggestion objects.

        Args:
            diff_pair_nets: Set of net names handled as differential pairs.
        """
        from kicad_agent.routing.diff_pair import route_differential_pair

        # Route non-diff-pair nets via batch routing.
        regular_netlist = {
            name: pins
            for name, pins in self._netlist.items()
            if name not in diff_pair_nets and len(pins) >= 2
        }

        route_results = route_all_nets(self._graph, regular_netlist)

        for net_name, result in route_results.items():
            self._suggestions[net_name] = RoutingSuggestion(
                net_name=net_name,
                path=list(result.path),
                length_mm=result.length_mm,
            )

        # Route differential pairs.
        for pos_net, neg_net in self._differential_pairs:
            pos_pins = self._netlist.get(pos_net, [])
            neg_pins = self._netlist.get(neg_net, [])
            if len(pos_pins) < 2 or len(neg_pins) < 2:
                continue

            dp_result: DiffPairResult = route_differential_pair(
                self._graph,
                source_pos=pos_pins[0],
                target_pos=pos_pins[-1],
                source_neg=neg_pins[0],
                target_neg=neg_pins[-1],
                net_name_pos=pos_net,
                net_name_neg=neg_net,
            )

            if dp_result.valid:
                # Positive net suggestion.
                self._suggestions[pos_net] = RoutingSuggestion(
                    net_name=pos_net,
                    path=list(dp_result.net_positive),
                    length_mm=dp_result.length_positive_mm,
                    is_differential_pair=True,
                    diff_pair_complement=neg_net,
                )
                # Negative net suggestion.
                self._suggestions[neg_net] = RoutingSuggestion(
                    net_name=neg_net,
                    path=list(dp_result.net_negative),
                    length_mm=dp_result.length_negative_mm,
                    is_differential_pair=True,
                    diff_pair_complement=pos_net,
                )

    def approve(self, net_name: str) -> None:
        """Approve a routing suggestion.

        Moves the suggestion to locked_routes. If the net is part of a
        differential pair, the complement net is also approved.

        Args:
            net_name: Name of the net to approve.

        Raises:
            KeyError: If net_name is not in the current suggestions.
        """
        suggestion = self._suggestions.get(net_name)
        if suggestion is None:
            raise KeyError(f"Net '{net_name}' not found in suggestions")

        suggestion.status = SuggestionStatus.APPROVED
        self._locked_routes[net_name] = suggestion

        # Approve diff pair complement if applicable.
        complement = self._diff_pair_map.get(net_name)
        if complement and complement in self._suggestions:
            comp_suggestion = self._suggestions[complement]
            comp_suggestion.status = SuggestionStatus.APPROVED
            self._locked_routes[complement] = comp_suggestion

    def reject(self, net_name: str, reason: str = "") -> None:
        """Reject a routing suggestion.

        If the net is part of a differential pair, the complement net is
        also rejected.

        Args:
            net_name: Name of the net to reject.
            reason: Optional reason for rejection.

        Raises:
            KeyError: If net_name is not in the current suggestions.
        """
        suggestion = self._suggestions.get(net_name)
        if suggestion is None:
            raise KeyError(f"Net '{net_name}' not found in suggestions")

        suggestion.status = SuggestionStatus.REJECTED
        suggestion.reject_reason = reason

        # Remove from locked if previously approved.
        self._locked_routes.pop(net_name, None)

        # Reject diff pair complement if applicable.
        complement = self._diff_pair_map.get(net_name)
        if complement and complement in self._suggestions:
            comp_suggestion = self._suggestions[complement]
            comp_suggestion.status = SuggestionStatus.REJECTED
            comp_suggestion.reject_reason = reason
            self._locked_routes.pop(complement, None)

    def set_constraint(self, net_name: str, key: str, value: float) -> None:
        """Set a user constraint override for a specific net.

        Constraints persist through reroute cycles and can influence
        the routing graph rebuild (e.g., increased clearance).

        Args:
            net_name: Name of the net.
            key: Constraint key (e.g., "clearance_mm", "trace_width_mm").
            value: Constraint value. Must be a positive float.

        Raises:
            KeyError: If net_name is not in the current suggestions.
            ValueError: If value is not a positive float.
        """
        if net_name not in self._suggestions:
            raise KeyError(f"Net '{net_name}' not found in suggestions")
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(
                f"Constraint value must be a positive float, got {value}"
            )

        self._suggestions[net_name].user_constraints[key] = float(value)

    def reroute_rejected(self) -> list[RoutingSuggestion]:
        """Reroute all rejected nets, respecting locked routes.

        Collects rejected nets and their user constraints, optionally
        rebuilds the routing graph with updated constraints, and re-routes
        only the rejected nets. Locked (approved) route waypoints are
        added as obstacles to prevent interference.

        Returns:
            List of new RoutingSuggestion objects with PENDING status.

        Raises:
            RuntimeError: If max_iterations has been reached.
        """
        if self._iteration >= self._max_iterations:
            raise RuntimeError(
                f"Maximum iterations ({self._max_iterations}) reached. "
                f"Cannot reroute further."
            )

        # Collect rejected nets.
        rejected = {
            name: sugg
            for name, sugg in self._suggestions.items()
            if sugg.status == SuggestionStatus.REJECTED
        }

        if not rejected:
            return []

        # Check if any rejected net has user constraint overrides that
        # require a graph rebuild (e.g., increased clearance).
        needs_rebuild = any(
            sugg.user_constraints.get("clearance_mm")
            and sugg.user_constraints["clearance_mm"]
            > self._constraints.clearance_mm
            for sugg in rejected.values()
        )

        # Build obstacles from locked route waypoints.
        from kicad_agent.spatial.primitives import SpatialBox

        locked_obstacles: list[SpatialBox] = []
        trace_w = self._constraints.trace_width_mm
        for sugg in self._locked_routes.values():
            for px, py in sugg.path:
                half_w = trace_w / 2.0
                locked_obstacles.append(
                    SpatialBox(
                        px - half_w, py - half_w,
                        px + half_w, py + half_w,
                        "locked_route", sugg.net_name,
                    )
                )

        # Rebuild graph if constraints changed.
        if needs_rebuild:
            updated_fields: dict[str, float] = {}
            max_clearance = self._constraints.clearance_mm
            for sugg in rejected.values():
                if sugg.user_constraints.get("clearance_mm", 0) > max_clearance:
                    max_clearance = sugg.user_constraints["clearance_mm"]
            updated_fields["clearance_mm"] = max_clearance

            # Also propagate trace_width overrides if present.
            for sugg in rejected.values():
                if "trace_width_mm" in sugg.user_constraints:
                    updated_fields.setdefault(
                        "trace_width_mm",
                        self._constraints.trace_width_mm,
                    )

            new_constraints = RoutingConstraints(
                clearance_mm=updated_fields.get(
                    "clearance_mm", self._constraints.clearance_mm
                ),
                grid_resolution_mm=self._constraints.grid_resolution_mm,
                trace_width_mm=updated_fields.get(
                    "trace_width_mm", self._constraints.trace_width_mm
                ),
                via_diameter_mm=self._constraints.via_diameter_mm,
                via_drill_mm=self._constraints.via_drill_mm,
                max_nodes=self._constraints.max_nodes,
            )
            active_graph = RoutingGraph(
                board_bounds=self._get_board_bounds(),
                obstacles=locked_obstacles,
                constraints=new_constraints,
            )
        else:
            # Rebuild with original constraints but locked route obstacles.
            active_graph = RoutingGraph(
                board_bounds=self._get_board_bounds(),
                obstacles=locked_obstacles,
                constraints=self._constraints,
            )

        # Re-route rejected nets only.
        rejected_netlist = {
            name: self._netlist[name]
            for name in rejected
            if name in self._netlist and len(self._netlist[name]) >= 2
        }

        new_route_results = route_all_nets(active_graph, rejected_netlist)

        new_suggestions: list[RoutingSuggestion] = []
        for net_name, result in new_route_results.items():
            old_sugg = rejected.get(net_name)
            new_sugg = RoutingSuggestion(
                net_name=net_name,
                path=list(result.path),
                length_mm=result.length_mm,
                user_constraints=old_sugg.user_constraints.copy()
                if old_sugg
                else {},
                is_differential_pair=old_sugg.is_differential_pair
                if old_sugg
                else False,
                diff_pair_complement=old_sugg.diff_pair_complement
                if old_sugg
                else "",
            )
            self._suggestions[net_name] = new_sugg
            new_suggestions.append(new_sugg)

        self._iteration += 1
        return new_suggestions

    def summary(self) -> dict:
        """Return a summary of the session state.

        Returns:
            Dict with iteration count, net totals by status, and max_iterations.
        """
        approved = sum(
            1 for s in self._suggestions.values()
            if s.status == SuggestionStatus.APPROVED
        )
        rejected = sum(
            1 for s in self._suggestions.values()
            if s.status == SuggestionStatus.REJECTED
        )
        pending = sum(
            1 for s in self._suggestions.values()
            if s.status == SuggestionStatus.PENDING
        )
        return {
            "iteration": self._iteration,
            "total_nets": len(self._suggestions),
            "approved": approved,
            "rejected": rejected,
            "pending": pending,
            "max_iterations": self._max_iterations,
        }

    def _get_board_bounds(self) -> tuple[float, float, float, float]:
        """Compute board bounds from netlist pin positions.

        Returns:
            (x_min, y_min, x_max, y_max) bounding box with padding.
        """
        if self._board_bounds != (0.0, 0.0, 0.0, 0.0):
            return self._board_bounds

        all_x: list[float] = []
        all_y: list[float] = []
        for pins in self._netlist.values():
            for x, y in pins:
                all_x.append(x)
                all_y.append(y)

        if not all_x:
            return (0.0, 0.0, 50.0, 50.0)

        padding = max(
            self._constraints.clearance_mm * 5,
            5.0,
        )
        self._board_bounds = (
            min(all_x) - padding,
            min(all_y) - padding,
            max(all_x) + padding,
            max(all_y) + padding,
        )
        return self._board_bounds

    @property
    def suggestions(self) -> dict[str, RoutingSuggestion]:
        """All current routing suggestions."""
        return self._suggestions

    @property
    def locked_routes(self) -> dict[str, RoutingSuggestion]:
        """Approved routes that are locked during reroute."""
        return self._locked_routes

    @property
    def iteration(self) -> int:
        """Current reroute iteration count."""
        return self._iteration

    @property
    def is_complete(self) -> bool:
        """True when all suggestions are approved (no pending or rejected)."""
        return all(
            s.status == SuggestionStatus.APPROVED
            for s in self._suggestions.values()
        ) and len(self._suggestions) > 0
