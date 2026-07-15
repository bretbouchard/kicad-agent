"""Tests for parser integration and native PCB parser types."""

from pathlib import Path

import pytest

from volta.parser.pcb_native_parser import NativeParser
from volta.parser.pcb_native_types import (
    NativeBoard,
    NativeFootprint,
    NativeNet,
    NativeSegment,
    NativeVia,
    NativeZone,
    NativeGraphicItem,
    NativeGeneral,
)


class TestNativeBoard:
    """Tests for NativeBoard dataclass."""

    def test_creation_empty(self):
        """NativeBoard can be created with minimal args."""
        board = NativeBoard(raw_content="", file_path="")
        # CR-01: collection fields default to empty tuples (immutable).
        assert board.footprints == ()
        assert board.nets == ()
        assert board.segments == ()

    def test_creation_with_content(self):
        """NativeBoard stores raw_content."""
        content = '(kicad_pcb (version 20240108))'
        board = NativeBoard(raw_content=content, file_path="test.kicad_pcb")
        assert board.raw_content == content


class TestNativeFootprint:
    """Tests for NativeFootprint dataclass."""

    def test_creation(self):
        """NativeFootprint can be created."""
        fp = NativeFootprint()
        assert fp.lib_id == ""
        # CR-01: collection fields default to empty tuples (immutable).
        assert fp.pads == ()
        assert fp.graphic_items == ()


class TestNativeNet:
    """Tests for NativeNet dataclass."""

    def test_creation(self):
        """NativeNet can be created."""
        net = NativeNet(number=0, name="")
        assert net.number == 0
        assert net.name == ""


class TestNativeSegment:
    """Tests for NativeSegment dataclass."""

    def test_creation(self):
        """NativeSegment can be created."""
        seg = NativeSegment()
        assert seg.width == 0.0
        assert seg.layer == ""


class TestNativeVia:
    """Tests for NativeVia dataclass."""

    def test_creation(self):
        """NativeVia can be created."""
        via = NativeVia()
        assert via.diameter == 0.0
        assert via.drill == 0.0


class TestNativeZone:
    """Tests for NativeZone dataclass."""

    def test_creation(self):
        """NativeZone can be created."""
        zone = NativeZone()
        # CR-01: collection fields default to empty tuples (immutable).
        assert zone.polygon_points == ()


class TestNativeGraphicItem:
    """Tests for NativeGraphicItem dataclass."""

    def test_creation(self):
        """NativeGraphicItem can be created."""
        gi = NativeGraphicItem(item_type="line")
        assert gi.item_type == "line"


class TestNativeGeneral:
    """Tests for NativeGeneral dataclass."""

    def test_creation(self):
        """NativeGeneral can be created."""
        gen = NativeGeneral()
        assert gen.thickness == 1.6


class TestParsePcbContent:
    """Tests for NativeParser.parse_pcb_content."""

    def test_empty_content(self):
        """Empty content returns empty board."""
        board = NativeParser.parse_pcb_content("")
        # CR-01: collection fields default to empty tuples (immutable).
        assert board.footprints == ()

    def test_whitespace_only(self):
        """Whitespace-only content returns empty board."""
        board = NativeParser.parse_pcb_content("   \n  ")
        assert board.footprints == ()

    def test_minimal_valid(self):
        """Minimal valid PCB content parses."""
        content = '(kicad_pcb (version 20240108) (generator "test"))'
        board = NativeParser.parse_pcb_content(content)
        assert board.version == "20240108"

    def test_nets_extracted(self):
        """Net declarations are extracted."""
        content = '(kicad_pcb (version 20240108) (net 0 "") (net 1 "GND") (net 2 "VCC"))'
        board = NativeParser.parse_pcb_content(content)
        assert len(board.nets) == 3
        assert board.nets[1].name == "GND"

    def test_net_classes_extracted(self):
        """Net class declarations are extracted."""
        content = '(kicad_pcb (version 20240108) (net_class "Default" (clearance 0.2) (trace_width 0.25) (add_net "GND") (add_net "VCC")))'
        board = NativeParser.parse_pcb_content(content)
        assert len(board.net_classes) == 1
        assert board.net_classes[0].name == "Default"

    def test_segments_extracted(self):
        """Segment blocks are extracted."""
        content = '(kicad_pcb (version 20240108) (segment (start 10 20) (end 30 40) (width 0.25) (layer "F.Cu") (net 1 "GND")))'
        board = NativeParser.parse_pcb_content(content)
        assert len(board.segments) == 1

    def test_vias_extracted(self):
        """Via blocks are extracted."""
        content = '(kicad_pcb (version 20240108) (via (at 10 20) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1 "GND")))'
        board = NativeParser.parse_pcb_content(content)
        assert len(board.vias) == 1

    def test_zones_extracted(self):
        """Zone blocks are extracted."""
        content = '(kicad_pcb (version 20240108) (zone (net 1) (net_name "GND") (layer "F.Cu")))'
        board = NativeParser.parse_pcb_content(content)
        assert len(board.zones) == 1

    def test_graphic_items_extracted(self):
        """Graphic items are extracted."""
        content = '(kicad_pcb (version 20240108) (gr_line (start 0 0) (end 10 5) (layer "Edge.Cuts") (width 0.1)))'
        board = NativeParser.parse_pcb_content(content)
        assert len(board.graphic_items) == 1
