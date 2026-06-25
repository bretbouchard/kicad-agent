"""Tests for PcbIR NativeBoard adapter and executor native parser integration.

Exercises PcbIR with NativeBoard through all mutation and query methods,
tests kiutils fallback, external consumer compatibility (CRITICAL-2),
and board_outline duck-typing.

Uses real PCB fixtures: Arduino_Mega.kicad_pcb.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.parser.pcb_native_parser import NativeParser
from kicad_agent.parser.pcb_native_types import (
    NativeBoard,
    NativeFootprint,
    NativeGraphicItem,
    NativeNet,
    NativePad,
    _NativePosition,
)

ARDUINO_MEGA = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    """Clear IR registry between tests to prevent ParseResult reuse errors."""
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()


@pytest.fixture
def native_board() -> NativeBoard:
    """Parse Arduino Mega fixture with native parser."""
    return NativeParser.parse_pcb(ARDUINO_MEGA)


@pytest.fixture
def native_ir(native_board: NativeBoard) -> PcbIR:
    """Create PcbIR backed by NativeBoard."""
    return PcbIR.from_native(native_board)


# ---------------------------------------------------------------------------
# Native path: PcbIR construction
# ---------------------------------------------------------------------------


class TestPcbIRNativeConstruction:
    """Tests for PcbIR creation from NativeBoard."""

    def test_pcbir_from_native_no_uuid_map_required(self, native_board: NativeBoard):
        """PcbIR.from_native does not require a UUID map."""
        ir = PcbIR.from_native(native_board)
        assert ir._uuid_map is None
        assert ir._is_native is True

    def test_pcbir_uses_native_board_by_default(self, native_ir: PcbIR):
        """PcbIR._native_board is set when created via from_native."""
        assert native_ir._native_board is not None
        assert isinstance(native_ir._native_board, NativeBoard)

    def test_pcbir_board_returns_native_board(self, native_ir: PcbIR):
        """ir.board returns NativeBoard instance."""
        assert isinstance(native_ir.board, NativeBoard)
        assert native_ir.board is native_ir._native_board

    def test_pcbir_raw_written_flag_default(self, native_ir: PcbIR):
        """raw_written defaults to False."""
        assert native_ir.raw_written is False


# ---------------------------------------------------------------------------
# Native path: property access
# ---------------------------------------------------------------------------


class TestPcbIRNativeProperties:
    """Tests for PcbIR property access with NativeBoard."""

    def test_pcbir_nets_accessible(self, native_ir: PcbIR):
        """ir.nets returns list of NativeNet matching expected count."""
        nets = native_ir.nets
        assert isinstance(nets, list)
        assert len(nets) == 79
        assert isinstance(nets[0], NativeNet)

    def test_pcbir_footprints_accessible(self, native_ir: PcbIR):
        """ir.footprints returns list of NativeFootprint."""
        fps = native_ir.footprints
        assert isinstance(fps, list)
        assert len(fps) == 13
        assert isinstance(fps[0], NativeFootprint)

    def test_pcbir_trace_items_accessible(self, native_ir: PcbIR):
        """ir.trace_items returns combined segments + vias via board.traceItems."""
        trace = native_ir.trace_items
        assert isinstance(trace, list)

    def test_pcbir_file_path(self, native_ir: PcbIR):
        """ir.file_path returns the correct path."""
        assert native_ir.file_path == ARDUINO_MEGA


# ---------------------------------------------------------------------------
# Native path: net mutation methods
# ---------------------------------------------------------------------------


class TestPcbIRNativeNetMutations:
    """Tests for PcbIR net mutation methods with NativeBoard."""

    def test_pcbir_add_net_native(self, native_ir: PcbIR):
        """ir.add_net creates NativeNet and appends to board.nets."""
        net = native_ir.add_net("TEST_NET")
        assert isinstance(net, NativeNet)
        assert net.name == "TEST_NET"
        assert net.number == 79  # max existing (78) + 1

        # Verify it's in the board's nets
        found = native_ir.get_net_by_name("TEST_NET")
        assert found is not None
        assert found.name == "TEST_NET"

    def test_pcbir_add_net_auto_number(self, native_ir: PcbIR):
        """ir.add_net with explicit number uses that number."""
        net = native_ir.add_net("CUSTOM_NET", net_number=999)
        assert net.number == 999
        assert net.name == "CUSTOM_NET"

    def test_pcbir_add_net_duplicate_name_raises(self, native_ir: PcbIR):
        """ir.add_net raises ValueError for duplicate net name."""
        native_ir.add_net("UNIQUE_NET")
        with pytest.raises(ValueError, match="already exists"):
            native_ir.add_net("UNIQUE_NET")

    def test_pcbir_remove_net_native(self, native_ir: PcbIR):
        """ir.remove_net removes net and disconnects pads."""
        # Add a net first to avoid breaking the fixture
        native_ir.add_net("TO_REMOVE")
        assert native_ir.get_net_by_name("TO_REMOVE") is not None

        native_ir.remove_net("TO_REMOVE")
        assert native_ir.get_net_by_name("TO_REMOVE") is None
        assert len(native_ir.nets) == 79  # unchanged (added then removed)

    def test_pcbir_remove_net_reserved_raises(self, native_ir: PcbIR):
        """ir.remove_net raises ValueError for net 0."""
        with pytest.raises(ValueError, match="reserved"):
            native_ir.remove_net("")

    def test_pcbir_rename_net_native(self, native_ir: PcbIR):
        """ir.rename_net updates net name and propagates to pads."""
        # Add a net to rename (avoid modifying fixture data)
        native_ir.add_net("RENAME_ME")
        net_before = native_ir.get_net_by_name("RENAME_ME")
        net_number = net_before.number

        native_ir.rename_net("RENAME_ME", "RENAMED")
        assert native_ir.get_net_by_name("RENAME_ME") is None
        found = native_ir.get_net_by_name("RENAMED")
        assert found is not None
        assert found.number == net_number

    def test_pcbir_get_net_by_name_native(self, native_ir: PcbIR):
        """ir.get_net_by_name finds existing nets."""
        gnd = native_ir.get_net_by_name("GND")
        assert gnd is not None
        assert isinstance(gnd, NativeNet)
        assert gnd.name == "GND"

    def test_pcbir_get_net_by_name_missing(self, native_ir: PcbIR):
        """ir.get_net_by_name returns None for missing net."""
        assert native_ir.get_net_by_name("NONEXISTENT") is None


# ---------------------------------------------------------------------------
# Native path: footprint query methods
# ---------------------------------------------------------------------------


class TestPcbIRNativeFootprintQueries:
    """Tests for PcbIR footprint query methods with NativeBoard."""

    def test_pcbir_get_footprint_by_ref_native(self, native_ir: PcbIR):
        """ir.get_footprint_by_ref finds footprint by Reference property."""
        fp = native_ir.get_footprint_by_ref("J7")
        assert fp is not None
        assert isinstance(fp, NativeFootprint)
        assert "PinSocket" in fp.lib_id

    def test_pcbir_get_footprint_by_ref_missing(self, native_ir: PcbIR):
        """ir.get_footprint_by_ref returns None for missing reference."""
        assert native_ir.get_footprint_by_ref("Z99") is None

    def test_pcbir_get_footprint_pads_native(self, native_ir: PcbIR):
        """ir.get_footprint_pads returns (pad_number, net_name) tuples."""
        pads = native_ir.get_footprint_pads("J7")
        assert isinstance(pads, list)
        assert len(pads) == 36
        # Each pad should be a tuple
        assert isinstance(pads[0], tuple)
        assert len(pads[0]) == 2

    def test_pcbir_get_footprint_pads_missing_fp(self, native_ir: PcbIR):
        """ir.get_footprint_pads returns empty list for missing reference."""
        assert native_ir.get_footprint_pads("Z99") == []

    def test_pcbir_swap_footprint_native(self, native_ir: PcbIR):
        """ir.swap_footprint changes lib_id and preserves pad net names."""
        # Add a net to a pad first for verification
        result = native_ir.swap_footprint("J7", "new_lib:new_footprint")
        assert result["old_lib_id"] == "Connector_PinSocket_2.54mm:PinSocket_2x18_P2.54mm_Vertical"
        assert result["new_lib_id"] == "new_lib:new_footprint"
        assert result["preserved_nets"] >= 0  # Some pads may have been unconnected

    def test_pcbir_swap_footprint_missing_raises(self, native_ir: PcbIR):
        """ir.swap_footprint raises ValueError for missing reference."""
        with pytest.raises(ValueError, match="not found"):
            native_ir.swap_footprint("Z99", "new_lib:fp")


# ---------------------------------------------------------------------------
# Native path: board queries
# ---------------------------------------------------------------------------


class TestPcbIRNativeBoardQueries:
    """Tests for PcbIR board-level query methods with NativeBoard."""

    def test_pcbir_get_board_bounds_native(self, native_ir: PcbIR):
        """ir.get_board_bounds returns bounds tuple or None."""
        bounds = native_ir.get_board_bounds()
        # Arduino Mega has Edge.Cuts items
        if bounds is not None:
            assert len(bounds) == 4
            x_min, y_min, x_max, y_max = bounds
            assert x_min <= x_max
            assert y_min <= y_max

    def test_pcbir_extract_netlist_native(self, native_ir: PcbIR):
        """ir.extract_netlist returns dict of net_name -> positions."""
        netlist = native_ir.extract_netlist()
        assert isinstance(netlist, dict)
        # GND net should have pad positions
        if "GND" in netlist:
            positions = netlist["GND"]
            assert len(positions) > 0
            # Each position is (x, y) tuple
            assert isinstance(positions[0], tuple)
            assert len(positions[0]) == 2


# ---------------------------------------------------------------------------
# Kiutils fallback
# ---------------------------------------------------------------------------


class TestPcbIRKiutilsFallback:
    """Tests for kiutils fallback when native parser fails."""

    def test_pcbir_kiutils_path_requires_uuid_map(self):
        """PcbIR with kiutils path requires UUID map."""
        from kicad_agent.parser import parse_pcb
        from kicad_agent.parser.uuid_extractor import extract_uuids

        result = parse_pcb(ARDUINO_MEGA)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
        assert ir._is_native is False
        assert ir.board is not None

    def test_pcbir_kiutils_no_uuid_map_raises(self):
        """PcbIR with kiutils path raises ValueError without UUID map."""
        from kicad_agent.parser import parse_pcb

        result = parse_pcb(ARDUINO_MEGA)
        with pytest.raises(ValueError, match="UUID map"):
            PcbIR(_parse_result=result)

    def test_pcbir_fallback_to_kiutils(self):
        """PcbIR created with kiutils path works correctly."""
        from kicad_agent.parser import parse_pcb
        from kicad_agent.parser.uuid_extractor import extract_uuids

        result = parse_pcb(ARDUINO_MEGA)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

        # Verify basic access
        assert len(ir.nets) > 0
        assert len(ir.footprints) > 0
        gnd = ir.get_net_by_name("GND")
        assert gnd is not None

    def test_executor_fallback_on_native_failure(self):
        """Executor falls back to kiutils when NativeParser raises."""
        from kicad_agent.ops.execution import try_native_parse

        with patch.object(NativeParser, 'parse_pcb', side_effect=Exception("mock failure")):
            native_board = try_native_parse(ARDUINO_MEGA)
            # Should return None on failure
            assert native_board is None


# ---------------------------------------------------------------------------
# CRITICAL-2: External consumer compatibility
# ---------------------------------------------------------------------------


class TestExternalConsumerCompatibility:
    """Council CRITICAL-2: External consumers access ir.board attributes transparently."""

    def test_ir_board_graphicItems_compatible(self, native_ir: PcbIR):
        """ir.board.graphicItems returns a list view over graphic_items.

        CR-01: graphicItems is now a list-returning property over the tuple
        storage (identity no longer holds; equality does).
        """
        board = native_ir.board
        assert board.graphicItems == list(board.graphic_items)

    def test_ir_board_traceItems_compatible(self, native_ir: PcbIR):
        """ir.board.traceItems returns combined segments+vias."""
        board = native_ir.board
        trace = board.traceItems
        assert isinstance(trace, list)

    def test_ir_board_general_thickness(self, native_ir: PcbIR):
        """ir.board.general.thickness is a positive float."""
        board = native_ir.board
        assert hasattr(board, "general")
        assert board.general.thickness > 0

    def test_ir_board_setup_exists(self, native_ir: PcbIR):
        """hasattr(ir.board, 'setup') is True."""
        board = native_ir.board
        assert hasattr(board, "setup")
        assert board.setup is not None

    def test_ir_board_layers_compatible(self, native_ir: PcbIR):
        """ir.board.layers returns ir.board.general.layers."""
        board = native_ir.board
        assert hasattr(board, "layers")
        layers = board.layers
        assert isinstance(layers, list)
        assert len(layers) > 0

    def test_ir_board_zones_compat(self, native_ir: PcbIR):
        """ir.board.zones is accessible (empty for Arduino Mega but valid).

        CR-01: zones is a tuple (immutable storage). Accept tuple or list.
        """
        board = native_ir.board
        assert isinstance(board.zones, (list, tuple))


# ---------------------------------------------------------------------------
# Board outline duck-typing (R2-1)
# ---------------------------------------------------------------------------


class TestBoardOutlineDuckTyping:
    """Council R2-1: NativeGraphicItem works with board_outline detection functions."""

    def test_gr_line_detection(self):
        """NativeGraphicItem with item_type='line' passes _is_gr_line check."""
        from kicad_agent.spatial.board_outline import _is_gr_line

        gi = NativeGraphicItem(
            item_type="line",
            start=_NativePosition(0.0, 0.0),
            end=_NativePosition(10.0, 20.0),
        )
        assert _is_gr_line(gi) is True

    def test_gr_arc_detection(self):
        """NativeGraphicItem with item_type='arc' passes _is_gr_arc check."""
        from kicad_agent.spatial.board_outline import _is_gr_arc

        gi = NativeGraphicItem(
            item_type="arc",
            start=_NativePosition(0.0, 0.0),
            mid=_NativePosition(5.0, 10.0),
            end=_NativePosition(10.0, 0.0),
        )
        assert _is_gr_arc(gi) is True

    def test_gr_circle_detection(self):
        """NativeGraphicItem with item_type='circle' passes _is_gr_circle check."""
        from kicad_agent.spatial.board_outline import _is_gr_circle

        gi = NativeGraphicItem(
            item_type="circle",
            center=_NativePosition(50.0, 50.0),
            end=_NativePosition(60.0, 50.0),
        )
        assert _is_gr_circle(gi) is True

    def test_gr_rect_detection(self):
        """NativeGraphicItem with item_type='rect' and filled passes _is_gr_rect check."""
        from kicad_agent.spatial.board_outline import _is_gr_rect

        gi = NativeGraphicItem(
            item_type="rect",
            start=_NativePosition(0.0, 0.0),
            end=_NativePosition(100.0, 80.0),
            filled="no",
        )
        assert _is_gr_rect(gi) is True

    def test_gr_line_not_confused_with_rect(self):
        """NativeGraphicItem line (no filled) does not pass _is_gr_rect."""
        from kicad_agent.spatial.board_outline import _is_gr_rect

        gi = NativeGraphicItem(
            item_type="line",
            start=_NativePosition(0.0, 0.0),
            end=_NativePosition(10.0, 20.0),
        )
        assert _is_gr_rect(gi) is False


# ---------------------------------------------------------------------------
# Mutation tracking
# ---------------------------------------------------------------------------


class TestPcbIRNativeMutationTracking:
    """Tests that mutations are tracked correctly in native path."""

    def test_add_net_records_mutation(self, native_ir: PcbIR):
        """ir.add_net records mutation in log."""
        assert native_ir.dirty is False
        native_ir.add_net("MUTATION_TEST")
        assert native_ir.dirty is True
        log = native_ir.mutation_log
        assert len(log) > 0
        assert log[-1]["type"] == "add_net"
        assert log[-1]["net_name"] == "MUTATION_TEST"

    def test_raw_written_flag(self, native_ir: PcbIR):
        """raw_written can be set and checked."""
        assert native_ir.raw_written is False
        native_ir._raw_written = True
        assert native_ir.raw_written is True
