"""RoutingStrategy Protocol and DeterministicStrategy implementation.

Defines the integration contract that Phase 98 (AI Routing Strategy Advisor)
will later implement. Phase 100 provides DeterministicStrategy as the
default/fallback policy derived from Phase 99 Freerouting baseline data.

Contract (CONTEXT.md:54-77):
- Pure: strategize() has no side effects and no I/O
- Serializable: RoutingStrategyResult is JSON-dumpable for the audit trail
- Validatable: Phase 98's R-4 validation gate will sit at this boundary

Council corrections applied:
- H1: RouterBackend has exactly 2 variants (ASTAR, FREEROUTING). MULTI_PASS
  removed — no dispatch case uses it. Phase 98 can extend the enum if needed.
- H3: BoardState has NO layer_count field — no dispatch case reads it.
- M3: DeterministicStrategy is a frozen dataclass with differential_pairs
  and net_class_map fields (shown in interface block).
- L2: _dispatch has an explicit "first match wins" ordering comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class RouterBackend(str, Enum):
    """Available routing backends.

    H1 correction: exactly 2 variants. MULTI_PASS removed (dead variant —
    no dispatch case uses it). Phase 98 can extend the enum if multi-pass
    dispatch is needed (YAGNI for now).
    """

    ASTAR = "astar"
    FREEROUTING = "freerouting"


@dataclass(frozen=True)
class Keepout:
    """Additional routing keepout beyond board rules.

    A rectangular region on a specific layer where routing is forbidden.
    Strategies may emit these to communicate constraints derived from
    board analysis (e.g., RF exclusion zones, mechanical keepouts).
    """

    x1: float
    y1: float
    x2: float
    y2: float
    layer: str
    reason: str


@dataclass(frozen=True)
class BoardState:
    """Immutable snapshot of board state for strategy evaluation.

    H3 correction: NO layer_count field — no dispatch case reads it.
    Phase 98 can re-add it if layer-aware routing is needed (YAGNI).

    Phase 98 consumes this — must be pure data, no I/O. All fields are
    deterministic snapshots derivable from PcbIR/NativeBoard inspection.
    """

    total_nets: int
    has_zones: bool
    board_bounds: tuple[float, float, float, float]
    net_classes: tuple[str, ...]


@dataclass(frozen=True)
class Pin:
    """Pin reference for netlist.

    A single pad on a footprint, identified by its (footprint_ref, pad_number)
    pair plus its absolute (x, y) board position in mm.
    """

    footprint_ref: str
    pad_number: str
    x: float
    y: float


@dataclass(frozen=True)
class RoutingStrategyResult:
    """Output of RoutingStrategy.strategize().

    Phase 98 R-4 validation gate will validate this structure before
    the orchestrator executes it. The orchestrator also validates
    defensively (H4 — see _validate_strategy_result in orchestrator.py).

    Attributes:
        net_priorities: Net names in the order they should be routed.
            Diff pairs first, then power, then signal (deterministic mode).
        layer_hints: Optional net_name -> copper layer mapping. Deterministic
            mode emits an empty dict (no layer hints). Phase 98 may populate.
        keepouts: Additional keepout rectangles beyond board rules.
        router_assignment: Per-net backend selection. Every net in the
            netlist must have an entry. Values must be valid RouterBackend.
        routing_notes: Free-text rationale for audit trail.
    """

    net_priorities: tuple[str, ...]
    layer_hints: dict[str, str]
    keepouts: tuple[Keepout, ...]
    router_assignment: dict[str, RouterBackend]
    routing_notes: str


class RoutingStrategy(Protocol):
    """Strategy for deciding how to route each net.

    Phase 98 (AI Routing Strategy Advisor) will implement this with an
    LLM-backed advisor. Phase 100 provides DeterministicStrategy as the
    default/fallback.

    Contract:
    - MUST be pure (no side effects, no I/O)
    - MUST be serializable (result must be JSON-dumpable for audit trail)
    - MUST be validatable (Phase 98 R-4 gate validates before execution)

    Why Protocol not ABC: Phase 98's AI advisor should be able to implement
    the strategy without inheriting from a base class. Protocol enables
    structural subtyping (duck typing with type checker support).
    """

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        """Return a routing plan for the orchestrator to execute.

        Args:
            board_state: Immutable snapshot of board-level metadata.
            netlist: Dict mapping net names to lists of Pin objects.

        Returns:
            RoutingStrategyResult with per-net router assignments and
            routing priority order.
        """
        ...


def _priority_rank(
    net_name: str,
    netlist: dict[str, list[Pin]],
    *,
    diff_pair_nets: set[str],
    power_nets: set[str],
) -> int:
    """Compute routing priority rank for a net (lower = earlier).

    Order: diff pairs (0) → power (1) → signal (2).
    """
    if net_name in diff_pair_nets:
        return 0
    if net_name in power_nets:
        return 1
    return 2


@dataclass(frozen=True)
class DeterministicStrategy:
    """Default routing strategy with no AI dependency.

    Uses deterministic heuristics derived from Phase 99 baseline data
    (smd_test_board 50% completion, RaspberryPi-uHAT 3.2%, synthetic
    4-layer NPE). Phase 98's AI advisor will replace this with a learned
    policy.

    M3 correction: fields shown in interface block. differential_pairs
    and net_class_map are configurable at construction time so the
    orchestrator can pass them through from route_board kwargs.

    Attributes:
        differential_pairs: Tuples of (positive_net, negative_net). Nets
            appearing in any pair are dispatched to ASTAR for length matching.
        net_class_map: Optional dict mapping net_name -> class label
            (e.g., "Power", "Signal"). When None, no net is treated as Power.
    """

    differential_pairs: tuple[tuple[str, str], ...] = ()
    net_class_map: dict[str, str] | None = None

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        """Produce a routing plan using deterministic heuristics.

        Iterates every net in the netlist, dispatches each via _dispatch,
        and builds a priority-ordered net list (diff pairs first, then
        power, then signal).

        Pure: calling twice with the same inputs returns equal results.
        """
        # Build diff pair membership set for fast lookup.
        diff_pair_nets: set[str] = set()
        for pos, neg in self.differential_pairs:
            diff_pair_nets.add(pos)
            diff_pair_nets.add(neg)

        # Build power net set from net_class_map.
        power_nets: set[str] = set()
        if self.net_class_map is not None:
            for net_name, cls in self.net_class_map.items():
                if cls == "Power":
                    power_nets.add(net_name)

        assignment: dict[str, RouterBackend] = {}
        for net_name, pins in netlist.items():
            is_diff = net_name in diff_pair_nets
            net_class = ""
            if self.net_class_map is not None:
                net_class = self.net_class_map.get(net_name, "")
            assignment[net_name] = self._dispatch(
                net_name,
                pins,
                board_state,
                is_diff_pair=is_diff,
                net_class=net_class,
            )

        priorities = sorted(
            netlist.keys(),
            key=lambda n: _priority_rank(
                n, netlist,
                diff_pair_nets=diff_pair_nets,
                power_nets=power_nets,
            ),
        )

        return RoutingStrategyResult(
            net_priorities=tuple(priorities),
            layer_hints={},
            keepouts=(),
            router_assignment=assignment,
            routing_notes="deterministic: Phase 99 baseline heuristics",
        )

    def _dispatch(
        self,
        net_name: str,
        pins: list[Pin],
        board_state: BoardState,
        *,
        is_diff_pair: bool = False,
        net_class: str = "",
    ) -> RouterBackend:
        """Choose a router backend for a single net.

        L2 correction: order matters — first match wins.
        Diff pair → power+zones → high pin → simple 2-pin → default.
        """
        # Order matters: first match wins. Diff pair → power+zones →
        # high pin → simple 2-pin → default.
        if is_diff_pair:
            return RouterBackend.ASTAR  # length matching is in-house

        if net_class == "Power" and board_state.has_zones:
            return RouterBackend.ASTAR  # Freerouting crashes on zone polygons

        if len(pins) > 10:
            return RouterBackend.FREEROUTING  # dense connectivity

        if len(pins) <= 2 and board_state.total_nets <= 20:
            return RouterBackend.FREEROUTING  # proven on smd_test_board

        return RouterBackend.ASTAR  # safe default
