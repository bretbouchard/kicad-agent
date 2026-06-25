"""Phase 100 R-2: Per-net dispatch heuristics tests.

5 dispatch cases + priority ordering (L1):
- diff pair → ASTAR
- power + zones → ASTAR
- high pin count (>10) → FREEROUTING
- simple 2-pin ≤20 nets → FREEROUTING
- default → ASTAR
- L1: diff pair wins over high pin count (priority ordering)

The dispatch order matters: first match wins.
"""

from __future__ import annotations

from kicad_agent.routing.strategy import (
    BoardState,
    DeterministicStrategy,
    Pin,
    RouterBackend,
)


def _pin(pad: str = "1", x: float = 0.0, y: float = 0.0) -> Pin:
    return Pin(footprint_ref="U1", pad_number=pad, x=x, y=y)


def _pins(n: int) -> list[Pin]:
    return [_pin(pad=str(i), x=float(i), y=float(i)) for i in range(1, n + 1)]


def _board_state(
    total_nets: int = 5,
    has_zones: bool = False,
    net_classes: tuple[str, ...] = ("Default",),
) -> BoardState:
    return BoardState(
        total_nets=total_nets,
        has_zones=has_zones,
        board_bounds=(0.0, 0.0, 100.0, 100.0),
        net_classes=net_classes,
    )


# ---------------------------------------------------------------------------
# 5 dispatch cases
# ---------------------------------------------------------------------------


class TestDiffPairDispatchesAstar:
    def test(self) -> None:
        # Diff pair net → ASTAR (length matching is in-house).
        ds = DeterministicStrategy(differential_pairs=(("USB+", "USB-"),))
        bs = _board_state()
        nl = {"USB+": _pins(2), "USB-": _pins(2)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["USB+"] == RouterBackend.ASTAR
        assert result.router_assignment["USB-"] == RouterBackend.ASTAR


class TestPowerWithZonesDispatchesAstar:
    def test(self) -> None:
        # Power net class + board has zones → ASTAR (Freerouting crashes on zones).
        ds = DeterministicStrategy(net_class_map={"VCC": "Power"})
        bs = _board_state(has_zones=True)
        nl = {"VCC": _pins(2)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["VCC"] == RouterBackend.ASTAR


class TestHighPinCountDispatchesFreerouting:
    def test(self) -> None:
        # >10 pins → FREEROUTING (dense connectivity).
        ds = DeterministicStrategy()
        bs = _board_state(total_nets=30)
        nl = {"BUS": _pins(12)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["BUS"] == RouterBackend.FREEROUTING


class TestSimpleTwoPinDispatchesFreerouting:
    def test(self) -> None:
        # ≤2 pins + total_nets ≤20 → FREEROUTING (proven on smd_test_board).
        ds = DeterministicStrategy()
        bs = _board_state(total_nets=10)
        nl = {"SIG": _pins(2)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["SIG"] == RouterBackend.FREEROUTING


class TestDefaultDispatchesAstar:
    def test(self) -> None:
        # None of the above match → ASTAR (safe default).
        # 4 pins, no zones, >20 nets total: not diff pair, not power+zones,
        # not high pin (>10), not simple 2-pin ≤20 nets.
        ds = DeterministicStrategy()
        bs = _board_state(total_nets=30, has_zones=False)
        nl = {"SIG": _pins(4)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["SIG"] == RouterBackend.ASTAR


# ---------------------------------------------------------------------------
# L1: Priority ordering (first match wins)
# ---------------------------------------------------------------------------


class TestDiffPairWinsOverHighPinCount:
    def test(self) -> None:
        # L1: diff pair check is FIRST in dispatch order. A diff pair net
        # with 12 pins (>10) must still dispatch to ASTAR, not FREEROUTING.
        ds = DeterministicStrategy(differential_pairs=(("CLK+", "CLK-"),))
        bs = _board_state(total_nets=30)
        nl = {"CLK+": _pins(12), "CLK-": _pins(12)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["CLK+"] == RouterBackend.ASTAR
        assert result.router_assignment["CLK-"] == RouterBackend.ASTAR


class TestSimpleTwoPinExcludedWhenManyNets:
    def test(self) -> None:
        # 2-pin net on board with >20 nets does NOT match simple-2-pin rule
        # (total_nets ≤20 condition fails). Falls through to default ASTAR.
        ds = DeterministicStrategy()
        bs = _board_state(total_nets=25)
        nl = {"SIG": _pins(2)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["SIG"] == RouterBackend.ASTAR


class TestPowerWithoutZonesFallsThrough:
    def test(self) -> None:
        # Power net but NO zones → power+zones rule does not match.
        # 2-pin, ≤20 nets → simple-2-pin rule catches it → FREEROUTING.
        ds = DeterministicStrategy(net_class_map={"VCC": "Power"})
        bs = _board_state(total_nets=10, has_zones=False)
        nl = {"VCC": _pins(2)}
        result = ds.strategize(bs, nl)
        assert result.router_assignment["VCC"] == RouterBackend.FREEROUTING
