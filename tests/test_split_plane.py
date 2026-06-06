"""Tests for AnalyzeSplitPlaneOp operation and split_plane validation module.

Covers:
- Frozen dataclass immutability (SplitGap, SplitCrossing, SplitPlaneAnalysis)
- Schema validation (AnalyzeSplitPlaneOp defaults, custom fields, invalid inputs)
- Registry metadata (read-only, category, file_types)
- Handler registration
- Geometry helpers (_compute_zone_bounds, _boxes_overlap, _estimate_gap)
- Zone polygon extraction (_extract_zone_polygons)
- Full analysis pipeline with mock PcbIR (analyze_split_plane)
- Point extraction (_extract_point)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers: create test PcbIR backed by NativeBoard
# ---------------------------------------------------------------------------


def _make_pcb_ir(board) -> "PcbIR":
    """Create a minimal PcbIR for testing, backed by a NativeBoard.

    Uses PcbIR.__new__ to bypass __post_init__ validation (which requires
    a UUID map for kiutils path, but we use the native path).
    """
    from kicad_agent.ir.pcb_ir import PcbIR

    ir = PcbIR.__new__(PcbIR)
    ir._parse_result = type("PR", (), {
        "file_path": "test.kicad_pcb",
        "raw_content": "",
        "kiutils_obj": board,
        "file_type": "pcb",
    })()
    ir._native_board = board  # Set native board so _is_native returns True
    ir._uuid_map = None
    ir._raw_written = False
    ir._dirty = False
    return ir


def _make_board_with_zones(zones):
    """Create a NativeBoard with the given zones."""
    from kicad_agent.parser.pcb_native_types import NativeBoard

    board = NativeBoard()
    board.zones = list(zones)
    return board


# ===================================================================
# Test: Frozen dataclasses
# ===================================================================


class TestSplitGapFrozen:
    """SplitGap dataclass immutability and field access."""

    def test_fields(self) -> None:
        from kicad_agent.validation.split_plane import SplitGap

        g = SplitGap(
            zone_a_id="z0", zone_b_id="z1",
            gap_mm=0.5,
            boundary_points=((10.0, 20.0), (10.0, 30.0)),
        )
        assert g.zone_a_id == "z0"
        assert g.zone_b_id == "z1"
        assert g.gap_mm == 0.5
        assert g.boundary_points == ((10.0, 20.0), (10.0, 30.0))

    def test_frozen_immutable(self) -> None:
        from kicad_agent.validation.split_plane import SplitGap

        g = SplitGap(zone_a_id="z0", zone_b_id="z1", gap_mm=0.5, boundary_points=())
        with pytest.raises(AttributeError):
            g.gap_mm = 1.0  # type: ignore[misc]

    def test_empty_boundary_points(self) -> None:
        from kicad_agent.validation.split_plane import SplitGap

        g = SplitGap(zone_a_id="a", zone_b_id="b", gap_mm=1.0, boundary_points=())
        assert g.boundary_points == ()


class TestSplitCrossingFrozen:
    """SplitCrossing dataclass immutability and field access."""

    def test_fields(self) -> None:
        from kicad_agent.validation.split_plane import SplitCrossing

        c = SplitCrossing(
            trace_net="SIG1",
            crossing_point=(5.0, 5.0),
            zone_a="z0",
            zone_b="z1",
        )
        assert c.trace_net == "SIG1"
        assert c.crossing_point == (5.0, 5.0)
        assert c.zone_a == "z0"
        assert c.zone_b == "z1"

    def test_frozen_immutable(self) -> None:
        from kicad_agent.validation.split_plane import SplitCrossing

        c = SplitCrossing(trace_net="SIG1", crossing_point=(0, 0), zone_a="a", zone_b="b")
        with pytest.raises(AttributeError):
            c.trace_net = "OTHER"  # type: ignore[misc]


class TestSplitPlaneAnalysisDefault:
    """SplitPlaneAnalysis default/empty state."""

    def test_default_zero(self) -> None:
        from kicad_agent.validation.split_plane import SplitPlaneAnalysis

        a = SplitPlaneAnalysis(
            num_zones=0, num_splits=0, num_crossings=0,
            splits=(), crossings=(),
        )
        assert a.num_zones == 0
        assert a.num_splits == 0
        assert a.num_crossings == 0
        assert a.splits == ()
        assert a.crossings == ()

    def test_frozen(self) -> None:
        from kicad_agent.validation.split_plane import SplitPlaneAnalysis

        a = SplitPlaneAnalysis(
            num_zones=2, num_splits=1, num_crossings=0,
            splits=(), crossings=(),
        )
        with pytest.raises(AttributeError):
            a.num_zones = 99  # type: ignore[misc]


# ===================================================================
# Test: Schema validation
# ===================================================================


class TestAnalyzeSplitPlaneOpSchema:
    """AnalyzeSplitPlaneOp Pydantic schema validation."""

    def test_valid_default(self) -> None:
        from kicad_agent.ops._schema_pcb import AnalyzeSplitPlaneOp

        op = AnalyzeSplitPlaneOp(target_file="board.kicad_pcb")
        assert op.op_type == "analyze_split_plane"
        assert op.layer == "GND"
        assert op.min_gap_mm == 0.0

    def test_valid_custom(self) -> None:
        from kicad_agent.ops._schema_pcb import AnalyzeSplitPlaneOp

        op = AnalyzeSplitPlaneOp(
            target_file="board.kicad_pcb",
            layer="VCC",
            min_gap_mm=0.5,
        )
        assert op.layer == "VCC"
        assert op.min_gap_mm == 0.5

    def test_invalid_negative_gap(self) -> None:
        from kicad_agent.ops._schema_pcb import AnalyzeSplitPlaneOp

        with pytest.raises(ValidationError):
            AnalyzeSplitPlaneOp(
                target_file="board.kicad_pcb",
                min_gap_mm=-0.1,
            )

    def test_registry_entry_exists(self) -> None:
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        assert "analyze_split_plane" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["analyze_split_plane"]
        assert meta.category == "pcb"
        assert meta.is_readonly is True
        assert ".kicad_pcb" in meta.file_types

    def test_discriminated_union_accepts(self) -> None:
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({"root": {
            "op_type": "analyze_split_plane",
            "target_file": "board.kicad_pcb",
            "layer": "GND",
        }})
        assert op.root.op_type == "analyze_split_plane"


# ===================================================================
# Test: Registry and handler registration
# ===================================================================


class TestAnalyzeSplitPlaneOpRegistration:
    """Verify analyze_split_plane is registered correctly."""

    def test_registered_in_raw_catalog(self) -> None:
        from kicad_agent.ops.registry import _RAW_CATALOG

        assert "analyze_split_plane" in _RAW_CATALOG
        assert _RAW_CATALOG["analyze_split_plane"]["is_readonly"] is True
        assert _RAW_CATALOG["analyze_split_plane"]["category"] == "pcb"
        assert ".kicad_pcb" in _RAW_CATALOG["analyze_split_plane"]["file_types"]

    def test_handler_registered(self) -> None:
        from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS

        assert "analyze_split_plane" in _PCB_HANDLERS


# ===================================================================
# Test: Internal geometry helpers
# ===================================================================


class TestComputeZoneBounds:
    """_compute_zone_bounds bounding box computation."""

    def test_unit_square(self) -> None:
        from kicad_agent.validation.split_plane import _compute_zone_bounds

        box = _compute_zone_bounds(((0, 0), (10, 0), (10, 10), (0, 10)))
        assert box == (0.0, 0.0, 10.0, 10.0)

    def test_offset_square(self) -> None:
        from kicad_agent.validation.split_plane import _compute_zone_bounds

        box = _compute_zone_bounds(((5, 5), (15, 5), (15, 15), (5, 15)))
        assert box == (5.0, 5.0, 15.0, 15.0)

    def test_negative_coords(self) -> None:
        from kicad_agent.validation.split_plane import _compute_zone_bounds

        box = _compute_zone_bounds(((-10, -5), (10, -5), (10, 5), (-10, 5)))
        assert box == (-10.0, -5.0, 10.0, 5.0)


class TestBoxesOverlap:
    """_boxes_overlap proximity check."""

    def test_overlapping_boxes(self) -> None:
        from kicad_agent.validation.split_plane import _boxes_overlap

        a = (0, 0, 10, 10)
        b = (5, 5, 15, 15)
        assert _boxes_overlap(a, b) is True

    def test_adjacent_boxes(self) -> None:
        from kicad_agent.validation.split_plane import _boxes_overlap

        a = (0, 0, 10, 10)
        b = (10, 0, 20, 10)
        assert _boxes_overlap(a, b) is True

    def test_separated_boxes(self) -> None:
        from kicad_agent.validation.split_plane import _boxes_overlap

        a = (0, 0, 10, 10)
        b = (20, 0, 30, 10)
        assert _boxes_overlap(a, b) is False

    def test_with_margin(self) -> None:
        from kicad_agent.validation.split_plane import _boxes_overlap

        a = (0, 0, 10, 10)
        b = (12, 0, 22, 10)
        # Without margin: no overlap (gap=2).
        assert _boxes_overlap(a, b) is False
        # With margin=2.5: overlap detected.
        assert _boxes_overlap(a, b, margin=2.5) is True

    def test_contained_box(self) -> None:
        from kicad_agent.validation.split_plane import _boxes_overlap

        a = (0, 0, 100, 100)
        b = (10, 10, 20, 20)
        assert _boxes_overlap(a, b) is True


class TestEstimateGap:
    """_estimate_gap minimum gap between bounding boxes."""

    def test_horizontal_gap(self) -> None:
        from kicad_agent.validation.split_plane import _estimate_gap

        a = (0, 0, 10, 10)
        b = (12, 0, 22, 10)
        assert _estimate_gap(a, b) == 2.0

    def test_vertical_gap(self) -> None:
        from kicad_agent.validation.split_plane import _estimate_gap

        a = (0, 0, 10, 10)
        b = (0, 15, 10, 25)
        assert _estimate_gap(a, b) == 5.0

    def test_overlapping_boxes(self) -> None:
        from kicad_agent.validation.split_plane import _estimate_gap

        a = (0, 0, 10, 10)
        b = (5, 5, 15, 15)
        # Overlapping in both axes -> gap=0.
        assert _estimate_gap(a, b) == 0.0

    def test_diagonal_gap(self) -> None:
        from kicad_agent.validation.split_plane import _estimate_gap

        a = (0, 0, 10, 10)
        b = (13, 14, 23, 24)
        # Horizontal gap=3, vertical gap=4, min=3.
        assert _estimate_gap(a, b) == 3.0


# ===================================================================
# Test: Zone polygon extraction
# ===================================================================


class TestExtractZonePolygons:
    """_extract_zone_polygons zone filtering and polygon extraction."""

    def test_no_zones(self) -> None:
        from kicad_agent.validation.split_plane import _extract_zone_polygons

        board = _make_board_with_zones([])
        ir = _make_pcb_ir(board)
        zones = _extract_zone_polygons(ir, "GND")
        assert zones == []

    def test_matching_net(self) -> None:
        from kicad_agent.validation.split_plane import _extract_zone_polygons
        from kicad_agent.parser.pcb_native_types import NativeZone

        zone = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (100, 0), (100, 100), (0, 100)],
        )
        board = _make_board_with_zones([zone])
        ir = _make_pcb_ir(board)
        zones = _extract_zone_polygons(ir, "GND")
        assert len(zones) == 1
        assert zones[0]["id"] == "z1"
        assert len(zones[0]["polygon_points"]) == 4

    def test_wrong_net_filtered(self) -> None:
        from kicad_agent.validation.split_plane import _extract_zone_polygons
        from kicad_agent.parser.pcb_native_types import NativeZone

        zone = NativeZone(
            net_name="VCC", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (100, 0), (100, 100), (0, 100)],
        )
        board = _make_board_with_zones([zone])
        ir = _make_pcb_ir(board)
        zones = _extract_zone_polygons(ir, "GND")
        assert zones == []

    def test_zone_without_enough_points_skipped(self) -> None:
        from kicad_agent.validation.split_plane import _extract_zone_polygons
        from kicad_agent.parser.pcb_native_types import NativeZone

        zone = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[],
        )
        board = _make_board_with_zones([zone])
        ir = _make_pcb_ir(board)
        zones = _extract_zone_polygons(ir, "GND")
        assert zones == []

    def test_zone_fallback_id(self) -> None:
        from kicad_agent.validation.split_plane import _extract_zone_polygons
        from kicad_agent.parser.pcb_native_types import NativeZone

        zone = NativeZone(
            net_name="GND", layer="B.Cu", uuid="",
            polygon_points=[(0, 0), (10, 0), (10, 10), (0, 10)],
        )
        board = _make_board_with_zones([zone])
        ir = _make_pcb_ir(board)
        zones = _extract_zone_polygons(ir, "GND")
        # tstamp property returns uuid which is "", fallback to "zone_0".
        assert zones[0]["id"] == "zone_0"


# ===================================================================
# Test: Full analysis pipeline
# ===================================================================


class TestAnalyzeSplitPlaneNoZones:
    """analyze_split_plane with no zones on target net."""

    def test_empty_board(self) -> None:
        from kicad_agent.validation.split_plane import analyze_split_plane

        board = _make_board_with_zones([])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND")
        assert result.num_zones == 0
        assert result.num_splits == 0
        assert result.num_crossings == 0
        assert result.splits == ()
        assert result.crossings == ()

    def test_board_no_zones_attr(self) -> None:
        from kicad_agent.validation.split_plane import analyze_split_plane

        board = _make_board_with_zones([])
        board.zones = None  # type: ignore[assignment]
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND")
        assert result.num_zones == 0


class TestAnalyzeSplitPlaneSingleZone:
    """analyze_split_plane with only one zone (no split possible)."""

    def test_single_zone_no_split(self) -> None:
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        zone = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (100, 0), (100, 100), (0, 100)],
        )
        board = _make_board_with_zones([zone])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND")
        assert result.num_zones == 1
        assert result.num_splits == 0


class TestAnalyzeSplitPlaneTwoZones:
    """Two zones on the same net: gap detection and filtering.

    The algorithm uses _boxes_overlap with margin=1.0 to identify
    "nearby" zones (potential split candidates), then _estimate_gap
    to measure the gap. A split is only detected when:
    1. Zone bounding boxes overlap with margin=1.0 (zones are close)
    2. The estimated gap >= min_gap_mm
    """

    def test_adjacent_zones_diagonal_gap_detected(self) -> None:
        """Zones with a small diagonal gap -> split detected."""
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 40), (0, 40)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(40.3, 40.3), (80, 40.3), (80, 80), (40.3, 80)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND", min_gap_mm=0.0)
        # Boxes: a=(0,0,40,40), b=(40.3,40.3,80,80).
        # Overlap with margin=1.0: 40+1=41 >= 40.3 -> yes, 40+1=41 >= 40.3 -> yes.
        # Gap: gap_x=40.3-40=0.3, gap_y=40.3-40=0.3. min(0.3,0.3)=0.3.
        assert result.num_zones == 2
        assert result.num_splits == 1
        assert result.splits[0].zone_a_id == "z1"
        assert result.splits[0].zone_b_id == "z2"
        assert result.splits[0].gap_mm == 0.3

    def test_overlapping_zones_zero_gap(self) -> None:
        """Overlapping zones have zero gap -> split with min_gap_mm=0.

        With min_gap_mm=0 (default), even touching/overlapping zones
        produce a split entry since gap >= 0 is True. Use min_gap_mm > 0
        to filter out non-splits.
        """
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 40), (0, 40)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(20, 20), (60, 20), (60, 60), (20, 60)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND")
        # Overlapping in both axes -> _estimate_gap returns 0.0.
        # With min_gap_mm=0, 0.0 >= 0.0 is True -> split detected.
        assert result.num_zones == 2
        assert result.num_splits == 1
        assert result.splits[0].gap_mm == 0.0

    def test_overlapping_zones_filtered_by_min_gap(self) -> None:
        """Overlapping zones filtered out with min_gap_mm > 0."""
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 40), (0, 40)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(20, 20), (60, 20), (60, 60), (20, 60)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND", min_gap_mm=0.01)
        # Overlapping zones have gap=0.0 which is < 0.01 -> filtered.
        assert result.num_zones == 2
        assert result.num_splits == 0

    def test_far_apart_zones_not_split(self) -> None:
        """Zones too far apart (>1mm margin) -> not a split candidate."""
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 40), (0, 40)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(60, 0), (100, 0), (100, 40), (60, 40)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND")
        # Boxes: a=(0,0,40,40), b=(60,0,100,40).
        # _boxes_overlap(margin=1.0): 40+1=41 < 60 -> no overlap.
        assert result.num_zones == 2
        assert result.num_splits == 0

    def test_wrong_net_not_counted(self) -> None:
        """Zones on different net are not counted."""
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="VCC", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 40), (0, 40)],
        )
        z2 = NativeZone(
            net_name="VCC", layer="B.Cu", uuid="z2",
            polygon_points=[(40.3, 40.3), (80, 40.3), (80, 80), (40.3, 80)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND")
        assert result.num_zones == 0
        assert result.num_splits == 0

    def test_min_gap_filter(self) -> None:
        """Gaps below min_gap_mm threshold are filtered out."""
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 40), (0, 40)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(40.3, 40.3), (80, 40.3), (80, 80), (40.3, 80)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        # Gap is 0.3mm. With min_gap_mm=0.5, it should be filtered.
        result = analyze_split_plane(ir, layer="GND", min_gap_mm=0.5)
        assert result.num_splits == 0

    def test_single_axis_gap_split_detected(self) -> None:
        """Zones overlapping in one axis with gap in other -> split detected.

        _estimate_gap handles single-axis gaps: returns the non-zero gap.
        """
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        # Pure horizontal gap, overlapping in y.
        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (40, 0), (40, 100), (0, 100)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(40.5, 0), (80, 0), (80, 100), (40.5, 100)],
        )
        board = _make_board_with_zones([z1, z2])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND", min_gap_mm=0.0)
        assert result.num_zones == 2
        # gap_x=0.5, gap_y < 0 -> _estimate_gap returns 0.5.
        assert result.num_splits == 1
        assert result.splits[0].gap_mm == 0.5

    def test_three_zones_pairwise(self) -> None:
        """Three zones: two close (split), one far (no split)."""
        from kicad_agent.validation.split_plane import analyze_split_plane
        from kicad_agent.parser.pcb_native_types import NativeZone

        z1 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z1",
            polygon_points=[(0, 0), (30, 0), (30, 30), (0, 30)],
        )
        z2 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z2",
            polygon_points=[(30.3, 30.3), (60, 30.3), (60, 60), (30.3, 60)],
        )
        z3 = NativeZone(
            net_name="GND", layer="B.Cu", uuid="z3",
            polygon_points=[(200, 200), (240, 200), (240, 240), (200, 240)],
        )
        board = _make_board_with_zones([z1, z2, z3])
        ir = _make_pcb_ir(board)
        result = analyze_split_plane(ir, layer="GND", min_gap_mm=0.0)
        assert result.num_zones == 3
        # z1-z2 are close -> 1 split. z3 is far from both -> no split.
        assert result.num_splits == 1


# ===================================================================
# Test: Point extraction
# ===================================================================


class TestExtractPoint:
    """_extract_point handles various point representations."""

    def test_tuple(self) -> None:
        from kicad_agent.validation.split_plane import _extract_point

        assert _extract_point((2.5, 3.5)) == (2.5, 3.5)

    def test_list(self) -> None:
        from kicad_agent.validation.split_plane import _extract_point

        assert _extract_point([1.0, 2.0]) == (1.0, 2.0)

    def test_uppercase_xy(self) -> None:
        from kicad_agent.validation.split_plane import _extract_point

        pt = type("P", (), {"X": 3.0, "Y": 7.0})()
        assert _extract_point(pt) == (3.0, 7.0)

    def test_lowercase_xy(self) -> None:
        from kicad_agent.validation.split_plane import _extract_point

        pt = type("P", (), {"x": 4.0, "y": 8.0})()
        assert _extract_point(pt) == (4.0, 8.0)

    def test_none_fallback(self) -> None:
        from kicad_agent.validation.split_plane import _extract_point

        assert _extract_point(None) == (0.0, 0.0)
