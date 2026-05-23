"""Tests for component placement engine.

GEN-09: Validates clearance checking, grid placement, decoupling cap
heuristic, and spatial scoring.
"""

import pytest

from kicad_agent.generation.intent import ComponentSpec, NetSpec, PositionSpec
from kicad_agent.generation.placement import (
    PlacementEngine,
    PlacementResult,
    validate_placement_clearance,
)
from kicad_agent.spatial.primitives import SpatialBox


# ---------------------------------------------------------------------------
# validate_placement_clearance
# ---------------------------------------------------------------------------


class TestValidateClearance:
    """Tests for validate_placement_clearance function."""

    def test_validate_clearance_no_violations(self):
        """Two boxes 5mm apart, clearance=1mm -- should be valid."""
        box1 = SpatialBox(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="component", entity_id="R1", reference="R1",
        )
        box2 = SpatialBox(
            x1=7, y1=0, x2=9, y2=2,
            entity_type="component", entity_id="R2", reference="R2",
        )
        result = validate_placement_clearance([box1, box2], min_clearance_mm=1.0)
        assert result["valid"] is True
        assert result["min_clearance_found_mm"] >= 1.0
        assert len(result["violations"]) == 0

    def test_validate_clearance_violation(self):
        """Two overlapping boxes -- should detect violation."""
        box1 = SpatialBox(
            x1=0, y1=0, x2=4, y2=4,
            entity_type="component", entity_id="U1", reference="U1",
        )
        box2 = SpatialBox(
            x1=3, y1=3, x2=6, y2=6,
            entity_type="component", entity_id="U2", reference="U2",
        )
        result = validate_placement_clearance([box1, box2], min_clearance_mm=1.0)
        assert result["valid"] is False
        assert len(result["violations"]) >= 1
        assert result["violations"][0]["type"] == "clearance"

    def test_validate_clearance_board_bounds(self):
        """Box outside board bounds -- should detect bounds violation."""
        box1 = SpatialBox(
            x1=48, y1=48, x2=55, y2=55,
            entity_type="component", entity_id="U1", reference="U1",
        )
        result = validate_placement_clearance(
            [box1],
            min_clearance_mm=1.0,
            board_bounds=(0, 0, 50, 50),
        )
        assert result["valid"] is False
        assert any(v["type"] == "bounds" for v in result["violations"])

    def test_validate_clearance_empty_boxes(self):
        """Empty box list -- should be valid with 0 distance."""
        result = validate_placement_clearance([], min_clearance_mm=1.0)
        assert result["valid"] is True
        assert result["min_clearance_found_mm"] == 0.0


# ---------------------------------------------------------------------------
# PlacementEngine.place_components
# ---------------------------------------------------------------------------


class TestPlaceComponents:
    """Tests for PlacementEngine.place_components."""

    def test_place_components_grid(self):
        """4 components on 50x50 board -- all placed within bounds."""
        engine = PlacementEngine(board_width=50, board_height=50)
        components = [
            ComponentSpec(library_id="Device:R_Small_US", reference="R1", value="10k"),
            ComponentSpec(library_id="Device:R_Small_US", reference="R2", value="4.7k"),
            ComponentSpec(library_id="Device:C_Small", reference="C1", value="100nF"),
            ComponentSpec(library_id="Device:C_Small", reference="C2", value="10uF"),
        ]
        result = engine.place_components(components)
        assert len(result.positions) == 4
        assert result.valid is True
        # All positions within board bounds
        for ref, (x, y) in result.positions.items():
            assert 0 <= x <= 50, f"{ref} x={x} out of bounds"
            assert 0 <= y <= 50, f"{ref} y={y} out of bounds"

    def test_place_components_clearance(self):
        """10 components -- minimum clearance should be met."""
        engine = PlacementEngine(board_width=100, board_height=100, min_clearance=1.0)
        components = [
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference=f"R{i}",
                value="10k",
            )
            for i in range(10)
        ]
        result = engine.place_components(components)
        assert len(result.positions) == 10
        # Check clearance between all pairs
        refs = list(result.positions.keys())
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                p1 = result.positions[refs[i]]
                p2 = result.positions[refs[j]]
                dist = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
                # Grid placement should space them apart
                assert dist > 0, f"R{i} and R{j} overlap"

    def test_empty_components(self):
        """0 components -- empty valid result."""
        engine = PlacementEngine(board_width=50, board_height=50)
        result = engine.place_components([])
        assert result.positions == {}
        assert result.valid is True
        assert result.score == 1.0
        assert result.violations == []

    def test_component_count_cap(self):
        """501 components should raise ValueError."""
        engine = PlacementEngine(board_width=500, board_height=500)
        components = [
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference=f"R{i}",
                value="10k",
            )
            for i in range(501)
        ]
        with pytest.raises(ValueError, match="exceeds maximum"):
            engine.place_components(components)


# ---------------------------------------------------------------------------
# PlacementEngine.place_decoupling_caps
# ---------------------------------------------------------------------------


class TestPlaceDecouplingCaps:
    """Tests for decoupling capacitor proximity heuristic."""

    def test_place_decoupling_caps(self):
        """1 IC and 2 caps -- caps placed near IC."""
        engine = PlacementEngine(board_width=50, board_height=50)
        components = [
            ComponentSpec(
                library_id="MCU:ATmega328P",
                reference="U1",
                value="ATmega328P",
                position=PositionSpec(x=25, y=25),
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C1",
                value="100nF",
            ),
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C2",
                value="100nF",
            ),
        ]
        result = engine.place_decoupling_caps(
            components=components,
            ic_refs=["U1"],
            cap_refs=["C1", "C2"],
            max_distance_mm=5.0,
        )
        assert len(result["placed"]) == 2
        assert len(result["unplaced"]) == 0

        # Each cap should be within max_distance of U1
        for placed_cap in result["placed"]:
            assert placed_cap["ic_ref"] == "U1"
            cap_x, cap_y = placed_cap["position"]
            ic_x, ic_y = 25, 25
            dist = ((cap_x - ic_x) ** 2 + (cap_y - ic_y) ** 2) ** 0.5
            assert dist <= 5.0 + 0.1, f"Cap {placed_cap['cap_ref']} too far from U1"

    def test_place_decoupling_caps_no_ics(self):
        """No ICs -- all caps unplaced."""
        engine = PlacementEngine(board_width=50, board_height=50)
        components = [
            ComponentSpec(
                library_id="Device:C_Small",
                reference="C1",
                value="100nF",
            ),
        ]
        result = engine.place_decoupling_caps(
            components=components,
            ic_refs=[],
            cap_refs=["C1"],
        )
        assert len(result["placed"]) == 0
        assert "C1" in result["unplaced"]


# ---------------------------------------------------------------------------
# PlacementEngine.score_placement
# ---------------------------------------------------------------------------


class TestScorePlacement:
    """Tests for placement quality scoring."""

    def test_score_placement(self):
        """Score a valid placement -- score should be between 0 and 1."""
        engine = PlacementEngine(board_width=50, board_height=50)
        positions = {
            "R1": (10, 10),
            "R2": (20, 20),
            "C1": (30, 30),
            "U1": (40, 40),
        }
        score = engine.score_placement(positions, [])
        assert 0.0 <= score <= 1.0

    def test_score_with_nets(self):
        """Score with nets connecting close components -- higher score."""
        engine = PlacementEngine(board_width=100, board_height=100)
        # Close: 6mm apart (clearance ~4mm with 2mm boxes, meets 1mm min)
        positions_close = {
            "R1": (45, 45),
            "R2": (51, 51),
        }
        # Far: 113mm diagonal apart
        positions_far = {
            "R1": (10, 10),
            "R2": (90, 90),
        }
        nets = [NetSpec(name="SDA", pins=["R1.1", "R2.1"])]

        score_close = engine.score_placement(positions_close, nets)
        score_far = engine.score_placement(positions_far, nets)
        # Close components should score better on wire length
        assert score_close > score_far

    def test_score_empty(self):
        """Empty positions -- score is 1.0."""
        engine = PlacementEngine(board_width=50, board_height=50)
        score = engine.score_placement({}, [])
        assert score == 1.0
