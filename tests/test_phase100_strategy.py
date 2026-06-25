"""Phase 100 R-1: RoutingStrategy Protocol + DeterministicStrategy tests.

Covers:
- RouterBackend enum (exactly 2 variants: ASTAR, FREEROUTING — H1 correction)
- BoardState frozen dataclass (NO layer_count field — H3 correction)
- RoutingStrategyResult frozen dataclass
- RoutingStrategy Protocol (structural typing via hasattr)
- DeterministicStrategy implements Protocol, returns RoutingStrategyResult
- DeterministicStrategy is pure (same inputs → equal outputs)
- DeterministicStrategy fields (M3): differential_pairs, net_class_map
"""

from __future__ import annotations

import dataclasses
import logging

import pytest

from kicad_agent.routing.strategy import (
    BoardState,
    DeterministicStrategy,
    Keepout,
    Pin,
    RouterBackend,
    RoutingStrategy,
    RoutingStrategyResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_board_state(
    *,
    total_nets: int = 5,
    has_zones: bool = False,
    board_bounds: tuple[float, float, float, float] = (0.0, 0.0, 50.0, 50.0),
    net_classes: tuple[str, ...] = ("Default",),
) -> BoardState:
    return BoardState(
        total_nets=total_nets,
        has_zones=has_zones,
        board_bounds=board_bounds,
        net_classes=net_classes,
    )


def _make_pin(ref: str = "R1", pad: str = "1", x: float = 10.0, y: float = 10.0) -> Pin:
    return Pin(footprint_ref=ref, pad_number=pad, x=x, y=y)


def _make_netlist(**nets: int) -> dict[str, list[Pin]]:
    """Build a netlist where each kwarg is net_name=pin_count."""
    out: dict[str, list[Pin]] = {}
    for name, count in nets.items():
        out[name] = [_make_pin(pad=str(i), x=float(i * 5), y=float(i * 5)) for i in range(count)]
    return out


# ---------------------------------------------------------------------------
# RouterBackend enum (H1: exactly 2 variants)
# ---------------------------------------------------------------------------


class TestRouterBackend:
    def test_astar_value(self) -> None:
        assert RouterBackend.ASTAR == "astar"
        assert RouterBackend.ASTAR.value == "astar"

    def test_freerouting_value(self) -> None:
        assert RouterBackend.FREEROUTING == "freerouting"
        assert RouterBackend.FREEROUTING.value == "freerouting"

    def test_exactly_two_members(self) -> None:
        # H1 correction: MULTI_PASS removed. Exactly 2 variants.
        members = list(RouterBackend)
        assert len(members) == 2
        assert set(members) == {RouterBackend.ASTAR, RouterBackend.FREEROUTING}

    def test_no_multi_pass_member(self) -> None:
        # H1: guard against re-introduction.
        assert not hasattr(RouterBackend, "MULTI_PASS")


# ---------------------------------------------------------------------------
# BoardState (H3: NO layer_count)
# ---------------------------------------------------------------------------


class TestBoardState:
    def test_is_frozen(self) -> None:
        bs = _make_board_state()
        with pytest.raises(dataclasses.FrozenInstanceError):
            bs.total_nets = 99  # type: ignore[misc]

    def test_no_layer_count_field(self) -> None:
        # H3 correction: layer_count removed (dead field).
        field_names = {f.name for f in dataclasses.fields(BoardState)}
        assert "layer_count" not in field_names

    def test_fields_present(self) -> None:
        field_names = {f.name for f in dataclasses.fields(BoardState)}
        assert field_names == {"total_nets", "has_zones", "board_bounds", "net_classes"}


# ---------------------------------------------------------------------------
# RoutingStrategyResult
# ---------------------------------------------------------------------------


class TestRoutingStrategyResult:
    def test_is_frozen(self) -> None:
        r = RoutingStrategyResult(
            net_priorities=("VCC",),
            layer_hints={},
            keepouts=(),
            router_assignment={"VCC": RouterBackend.ASTAR},
            routing_notes="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.routing_notes = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RoutingStrategy Protocol
# ---------------------------------------------------------------------------


class TestRoutingStrategyProtocol:
    def test_strategize_method_exists_on_protocol(self) -> None:
        # Protocol classes expose their methods via __protocol_attrs__ or
        # direct attribute access. get_type_hints returns only annotated
        # fields, not methods, so we check method presence directly.
        assert hasattr(RoutingStrategy, "strategize")
        assert callable(getattr(RoutingStrategy, "strategize", None))

    def test_deterministic_strategy_satisfies_protocol(self) -> None:
        # Structural typing: Protocol satisfaction checked via hasattr.
        ds = DeterministicStrategy()
        assert hasattr(ds, "strategize")
        assert callable(ds.strategize)


# ---------------------------------------------------------------------------
# DeterministicStrategy
# ---------------------------------------------------------------------------


class TestDeterministicStrategy:
    def test_returns_routing_strategy_result(self) -> None:
        ds = DeterministicStrategy()
        bs = _make_board_state(total_nets=3)
        nl = _make_netlist(VCC=2, GND=2, SIG=2)
        result = ds.strategize(bs, nl)
        assert isinstance(result, RoutingStrategyResult)

    def test_router_assignment_non_empty(self) -> None:
        ds = DeterministicStrategy()
        bs = _make_board_state(total_nets=3)
        nl = _make_netlist(VCC=2, GND=2, SIG=2)
        result = ds.strategize(bs, nl)
        assert len(result.router_assignment) == 3
        for net in ("VCC", "GND", "SIG"):
            assert net in result.router_assignment
            assert isinstance(result.router_assignment[net], RouterBackend)

    def test_is_pure(self) -> None:
        # Same inputs → equal outputs (no side effects).
        ds = DeterministicStrategy()
        bs = _make_board_state(total_nets=2)
        nl = _make_netlist(VCC=2, GND=2)
        r1 = ds.strategize(bs, nl)
        r2 = ds.strategize(bs, nl)
        assert r1 == r2
        assert r1.router_assignment == r2.router_assignment

    def test_routing_notes_mentions_deterministic(self) -> None:
        ds = DeterministicStrategy()
        bs = _make_board_state()
        nl = _make_netlist(VCC=2)
        result = ds.strategize(bs, nl)
        assert "deterministic" in result.routing_notes.lower()

    def test_fields_differential_pairs_default(self) -> None:
        # M3: differential_pairs field with empty tuple default.
        ds = DeterministicStrategy()
        assert ds.differential_pairs == ()

    def test_fields_net_class_map_default(self) -> None:
        # M3: net_class_map field with None default.
        ds = DeterministicStrategy()
        assert ds.net_class_map is None

    def test_fields_custom_construction(self) -> None:
        # M3: fields settable at construction time.
        ds = DeterministicStrategy(
            differential_pairs=(("USB+", "USB-"),),
            net_class_map={"VCC": "Power"},
        )
        assert ds.differential_pairs == (("USB+", "USB-"),)
        assert ds.net_class_map == {"VCC": "Power"}

    def test_is_frozen(self) -> None:
        ds = DeterministicStrategy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ds.differential_pairs = (("A", "B"),)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Keepout frozen dataclass
# ---------------------------------------------------------------------------


class TestKeepout:
    def test_is_frozen(self) -> None:
        k = Keepout(x1=0.0, y1=0.0, x2=10.0, y2=10.0, layer="F.Cu", reason="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            k.layer = "B.Cu"  # type: ignore[misc]

    def test_fields(self) -> None:
        field_names = {f.name for f in dataclasses.fields(Keepout)}
        assert field_names == {"x1", "y1", "x2", "y2", "layer", "reason"}


# ---------------------------------------------------------------------------
# Pin frozen dataclass
# ---------------------------------------------------------------------------


class TestPin:
    def test_is_frozen(self) -> None:
        p = _make_pin()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.x = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LO-05: DeterministicStrategy must not emit noisy warnings during population
# ---------------------------------------------------------------------------


class TestDeterministicStrategyNoWarningsOnPopulation:
    """LO-05: When DeterministicStrategy builds dispatch from board state, it
    must NOT log warnings for every populated net_class_map entry or
    differential_pair. Normal population is expected behavior, not a warning
    condition.

    Acceptance: caplog captures zero WARNING (or higher) records emitted by
    the strategy module during strategize() with a populated net_class_map
    and differential_pairs.
    """

    def test_deterministic_strategy_no_warnings_on_normal_population(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        ds = DeterministicStrategy(
            differential_pairs=(("USB+", "USB-"), ("CLK+", "CLK-")),
            net_class_map={
                "VCC": "Power",
                "GND": "Power",
                "USB+": "Signal",
                "USB-": "Signal",
                "CLK+": "Signal",
                "CLK-": "Signal",
            },
        )
        bs = _make_board_state(total_nets=6, has_zones=True)
        nl = _make_netlist(VCC=3, GND=3, USB=2, USBb=2, CLK=2, CLKb=2)
        # Rename to match the diff pair net names.
        nl.clear()
        nl["VCC"] = [_make_pin(pad=str(i), x=float(i * 5), y=float(i * 5)) for i in range(3)]
        nl["GND"] = [_make_pin(pad=str(i), x=float(i * 5), y=float(i * 5)) for i in range(3)]
        nl["USB+"] = [_make_pin(pad="1"), _make_pin(pad="2", x=15.0)]
        nl["USB-"] = [_make_pin(pad="1", x=20.0), _make_pin(pad="2", x=25.0)]
        nl["CLK+"] = [_make_pin(pad="1", x=30.0), _make_pin(pad="2", x=35.0)]
        nl["CLK-"] = [_make_pin(pad="1", x=40.0), _make_pin(pad="2", x=45.0)]

        with caplog.at_level(logging.WARNING, logger="kicad_agent.routing.strategy"):
            result = ds.strategize(bs, nl)

        # LO-05 acceptance: zero WARNING records from strategy module.
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and r.name == "kicad_agent.routing.strategy"
        ]
        assert len(warning_records) == 0, (
            f"DeterministicStrategy emitted {len(warning_records)} WARNING(s) "
            f"during normal population (LO-05 violation): "
            f"{[r.getMessage() for r in warning_records]}"
        )
        # Sanity: the strategy still produced a valid result.
        assert isinstance(result, RoutingStrategyResult)
        assert len(result.router_assignment) == 6
