"""Tests for routing bridge module with detailed segment tests."""

import pytest

from kicad_agent.routing.bridge import TrackSegment, ViaSegment


class TestTrackSegmentDetailed:
    """Detailed tests for TrackSegment."""

    def test_creation_with_all_fields(self):
        """TrackSegment with all fields creates correctly."""
        seg = TrackSegment(
            start_x=0.0, start_y=0.0,
            end_x=10.0, end_y=5.0,
            width=0.25,
            layer="F.Cu",
            net="NET1",
            net_id=1,
        )
        assert seg.net_id == 1

    def test_to_sexpr_full(self):
        """TrackSegment serializes all fields to S-expression."""
        seg = TrackSegment(
            start_x=1.0, start_y=2.0,
            end_x=3.0, end_y=4.0,
            width=0.15,
            layer="B.Cu",
            net="NET2",
            net_id=2,
        )
        sexpr = seg.to_sexpr()
        assert "NET2" in sexpr
        assert "B.Cu" in sexpr


class TestViaSegmentDetailed:
    """Detailed tests for ViaSegment."""

    def test_creation_with_all_fields(self):
        """ViaSegment with all fields creates correctly."""
        via = ViaSegment(
            x=5.0, y=3.0,
            from_layer="F.Cu", to_layer="B.Cu",
            diameter=0.8, drill=0.4,
            net="NET1",
            net_id=1,
        )
        assert via.net_id == 1

    def test_to_sexpr_full(self):
        """ViaSegment serializes all fields."""
        via = ViaSegment(
            x=10.0, y=20.0,
            from_layer="F.Cu", to_layer="In1.Cu",
            diameter=1.0, drill=0.5,
            net="NET3",
        )
        sexpr = via.to_sexpr()
        assert "NET3" in sexpr
        assert "In1.Cu" in sexpr
