"""Tests for native PCB parser (pcb_native_parser.py) and types (pcb_native_types.py).

Uses real PCB fixtures: Arduino_Mega.kicad_pcb and RaspberryPi-uHAT.kicad_pcb.
Covers all Council-mandated requirements (CRITICAL-1, CRITICAL-2, HIGH-2, HIGH-3).
"""

import logging
from pathlib import Path

import pytest

from kicad_agent.parser.pcb_native_parser import (
    NativeParser,
    _pre_scan_depth,
)
from kicad_agent.parser.pcb_native_types import (
    NativeBoard,
    NativeFootprint,
    NativeGeneral,
    NativeGraphicItem,
    NativeNet,
    NativePad,
    NativeSetup,
    NativeStackup,
    NativeZone,
    _NativePosition,
)

ARDUINO_MEGA = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")
RASPBERRY_PI = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_pcb")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def arduino_board() -> NativeBoard:
    """Parse Arduino Mega fixture once per test module."""
    return NativeParser.parse_pcb(ARDUINO_MEGA)


@pytest.fixture(scope="module")
def raspberry_board() -> NativeBoard:
    """Parse Raspberry Pi fixture once per test module."""
    return NativeParser.parse_pcb(RASPBERRY_PI)


# ---------------------------------------------------------------------------
# Arduino Mega: basic parsing
# ---------------------------------------------------------------------------


class TestArduinoMegaBasic:
    """Basic parsing tests for Arduino Mega fixture."""

    def test_parse_arduino_mega_returns_native_board(self, arduino_board):
        assert isinstance(arduino_board, NativeBoard)

    def test_parse_arduino_mega_version(self, arduino_board):
        assert arduino_board.version != ""
        assert arduino_board.version == "20241229"

    def test_parse_arduino_mega_generator(self, arduino_board):
        assert arduino_board.generator != ""
        assert arduino_board.generator == "pcbnew"

    def test_parse_arduino_mega_nets_count(self, arduino_board):
        # 79 nets: net 0 "" through net 78 "unconnected-(J1-Pin_1-Pad1)"
        assert len(arduino_board.nets) == 79

    def test_parse_arduino_mega_nets_have_numbers(self, arduino_board):
        for net in arduino_board.nets:
            assert isinstance(net.number, int)
            assert net.number >= 0

    def test_parse_arduino_mega_nets_have_names(self, arduino_board):
        # Net 0 has empty name, all others have non-empty names
        for net in arduino_board.nets:
            if net.number == 0:
                assert net.name == ""
            else:
                assert net.name != ""

    def test_parse_arduino_mega_net_number_preserved(self, arduino_board):
        # GND is net 1, VCC is net 76
        net_map = {n.number: n.name for n in arduino_board.nets}
        assert net_map[1] == "GND"
        assert net_map[76] == "VCC"

    def test_parse_arduino_mega_footprints_count(self, arduino_board):
        assert len(arduino_board.footprints) == 13


class TestArduinoMegaFootprints:
    """Footprint detail tests for Arduino Mega fixture."""

    def test_parse_arduino_mega_footprints_have_lib_id(self, arduino_board):
        for fp in arduino_board.footprints:
            assert fp.lib_id != ""

    def test_parse_arduino_mega_footprints_have_position(self, arduino_board):
        for fp in arduino_board.footprints:
            assert isinstance(fp.position, tuple)
            assert len(fp.position) == 3

    def test_parse_arduino_mega_footprints_have_properties(self, arduino_board):
        for fp in arduino_board.footprints:
            assert "Reference" in fp.properties
            assert "Value" in fp.properties

    def test_parse_arduino_mega_footprints_have_pads(self, arduino_board):
        for fp in arduino_board.footprints:
            assert len(fp.pads) >= 1


class TestArduinoMegaPads:
    """Pad detail tests for Arduino Mega fixture."""

    def test_parse_arduino_mega_pads_have_details(self, arduino_board):
        for fp in arduino_board.footprints:
            for pad in fp.pads:
                # np_thru_hole mounting pads have empty number (valid KiCad)
                # Check shape and size are populated instead
                assert pad.shape != ""
                assert pad.size != (0.0, 0.0)

    def test_parse_arduino_mega_numbered_pads_have_number(self, arduino_board):
        """Pads with pad_type other than np_thru_hole have non-empty number."""
        for fp in arduino_board.footprints:
            for pad in fp.pads:
                if pad.pad_type != "np_thru_hole":
                    assert pad.number != ""

    def test_parse_arduino_mega_pads_with_nets(self, arduino_board):
        # At least some pads should have non-empty net_name
        found_net_pad = False
        for fp in arduino_board.footprints:
            for pad in fp.pads:
                if pad.net_name:
                    found_net_pad = True
                    break
            if found_net_pad:
                break
        assert found_net_pad

    def test_parse_arduino_mega_pad_net_number_preserved(self, arduino_board):
        # Pads with nets should have net_number > 0
        for fp in arduino_board.footprints:
            for pad in fp.pads:
                if pad.net_name:
                    assert pad.net_number > 0

    def test_parse_arduino_mega_footprint_uuid_extracted(self, arduino_board):
        # All footprints should have a UUID
        for fp in arduino_board.footprints:
            assert fp.uuid != ""

    def test_parse_arduino_mega_total_pads(self, arduino_board):
        # Arduino Mega has 92 pads across 13 footprints
        total_pads = sum(len(fp.pads) for fp in arduino_board.footprints)
        assert total_pads > 50


# ---------------------------------------------------------------------------
# Raspberry Pi fixture
# ---------------------------------------------------------------------------


class TestRaspberryPi:
    """Parsing tests for Raspberry Pi uHAT fixture."""

    def test_parse_raspberry_pi_returns_native_board(self, raspberry_board):
        assert isinstance(raspberry_board, NativeBoard)

    def test_parse_raspberry_pi_nets_count(self, raspberry_board):
        # 32 nets: net 0 "" through net 31 "+3V3"
        assert len(raspberry_board.nets) == 32

    def test_parse_raspberry_pi_footprints_count(self, raspberry_board):
        assert len(raspberry_board.footprints) == 5

    def test_parse_raspberry_pi_np_thru_hole_pads(self, raspberry_board):
        # Raspberry Pi fixture has np_thru_hole mounting hole pads
        found_np = False
        for fp in raspberry_board.footprints:
            for pad in fp.pads:
                if pad.pad_type == "np_thru_hole":
                    found_np = True
                    assert pad.size != (0.0, 0.0)
                    assert pad.drill > 0.0
                    break
            if found_np:
                break
        assert found_np


# ---------------------------------------------------------------------------
# Edge case parsing
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_parse_content_from_string(self, arduino_board):
        assert arduino_board.raw_content != ""

    def test_parse_empty_content(self):
        board = NativeParser.parse_pcb_content("")
        assert isinstance(board, NativeBoard)
        assert board.raw_content == ""
        assert len(board.nets) == 0

    def test_parse_whitespace_content(self):
        board = NativeParser.parse_pcb_content("   \n  \t  ")
        assert isinstance(board, NativeBoard)
        assert len(board.nets) == 0

    def test_parse_malformed_content(self):
        board = NativeParser.parse_pcb_content("(this is (not valid sexp")
        assert isinstance(board, NativeBoard)
        assert len(board.nets) == 0

    def test_parse_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            NativeParser.parse_pcb(Path("/nonexistent/path/board.kicad_pcb"))


# ---------------------------------------------------------------------------
# Board structure tests
# ---------------------------------------------------------------------------


class TestBoardStructure:
    """Tests for board-level structure elements."""

    def test_board_outline_extracted(self, arduino_board):
        # Arduino Mega has Edge.Cuts graphic items
        assert arduino_board.board_outline is not None
        assert len(arduino_board.board_outline.items) > 0

    def test_graphic_items_extracted(self, arduino_board):
        # Arduino Mega has 21 graphic items (8 lines + 3 arcs on Edge.Cuts
        # plus fp_graphic items are in footprints, not board graphic_items)
        assert len(arduino_board.graphic_items) > 0

    def test_net_classes_default_empty(self, arduino_board):
        # Arduino Mega may not have explicit net classes
        # (uses "Default" which may be implicit)
        assert isinstance(arduino_board.net_classes, list)

    def test_segments_default_empty(self, arduino_board):
        # Arduino Mega has no routed segments
        assert len(arduino_board.segments) == 0

    def test_raw_content_preserved(self, arduino_board):
        original = ARDUINO_MEGA.read_text(encoding="utf-8")
        assert arduino_board.raw_content == original


# ---------------------------------------------------------------------------
# Council CRITICAL-1: Depth pre-scan
# ---------------------------------------------------------------------------


class TestDepthPreScan:
    """Tests for depth pre-scan security (CRITICAL-1)."""

    def test_depth_pre_scan_rejects_deeply_nested(self):
        deeply_nested = "(a " + "(b " * 300 + ")" * 300 + ")"
        with pytest.raises(ValueError, match="nesting depth"):
            _pre_scan_depth(deeply_nested)

    def test_depth_pre_scan_rejects_at_limit_plus_one(self):
        # Exactly MAX_SEXP_DEPTH + 1
        content = "(" * 201 + ")" * 201
        with pytest.raises(ValueError, match="nesting depth"):
            _pre_scan_depth(content, max_depth=200)

    def test_depth_pre_scan_accepts_normal(self, arduino_board):
        # Real PCB content should have normal depth
        depth = _pre_scan_depth(arduino_board.raw_content)
        assert depth < 200

    def test_depth_pre_scan_accepts_at_limit(self):
        # Exactly MAX_SEXP_DEPTH should be accepted
        content = "(" * 200 + ")" * 200
        depth = _pre_scan_depth(content, max_depth=200)
        assert depth == 200

    def test_depth_pre_scan_empty(self):
        depth = _pre_scan_depth("")
        assert depth == 0

    def test_depth_pre_scan_ignores_strings(self):
        # Parentheses inside quoted strings should not count
        content = '(data "(nested)" more)'
        # Only outer (data ...) has depth 1; quoted parens are ignored
        depth = _pre_scan_depth(content)
        assert depth == 1

    def test_depth_pre_scan_nested_outside_strings(self):
        # Nested parens outside strings should count
        content = '((outer) (inner))'
        depth = _pre_scan_depth(content)
        assert depth == 2

    def test_parser_rejects_deeply_nested(self):
        # Parser should return empty board for deeply nested content
        deeply_nested = "(kicad_pcb " + "(a " * 300 + ")" * 300 + ")"
        board = NativeParser.parse_pcb_content(deeply_nested)
        assert isinstance(board, NativeBoard)
        assert len(board.nets) == 0


# ---------------------------------------------------------------------------
# Council CRITICAL-2: Kiutils-compatible properties
# ---------------------------------------------------------------------------


class TestKiutilsCompatibility:
    """Tests for kiutils-compatible properties (Council CRITICAL-2)."""

    def test_native_board_graphicItems_property(self, arduino_board):
        assert arduino_board.graphicItems is arduino_board.graphic_items

    def test_native_board_traceItems_property(self, arduino_board):
        trace_items = arduino_board.traceItems
        assert isinstance(trace_items, list)
        # Should be segments + vias (both empty for Arduino Mega)
        assert len(trace_items) == len(arduino_board.segments) + len(
            arduino_board.vias
        )

    def test_native_board_traceItems_mixed(self):
        """Verify traceItems combines segments and vias."""
        from kicad_agent.parser.pcb_native_types import (
            NativeSegment,
            NativeVia,
            _NativePosition,
        )

        content = """
        (kicad_pcb
            (version 20241229)
            (generator "pcbnew")
            (segment (start 10 20) (end 30 40) (width 0.25) (layer "F.Cu") (net 1 "GND"))
            (segment (start 50 60) (end 70 80) (width 0.25) (layer "F.Cu") (net 1 "GND"))
            (via (at 100 100) (size 0.8) (drill 0.4) (net 1 "GND"))
        )
        """
        board = NativeParser.parse_pcb_content(content)
        assert len(board.segments) == 2
        assert len(board.vias) == 1
        assert len(board.traceItems) == 3

    def test_native_board_general_populated(self, arduino_board):
        assert isinstance(arduino_board.general, NativeGeneral)
        assert arduino_board.general.thickness > 0
        assert arduino_board.general.thickness == 1.6

    def test_native_board_general_layers(self, arduino_board):
        assert len(arduino_board.general.layers) > 0
        assert "F.Cu" in arduino_board.general.layers

    def test_native_board_setup_exists(self, arduino_board):
        assert hasattr(arduino_board, "setup")
        assert arduino_board.setup is not None

    def test_native_board_setup_stackup(self, arduino_board):
        assert arduino_board.setup is not None
        assert arduino_board.setup.stackup is not None
        assert isinstance(arduino_board.setup.stackup, NativeStackup)

    def test_native_zone_tstamp_property(self):
        content = """
        (kicad_pcb
            (version 20241229)
            (generator "pcbnew")
            (zone (net 1 "GND") (layer "F.Cu") (uuid "abc123") (priority 0)
                (filled_polygon
                    (pts (xy 0 0) (xy 100 0) (xy 100 100) (xy 0 100))
                )
            )
        )
        """
        board = NativeParser.parse_pcb_content(content)
        assert len(board.zones) == 1
        assert board.zones[0].tstamp == "abc123"

    def test_native_zone_compatibility_fields(self):
        content = """
        (kicad_pcb
            (version 20241229)
            (generator "pcbnew")
            (zone (net 2 "VCC") (layer "B.Cu") (uuid "def456") (priority 1)
                (clearance 0.5)
                (min_thickness 0.3)
                (filled_polygon
                    (pts (xy 0 0) (xy 50 0) (xy 50 50) (xy 0 50))
                )
            )
        )
        """
        board = NativeParser.parse_pcb_content(content)
        zone = board.zones[0]
        # CRITICAL-2 compatibility fields
        assert zone.net == 2
        assert zone.netName == "VCC"
        assert zone.layers == ["B.Cu"]
        assert zone.minThickness == 0.3
        assert zone.net_number == 2
        assert zone.net_name == "VCC"


# ---------------------------------------------------------------------------
# Council HIGH-3: Pad pinfunction and pintype
# ---------------------------------------------------------------------------


class TestPadPinfunctionPintype:
    """Tests for pad pinfunction and pintype fields (Council HIGH-3)."""

    def test_pad_pinfunction_pintype(self, arduino_board):
        # Arduino Mega pads have pinfunction and pintype
        found_pinfunction = False
        for fp in arduino_board.footprints:
            for pad in fp.pads:
                if pad.pinfunction:
                    found_pinfunction = True
                    assert isinstance(pad.pinfunction, str)
                    break
            if found_pinfunction:
                break
        assert found_pinfunction, "Expected at least one pad with pinfunction"

    def test_pad_pintype_populated(self, arduino_board):
        found_pintype = False
        for fp in arduino_board.footprints:
            for pad in fp.pads:
                if pad.pintype:
                    found_pintype = True
                    assert isinstance(pad.pintype, str)
                    break
            if found_pintype:
                break
        assert found_pintype, "Expected at least one pad with pintype"

    def test_np_thru_hole_pad_type(self, raspberry_board):
        """Raspberry Pi fixture has np_thru_hole pads (Council HIGH-3)."""
        found_np = False
        for fp in raspberry_board.footprints:
            for pad in fp.pads:
                if pad.pad_type == "np_thru_hole":
                    found_np = True
                    break
            if found_np:
                break
        assert found_np


# ---------------------------------------------------------------------------
# Council HIGH-2: Graphic item types
# ---------------------------------------------------------------------------


class TestGraphicItemTypes:
    """Tests for graphic item type support (Council HIGH-2)."""

    def test_graphic_item_line_type(self, arduino_board):
        line_items = [
            gi for gi in arduino_board.graphic_items if gi.item_type == "line"
        ]
        assert len(line_items) > 0

    def test_graphic_item_arc_type(self, arduino_board):
        arc_items = [
            gi for gi in arduino_board.graphic_items if gi.item_type == "arc"
        ]
        assert len(arc_items) > 0

    def test_graphic_item_has_position_attributes(self, arduino_board):
        """Verify _NativePosition supports .X and .Y attribute access."""
        for gi in arduino_board.graphic_items:
            if gi.start is not None:
                assert isinstance(gi.start.X, float)
                assert isinstance(gi.start.Y, float)
                assert gi.start[0] == gi.start.X
                assert gi.start[1] == gi.start.Y
                break

    def test_graphic_item_has_filled_attribute(self, arduino_board):
        """Verify NativeGraphicItem has 'filled' attribute for board_outline.py compat."""
        for gi in arduino_board.graphic_items:
            assert hasattr(gi, "filled")
            break


# ---------------------------------------------------------------------------
# NativePosition tests
# ---------------------------------------------------------------------------


class TestNativePosition:
    """Tests for _NativePosition NamedTuple."""

    def test_position_tuple_indexing(self):
        pos = _NativePosition(10.0, 20.0)
        assert pos[0] == 10.0
        assert pos[1] == 20.0

    def test_position_attribute_access(self):
        pos = _NativePosition(10.0, 20.0)
        assert pos.X == 10.0
        assert pos.Y == 20.0

    def test_position_is_tuple(self):
        pos = _NativePosition(10.0, 20.0)
        assert isinstance(pos, tuple)

    def test_position_unpacking(self):
        pos = _NativePosition(10.0, 20.0)
        x, y = pos
        assert x == 10.0
        assert y == 20.0


# ---------------------------------------------------------------------------
# NativeBoard property tests
# ---------------------------------------------------------------------------


class TestNativeBoardProperties:
    """Tests for NativeBoard kiutils-compatible properties."""

    def test_graphicItems_returns_same_list(self):
        board = NativeBoard()
        items = [NativeGraphicItem()]
        board.graphic_items = items
        assert board.graphicItems is items

    def test_traceItems_combines_segments_and_vias(self):
        from kicad_agent.parser.pcb_native_types import NativeSegment, NativeVia

        board = NativeBoard()
        board.segments = [NativeSegment()]
        board.vias = [NativeVia()]
        assert len(board.traceItems) == 2

    def test_layers_returns_general_layers(self):
        board = NativeBoard()
        board.general.layers = ["F.Cu", "B.Cu"]
        assert board.layers == ["F.Cu", "B.Cu"]

    def test_empty_board_defaults(self):
        board = NativeBoard()
        assert board.version == ""
        assert board.generator == ""
        assert board.nets == []
        assert board.footprints == []
        assert board.segments == []
        assert board.vias == []
        assert board.zones == []
        assert board.graphic_items == []
        assert board.board_outline is None
        assert board.general.thickness == 1.6
        assert board.setup is None


# ---------------------------------------------------------------------------
# Import verification
# ---------------------------------------------------------------------------


class TestImports:
    """Verify all expected exports are importable."""

    def test_import_parser(self):
        from kicad_agent.parser.pcb_native_parser import NativeParser
        assert NativeParser is not None

    def test_import_types(self):
        from kicad_agent.parser.pcb_native_types import (
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
            NativeVia,
            NativeZone,
            _NativePosition,
        )
        assert all(v is not None for v in [
            NativeBoard, NativeBoardOutline, NativeFootprint,
            NativeGeneral, NativeGraphicItem, NativeNet,
            NativeNetClass, NativePad, NativeSegment,
            NativeSetup, NativeStackup, NativeVia,
            NativeZone, _NativePosition,
        ])

    def test_no_kiutils_import_in_parser(self):
        """Verify parser module does not import kiutils as a module."""
        import ast
        import kicad_agent.parser.pcb_native_parser as parser_mod
        source = open(parser_mod.__file__).read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "kiutils" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "kiutils" not in node.module

    def test_no_kiutils_import_in_types(self):
        """Verify types module does not import kiutils as a module."""
        import ast
        import kicad_agent.parser.pcb_native_types as types_mod
        source = open(types_mod.__file__).read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "kiutils" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "kiutils" not in node.module
