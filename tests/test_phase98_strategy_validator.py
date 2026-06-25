"""Phase 98 Plan 02 Task 1: StrategyValidator (R-4) tests.

Validates the R-4 semantic gate. Three categories:
1. Coordinate bounds — keepouts inside board_bounds
2. Net existence — all referenced nets present in netlist
3. Layer validity — layer hints/keepouts match board stackup

Plus SC-4: synthetic invalid rejection (batch of 10 must all raise).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kicad_agent.routing.strategy import (
    BoardState,
    Keepout,
    Pin,
    RouterBackend,
    RoutingStrategyResult,
)
from kicad_agent.routing.strategy_validator import StrategyValidator


# --- Helpers -----------------------------------------------------------------


def _board_state(
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 100.0, 80.0),
    total_nets: int = 3,
) -> BoardState:
    return BoardState(
        total_nets=total_nets,
        has_zones=False,
        board_bounds=bounds,
        net_classes=("Power", "Signal"),
    )


def _netlist() -> dict[str, list[Pin]]:
    return {
        "GND": [Pin("U1", "1", 10.0, 10.0)],
        "VCC": [Pin("U1", "2", 20.0, 20.0)],
        "N1": [Pin("U1", "3", 30.0, 30.0)],
    }


def _make_result(
    *,
    net_priorities=("GND", "VCC", "N1"),
    layer_hints: dict | None = None,
    keepouts: tuple[Keepout, ...] = (),
    router_assignment: dict | None = None,
    routing_notes: str = "",
) -> RoutingStrategyResult:
    if router_assignment is None:
        router_assignment = {
            "GND": RouterBackend.ASTAR,
            "VCC": RouterBackend.ASTAR,
            "N1": RouterBackend.ASTAR,
        }
    if layer_hints is None:
        layer_hints = {}
    return RoutingStrategyResult(
        net_priorities=net_priorities,
        layer_hints=dict(layer_hints),
        keepouts=keepouts,
        router_assignment=dict(router_assignment),
        routing_notes=routing_notes,
    )


@dataclass
class _FakeStackupLayer:
    name: str
    type: str


@dataclass
class _FakeStackup:
    layers: tuple


@dataclass
class _FakeSetup:
    stackup: _FakeStackup | None = None


@dataclass
class _FakeGeneral:
    layers: tuple = ()


@dataclass
class _FakeBoard:
    general: _FakeGeneral = None
    setup: _FakeSetup | None = None

    def __post_init__(self):
        if self.general is None:
            self.general = _FakeGeneral()


def _two_layer_board() -> _FakeBoard:
    """2-layer board: F.Cu, B.Cu (via general.layers, no typed stackup)."""
    return _FakeBoard(
        general=_FakeGeneral(layers=("F.Cu", "B.Cu")),
        setup=_FakeSetup(stackup=None),
    )


def _four_layer_typed_board() -> _FakeBoard:
    """4-layer board with typed stackup (copper + dielectric)."""
    return _FakeBoard(
        general=_FakeGeneral(
            layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
        ),
        setup=_FakeSetup(
            stackup=_FakeStackup(
                layers=(
                    _FakeStackupLayer("F.Cu", "copper"),
                    _FakeStackupLayer("dielectric 1", "core"),
                    _FakeStackupLayer("In1.Cu", "copper"),
                    _FakeStackupLayer("dielectric 2", "core"),
                    _FakeStackupLayer("In2.Cu", "copper"),
                    _FakeStackupLayer("dielectric 3", "core"),
                    _FakeStackupLayer("B.Cu", "copper"),
                )
            )
        ),
    )


def _empty_stackup_board() -> _FakeBoard:
    """Board with no stackup info — triggers {F.Cu, B.Cu} default."""
    return _FakeBoard(
        general=_FakeGeneral(layers=()),
        setup=_FakeSetup(stackup=None),
    )


# --- TestCategoryCoordinateBounds -------------------------------------------


class TestCategoryCoordinateBounds:
    def test_keepout_inside_bounds_no_raise(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(10.0, 10.0, 50.0, 50.0, "F.Cu", "ok"),),
        )
        v.validate(result, _board_state(), _netlist())  # no raise

    def test_x1_below_min_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(-1.0, 10.0, 50.0, 50.0, "F.Cu", "x"),),
        )
        with pytest.raises(ValueError, match="x"):
            v.validate(result, _board_state(), _netlist())

    def test_x2_above_max_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(10.0, 10.0, 101.0, 50.0, "F.Cu", "x"),),
        )
        with pytest.raises(ValueError, match="x"):
            v.validate(result, _board_state(), _netlist())

    def test_y1_below_min_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(10.0, -1.0, 50.0, 50.0, "F.Cu", "x"),),
        )
        with pytest.raises(ValueError, match="y"):
            v.validate(result, _board_state(), _netlist())

    def test_y2_above_max_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(10.0, 10.0, 50.0, 81.0, "F.Cu", "x"),),
        )
        with pytest.raises(ValueError, match="y"):
            v.validate(result, _board_state(), _netlist())

    def test_x1_gte_x2_zero_area_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(50.0, 10.0, 50.0, 50.0, "F.Cu", "x"),),
        )
        with pytest.raises(ValueError, match="area"):
            v.validate(result, _board_state(), _netlist())

    def test_y1_gte_y2_zero_area_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(10.0, 50.0, 50.0, 50.0, "F.Cu", "x"),),
        )
        with pytest.raises(ValueError, match="area"):
            v.validate(result, _board_state(), _netlist())

    def test_boundary_edge_no_raise(self) -> None:
        # Keepout exactly on min boundary — should pass.
        v = StrategyValidator()
        result = _make_result(
            keepouts=(Keepout(0.0, 0.0, 100.0, 80.0, "F.Cu", "full board"),),
        )
        v.validate(result, _board_state(), _netlist())  # no raise


# --- TestCategoryNetValidation ----------------------------------------------


class TestCategoryNetValidation:
    def test_all_nets_known_no_raise(self) -> None:
        v = StrategyValidator()
        v.validate(_make_result(), _board_state(), _netlist())  # no raise

    def test_unknown_net_in_priorities_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(net_priorities=("GND", "PHANTOM"))
        with pytest.raises(ValueError, match="priorities"):
            v.validate(result, _board_state(), _netlist())

    def test_unknown_net_in_router_assignment_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            router_assignment={
                "GND": RouterBackend.ASTAR,
                "VCC": RouterBackend.ASTAR,
                "N1": RouterBackend.ASTAR,
                "GHOST": RouterBackend.ASTAR,
            },
        )
        with pytest.raises(ValueError, match="router_assignment"):
            v.validate(result, _board_state(), _netlist())

    def test_unknown_net_in_layer_hints_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(layer_hints={"GHOST": "F.Cu"})
        with pytest.raises(ValueError, match="layer_hints"):
            v.validate(result, _board_state(), _netlist())

    def test_net_missing_from_router_assignment_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(
            router_assignment={
                "GND": RouterBackend.ASTAR,
                "VCC": RouterBackend.ASTAR,
                # N1 missing
            },
            # net_priorities still complete so we hit the assignment check first
        )
        with pytest.raises(ValueError, match="router_assignment"):
            v.validate(result, _board_state(), _netlist())

    def test_net_missing_from_priorities_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(net_priorities=("GND", "VCC"))
        with pytest.raises(ValueError, match="priorities"):
            v.validate(result, _board_state(), _netlist())


# --- TestCategoryLayerValidation --------------------------------------------


class TestCategoryLayerValidation:
    def test_valid_fc_on_two_layer_no_raise(self) -> None:
        v = StrategyValidator(board=_two_layer_board())
        result = _make_result(layer_hints={"GND": "F.Cu"})
        v.validate(result, _board_state(), _netlist())  # no raise

    def test_in3_cu_on_two_layer_raises(self) -> None:
        v = StrategyValidator(board=_two_layer_board())
        result = _make_result(layer_hints={"GND": "In3.Cu"})
        with pytest.raises(ValueError, match="layer"):
            v.validate(result, _board_state(), _netlist())

    def test_in1_cu_on_four_layer_no_raise(self) -> None:
        v = StrategyValidator(board=_four_layer_typed_board())
        result = _make_result(layer_hints={"GND": "In1.Cu"})
        v.validate(result, _board_state(), _netlist())  # no raise

    def test_magic_layer_invalid_name_raises(self) -> None:
        v = StrategyValidator(board=_two_layer_board())
        result = _make_result(layer_hints={"GND": "MagicLayer"})
        with pytest.raises(ValueError, match="layer"):
            v.validate(result, _board_state(), _netlist())

    def test_no_stackup_falls_back_to_default_fc_passes_in1_fails(self) -> None:
        v = StrategyValidator(board=_empty_stackup_board())
        # F.Cu passes (default 2-layer)
        result_fc = _make_result(layer_hints={"GND": "F.Cu"})
        v.validate(result_fc, _board_state(), _netlist())  # no raise
        # In1.Cu fails (default 2-layer does not include inner layers)
        result_in1 = _make_result(layer_hints={"GND": "In1.Cu"})
        with pytest.raises(ValueError, match="layer"):
            v.validate(result_in1, _board_state(), _netlist())

    def test_keepout_invalid_layer_raises(self) -> None:
        v = StrategyValidator(board=_two_layer_board())
        result = _make_result(
            keepouts=(Keepout(10.0, 10.0, 50.0, 50.0, "In3.Cu", "bad"),),
        )
        with pytest.raises(ValueError, match="layer"):
            v.validate(result, _board_state(), _netlist())


# --- TestCategorySyntheticInvalid (SC-4) ------------------------------------


def _synthetic_invalid_results() -> list[tuple[RoutingStrategyResult, str]]:
    """Return 10 deliberately-invalid RoutingStrategyResults.

    Each has at least one violation. Per SC-4 the validator must reject 100%.
    """
    bs = _board_state()
    nl = _netlist()
    out: list[tuple[RoutingStrategyResult, str]] = []

    # 1: out-of-bounds x
    out.append((
        _make_result(keepouts=(Keepout(-5.0, 0.0, 50.0, 50.0, "F.Cu", "x"),)),
        "oob-x",
    ))
    # 2: out-of-bounds y2
    out.append((
        _make_result(keepouts=(Keepout(0.0, 0.0, 50.0, 999.0, "F.Cu", "x"),)),
        "oob-y2",
    ))
    # 3: zero area
    out.append((
        _make_result(keepouts=(Keepout(10.0, 10.0, 10.0, 50.0, "F.Cu", "x"),)),
        "zero-area",
    ))
    # 4: unknown net in priorities
    out.append((
        _make_result(net_priorities=("GND", "VCC", "PHANTOM")),
        "unknown-priority",
    ))
    # 5: unknown net in router_assignment
    out.append((
        _make_result(
            router_assignment={
                "GND": RouterBackend.ASTAR,
                "VCC": RouterBackend.ASTAR,
                "N1": RouterBackend.ASTAR,
                "GHOST": RouterBackend.ASTAR,
            },
        ),
        "unknown-assignment",
    ))
    # 6: net missing from priorities
    out.append((
        _make_result(net_priorities=("GND", "VCC")),
        "missing-priority",
    ))
    # 7: net missing from router_assignment
    out.append((
        _make_result(
            router_assignment={
                "GND": RouterBackend.ASTAR,
                "VCC": RouterBackend.ASTAR,
            },
        ),
        "missing-assignment",
    ))
    # 8: invalid layer hint (In3.Cu on 2-layer)
    out.append((
        _make_result(layer_hints={"GND": "In3.Cu"}),
        "invalid-layer-hint",
    ))
    # 9: invalid keepout layer
    out.append((
        _make_result(
            keepouts=(Keepout(10.0, 10.0, 50.0, 50.0, "MagicLayer", "x"),),
        ),
        "invalid-keepout-layer",
    ))
    # 10: unknown net in layer_hints
    out.append((
        _make_result(layer_hints={"GHOST": "F.Cu"}),
        "unknown-layer-hint-net",
    ))
    assert len(out) == 10
    return out


class TestCategorySyntheticInvalid:
    def test_all_ten_synthetic_invalid_raise(self) -> None:
        v = StrategyValidator(board=_two_layer_board())
        bs = _board_state()
        nl = _netlist()
        cases = _synthetic_invalid_results()
        raises = 0
        for result, label in cases:
            with pytest.raises(ValueError):
                v.validate(result, bs, nl)
            raises += 1
        assert raises == 10

    def test_empty_keepouts_no_raise(self) -> None:
        v = StrategyValidator()
        result = _make_result(keepouts=())
        v.validate(result, _board_state(), _netlist())  # no raise

    def test_empty_layer_hints_no_raise(self) -> None:
        v = StrategyValidator()
        result = _make_result(layer_hints={})
        v.validate(result, _board_state(), _netlist())  # no raise

    def test_empty_priorities_with_nonempty_netlist_raises(self) -> None:
        v = StrategyValidator()
        result = _make_result(net_priorities=())
        with pytest.raises(ValueError, match="priorities"):
            v.validate(result, _board_state(), _netlist())
