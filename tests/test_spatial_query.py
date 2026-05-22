"""Tests for spatial query engine (VP-06).

12 tests covering SpatialQueryEngine: proximity, containment, clearance,
and attribute-based find queries. All pure unit tests with no external
dependencies beyond Shapely.
"""

from __future__ import annotations

import pytest

from kicad_agent.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
)
from kicad_agent.spatial.query import SpatialQueryEngine


@pytest.fixture
def known_primitives():
    """A known set of spatial primitives for testing queries."""
    return [
        SpatialPoint(10.0, 10.0, "via", "v1", "F.Cu", "GND"),
        SpatialPoint(50.0, 50.0, "via", "v2", "F.Cu", "VCC"),
        SpatialPoint(20.0, 20.0, "pad", "U1.1", "F.Cu", "SDA"),
        SpatialBox(15.0, 15.0, 25.0, 25.0, "footprint", "U1", "F.Cu", "U1"),
        SpatialBox(45.0, 45.0, 55.0, 55.0, "footprint", "R1", "F.Cu", "R1"),
        SpatialPath(
            ((10.0, 10.0), (20.0, 20.0), (30.0, 10.0)),
            "segment",
            "t1",
            "F.Cu",
            "SDA",
        ),
    ]


class TestEngineConstruction:
    def test_engine_builds_from_primitives(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        assert engine.primitive_count == 6

    def test_engine_handles_empty_primitives(self):
        engine = SpatialQueryEngine([])
        assert engine.primitive_count == 0
        assert engine.proximity(0.0, 0.0, 5.0) == []


class TestProximity:
    def test_proximity_finds_nearby(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.proximity(15.0, 15.0, 8.0)

        # Should find:
        # - SpatialPoint(10, 10, "via", "v1") -- distance ~7.07, within 8mm buffer
        # - SpatialBox(15-25, 15-25, "U1") -- center at (20,20), intersects buffer
        # - SpatialPath through (20,20) -- intersects buffer
        # - SpatialPoint(20, 20, "pad", "U1.1") -- distance ~7.07, within 8mm buffer
        # Should NOT find:
        # - SpatialPoint(50, 50) -- too far
        result_ids = [p.entity_id for p in results]

        assert "v1" in result_ids, f"Expected v1 in results, got {result_ids}"
        assert "U1" in result_ids, f"Expected U1 in results, got {result_ids}"
        assert "t1" in result_ids, f"Expected t1 in results, got {result_ids}"
        assert "v2" not in result_ids, f"v2 should not be in results: {result_ids}"

    def test_proximity_radius_validation(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)

        with pytest.raises(ValueError, match="must be > 0"):
            engine.proximity(0.0, 0.0, 0.0)

        with pytest.raises(ValueError, match="must be > 0"):
            engine.proximity(0.0, 0.0, -1.0)

        with pytest.raises(ValueError, match="must be <="):
            engine.proximity(0.0, 0.0, 10001.0)

    def test_proximity_rejects_non_finite_coordinates(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)

        with pytest.raises(ValueError, match="finite"):
            engine.proximity(float("nan"), 0.0, 5.0)

        with pytest.raises(ValueError, match="finite"):
            engine.proximity(0.0, float("inf"), 5.0)


class TestContainment:
    def test_containment_finds_inside(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.containment(0.0, 0.0, 30.0, 30.0)
        result_ids = [p.entity_id for p in results]

        # v1 (10,10) is contained in [0,30]x[0,30]
        assert "v1" in result_ids, f"Expected v1 in results, got {result_ids}"
        # U1.1 pad (20,20) is contained
        assert "U1.1" in result_ids, f"Expected U1.1 in results, got {result_ids}"
        # U1 box (15-25, 15-25) is contained in [0,30]x[0,30]
        assert "U1" in result_ids, f"Expected U1 in results, got {result_ids}"
        # t1 path vertices at (10,10), (20,20), (30,10) -- LineString
        # should be contained since all vertices are within [0,30]x[0,30]
        assert "t1" in result_ids, f"Expected t1 in results, got {result_ids}"
        # v2 (50,50) should NOT be contained
        assert "v2" not in result_ids, f"v2 should not be in results: {result_ids}"
        # R1 box (45-55, 45-55) should NOT be contained
        assert "R1" not in result_ids, f"R1 should not be in results: {result_ids}"

    def test_containment_strict_containment(self, known_primitives):
        """Point at exact boundary of containment box is NOT contained.

        Shapely .contains() is strict: boundary points are excluded.
        """
        engine = SpatialQueryEngine(known_primitives)
        # Query box [0, 10] x [0, 10] -- point (10, 10) is ON the boundary
        results = engine.containment(0.0, 0.0, 10.0, 10.0)
        result_ids = [p.entity_id for p in results]

        # v1 at (10, 10) is on the boundary, so Shapely contains returns False
        assert "v1" not in result_ids, (
            "Point on boundary should not be 'contained' (Shapely strict semantics)"
        )


class TestClearance:
    def test_clearance_computes_distances(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.clearance("v1", search_radius_mm=60.0)

        # v1 is at (10, 10). Results should be sorted by distance.
        assert len(results) > 0, "Expected some clearance results for v1"

        # Verify sorting: distances should be ascending
        distances = [d for _, d in results]
        assert distances == sorted(distances), "Results should be sorted by distance"

        # v2 should NOT be self-matched
        result_ids = [p.entity_id for p, _ in results]
        assert "v1" not in result_ids, "Self should be excluded from clearance"

        # R1 box (45-55, 45-55) should appear with a known distance
        assert "R1" in result_ids, f"Expected R1 in clearance results: {result_ids}"

    def test_clearance_unknown_entity(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.clearance("nonexistent")
        assert results == []


class TestFindBy:
    def test_find_by_entity_id(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.find_by_entity_id("v1")
        assert len(results) == 1
        assert results[0].x == 10.0
        assert results[0].y == 10.0
        assert results[0].entity_type == "via"

    def test_find_by_net(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.find_by_net("GND")
        assert len(results) == 1
        assert results[0].entity_id == "v1"

    def test_find_by_layer(self, known_primitives):
        engine = SpatialQueryEngine(known_primitives)
        results = engine.find_by_layer("F.Cu")
        assert len(results) == 6  # All test primitives are on F.Cu
