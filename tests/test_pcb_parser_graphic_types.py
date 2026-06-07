"""Tests for P-BUG-005: KiCad 10 graphic type parsing.

Validates that gr_text, gr_text_box, dimension, and target elements
are parsed from PCB S-expression content into NativeGraphicItem.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kicad_agent.parser.pcb_native_parser import NativeParser


# Minimal PCB with all 10 graphic types
_MINIMAL_PCB_10_TYPES = """\
(kicad_pcb (version 20241118) (generator kicad)

  (general (thickness 1.6) (layers ...))

  (paper "A4")

  (net 0 "")

  (gr_line (start 10 20) (end 30 40) (layer "F.SilkS") (width 0.2) (uuid "11111111-1111-1111-1111-111111111111"))
  (gr_arc (start 10 20) (end 30 40) (mid 20 35) (layer "F.SilkS") (width 0.2) (uuid "22222222-2222-2222-2222-222222222222"))
  (gr_circle (center 50 50) (radius 5) (layer "F.SilkS") (width 0.2) (uuid "33333333-3333-3333-3333-333333333333"))
  (gr_rect (start 5 5) (end 25 25) (layer "Edge.Cuts") (width 0.1) (uuid "44444444-4444-4444-4444-444444444444"))
  (gr_poly (pts (xy 0 0) (xy 10 0) (xy 5 10)) (layer "F.SilkS") (width 0.15) (uuid "55555555-5555-5555-5555-555555555555"))
  (gr_curve (start 0 0) (mid 5 10) (end 10 0) (layer "F.SilkS") (width 0.2) (uuid "66666666-6666-6666-6666-666666666666"))
  (gr_text "Rev 1.0" (at 100 100 90) (layer "F.SilkS") (uuid "77777777-7777-7777-7777-777777777777"))
  (gr_text_box "Warning" (at 60 60) (size 20 5) (layer "F.SilkS") (uuid "88888888-8888-8888-8888-888888888888"))
  (dimension (type aligned) (style default) (value 25.4) (layer "Dwgs.User") (uuid "99999999-9999-9999-9999-999999999999"))
  (target through_hole (at 0 0) (size 5 5) (layer "F.Fab") (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
)
"""


class TestGraphicTypesPBUG005:
    """P-BUG-005: All 10 KiCad 10 graphic types parsed."""

    def test_all_ten_types_parsed(self):
        """All 10 graphic types are parsed from a PCB."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
        ) as f:
            f.write(_MINIMAL_PCB_10_TYPES)
            f.flush()

        board = NativeParser.parse_pcb(Path(f.name))
        assert len(board.graphic_items) == 10, (
            f"Expected 10 graphic items, got {len(board.graphic_items)}"
        )

    def test_text_type_parsed(self):
        """gr_text items have text content."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
        ) as f:
            f.write(_MINIMAL_PCB_10_TYPES)
            f.flush()

        board = NativeParser.parse_pcb(Path(f.name))
        text_items = [gi for gi in board.graphic_items if gi.item_type == "text"]
        assert len(text_items) == 1
        assert text_items[0].text == "Rev 1.0"

    def test_text_box_type_parsed(self):
        """gr_text_box items are parsed."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
        ) as f:
            f.write(_MINIMAL_PCB_10_TYPES)
            f.flush()

        board = NativeParser.parse_pcb(Path(f.name))
        text_box_items = [gi for gi in board.graphic_items if gi.item_type == "text_box"]
        assert len(text_box_items) == 1
        assert text_box_items[0].text == "Warning"

    def test_dimension_type_parsed(self):
        """dimension items are parsed."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
        ) as f:
            f.write(_MINIMAL_PCB_10_TYPES)
            f.flush()

        board = NativeParser.parse_pcb(Path(f.name))
        dim_items = [gi for gi in board.graphic_items if gi.item_type == "dimension"]
        assert len(dim_items) == 1

    def test_target_type_parsed(self):
        """target items are parsed."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
        ) as f:
            f.write(_MINIMAL_PCB_10_TYPES)
            f.flush()

        board = NativeParser.parse_pcb(Path(f.name))
        target_items = [gi for gi in board.graphic_items if gi.item_type == "target"]
        assert len(target_items) == 1

    def test_existing_types_unchanged(self):
        """Original 6 geometric types still parse correctly."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
        ) as f:
            f.write(_MINIMAL_PCB_10_TYPES)
            f.flush()

        board = NativeParser.parse_pcb(Path(f.name))
        line_items = [gi for gi in board.graphic_items if gi.item_type == "line"]
        assert len(line_items) == 1
        assert line_items[0].start is not None
        assert line_items[0].end is not None
        assert line_items[0].layer == "F.SilkS"
