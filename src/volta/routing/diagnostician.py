"""Phase 104: Reverse-perspective blocker diagnosis.

When routing hits a dead end, look from the dead end's perspective. Find
what blocks its path. That blocker is the thing to move (rip up, reroute,
or nudge the component).

The diagnostic powers three downstream loops:
  - Loop A (close orchestrator loop): "failed net → diagnose blocker →
    rip up THAT → reroute" (targeted, not blind retry)
  - Loop B (DRC as reward): "failed BECAUSE of clearance-to-net-M at
    point P" (rich typed signal, not binary pass/fail)
  - Loop C (learned policy): learn WHICH blocker to rip up first (small
    decision space, fast to train)

Classification (F-07 precedence: most restrictive wins):

  SOFT_OTHER    — another net's trace blocks the corridor → rip_and_reroute
  SOFT_OWN      — this net's own prior trace blocks → reroute_self
  HARD_COMPONENT — movable component courtyard blocks → nudge_component
  HARD_FIXED    — locked/edge/connector blocks → escalate
  CONTESTED     — corridor blocked in prior rounds → raise_priority

Council conditions honored:
  F-05: top-5 shadow obstacle cap (success gate, not just risk-register note)
  F-07: movability precedence — locked > connector-prefix > edge > movable
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from volta.routing.constraints import RoutingConstraints
from volta.routing.graph import RoutingGraph
from volta.routing.pathfinder import RouteFailure, RouteResult, route_net
from volta.spatial.primitives import SpatialBox

logger = logging.getLogger(__name__)

# F-05: maximum obstacles to test for causal blocking (reachability-per-blocker
# is O(blockers × BFS); capping keeps diagnosis fast on dense boards).
_MAX_CAUSALITY_TESTS = 5

# Corridor half-width for shadow casting: clearance + trace_width.
# Obstacles within this band of the dead_end→target line are candidates.
_DEFAULT_CORRIDOR_HALF_WIDTH = 0.5  # mm, generous default

# F-07: ref prefixes that are always fixed (cannot be nudged).
_FIXED_PREFIXES = ("J", "MH", "H", "TP")

# Board-edge proximity threshold: components within this of the edge are fixed.
_EDGE_PROXIMITY_MM = 1.0


@dataclass(frozen=True)
class Blocker:
    """A single obstacle identified as blocking a route.

    Attributes:
        entity_type: "track" | "via" | "footprint"
        entity_id: UUID or net name or ref designator
        classification: SOFT_OTHER | SOFT_OWN | HARD_COMPONENT | HARD_FIXED
            | CONTESTED
        blocks_path: True if removing this obstacle opens the route (causal).
        recommended_action: rip_and_reroute | reroute_self | nudge_component
            | escalate | raise_priority
        removal_benefit: 0.0–1.0, estimated probability removing this helps.
    """

    entity_type: str
    entity_id: str
    classification: str
    blocks_path: bool
    recommended_action: str
    removal_benefit: float
    reference: str = ""  # ref designator or net name for display


@dataclass(frozen=True)
class BlockerDiagnosis:
    """Per-failed-net blocker diagnosis — operational signal + training label.

    Attributes:
        net_name: The net that failed to route.
        dead_end_point: Where the router frontier stopped (from RouteFailure).
        target_point: Where the router was trying to reach.
        blockers: Ranked tuple of identified blockers (highest benefit first).
        failure_type: "no_path" | "blocked_source" | "blocked_target"
    """

    net_name: str
    dead_end_point: tuple[float, float]
    target_point: tuple[float, float]
    blockers: tuple[Blocker, ...]
    failure_type: str


class BlockerDiagnostician:
    """Diagnose routing failures by looking from the dead end's perspective.

    Algorithm:
      1. Shadow cast: build a corridor from dead_end_point toward
         target_point, query obstacles intersecting it.
      2. Rank candidates by proximity to the dead end.
      3. For the top-N (F-05: cap at 5), test causality: remove the obstacle,
         rebuild the graph, re-run route_net. If the path opens, it's causal.
      4. Classify each causal blocker by entity type and movability.

    The diagnostic is the leverage point — it converts a binary "it failed"
    into a typed "it failed because component U3 blocks the corridor."
    """

    def __init__(
        self,
        board_bounds: tuple[float, float, float, float],
        obstacles: list[SpatialBox],
        constraints: RoutingConstraints | None = None,
        layers: list[str] | None = None,
        required_nodes: set[tuple[float, float]] | None = None,
        board_raw_content: str | None = None,
    ) -> None:
        """Initialize the diagnostician with the board's obstacle model.

        Args:
            board_bounds: (x_min, y_min, x_max, y_max) in mm.
            obstacles: Full obstacle list (footprints + tracks + vias).
            constraints: Routing constraints (for graph rebuilds).
            layers: Copper layer names.
            required_nodes: Pad positions that must stay routable.
            board_raw_content: Raw PCB S-expression, for checking ``(locked
                yes)`` on footprints (F-07 movability heuristic). If None,
                locked-status detection is skipped (components assumed movable).
        """
        self._board_bounds = board_bounds
        self._obstacles = obstacles
        self._constraints = constraints or RoutingConstraints()
        self._layers = layers
        self._required_nodes = required_nodes
        self._raw_content = board_raw_content

    def diagnose(self, failure: RouteFailure) -> BlockerDiagnosis:
        """Diagnose a single routing failure — the main entry point.

        Args:
            failure: The RouteFailure from route_net (carries dead_end_point).

        Returns:
            BlockerDiagnosis with ranked blockers. Empty blockers tuple if
            no obstacles are in the shadow corridor (unusual — may indicate
            a graph construction issue rather than a physical blocker).
        """
        dead_end = failure.dead_end_point
        target = failure.target_point

        # Step 1: Shadow cast — find obstacles in the dead_end→target corridor.
        candidates = self._shadow_cast(dead_end, target)
        if not candidates:
            logger.debug(
                "Diagnose %s: no obstacles in corridor dead_end=%s target=%s",
                failure.net_name, dead_end, target,
            )
            return BlockerDiagnosis(
                net_name=failure.net_name,
                dead_end_point=dead_end,
                target_point=target,
                blockers=(),
                failure_type=failure.failure_type,
            )

        # Step 2: Rank by proximity to dead_end (closest first).
        ranked = self._rank_by_proximity(candidates, dead_end)

        # Step 3 (F-05): Test causality for top-5 only.
        causal = self._test_causality(failure, ranked[:_MAX_CAUSALITY_TESTS])

        # Step 4: Classify each causal blocker.
        blockers = tuple(
            self._classify(obs, failure.net_name, is_causal=obs_id in causal)
            for obs, obs_id in ranked[:_MAX_CAUSALITY_TESTS]
        )

        # Re-sort: causal blockers first (highest removal benefit), then by proximity.
        blockers = tuple(
            sorted(blockers, key=lambda b: (not b.blocks_path, -b.removal_benefit))
        )

        return BlockerDiagnosis(
            net_name=failure.net_name,
            dead_end_point=dead_end,
            target_point=target,
            blockers=blockers,
            failure_type=failure.failure_type,
        )

    def _shadow_cast(
        self,
        dead_end: tuple[float, float],
        target: tuple[float, float],
    ) -> list[tuple[SpatialBox, str]]:
        """Find obstacles intersecting the corridor from dead_end to target.

        The corridor is the bounding box of the dead_end→target line, inflated
        by the corridor half-width. This is a conservative (over-broad) filter
        — the causality test in step 3 refines it.

        Returns:
            List of (obstacle, entity_id) tuples.
        """
        corridor = self._corridor_bbox(dead_end, target)
        cx1, cy1, cx2, cy2 = corridor

        candidates: list[tuple[SpatialBox, str]] = []
        for obs in self._obstacles:
            # Bounding-box overlap test (cheap, no Shapely needed).
            if obs.x2 < cx1 or obs.x1 > cx2:
                continue
            if obs.y2 < cy1 or obs.y1 > cy2:
                continue
            candidates.append((obs, obs.entity_id))
        return candidates

    def _corridor_bbox(
        self,
        dead_end: tuple[float, float],
        target: tuple[float, float],
    ) -> tuple[float, float, float, float]:
        """Bounding box of the dead_end→target line, inflated by half-width."""
        hw = _DEFAULT_CORRIDOR_HALF_WIDTH
        x1 = min(dead_end[0], target[0]) - hw
        y1 = min(dead_end[1], target[1]) - hw
        x2 = max(dead_end[0], target[0]) + hw
        y2 = max(dead_end[1], target[1]) + hw
        return (x1, y1, x2, y2)

    def _rank_by_proximity(
        self,
        candidates: list[tuple[SpatialBox, str]],
        dead_end: tuple[float, float],
    ) -> list[tuple[SpatialBox, str]]:
        """Rank obstacles by distance from dead_end to the obstacle's center."""
        def center_dist(obs: SpatialBox) -> float:
            cx = (obs.x1 + obs.x2) / 2
            cy = (obs.y1 + obs.y2) / 2
            return math.hypot(cx - dead_end[0], cy - dead_end[1])

        return sorted(candidates, key=lambda pair: center_dist(pair[0]))

    def _test_causality(
        self,
        failure: RouteFailure,
        candidates: list[tuple[SpatialBox, str]],
    ) -> set[str]:
        """Test which obstacles, when removed, open the route.

        F-05: capped at _MAX_CAUSALITY_TESTS. For each candidate, rebuild the
        graph without that obstacle and re-run route_net. If it succeeds,
        the obstacle is causal (blocks_path=True).

        Returns:
            Set of entity_ids that are causal blockers.
        """
        causal: set[str] = set()
        source = failure.source_point
        target = failure.target_point

        for obs, obs_id in candidates:
            # Rebuild graph without this obstacle.
            reduced = [o for o in self._obstacles if o.entity_id != obs_id]
            try:
                test_graph = RoutingGraph(
                    board_bounds=self._board_bounds,
                    obstacles=reduced,
                    constraints=self._constraints,
                    layers=self._layers,
                    required_nodes=self._required_nodes,
                )
            except ValueError:
                logger.debug("Graph rebuild failed for %s, skipping", obs_id)
                continue

            result = route_net(test_graph, source, target, failure.net_name)
            if result:
                causal.add(obs_id)
                logger.debug(
                    "Causal blocker found: %s (%s) — removing opens %s",
                    obs_id, obs.entity_type, failure.net_name,
                )

        return causal

    def _classify(
        self,
        obs: SpatialBox,
        failing_net: str,
        is_causal: bool,
    ) -> Blocker:
        """Classify an obstacle into a blocker category.

        F-07 precedence: locked > connector-prefix > edge-proximity > movable.
        Conflicts resolve to the most restrictive (fixed).
        """
        entity_type = obs.entity_type
        entity_id = obs.entity_id
        ref = obs.reference or obs.entity_id

        # Determine classification.
        if entity_type in ("track", "via"):
            # Copper obstacle — is it ours or another net's?
            obs_net = getattr(obs, "reference", "") or ""
            if obs_net == failing_net:
                classification = "SOFT_OWN"
                action = "reroute_self"
            else:
                classification = "SOFT_OTHER"
                action = "rip_and_reroute"
            benefit = 0.9 if is_causal else 0.3
        elif entity_type == "footprint":
            # Component courtyard — can we move it?
            if self._is_fixed_component(obs):
                classification = "HARD_FIXED"
                action = "escalate"
                benefit = 0.1  # Can't fix by routing alone.
            else:
                classification = "HARD_COMPONENT"
                action = "nudge_component"
                benefit = 0.7 if is_causal else 0.2
        else:
            # Unknown obstacle type — treat as fixed/escalate.
            classification = "HARD_FIXED"
            action = "escalate"
            benefit = 0.1

        return Blocker(
            entity_type=entity_type,
            entity_id=entity_id,
            classification=classification,
            blocks_path=is_causal,
            recommended_action=action,
            removal_benefit=round(benefit, 2),
            reference=ref,
        )

    def _is_fixed_component(self, obs: SpatialBox) -> bool:
        """F-07: determine if a component is fixed (cannot be nudged).

        Precedence (most restrictive wins):
          1. ``(locked yes)`` in raw PCB content → fixed
          2. Ref prefix J*/MH*/H*/TP* → fixed
          3. Within _EDGE_PROXIMITY_MM of board edge → fixed
          4. Otherwise → movable
        """
        ref = obs.reference or ""

        # Check 1: KiCad lock flag (greppable from raw content).
        if self._raw_content and self._is_locked(ref):
            return True

        # Check 2: Connector/mounting-hole prefix.
        if ref:
            upper_ref = ref.upper()
            for prefix in _FIXED_PREFIXES:
                if upper_ref.startswith(prefix):
                    return True

        # Check 3: Board-edge proximity.
        if self._is_near_edge(obs):
            return True

        return False

    def _is_locked(self, ref: str) -> bool:
        """Check if a footprint is marked ``(locked yes)`` in the raw PCB.

        Avoids a parser change by scanning the raw S-expression. Reuses the
        same block-finding logic as PcbRawWriter (finds the footprint block
        by Reference property, then checks for the locked token before the
        ``(at ...)`` line.
        """
        if not self._raw_content or not ref:
            return False
        # Simple heuristic: find "(footprint ...REF..." block and check for
        # "(locked yes)" near the top. This is deliberately conservative —
        # a false positive (treating movable as fixed) is safe (just escalates).
        import re
        # Find the footprint block by reference.
        pattern = rf'\(footprint\s+"[^"]*"\s*(\([^)]*\))*\s*\(layer[^)]*\)\s*\(uuid[^)]*\)\s*\(at[^)]*\)\s*\(property\s+"Reference"\s+"{re.escape(ref)}"'
        # Simpler: just check if "(locked yes)" appears anywhere near this ref.
        # For a conservative check, look for the ref then locked within 500 chars before it.
        ref_idx = self._raw_content.find(f'"Reference" "{ref}"')
        if ref_idx == -1:
            return False
        # Search backwards up to 500 chars for "(locked yes)".
        search_start = max(0, ref_idx - 500)
        chunk = self._raw_content[search_start:ref_idx]
        return "(locked yes)" in chunk or "(locked)" in chunk

    def _is_near_edge(self, obs: SpatialBox) -> bool:
        """Check if an obstacle is within _EDGE_PROXIMITY_MM of the board edge."""
        x_min, y_min, x_max, y_max = self._board_bounds
        threshold = _EDGE_PROXIMITY_MM

        # Distance from each edge of the obstacle to the board edge.
        dist_left = obs.x1 - x_min
        dist_right = x_max - obs.x2
        dist_top = obs.y1 - y_min
        dist_bottom = y_max - obs.y2

        return min(dist_left, dist_right, dist_top, dist_bottom) <= threshold


def diagnose_routing_failures(
    failures: list[RouteFailure],
    board_bounds: tuple[float, float, float, float],
    obstacles: list[SpatialBox],
    constraints: RoutingConstraints | None = None,
    layers: list[str] | None = None,
    required_nodes: set[tuple[float, float]] | None = None,
    board_raw_content: str | None = None,
) -> list[BlockerDiagnosis]:
    """Diagnose multiple routing failures — standalone convenience function.

    Args:
        failures: List of RouteFailure objects from route_net/route_all_nets.
        board_bounds: (x_min, y_min, x_max, y_max) in mm.
        obstacles: Full obstacle list (footprints + tracks + vias).
        constraints: Routing constraints.
        layers: Copper layer names.
        required_nodes: Pad positions that must stay routable.
        board_raw_content: Raw PCB content for locked-footprint detection.

    Returns:
        List of BlockerDiagnosis, one per failure (same order).
    """
    diag = BlockerDiagnostician(
        board_bounds=board_bounds,
        obstacles=obstacles,
        constraints=constraints,
        layers=layers,
        required_nodes=required_nodes,
        board_raw_content=board_raw_content,
    )
    return [diag.diagnose(f) for f in failures]
