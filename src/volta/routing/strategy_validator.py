"""Phase 98 Plan 02 R-4: StrategyValidator — semantic validation gate.

Validates model-emitted :class:`RoutingStrategyResult` against board state and
netlist before the orchestrator consumes it. Three categories:

1. Coordinate bounds — every keepout coordinate inside ``board_bounds`` and
   forms a positive-area rectangle.
2. Net existence — every net referenced in ``net_priorities``,
   ``router_assignment``, or ``layer_hints`` exists in the netlist; every net
   in the netlist has both a priority entry and a router_assignment entry.
3. Layer validity — every layer string in ``layer_hints`` and every
   ``keepout.layer`` is a valid copper layer for the board stackup (falls back
   to ``{F.Cu, B.Cu}`` when stackup metadata is unavailable).

This is the semantic complement to Phase 100's structural H4 gate
(:func:`RoutingOrchestrator._validate_strategy_result`). R-4 catches
domain-specific errors (coordinates, layers); H4 catches contract errors
(enum validity, net coverage). Defense in depth — the model output is
untrusted.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from volta.routing.strategy import (
    BoardState,
    Keepout,
    Pin,
    RoutingStrategyResult,
)

if TYPE_CHECKING:
    from volta.parser.pcb_native_types import NativeBoard

# Matches KiCad copper signal layer names: F.Cu, B.Cu, In1.Cu, In2.Cu, ...
_COPPER_LAYER_RE = re.compile(r"^(F|B|In\d+)\.Cu$")

# Default 2-layer fallback when board stackup metadata is unavailable.
_DEFAULT_COPPER_LAYERS: frozenset[str] = frozenset({"F.Cu", "B.Cu"})


class StrategyValidator:
    """R-4 semantic validation gate for :class:`RoutingStrategyResult`.

    The validator is stateless apart from the optional board reference used
    for layer-stackup lookups. Instantiating without a board restricts layer
    validation to the {F.Cu, B.Cu} 2-layer default — sufficient for unit
    tests that do not exercise multi-layer scenarios.

    Args:
        board: Optional :class:`NativeBoard` (or duck-typed equivalent with
            ``setup.stackup.layers`` and ``general.layers`` attributes) used
            to determine the valid copper layer set. ``None`` triggers the
            2-layer default.
    """

    def __init__(self, board=None) -> None:
        self._board = board

    def validate(
        self,
        result: RoutingStrategyResult,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> None:
        """Raise :class:`ValueError` on any invalid field.

        Returns ``None`` on success. Sub-validators run in a fixed order
        (keepout coordinates -> net references -> layer hints -> keepout
        layers) so the first violation surfaced is deterministic — useful
        for debugging model output.
        """
        self._validate_keepouts(result.keepouts, board_state.board_bounds)
        self._validate_net_references(result, netlist)
        valid_layers = self._extract_valid_copper_layers()
        self._validate_layer_hints(result.layer_hints, valid_layers)
        self._validate_keepout_layers(result.keepouts, valid_layers)

    # -- coordinate bounds ---------------------------------------------------

    @staticmethod
    def _validate_keepouts(
        keepouts: tuple[Keepout, ...],
        board_bounds: tuple[float, float, float, float],
    ) -> None:
        min_x, min_y, max_x, max_y = board_bounds
        for k in keepouts:
            # x range
            if not (min_x <= k.x1 <= max_x):
                raise ValueError(
                    f"keepout x1={k.x1} out of bounds "
                    f"[{min_x}, {max_x}]: {k}"
                )
            if not (min_x <= k.x2 <= max_x):
                raise ValueError(
                    f"keepout x2={k.x2} out of bounds "
                    f"[{min_x}, {max_x}]: {k}"
                )
            # y range
            if not (min_y <= k.y1 <= max_y):
                raise ValueError(
                    f"keepout y1={k.y1} out of bounds "
                    f"[{min_y}, {max_y}]: {k}"
                )
            if not (min_y <= k.y2 <= max_y):
                raise ValueError(
                    f"keepout y2={k.y2} out of bounds "
                    f"[{min_y}, {max_y}]: {k}"
                )
            # positive area
            if k.x1 >= k.x2:
                raise ValueError(
                    f"keepout has zero/negative x area (x1={k.x1} >= x2={k.x2}): {k}"
                )
            if k.y1 >= k.y2:
                raise ValueError(
                    f"keepout has zero/negative y area (y1={k.y1} >= y2={k.y2}): {k}"
                )

    # -- net references ------------------------------------------------------

    @staticmethod
    def _validate_net_references(
        result: RoutingStrategyResult,
        netlist: dict[str, list[Pin]],
    ) -> None:
        known = set(netlist.keys())

        for net in result.net_priorities:
            if net not in known:
                raise ValueError(
                    f"unknown net in net_priorities: {net!r} "
                    f"(not in netlist: {sorted(known)})"
                )

        for net in result.router_assignment:
            if net not in known:
                raise ValueError(
                    f"unknown net in router_assignment: {net!r} "
                    f"(not in netlist: {sorted(known)})"
                )

        for net in result.layer_hints:
            if net not in known:
                raise ValueError(
                    f"unknown net in layer_hints: {net!r} "
                    f"(not in netlist: {sorted(known)})"
                )

        # Every net in the netlist MUST have a router_assignment entry.
        missing_assignment = known - set(result.router_assignment.keys())
        if missing_assignment:
            raise ValueError(
                f"net(s) missing from router_assignment: "
                f"{sorted(missing_assignment)}"
            )

        # Every net in the netlist MUST appear in net_priorities (when the
        # netlist is non-empty). An empty priorities list with a non-empty
        # netlist is invalid — the orchestrator needs a routing order.
        if known:
            missing_priorities = known - set(result.net_priorities)
            if missing_priorities:
                raise ValueError(
                    f"net(s) missing from net_priorities: "
                    f"{sorted(missing_priorities)}"
                )

    # -- layer validity ------------------------------------------------------

    def _extract_valid_copper_layers(self) -> set[str]:
        """Return the set of valid copper layer names for this board.

        Preference order:
        1. Typed stackup (``board.setup.stackup.layers[*].type == 'copper'``)
        2. ``general.layers`` tuple filtered by ``_COPPER_LAYER_RE``
        3. ``{F.Cu, B.Cu}`` default if both are empty or board is None
        """
        if self._board is None:
            return set(_DEFAULT_COPPER_LAYERS)

        valid: set[str] = set()

        # 1. Typed stackup
        setup = getattr(self._board, "setup", None)
        stackup = getattr(setup, "stackup", None) if setup else None
        stackup_layers = getattr(stackup, "layers", None) if stackup else None
        if stackup_layers:
            for layer in stackup_layers:
                layer_type = getattr(layer, "type", "") or ""
                if layer_type == "copper":
                    name = getattr(layer, "name", "")
                    if name:
                        valid.add(str(name))

        # 2. Fall back to general.layers (regex-filtered)
        if not valid:
            general = getattr(self._board, "general", None)
            general_layers = getattr(general, "layers", None) if general else None
            if general_layers:
                for name in general_layers:
                    if _COPPER_LAYER_RE.match(str(name)):
                        valid.add(str(name))

        # 3. Final fallback: 2-layer default
        if not valid:
            return set(_DEFAULT_COPPER_LAYERS)

        return valid

    @staticmethod
    def _validate_layer_hints(
        layer_hints: dict[str, str],
        valid_layers: set[str],
    ) -> None:
        for net, layer in layer_hints.items():
            if layer not in valid_layers:
                raise ValueError(
                    f"invalid layer {layer!r} for net {net!r} "
                    f"(valid: {sorted(valid_layers)})"
                )

    @staticmethod
    def _validate_keepout_layers(
        keepouts: tuple[Keepout, ...],
        valid_layers: set[str],
    ) -> None:
        for k in keepouts:
            if k.layer not in valid_layers:
                raise ValueError(
                    f"invalid keepout layer {k.layer!r} "
                    f"(valid: {sorted(valid_layers)}): {k}"
                )
