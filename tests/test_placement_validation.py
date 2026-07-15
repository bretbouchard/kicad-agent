"""Tests for DRC-aware placement validation.

Validates that PlacementValidator catches clearance violations, overlaps,
and bounds issues using SpatialQueryEngine for O(n log n) clearance queries.
"""

import math

import pytest

from volta.generation.intent import ComponentSpec, NetSpec
from volta.placement.graph import PlacementGraph, netlist_to_placement_graph
from volta.placement.validation import (
    PlacementValidator,
    PlacementViolation,
    positions_to_boxes,
    validate_placement,
)
from volta.spatial.primitives import SpatialBox


# ---------------------------------------------------------------------------
# positions_to_boxes tests
# ---------------------------------------------------------------------------


class TestPositionsToBoxes:
    """Tests for the positions_to_boxes helper function."""

    def test_positions_to_boxes_basic(self) -> None:
        """Three components at known positions with known sizes, verify corners."""
        positions = {
            "R1": (10.0, 20.0, 0.0),
            "U1": (50.0, 40.0, 0.0),
            "C1": (80.0, 60.0, 0.0),
        }
        sizes = {"R1": 4.0, "U1": 10.0, "C1": 3.0}

        boxes = positions_to_boxes(positions, sizes)

        assert len(boxes) == 3

        # Build a lookup by reference
        box_map = {b.reference: b for b in boxes}

        # R1 at (10, 20), size 4 -> half=2 -> (8,18)-(12,22)
        assert box_map["R1"].x1 == pytest.approx(8.0)
        assert box_map["R1"].y1 == pytest.approx(18.0)
        assert box_map["R1"].x2 == pytest.approx(12.0)
        assert box_map["R1"].y2 == pytest.approx(22.0)

        # U1 at (50, 40), size 10 -> half=5 -> (45,35)-(55,45)
        assert box_map["U1"].x1 == pytest.approx(45.0)
        assert box_map["U1"].y1 == pytest.approx(35.0)
        assert box_map["U1"].x2 == pytest.approx(55.0)
        assert box_map["U1"].y2 == pytest.approx(45.0)

        # C1 at (80, 60), size 3 -> half=1.5 -> (78.5,58.5)-(81.5,61.5)
        assert box_map["C1"].x1 == pytest.approx(78.5)
        assert box_map["C1"].y1 == pytest.approx(58.5)
        assert box_map["C1"].x2 == pytest.approx(81.5)
        assert box_map["C1"].y2 == pytest.approx(61.5)

    def test_positions_to_boxes_rotation(self) -> None:
        """Rotated component has larger bounding box than unrotated."""
        # A 10mm square at (50, 40) with 90 degree rotation
        # After 90 degree rotation of a square, AABB is the same size
        # Use a non-square: make it wider by using position (50, 40)
        # Actually, with size=10 (square), rotation doesn't change AABB
        # Let's use different widths/heights conceptually -- but positions_to_boxes
        # uses the same size for both w and h. For a square, rotation doesn't
        # change the AABB. But we can still verify the rotated corner computation.

        positions = {"U1": (50.0, 40.0, 90.0)}
        sizes = {"U1": 10.0}

        boxes = positions_to_boxes(positions, sizes)
        assert len(boxes) == 1

        box = boxes[0]
        # 90-degree rotation of a square centered at (50, 40) with half=5
        # corners before rotation: (-5,-5), (5,-5), (5,5), (-5,5)
        # After 90 deg rotation: (-5,5), (5,5), (5,-5), (-5,-5) -- same AABB
        # Centered at (50,40): (45,35)-(55,45)
        assert box.x1 == pytest.approx(45.0)
        assert box.y1 == pytest.approx(35.0)
        assert box.x2 == pytest.approx(55.0)
        assert box.y2 == pytest.approx(45.0)

        # Now test with 45 degree rotation -- should produce larger AABB
        positions_45 = {"U1": (50.0, 40.0, 45.0)}
        boxes_45 = positions_to_boxes(positions_45, sizes)
        box_45 = boxes_45[0]

        # Original half-diagonal is 5, rotated by 45 degrees
        # corner (-5,-5) rotated 45: (-5*cos45 - (-5)*sin45, -5*sin45 + (-5)*cos45)
        # = (-5*0.707 + 5*0.707, -5*0.707 - 5*0.707) = (0, -7.07)
        # AABB height should be ~14.14 (2 * 5 * sqrt(2))
        expected_half = 5.0 * math.sqrt(2)
        assert box_45.x2 - box_45.x1 == pytest.approx(2 * expected_half, abs=0.01)
        assert box_45.y2 - box_45.y1 == pytest.approx(2 * expected_half, abs=0.01)

    def test_positions_to_boxes_default_size(self) -> None:
        """Component not in sizes dict defaults to 2.0mm size."""
        positions = {"X1": (50.0, 40.0, 0.0)}
        sizes: dict[str, float] = {}  # Empty -- X1 not found

        boxes = positions_to_boxes(positions, sizes)
        assert len(boxes) == 1

        box = boxes[0]
        # Default size 2.0 -> half=1.0 -> (49,39)-(51,41)
        assert box.x1 == pytest.approx(49.0)
        assert box.y1 == pytest.approx(39.0)
        assert box.x2 == pytest.approx(51.0)
        assert box.y2 == pytest.approx(41.0)


# ---------------------------------------------------------------------------
# PlacementValidator tests
# ---------------------------------------------------------------------------


class TestPlacementValidator:
    """Tests for the PlacementValidator class."""

    def test_validate_no_violations(self) -> None:
        """Three well-separated components on 100x80 board: valid."""
        positions = {
            "R1": (20.0, 20.0, 0.0),
            "U1": (50.0, 40.0, 0.0),
            "C1": (80.0, 60.0, 0.0),
        }
        sizes = {"R1": 2.0, "U1": 10.0, "C1": 2.0}

        validator = PlacementValidator(board_width=100.0, board_height=80.0)
        is_valid, violations = validator.validate(positions, sizes)

        assert is_valid is True
        assert len(violations) == 0

    def test_validate_clearance_violation(self) -> None:
        """Two components within min_clearance distance: violation detected."""
        # Place two small components close together
        positions = {
            "R1": (20.0, 20.0, 0.0),
            "R2": (21.0, 20.0, 0.0),  # 1mm apart centers, 2mm boxes -> overlap edge
        }
        sizes = {"R1": 2.0, "R2": 2.0}

        validator = PlacementValidator(
            board_width=100.0, board_height=80.0, min_clearance=1.0
        )
        is_valid, violations = validator.validate(positions, sizes)

        assert is_valid is False
        # Should find clearance violations (or overlap if touching)
        assert len(violations) > 0
        # At least one violation mentions R1 and R2
        refs_in_violations = set()
        for v in violations:
            refs_in_violations.update(v.component_refs)
        assert "R1" in refs_in_violations
        assert "R2" in refs_in_violations

    def test_validate_overlap(self) -> None:
        """Two components at same position: overlap detected with critical severity."""
        positions = {
            "R1": (50.0, 40.0, 0.0),
            "R2": (50.0, 40.0, 0.0),  # Same position
        }
        sizes = {"R1": 2.0, "R2": 2.0}

        validator = PlacementValidator(board_width=100.0, board_height=80.0)
        is_valid, violations = validator.validate(positions, sizes)

        assert is_valid is False
        overlap_violations = [v for v in violations if v.violation_type == "overlap"]
        assert len(overlap_violations) > 0
        assert overlap_violations[0].severity == "critical"

    def test_validate_bounds_violation(self) -> None:
        """Component partially outside board: bounds violation detected."""
        # Place component near edge so its bounding box extends outside
        positions = {"U1": (-5.0, 40.0, 0.0)}  # Center at x=-5
        sizes = {"U1": 10.0}  # half=5, box extends from -10 to 0

        validator = PlacementValidator(board_width=100.0, board_height=80.0)
        is_valid, violations = validator.validate(positions, sizes)

        assert is_valid is False
        bounds_violations = [v for v in violations if v.violation_type == "bounds"]
        assert len(bounds_violations) > 0
        assert bounds_violations[0].severity == "critical"
        assert "U1" in bounds_violations[0].component_refs

    def test_validate_convenience_function(self) -> None:
        """validate_placement convenience function works with PlacementGraph."""
        # Build graph from sample components
        from volta.generation.intent import ComponentSpec

        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R_Small_US", reference="R2", value="4.7k"),
        ]
        nets = []  # No nets needed for validation
        graph = netlist_to_placement_graph(
            components, nets, board_width=100.0, board_height=80.0
        )
        pg = PlacementGraph(graph)

        # Place components well apart
        positions = {
            "R1": (20.0, 20.0, 0.0),
            "R2": (80.0, 60.0, 0.0),
        }

        is_valid, violations = validate_placement(pg, positions)
        assert is_valid is True
        assert len(violations) == 0

    def test_validate_with_spatial_engine(self) -> None:
        """Full validation returns structured dict with all expected keys."""
        positions = {
            "R1": (20.0, 20.0, 0.0),
            "U1": (50.0, 40.0, 0.0),
            "C1": (80.0, 60.0, 0.0),
        }
        sizes = {"R1": 2.0, "U1": 10.0, "C1": 2.0}

        validator = PlacementValidator(board_width=100.0, board_height=80.0)
        result = validator.validate_with_spatial_engine(positions, sizes)

        # Check all expected keys
        assert "valid" in result
        assert "violations" in result
        assert "placement_violations" in result
        assert "min_clearance_found_mm" in result
        assert "n_components" in result
        assert "board_utilization" in result

        assert result["valid"] is True
        assert isinstance(result["violations"], list)
        assert isinstance(result["placement_violations"], list)
        assert isinstance(result["min_clearance_found_mm"], float)
        assert result["n_components"] == 3
        assert isinstance(result["board_utilization"], float)

    def test_validate_board_utilization(self) -> None:
        """Board utilization computed for known sizes on known board."""
        # Two 2mm x 2mm components on 100x80 board = 8 sq mm / 8000 sq mm
        positions = {
            "R1": (20.0, 20.0, 0.0),
            "R2": (80.0, 60.0, 0.0),
        }
        sizes = {"R1": 2.0, "R2": 2.0}

        validator = PlacementValidator(board_width=100.0, board_height=80.0)
        result = validator.validate_with_spatial_engine(positions, sizes)

        # 2 components * 2mm * 2mm = 8 sq mm
        # Board = 100 * 80 = 8000 sq mm
        # Utilization = 8 / 8000 = 0.001
        assert result["board_utilization"] == pytest.approx(0.001)

    def test_validate_empty_positions(self) -> None:
        """Empty positions dict returns valid=True."""
        validator = PlacementValidator(board_width=100.0, board_height=80.0)
        is_valid, violations = validator.validate({}, {})

        assert is_valid is True
        assert len(violations) == 0

    def test_validate_component_cap(self) -> None:
        """501 components raises ValueError."""
        positions = {f"R{i}": (float(i), 20.0, 0.0) for i in range(501)}
        sizes = {f"R{i}": 2.0 for i in range(501)}

        validator = PlacementValidator(board_width=10000.0, board_height=10000.0)
        with pytest.raises(ValueError, match="exceeds maximum"):
            validator.validate(positions, sizes)
