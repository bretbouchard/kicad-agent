"""Phase 100 CR-01: NativeBoard immutability regression suite.

Closes the §7.7-deferred CR-01 critical finding from Phase 99 Council Exec
Review. All 14 NativeBoard dataclasses must be frozen; mutation must go
through dataclasses.replace().
"""

import dataclasses
from types import MappingProxyType

import pytest

from volta.parser.pcb_native_types import (
    NativeBoard,
    NativeBoardOutline,
    NativeFootprint,
    NativeGeneral,
    NativeGraphicItem,
    NativeNet,
    NativeNetClass,
    NativePad,
    NativeSegment,
    NativeSetup,
    NativeStackup,
    NativeStackupLayer,
    NativeVia,
    NativeZone,
)

_FROZEN_CLASSES = [
    NativeNet,
    NativeNetClass,
    NativePad,
    NativeFootprint,
    NativeSegment,
    NativeVia,
    NativeGraphicItem,
    NativeZone,
    NativeBoardOutline,
    NativeGeneral,
    NativeStackupLayer,
    NativeStackup,
    NativeSetup,
    NativeBoard,
]


def test_all_native_dataclasses_frozen() -> None:
    """All 14 NativeBoard dataclasses must be declared frozen."""
    for cls in _FROZEN_CLASSES:
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} is not a dataclass"
        assert cls.__dataclass_params__.frozen is True, (
            f"{cls.__name__} is not frozen — must use @dataclass(frozen=True)"
        )


def test_frozen_assignment_raises() -> None:
    """Direct attribute assignment must raise FrozenInstanceError."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        NativePad().net_name = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        NativeNet().name = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        NativeBoard().version = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        NativeFootprint().lib_id = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        NativeZone().layer = "x"


def test_list_fields_are_tuples() -> None:
    """Collection-typed fields must default to tuple, not list."""
    assert isinstance(NativeBoard().nets, tuple)
    assert isinstance(NativeBoard().footprints, tuple)
    assert isinstance(NativeBoard().segments, tuple)
    assert isinstance(NativeBoard().vias, tuple)
    assert isinstance(NativeBoard().zones, tuple)
    assert isinstance(NativeBoard().net_classes, tuple)
    assert isinstance(NativeBoard().graphic_items, tuple)
    assert isinstance(NativeFootprint().pads, tuple)
    assert isinstance(NativeFootprint().graphic_items, tuple)
    assert isinstance(NativeZone().polygon_points, tuple)
    assert isinstance(NativeZone().layers, tuple)
    assert isinstance(NativeBoardOutline().items, tuple)
    assert isinstance(NativeGeneral().layers, tuple)
    assert isinstance(NativeStackup().layers, tuple)
    assert isinstance(NativeNetClass().add_nets, tuple)


def test_properties_is_readonly_view() -> None:
    """NativeFootprint.properties returns a read-only dict-like view.

    Readers (fp.properties.get("Reference")) work unchanged.
    Writers (fp.properties["x"] = "y") raise TypeError.
    """
    fp = NativeFootprint()
    # Read access works (returns a dict-like view)
    assert fp.properties.get("Reference") is None
    # Mutation must fail loudly
    with pytest.raises(TypeError):
        fp.properties["x"] = "y"


def test_replace_works() -> None:
    """dataclasses.replace produces a new instance with updated field."""
    pad = NativePad(number="1")
    new_pad = dataclasses.replace(pad, net_name="GND")
    assert new_pad.net_name == "GND"
    assert new_pad.number == "1"
    assert pad.net_name == ""  # original unchanged
    assert pad is not new_pad  # new object


def test_kiutils_compat_properties_preserved() -> None:
    """Kiutils-compatible list-returning properties still return lists."""
    board = NativeBoard()
    assert isinstance(board.graphicItems, list)
    assert isinstance(board.traceItems, list)
    assert isinstance(board.layers, list)


# ---------------------------------------------------------------------------
# Task 2 tests: PcbIR mutation methods use replace, not in-place mutation
# ---------------------------------------------------------------------------


def test_add_net_uses_replace() -> None:
    """PcbIR.add_net must build a new NativeBoard via dataclasses.replace."""
    from volta.ir.pcb_ir import PcbIR

    board = NativeBoard()
    ir = PcbIR.from_native(board)
    original_id = id(ir._native_board)

    ir.add_net(net_name="GND", net_number=5)

    assert ir._native_board is not None
    # Identity must change — proves a new object was built, not in-place append
    assert id(ir._native_board) != original_id, (
        "add_net mutated in place — must use dataclasses.replace"
    )
    names = [n.name for n in ir.board.nets]
    assert "GND" in names


def test_remove_net_rebuilds_immutably() -> None:
    """PcbIR.remove_net must rebuild footprints/pads/nets via replace."""
    from volta.ir.pcb_ir import PcbIR

    pad_vcc = NativePad(number="1", net_name="VCC", net_number=1)
    pad_gnd = NativePad(number="2", net_name="GND", net_number=2)
    fp = NativeFootprint(
        lib_id="Device:R",
        pads=(pad_vcc, pad_gnd),
    )
    board = NativeBoard(
        nets=(
            NativeNet(number=1, name="VCC"),
            NativeNet(number=2, name="GND"),
        ),
        footprints=(fp,),
    )
    ir = PcbIR.from_native(board)
    original_id = id(ir._native_board)

    ir.remove_net("VCC")

    assert id(ir._native_board) != original_id, (
        "remove_net mutated in place — must use dataclasses.replace"
    )
    # No pad has VCC anymore
    for fp_cur in ir.board.footprints:
        for pad in fp_cur.pads:
            assert pad.net_name != "VCC"
    # VCC net removed
    names = [n.name for n in ir.board.nets]
    assert "VCC" not in names
    # GND preserved
    assert "GND" in names
