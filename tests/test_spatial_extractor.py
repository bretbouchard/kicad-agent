"""Tests for spatial primitive extraction from PcbIR.

VP-02: Validates extraction of spatial points, boxes, paths, and regions
from PCB fixtures. Arduino_Mega has footprints with pads but no routed
traces, vias, or zones. RaspberryPi has a zone.
"""

import math
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.parser import parse_pcb
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.spatial.extractor import (
    extract_all,
    extract_boxes,
    extract_paths,
    extract_points,
    extract_regions,
)
from kicad_agent.spatial.primitives import SpatialBox, SpatialPath, SpatialPoint

from conftest import FIXTURE_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcb_ir(pcb_path: Path) -> PcbIR:
    """Build a PcbIR from a PCB file path (fresh registry each call)."""
    _clear_registry()
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


@pytest.fixture
def arduino_pcb_ir() -> PcbIR:
    """PcbIR built from Arduino_Mega.kicad_pcb (has footprints+pads, no traces)."""
    pcb_path = FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"
    return _make_pcb_ir(pcb_path)


@pytest.fixture
def rpi_pcb_ir() -> PcbIR:
    """PcbIR built from RaspberryPi-uHAT.kicad_pcb (has a zone)."""
    pcb_path = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"
    return _make_pcb_ir(pcb_path)


# ---------------------------------------------------------------------------
# extract_points
# ---------------------------------------------------------------------------


class TestExtractPoints:
    """Tests for pad and via point extraction."""

    def test_extract_points_returns_pad_points(self, arduino_pcb_ir: PcbIR):
        """Arduino_Mega has footprints with pads; extract_points returns them."""
        points = extract_points(arduino_pcb_ir)
        pad_points = [p for p in points if p.entity_type == "pad"]

        assert len(pad_points) >= 1, "Should extract at least 1 pad point"

        for pt in pad_points:
            assert pt.entity_type == "pad"
            assert math.isfinite(pt.x)
            assert math.isfinite(pt.y)

    def test_extract_points_all_have_valid_entity_types(self, arduino_pcb_ir: PcbIR):
        """All points have entity_type in expected set."""
        points = extract_points(arduino_pcb_ir)
        valid_types = {"via", "pad"}

        for pt in points:
            assert pt.entity_type in valid_types, (
                f"Unexpected entity_type: {pt.entity_type}"
            )

    def test_extract_points_returns_list(self, arduino_pcb_ir: PcbIR):
        """extract_points returns a list even with no vias."""
        points = extract_points(arduino_pcb_ir)
        assert isinstance(points, list)
        # Arduino_Mega has pads, so total should be > 0
        assert len(points) >= 1

    def test_pad_positions_are_absolute(self, arduino_pcb_ir: PcbIR):
        """Pad positions are NOT clustered at (0,0) -- they are absolute.

        If pad positions were local (not translated), they would cluster
        near the footprint origin. Absolute positions should be spread
        across the board.
        """
        points = extract_points(arduino_pcb_ir)
        pad_points = [p for p in points if p.entity_type == "pad"]

        # At least some pads should be far from (0,0)
        far_from_origin = [p for p in pad_points if abs(p.x) > 5.0 or abs(p.y) > 5.0]
        assert len(far_from_origin) >= 1, (
            "Pad positions appear to be local (clustered near origin). "
            "Check absolute position computation."
        )

    def test_pad_entity_ids_include_ref_and_number(self, arduino_pcb_ir: PcbIR):
        """Pad entity_id format is '{reference}.{pad_number}'."""
        points = extract_points(arduino_pcb_ir)
        pad_points = [p for p in points if p.entity_type == "pad"]

        for pt in pad_points:
            # Entity ID should contain a dot separating ref from pad number
            assert "." in pt.entity_id, (
                f"Pad entity_id should contain '.': {pt.entity_id}"
            )


# ---------------------------------------------------------------------------
# extract_boxes
# ---------------------------------------------------------------------------


class TestExtractBoxes:
    """Tests for footprint bounding box extraction."""

    def test_extract_boxes_returns_footprint_boxes(self, arduino_pcb_ir: PcbIR):
        """Extract at least 1 footprint box with valid geometry."""
        boxes = extract_boxes(arduino_pcb_ir)

        assert len(boxes) >= 1, "Should extract at least 1 footprint box"

        for box in boxes:
            assert box.entity_type == "footprint"
            assert box.x1 < box.x2, "x1 should be less than x2"
            assert box.y1 < box.y2, "y1 should be less than y2"

    def test_extract_boxes_have_references(self, arduino_pcb_ir: PcbIR):
        """Extracted boxes have reference designators."""
        boxes = extract_boxes(arduino_pcb_ir)

        # At least some boxes should have non-empty references
        with_ref = [b for b in boxes if b.reference]
        assert len(with_ref) >= 1, "Some boxes should have reference designators"


# ---------------------------------------------------------------------------
# extract_paths
# ---------------------------------------------------------------------------


class TestExtractPaths:
    """Tests for trace path extraction."""

    def test_extract_paths_returns_list(self, arduino_pcb_ir: PcbIR):
        """extract_paths returns a list (may be empty for unrouted boards)."""
        paths = extract_paths(arduino_pcb_ir)
        assert isinstance(paths, list)

    def test_extract_paths_items_have_valid_structure(self, arduino_pcb_ir: PcbIR):
        """Any extracted paths have correct entity_type and at least 2 points."""
        paths = extract_paths(arduino_pcb_ir)

        for path in paths:
            assert path.entity_type in {"segment", "arc"}
            assert len(path.points) >= 2, "Each path should have at least 2 points"

    def test_extract_paths_segment_paths_have_two_points(self, arduino_pcb_ir: PcbIR):
        """Segment paths have exactly 2 points."""
        paths = extract_paths(arduino_pcb_ir)
        segments = [p for p in paths if p.entity_type == "segment"]

        for seg in segments:
            assert len(seg.points) == 2


# ---------------------------------------------------------------------------
# extract_regions
# ---------------------------------------------------------------------------


class TestExtractRegions:
    """Tests for zone region extraction."""

    def test_extract_regions_returns_zones(self, rpi_pcb_ir: PcbIR):
        """RaspberryPi has a zone; extract_regions finds it."""
        regions = extract_regions(rpi_pcb_ir)

        assert len(regions) >= 1, "RaspberryPi should have at least 1 zone"

        for region in regions:
            assert region.entity_type == "zone"
            assert len(region.boundary) >= 3, "Zone boundary needs at least 3 vertices"

    def test_extract_regions_returns_list_for_empty(self, arduino_pcb_ir: PcbIR):
        """Arduino_Mega has no zones; extract_regions returns empty list."""
        regions = extract_regions(arduino_pcb_ir)
        assert isinstance(regions, list)


# ---------------------------------------------------------------------------
# extract_all
# ---------------------------------------------------------------------------


class TestExtractAll:
    """Tests for the combined extract_all function."""

    def test_extract_all_returns_all_types(self, arduino_pcb_ir: PcbIR):
        """extract_all returns dict with all 4 keys, each a list."""
        result = extract_all(arduino_pcb_ir)

        assert "points" in result
        assert "boxes" in result
        assert "paths" in result
        assert "regions" in result

        assert isinstance(result["points"], list)
        assert isinstance(result["boxes"], list)
        assert isinstance(result["paths"], list)
        assert isinstance(result["regions"], list)

    def test_extract_all_consistent_with_individual(self, arduino_pcb_ir: PcbIR):
        """extract_all matches individual extraction functions."""
        all_result = extract_all(arduino_pcb_ir)

        assert len(all_result["points"]) == len(extract_points(arduino_pcb_ir))
        assert len(all_result["boxes"]) == len(extract_boxes(arduino_pcb_ir))
        assert len(all_result["paths"]) == len(extract_paths(arduino_pcb_ir))
        assert len(all_result["regions"]) == len(extract_regions(arduino_pcb_ir))
