"""Tests for CoordinateConverter affine transform.

CP-06: Schematic-to-PCB Y-axis flip with full affine transform support.
"""

import math

from kicad_agent.constraints.coordinate import CoordinateConverter


class TestCoordinateConverterYFlip:
    """Test Y-flip (most common case: schematic Y-up to PCB Y-down)."""

    def test_y_flip_only(self):
        """schematic_to_pcb with board_height=100 flips Y axis."""
        conv = CoordinateConverter(board_height_mm=100.0)
        result = conv.schematic_to_pcb((50.0, 25.0))
        assert result == (50.0, 75.0)

    def test_y_flip_inverse(self):
        """pcb_to_schematic inverts Y-flip."""
        conv = CoordinateConverter(board_height_mm=100.0)
        result = conv.pcb_to_schematic((50.0, 75.0))
        assert result == (50.0, 25.0)

    def test_round_trip_y_flip(self):
        """schematic_to_pcb then pcb_to_schematic returns original."""
        conv = CoordinateConverter(board_height_mm=100.0)
        original = (30.0, 60.0)
        pcb = conv.schematic_to_pcb(original)
        recovered = conv.pcb_to_schematic(pcb)
        assert abs(recovered[0] - original[0]) < 1e-10
        assert abs(recovered[1] - original[1]) < 1e-10


class TestCoordinateConverterOffset:
    """Test offset transform."""

    def test_offset_applied_after_y_flip(self):
        """Offset applied after Y-flip."""
        conv = CoordinateConverter(board_height_mm=100.0, offset_x=10.0, offset_y=5.0)
        # Y-flip: (50, 25) -> (50, 75), then +offset: (60, 80)
        result = conv.schematic_to_pcb((50.0, 25.0))
        assert result == (60.0, 80.0)

    def test_offset_round_trip(self):
        """Offset round-trips correctly."""
        conv = CoordinateConverter(board_height_mm=100.0, offset_x=10.0, offset_y=5.0)
        original = (25.0, 50.0)
        pcb = conv.schematic_to_pcb(original)
        recovered = conv.pcb_to_schematic(pcb)
        assert abs(recovered[0] - original[0]) < 1e-10
        assert abs(recovered[1] - original[1]) < 1e-10


class TestCoordinateConverterRotation:
    """Test rotation transform."""

    def test_rotation_90_degrees(self):
        """90-degree rotation transforms correctly."""
        conv = CoordinateConverter(board_height_mm=100.0, rotation_deg=90.0)
        # Y-flip: (10, 20) -> (10, 80)
        # Rotate 90: (x,y) -> (-y, x) = (-80, 10)
        result = conv.schematic_to_pcb((10.0, 20.0))
        expected_x = -80.0
        expected_y = 10.0
        assert abs(result[0] - expected_x) < 1e-10
        assert abs(result[1] - expected_y) < 1e-10

    def test_rotation_round_trip(self):
        """Rotation round-trips correctly."""
        conv = CoordinateConverter(board_height_mm=100.0, rotation_deg=45.0)
        original = (30.0, 60.0)
        pcb = conv.schematic_to_pcb(original)
        recovered = conv.pcb_to_schematic(pcb)
        assert abs(recovered[0] - original[0]) < 1e-10
        assert abs(recovered[1] - original[1]) < 1e-10

    def test_full_affine_round_trip(self):
        """Full affine (Y-flip + rotation + scale + offset) round-trips."""
        conv = CoordinateConverter(
            board_height_mm=150.0,
            offset_x=5.0,
            offset_y=10.0,
            rotation_deg=30.0,
            scale=2.0,
        )
        original = (40.0, 80.0)
        pcb = conv.schematic_to_pcb(original)
        recovered = conv.pcb_to_schematic(pcb)
        assert abs(recovered[0] - original[0]) < 1e-10
        assert abs(recovered[1] - original[1]) < 1e-10


class TestCoordinateConverterScale:
    """Test scale transform."""

    def test_scale_applied(self):
        """Scale multiplies both coordinates."""
        conv = CoordinateConverter(board_height_mm=100.0, scale=2.0)
        # Y-flip: (10, 20) -> (10, 80), then *2: (20, 160)
        result = conv.schematic_to_pcb((10.0, 20.0))
        assert result == (20.0, 160.0)

    def test_scale_round_trip(self):
        """Scale round-trips correctly."""
        conv = CoordinateConverter(board_height_mm=100.0, scale=3.0)
        original = (15.0, 35.0)
        pcb = conv.schematic_to_pcb(original)
        recovered = conv.pcb_to_schematic(pcb)
        assert abs(recovered[0] - original[0]) < 1e-10
        assert abs(recovered[1] - original[1]) < 1e-10
