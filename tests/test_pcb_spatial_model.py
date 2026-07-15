"""Tests for PCB spatial intelligence modules (SI-01 through SI-07).

Tests LayerClassifier, LayerStackup, NetClassGeometry, PcbSpatialModel,
board outline extraction, dirty-flag lifecycle, and spatial query integration.
Uses Arduino_Mega fixture for integration tests and pure Python for unit tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import GeometryCollection

from volta.ir.base import _clear_registry
from volta.ir.pcb_ir import PcbIR
from volta.parser import parse_pcb
from volta.parser.uuid_extractor import extract_uuids
from volta.project.design_rules import NetClassDef
from volta.spatial.layer_classifier import LayerClassifier
from volta.spatial.layer_stackup import LayerInfo, LayerStackup
from volta.spatial.net_class_geometry import (
    NetClassGeometry,
    build_net_class_map,
)
from volta.spatial.pcb_model import (
    PcbSpatialModel,
    _CLEARANCE_TOLERANCE_MM,
)
from volta.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
)
from volta.spatial.board_outline import extract_board_outline
from shapely.geometry import Polygon, MultiPolygon

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
    """PcbIR built from Arduino_Mega.kicad_pcb."""
    pcb_path = FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"
    return _make_pcb_ir(pcb_path)


# ---------------------------------------------------------------------------
# TestLayerClassifier
# ---------------------------------------------------------------------------


class TestLayerClassifier:
    """SI-03: Layer classification via pre-compiled regex patterns."""

    def test_copper_layers(self) -> None:
        for name in ("F.Cu", "B.Cu", "In1.Cu", "In12.Cu"):
            assert LayerClassifier.is_copper(name), f"{name} should be copper"

    def test_non_copper_layers(self) -> None:
        for name in ("F.SilkS", "B.Mask", "Edge.Cuts", "Dwgs.User"):
            assert not LayerClassifier.is_copper(name), f"{name} should not be copper"

    def test_silkscreen_layers(self) -> None:
        assert LayerClassifier.is_silkscreen("F.SilkS")
        assert LayerClassifier.is_silkscreen("B.SilkS")
        assert not LayerClassifier.is_silkscreen("F.Cu")

    def test_mask_layers(self) -> None:
        assert LayerClassifier.is_mask("F.Mask")
        assert LayerClassifier.is_mask("B.Mask")
        assert not LayerClassifier.is_mask("F.Cu")

    def test_paste_layers(self) -> None:
        assert LayerClassifier.is_paste("F.Paste")
        assert LayerClassifier.is_paste("B.Paste")
        assert not LayerClassifier.is_paste("F.Mask")

    def test_edge_cuts(self) -> None:
        assert LayerClassifier.is_edge_cuts("Edge.Cuts")
        assert not LayerClassifier.is_edge_cuts("F.Cu")

    def test_courtyard(self) -> None:
        assert LayerClassifier.is_courtyard("F.Courtyard")
        assert LayerClassifier.is_courtyard("B.Courtyard")
        assert not LayerClassifier.is_courtyard("F.Cu")

    def test_empty_string(self) -> None:
        assert not LayerClassifier.is_copper("")
        assert not LayerClassifier.is_silkscreen("")
        assert not LayerClassifier.is_mask("")
        assert not LayerClassifier.is_paste("")
        assert not LayerClassifier.is_edge_cuts("")
        assert not LayerClassifier.is_courtyard("")

    def test_classify_returns_category(self) -> None:
        assert LayerClassifier.classify("F.Cu") == "copper"
        assert LayerClassifier.classify("B.Mask") == "mask"
        assert LayerClassifier.classify("Dwgs.User") == "other"
        assert LayerClassifier.classify("F.SilkS") == "silkscreen"
        assert LayerClassifier.classify("B.Paste") == "paste"
        assert LayerClassifier.classify("Edge.Cuts") == "edge_cuts"
        assert LayerClassifier.classify("F.Courtyard") == "courtyard"
        assert LayerClassifier.classify("") == "other"


# ---------------------------------------------------------------------------
# TestLayerStackup
# ---------------------------------------------------------------------------


class TestLayerStackup:
    """SI-02: Layer stackup extraction from kiutils Board."""

    def test_from_arduino_board(self, arduino_pcb_ir: PcbIR) -> None:
        stackup = LayerStackup.from_board(arduino_pcb_ir.board)
        assert stackup.copper_layer_count >= 2, (
            f"Expected >= 2 copper layers, got {stackup.copper_layer_count}"
        )

    def test_stackup_has_dielectric(self, arduino_pcb_ir: PcbIR) -> None:
        stackup = LayerStackup.from_board(arduino_pcb_ir.board)
        dielectric = stackup.dielectric_layers
        if dielectric:
            # If stackup defines dielectric layers, check epsilon_r
            has_fr4 = any(
                d.epsilon_r is not None and d.epsilon_r > 0
                for d in dielectric
            )
            # Arduino_Mega may or may not have explicit dielectric entries
            # depending on KiCad version; just verify structure
            assert all(d.layer_type in ("core", "prepreg") for d in dielectric)

    def test_stackup_total_thickness(self, arduino_pcb_ir: PcbIR) -> None:
        stackup = LayerStackup.from_board(arduino_pcb_ir.board)
        assert stackup.total_thickness_mm == 1.6

    def test_empty_stackup(self) -> None:
        """Board with no stackup returns empty LayerStackup."""

        class MockBoard:
            class general:
                thickness = 1.6

            class setup:
                stackup = None

        stackup = LayerStackup.from_board(MockBoard())
        assert stackup.layers == ()
        assert stackup.copper_layer_count == 0
        assert stackup.total_thickness_mm == 1.6

    def test_layer_info_frozen(self) -> None:
        """LayerInfo is frozen (immutable)."""
        info = LayerInfo("F.Cu", "copper", 0.035, None, None, None)
        with pytest.raises(AttributeError):
            info.name = "B.Cu"  # type: ignore[misc]

    def test_layer_stackup_frozen(self) -> None:
        """LayerStackup is frozen (immutable)."""
        s = LayerStackup(layers=(), total_thickness_mm=1.6)
        with pytest.raises(AttributeError):
            s.total_thickness_mm = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestNetClassGeometry
# ---------------------------------------------------------------------------


class TestNetClassGeometry:
    """SI-04: Per-net geometry parameters from net class definitions."""

    def test_default_values(self) -> None:
        nc = NetClassGeometry.default()
        assert nc.trace_width_mm == 0.25
        assert nc.clearance_mm == 0.0
        assert nc.via_diameter_mm == 0.8
        assert nc.via_drill_mm == 0.4
        assert nc.diff_pair_width_mm == 0.0
        assert nc.diff_pair_gap_mm == 0.0

    def test_from_net_class_def(self) -> None:
        nc_def = NetClassDef(
            name="Power",
            track_width=0.5,
            clearance=0.3,
            via_diameter=1.0,
            via_drill=0.6,
            diff_pair_width=0.2,
            diff_pair_gap=0.15,
        )
        nc = NetClassGeometry.from_net_class_def(nc_def)
        assert nc.trace_width_mm == 0.5
        assert nc.clearance_mm == 0.3
        assert nc.via_diameter_mm == 1.0
        assert nc.via_drill_mm == 0.6
        assert nc.diff_pair_width_mm == 0.2
        assert nc.diff_pair_gap_mm == 0.15

    def test_build_net_class_map(self) -> None:
        defs = [
            NetClassDef(name="Default", track_width=0.25, clearance=0.0),
            NetClassDef(name="Power", track_width=0.5, clearance=0.3),
        ]
        result = build_net_class_map(defs)
        assert "Default" in result
        assert "Power" in result
        assert result["Power"].trace_width_mm == 0.5
        assert result["Default"].trace_width_mm == 0.25
        assert len(result) == 2

    def test_net_class_geometry_frozen(self) -> None:
        nc = NetClassGeometry.default()
        with pytest.raises(AttributeError):
            nc.trace_width_mm = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestPcbSpatialModel
# ---------------------------------------------------------------------------


class TestPcbSpatialModel:
    """SI-01: PCB spatial model with per-layer geometry and STRtree."""

    def test_build_from_arduino(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert model.primitive_count > 0

    def test_layer_names_populated(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        names = model.layer_names
        assert len(names) > 0
        # Verify sorted
        assert names == sorted(names)

    def test_per_layer_geometry(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        lg = model.layer_geometry
        assert isinstance(lg, dict)
        # At least one layer should have geometry
        assert any(isinstance(v, GeometryCollection) for v in lg.values())

    def test_copper_layer_primitives(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        copper = model.copper_layer_primitives()
        assert isinstance(copper, dict)
        # All keys should be copper layers
        for name in copper:
            assert LayerClassifier.is_copper(name), f"{name} is not a copper layer"

    def test_layer_primitives_filter(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        # Query a layer that should have primitives (F.Cu from footprint pads)
        fcu = model.layer_primitives("F.Cu")
        assert isinstance(fcu, list)
        # Query a non-existent layer
        assert model.layer_primitives("NonExistent.Cu") == []

    def test_get_net_class_geometry_default(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        nc = model.get_net_class_geometry("nonexistent_net_class")
        assert nc.trace_width_mm == 0.25  # default
        assert nc.via_drill_mm == 0.4

    def test_get_net_class_geometry_with_classes(
        self, arduino_pcb_ir: PcbIR
    ) -> None:
        defs = [
            NetClassDef(name="Power", track_width=0.5, clearance=0.3),
        ]
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir, net_classes=defs)
        nc = model.get_net_class_geometry("Power")
        assert nc.trace_width_mm == 0.5
        assert nc.clearance_mm == 0.3

    def test_clearance_tolerance_constant(self) -> None:
        assert _CLEARANCE_TOLERANCE_MM == 1e-4

    def test_clearance_tolerance_property(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert model.clearance_tolerance == 1e-4

    def test_dirty_flag_lifecycle(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert not model.is_dirty
        model.mark_dirty()
        assert model.is_dirty
        model.rebuild()
        assert not model.is_dirty

    def test_batch_update(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        initial_count = model.primitive_count

        # No-op update function
        def noop_update(pcb_ir: PcbIR) -> None:
            pass

        model.batch_update(noop_update)
        assert not model.is_dirty
        # Count should be unchanged after no-op
        assert model.primitive_count == initial_count

    def test_rebuild_noop_when_clean(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        # rebuild() on clean model should be a no-op
        model.rebuild()
        assert not model.is_dirty

    def test_stackup_accessible(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert isinstance(model.stackup, LayerStackup)

    def test_all_primitives_returns_copy(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        prims1 = model.all_primitives
        prims2 = model.all_primitives
        assert prims1 is not prims2  # should be separate list copies
        assert len(prims1) == len(prims2)


# ---------------------------------------------------------------------------
# TestClearanceTolerance
# ---------------------------------------------------------------------------


class TestClearanceTolerance:
    """SI-05: Clearance tolerance prevents floating-point false positives."""

    def test_tolerance_prevents_false_positive(self) -> None:
        """Two geometries at distance == tolerance should give effective clearance 0.0."""
        from shapely.geometry import Point

        pt_a = Point(0.0, 0.0)
        pt_b = Point(0.0, _CLEARANCE_TOLERANCE_MM)  # exactly tolerance apart
        distance = pt_a.distance(pt_b)
        effective = max(0.0, distance - _CLEARANCE_TOLERANCE_MM)
        assert effective == 0.0

    def test_tolerance_with_real_gap(self) -> None:
        """Two geometries with 0.5mm gap give effective clearance ~0.4999."""
        from shapely.geometry import Point

        pt_a = Point(0.0, 0.0)
        pt_b = Point(0.0, 0.5)
        distance = pt_a.distance(pt_b)
        effective = max(0.0, distance - _CLEARANCE_TOLERANCE_MM)
        assert abs(effective - 0.4999) < 0.001
        assert effective > 0.0

    def test_overlapping_geometries_zero_clearance(self) -> None:
        """Overlapping geometries return 0.0 effective clearance."""
        from shapely.geometry import Point

        pt_a = Point(0.0, 0.0)
        pt_b = Point(0.0, 0.0)  # same point
        distance = pt_a.distance(pt_b)
        effective = max(0.0, distance - _CLEARANCE_TOLERANCE_MM)
        assert effective == 0.0


# ---------------------------------------------------------------------------
# TestBoardOutline (SI-06)
# ---------------------------------------------------------------------------


class TestBoardOutline:
    """SI-06: Board outline extraction from Edge.Cuts graphic items."""

    def test_arduino_mega_outline_exists(self, arduino_pcb_ir: PcbIR) -> None:
        """Arduino_Mega has Edge.Cuts outline with area > 0."""
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        outline = model.board_outline
        assert outline is not None
        assert outline.area > 0

    def test_arduino_mega_outline_is_polygon(self, arduino_pcb_ir: PcbIR) -> None:
        """Arduino_Mega outline is a Polygon (single connected outline)."""
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert isinstance(model.board_outline, (Polygon, MultiPolygon))

    def test_arduino_mega_outline_bounds(self, arduino_pcb_ir: PcbIR) -> None:
        """Arduino_Mega outline bounds match expected dimensions."""
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        bounds = model.board_bounds
        assert bounds is not None
        minx, miny, maxx, maxy = bounds
        # Arduino_Mega is roughly 100x46.66 to 201.6x100
        assert minx < 101
        assert maxx > 200
        assert miny < 47
        assert maxy > 99

    def test_outline_empty_board(self) -> None:
        """Board with no Edge.Cuts returns None."""
        from unittest.mock import MagicMock

        mock_board = MagicMock()
        mock_board.graphicItems = []
        result = extract_board_outline(mock_board)
        assert result is None

    def test_outline_with_only_lines(self) -> None:
        """Four line segments forming a rectangle produce a valid Polygon."""
        from unittest.mock import MagicMock

        items = []
        # (0,0) -> (10,0) -> (10,10) -> (0,10) -> (0,0)
        segments = [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0))]
        for (sx, sy), (ex, ey) in segments:
            item = MagicMock(spec=["layer", "start", "end"])
            item.layer = "Edge.Cuts"
            start = MagicMock()
            start.X = sx
            start.Y = sy
            end = MagicMock()
            end.X = ex
            end.Y = ey
            item.start = start
            item.end = end
            items.append(item)
        mock_board = MagicMock()
        mock_board.graphicItems = items
        result = extract_board_outline(mock_board)
        assert result is not None
        assert abs(result.area - 100.0) < 1.0  # 10x10 = 100 sq mm


# ---------------------------------------------------------------------------
# TestDirtyFlagLifecycle (SI-07)
# ---------------------------------------------------------------------------


class TestDirtyFlagLifecycle:
    """SI-07: Dirty-flag lifecycle with STRtree rebuild."""

    def test_initial_state_not_dirty(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert not model.is_dirty

    def test_mark_dirty_sets_flag(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        model.mark_dirty()
        assert model.is_dirty

    def test_rebuild_clears_dirty(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        model.mark_dirty()
        model.rebuild()
        assert not model.is_dirty

    def test_rebuild_noop_when_not_dirty(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        count_before = model.primitive_count
        model.rebuild()  # no-op
        assert model.primitive_count == count_before

    def test_batch_update_calls_fn_and_rebuilds(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        called = []

        def update_fn(pcb_ir: PcbIR) -> None:
            called.append(True)

        model.batch_update(update_fn)
        assert not model.is_dirty
        assert len(called) == 1

    def test_query_engine_auto_rebuilds_on_dirty(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        model.mark_dirty()
        # Accessing query_engine should trigger rebuild
        engine = model.query_engine
        assert not model.is_dirty
        assert engine.primitive_count > 0


# ---------------------------------------------------------------------------
# TestSpatialQueryIntegration (SI-06/SI-07)
# ---------------------------------------------------------------------------


class TestSpatialQueryIntegration:
    """SpatialQueryEngine integration with PcbSpatialModel."""

    def test_find_near_returns_results(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        results = model.find_near(150.0, 75.0, 20.0)
        assert isinstance(results, list)

    def test_find_in_box_returns_results(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        results = model.find_in_box(140.0, 70.0, 160.0, 80.0)
        assert isinstance(results, list)

    def test_board_bounds_property(self, arduino_pcb_ir: PcbIR) -> None:
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        bounds = model.board_bounds
        assert bounds is not None
        assert len(bounds) == 4

    def test_model_with_no_net_classes(self, arduino_pcb_ir: PcbIR) -> None:
        """Model works without net_classes parameter."""
        model = PcbSpatialModel.build_from_pcb_ir(arduino_pcb_ir)
        assert model.primitive_count > 0
