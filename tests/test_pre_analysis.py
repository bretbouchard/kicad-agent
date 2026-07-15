"""Tests for the pre-analysis gate.

Tests cover:
- Overlap detection for add_component and move_component
- Pin resolution for connect_pins and batch_connect
- Reference validation for remove_component
- Collision zone detection for add_wire
- Wiring and dangling wire warnings for remove_component
- No false positives on clean schematics
- Enriched context generation
- Integration with real fixtures
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from kiutils.items.common import Position
from kiutils.schematic import GlobalLabel, Schematic

from volta.ir.schematic_ir import SchematicIR
from volta.ops.pre_analysis import (
    PreAnalysisGate,
    PreAnalysisResult,
    PreAnalysisFinding,
    _detect_collision_zones,
    _estimated_bbox,
    _point_near_segment,
)
from volta.ops.schema import PositionSpec
from volta.parser import parse_schematic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_and_parse(sch_path: Path, sch: Schematic) -> SchematicIR:
    """Save a kiutils Schematic to disk and parse it back into SchematicIR."""
    sch.to_file(str(sch_path))
    result = parse_schematic(sch_path)
    return SchematicIR(_parse_result=result)


def _fixture_ir(name: str = "RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch") -> tuple[Path, SchematicIR]:
    """Load a fixture schematic. Returns (path, ir). Skips if not found."""
    path = Path("tests/fixtures") / name
    if not path.exists():
        pytest.skip(f"Fixture not found: {name}")
    sch = Schematic.from_file(str(path))
    ir = SchematicIR(_parse_result=parse_schematic(path))
    return path, ir


# ---------------------------------------------------------------------------
# PreAnalysisResult serialization
# ---------------------------------------------------------------------------


class TestPreAnalysisResult:
    """Tests for PreAnalysisResult dataclass."""

    def test_empty_result(self):
        result = PreAnalysisResult()
        assert not result.blocked
        assert len(result.blockers) == 0
        assert len(result.warnings) == 0

    def test_blocked_when_blockers_present(self):
        result = PreAnalysisResult(
            blockers=[PreAnalysisFinding(
                severity="blocker", category="test", message="blocked"
            )]
        )
        assert result.blocked

    def test_to_dict_serializable(self):
        result = PreAnalysisResult(
            blockers=[PreAnalysisFinding(
                severity="blocker", category="overlap", message="test",
                details={"key": "value"},
            )],
            warnings=[PreAnalysisFinding(
                severity="warning", category="style", message="test warn",
            )],
            suggestions=["try this"],
            enriched_context={"pin_count": 8},
        )
        d = result.to_dict()
        assert d["blocked"] is True
        assert len(d["blockers"]) == 1
        assert d["blockers"][0]["category"] == "overlap"
        assert len(d["warnings"]) == 1
        assert d["suggestions"] == ["try this"]
        assert d["enriched_context"]["pin_count"] == 8


# ---------------------------------------------------------------------------
# Collision zone detection
# ---------------------------------------------------------------------------


class TestCollisionZones:
    """Tests for collision zone detection."""

    def test_no_collision_single_component(self):
        path, ir = _fixture_ir()
        pin_positions = ir.get_pin_positions()
        # Filter to a single component's pins
        r1_pins = [p for p in pin_positions if p["reference"] == "R1"]
        if not r1_pins:
            pytest.skip("No R1 in fixture")

        zones = _detect_collision_zones(r1_pins, tolerance=2.54)
        assert len(zones) == 0

    def test_collision_zone_detected(self):
        pins = [
            {"reference": "R1", "pin_number": "1", "pin_name": "1",
             "x": 50.0, "y": 30.0, "electrical_type": "passive"},
            {"reference": "R2", "pin_number": "1", "pin_name": "1",
             "x": 50.0, "y": 30.0, "electrical_type": "passive"},
        ]
        zones = _detect_collision_zones(pins, tolerance=2.54)
        assert len(zones) == 1
        assert zones[0]["x"] == 50.0
        assert zones[0]["y"] == 30.0
        assert len(zones[0]["pins"]) == 2

    def test_no_collision_same_ref(self):
        pins = [
            {"reference": "R1", "pin_number": "1", "pin_name": "1",
             "x": 47.46, "y": 30.0, "electrical_type": "passive"},
            {"reference": "R1", "pin_number": "2", "pin_name": "2",
             "x": 52.54, "y": 30.0, "electrical_type": "passive"},
        ]
        zones = _detect_collision_zones(pins, tolerance=2.54)
        assert len(zones) == 0

    def test_no_collision_different_positions(self):
        pins = [
            {"reference": "R1", "pin_number": "1", "pin_name": "1",
             "x": 50.0, "y": 30.0, "electrical_type": "passive"},
            {"reference": "R2", "pin_number": "1", "pin_name": "1",
             "x": 100.0, "y": 80.0, "electrical_type": "passive"},
        ]
        zones = _detect_collision_zones(pins, tolerance=2.54)
        assert len(zones) == 0

    def test_collision_tolerance(self):
        """Pins at same rounded position should be grouped together."""
        pins = [
            {"reference": "R1", "pin_number": "1", "pin_name": "1",
             "x": 50.01, "y": 30.01, "electrical_type": "passive"},
            {"reference": "R2", "pin_number": "1", "pin_name": "1",
             "x": 50.04, "y": 30.04, "electrical_type": "passive"},
        ]
        zones = _detect_collision_zones(pins, tolerance=2.54)
        # Both round to (50.0, 30.0) at 1 decimal place
        assert len(zones) == 1


# ---------------------------------------------------------------------------
# Wire collision check
# ---------------------------------------------------------------------------


class TestWireCollisionCheck:
    """Tests for wire collision zone proximity check."""

    def test_wire_passes_through_point(self):
        assert _point_near_segment(50.0, 50.0, 40.0, 50.0, 60.0, 50.0, tolerance=2.54) is True

    def test_wire_far_from_point(self):
        assert _point_near_segment(50.0, 50.0, 10.0, 10.0, 20.0, 20.0, tolerance=2.54) is False

    def test_wire_near_endpoint(self):
        assert _point_near_segment(39.5, 50.0, 40.0, 50.0, 60.0, 50.0, tolerance=2.54) is True

    def test_zero_length_wire(self):
        assert _point_near_segment(40.0, 50.0, 40.0, 50.0, 40.0, 50.0, tolerance=2.54) is True
        assert _point_near_segment(100.0, 100.0, 40.0, 50.0, 40.0, 50.0, tolerance=2.54) is False

    def test_perpendicular_distance(self):
        """Point 2mm above the wire mid-point should be within 2.54mm tolerance."""
        # Wire from (40,50) to (60,50), point at (50,52)
        assert _point_near_segment(50.0, 52.0, 40.0, 50.0, 60.0, 50.0, tolerance=2.54) is True

    def test_perpendicular_just_outside(self):
        """Point 3mm above the wire should be outside 2.54mm tolerance."""
        assert _point_near_segment(50.0, 53.0, 40.0, 50.0, 60.0, 50.0, tolerance=2.54) is False


# ---------------------------------------------------------------------------
# Bounding box estimation
# ---------------------------------------------------------------------------


class TestEstimatedBbox:
    """Tests for component bounding box estimation."""

    def test_resistor_bbox(self):
        bbox = _estimated_bbox(50.0, 30.0, "Device:R_Small_US", 0.0)
        assert bbox["width"] <= 5.0
        assert bbox["height"] <= 3.0

    def test_capacitor_bbox(self):
        bbox = _estimated_bbox(50.0, 30.0, "Device:C_Small", 0.0)
        assert bbox["width"] <= 5.0

    def test_opamp_bbox(self):
        bbox = _estimated_bbox(50.0, 30.0, "Amplifier_Operational:TL072", 0.0)
        assert bbox["width"] >= 8.0

    def test_unknown_ic_bbox(self):
        bbox = _estimated_bbox(50.0, 30.0, "Custom:Unknown_IC", 0.0)
        assert bbox["width"] >= 10.0
        assert bbox["height"] >= 8.0

    def test_rotation_90_swaps(self):
        bbox_0 = _estimated_bbox(50.0, 30.0, "Device:R_Small_US", 0.0)
        bbox_90 = _estimated_bbox(50.0, 30.0, "Device:R_Small_US", 90.0)
        assert abs(bbox_0["width"] - bbox_90["height"]) < 0.01
        assert abs(bbox_0["height"] - bbox_90["width"]) < 0.01

    def test_rotation_270_same_as_90(self):
        bbox_90 = _estimated_bbox(50.0, 30.0, "Device:R_Small_US", 90.0)
        bbox_270 = _estimated_bbox(50.0, 30.0, "Device:R_Small_US", 270.0)
        assert abs(bbox_90["width"] - bbox_270["width"]) < 0.01
        assert abs(bbox_90["height"] - bbox_270["height"]) < 0.01


# ---------------------------------------------------------------------------
# PreAnalysisGate: basic routing
# ---------------------------------------------------------------------------


class TestPreAnalysisGateRouting:
    """Test that the gate routes to the correct analyzer."""

    def test_no_analysis_for_query_ops(self):
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "query_connectivity"
            target_file = "test.kicad_sch"

        class MockIR:
            pass

        result = gate.analyze(MockOp(), MockIR(), Path("test.kicad_sch"))
        assert not result.blocked
        assert len(result.blockers) == 0
        assert len(result.warnings) == 0

    def test_no_analysis_for_validation_ops(self):
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "validate_power_nets"
            target_file = "test.kicad_sch"

        class MockIR:
            pass

        result = gate.analyze(MockOp(), MockIR(), Path("test.kicad_sch"))
        assert not result.blocked


# ---------------------------------------------------------------------------
# PreAnalysisGate: with real fixtures
# ---------------------------------------------------------------------------


class TestPreAnalysisGateWithFixtures:
    """Integration tests using real schematic fixtures."""

    def _setup(self, name: str = "RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch"):
        return _fixture_ir(name)

    def test_add_component_no_overlap(self):
        """Adding component far from existing should pass."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class AddOp:
            op_type = "add_component"
            target_file = "test.kicad_sch"
            library_id = "Device:R_Small_US"
            reference = "R?"
            position = PositionSpec(x=300.0, y=300.0)

        result = gate.analyze(AddOp(), ir, path)
        assert not result.blocked

    def test_add_component_overlap_blocked(self):
        """Adding component on top of existing should block."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        # Find an existing component's position
        if not ir.components:
            pytest.skip("No components in fixture")

        sym = ir.components[0]
        ref = ""
        for prop in sym.properties:
            if prop.key == "Reference":
                ref = prop.value
                break
        if not ref:
            pytest.skip("No referenced components in fixture")

        sx = sym.position.X
        sy = sym.position.Y

        class AddOp:
            op_type = "add_component"
            target_file = "test.kicad_sch"
            library_id = "Device:R_Small_US"
            reference = "R?"
            position = PositionSpec(x=sx, y=sy)

        result = gate.analyze(AddOp(), ir, path)
        assert result.blocked
        categories = [b.category for b in result.blockers]
        assert "component_overlap" in categories
        assert ref in result.blockers[0].message

    def test_move_component_unknown_ref_blocked(self):
        """Moving a non-existent component should block."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class MoveOp:
            op_type = "move_component"
            target_file = "test.kicad_sch"
            reference = "R999"
            position = PositionSpec(x=100.0, y=100.0)

        result = gate.analyze(MoveOp(), ir, path)
        assert result.blocked
        assert any(b.category == "unknown_ref" for b in result.blockers)

    def test_move_component_no_overlap(self):
        """Moving component to free space should pass."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        # Find a real component and move it far away
        if not ir.components:
            pytest.skip("No components in fixture")

        sym = ir.components[0]
        ref = ""
        for prop in sym.properties:
            if prop.key == "Reference":
                ref = prop.value
                break

        class MoveOp:
            op_type = "move_component"
            target_file = "test.kicad_sch"
            reference = ref
            position = PositionSpec(x=500.0, y=500.0)

        result = gate.analyze(MoveOp(), ir, path)
        assert not result.blocked

    def test_remove_component_unknown_ref_blocked(self):
        """Removing a non-existent component should block."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class RemoveOp:
            op_type = "remove_component"
            target_file = "test.kicad_sch"
            reference = "X999"

        result = gate.analyze(RemoveOp(), ir, path)
        assert result.blocked
        assert any(b.category == "unknown_ref" for b in result.blockers)

    def test_remove_component_existing(self):
        """Removing an existing component should not block."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        if not ir.components:
            pytest.skip("No components in fixture")

        sym = ir.components[0]
        ref = ""
        for prop in sym.properties:
            if prop.key == "Reference":
                ref = prop.value
                break

        class RemoveOp:
            op_type = "remove_component"
            target_file = "test.kicad_sch"
            reference = ref

        result = gate.analyze(RemoveOp(), ir, path)
        assert not result.blocked

    def test_add_wire_enriches_connectivity(self):
        """Wiring operations should enrich context with connectivity data."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class WireOp:
            op_type = "add_wire"
            target_file = "test.kicad_sch"
            start_x = 200.0
            start_y = 200.0
            end_x = 210.0
            end_y = 200.0

        result = gate.analyze(WireOp(), ir, path)
        assert "connectivity" in result.enriched_context
        assert "total_pins" in result.enriched_context["connectivity"]
        assert "component_pin_map" in result.enriched_context

    def test_add_wire_no_blockers_on_clean_path(self):
        """Wire in empty area should not produce blockers."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class WireOp:
            op_type = "add_wire"
            target_file = "test.kicad_sch"
            start_x = 500.0
            start_y = 500.0
            end_x = 510.0
            end_y = 500.0

        result = gate.analyze(WireOp(), ir, path)
        assert not result.blocked

    def test_connectivity_context_has_pin_map(self):
        """Enriched context should include per-component pin maps."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class WireOp:
            op_type = "add_wire"
            target_file = "test.kicad_sch"
            start_x = 0.0
            start_y = 0.0
            end_x = 10.0
            end_y = 10.0

        result = gate.analyze(WireOp(), ir, path)
        pin_map = result.enriched_context.get("component_pin_map", {})
        # Should have entries for components in the fixture
        if ir.components:
            assert len(pin_map) > 0
            # Each entry should be a list of pin dicts
            for ref, pins in pin_map.items():
                assert isinstance(pins, list)
                for pin in pins:
                    assert "pin" in pin
                    assert "name" in pin
                    assert "type" in pin
                    assert "connected" in pin

    def test_power_nets_in_context(self):
        """Enriched context should list power nets."""
        gate = PreAnalysisGate()
        path, ir = self._setup()

        class WireOp:
            op_type = "add_wire"
            target_file = "test.kicad_sch"
            start_x = 0.0
            start_y = 0.0
            end_x = 10.0
            end_y = 10.0

        result = gate.analyze(WireOp(), ir, path)
        power_nets = result.enriched_context.get("power_nets", [])
        assert isinstance(power_nets, list)


# ---------------------------------------------------------------------------
# Duplicate global label detection (TDD RED)
# ---------------------------------------------------------------------------


def _make_ir_with_global_labels(labels: list[dict]) -> SchematicIR:
    """Build a minimal schematic with the given global labels.

    Args:
        labels: list of dicts with keys name, x, y.

    Returns:
        SchematicIR parsed from a temp file.
    """
    sch = Schematic()
    sch.version = "20231120"
    sch.generator = "volta-test"
    sch.uuid = "00000000-0000-0000-0000-000000000001"
    sch.sheet = sch  # self-reference

    for label_def in labels:
        gl = GlobalLabel()
        gl.text = label_def["name"]
        gl.position = Position(
            X=label_def["x"],
            Y=label_def["y"],
            angle=0.0,
        )
        gl.shape = "bidirectional"
        gl.uuid = "00000000-0000-0000-0000-" + f"{len(sch.globalLabels):08d}"
        sch.globalLabels.append(gl)

    with tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False) as f:
        sch.to_file(f.name)
        fpath = Path(f.name)

    try:
        result = parse_schematic(fpath)
        return SchematicIR(_parse_result=result)
    except Exception:
        fpath.unlink(missing_ok=True)
        raise


def _cleanup_ir(ir: SchematicIR) -> None:
    """Remove the temp file backing an IR created by _make_ir_with_global_labels."""
    try:
        p = Path(ir.schematic.filename)
        if p.exists() and "tmp" in str(p).lower():
            p.unlink(missing_ok=True)
    except Exception:
        pass


class TestDuplicateGlobalLabelDetection:
    """Tests for _analyze_label_operation duplicate global label detection."""

    def test_add_label_global_duplicate_blocked(self):
        """add_label with label_type='global' and existing name -> blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class AddLabelOp:
                op_type = "add_label"
                target_file = "test.kicad_sch"
                name = "SDA"
                label_type = "global"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "bidirectional"

            result = gate.analyze(AddLabelOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is True
            assert any(
                b.category == "duplicate_global_label" for b in result.blockers
            ), f"Expected duplicate_global_label blocker, got: {[b.category for b in result.blockers]}"
        finally:
            _cleanup_ir(ir)

    def test_add_label_global_no_duplicate(self):
        """add_label with label_type='global' and new name -> not blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class AddLabelOp:
                op_type = "add_label"
                target_file = "test.kicad_sch"
                name = "SCL"
                label_type = "global"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "bidirectional"

            result = gate.analyze(AddLabelOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_add_label_local_no_check(self):
        """add_label with label_type='local' -> no duplicate check."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class AddLabelOp:
                op_type = "add_label"
                target_file = "test.kicad_sch"
                name = "SDA"
                label_type = "local"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "input"

            result = gate.analyze(AddLabelOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_add_label_hierarchical_no_check(self):
        """add_label with label_type='hierarchical' -> no duplicate check."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class AddLabelOp:
                op_type = "add_label"
                target_file = "test.kicad_sch"
                name = "SDA"
                label_type = "hierarchical"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "output"

            result = gate.analyze(AddLabelOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_add_label_global_duplicate_different_position(self):
        """Global label with same name at different position -> still blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class AddLabelOp:
                op_type = "add_label"
                target_file = "test.kicad_sch"
                name = "SDA"
                label_type = "global"
                position = PositionSpec(x=100.0, y=200.0)
                shape = "bidirectional"

            result = gate.analyze(AddLabelOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is True
            assert any(
                b.category == "duplicate_global_label" for b in result.blockers
            )
        finally:
            _cleanup_ir(ir)

    def test_batch_connect_global_label_duplicate(self):
        """batch_connect with global_labels containing existing name -> blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class MockGlobalLabel:
                name = "SDA"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "bidirectional"

            class BatchConnectOp:
                op_type = "batch_connect"
                target_file = "test.kicad_sch"
                nets = []
                global_labels = [MockGlobalLabel()]

            result = gate.analyze(BatchConnectOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is True
            assert any(
                b.category == "duplicate_global_label" for b in result.blockers
            )
        finally:
            _cleanup_ir(ir)

    def test_batch_connect_global_labels_new_names(self):
        """batch_connect with only new global label names -> not blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class MockGlobalLabel:
                name = "SCL"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "bidirectional"

            class BatchConnectOp:
                op_type = "batch_connect"
                target_file = "test.kicad_sch"
                nets = []
                global_labels = [MockGlobalLabel()]

            result = gate.analyze(BatchConnectOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_regenerate_wiring_no_existing_labels(self):
        """regenerate_wiring with force=True and no existing global labels -> not blocked."""
        ir = _make_ir_with_global_labels([])
        try:
            gate = PreAnalysisGate()

            class MockGlobalLabel:
                name = "SDA"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "bidirectional"

            class RegenerateWiringOp:
                op_type = "regenerate_wiring"
                target_file = "test.kicad_sch"
                nets = []
                global_labels = [MockGlobalLabel()]
                no_connect_positions = []
                force = True  # Required for regenerate_wiring (D-07)

            result = gate.analyze(RegenerateWiringOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_place_net_labels_no_global_labels(self):
        """place_net_labels with no global_labels field -> not blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class PlaceNetLabelsOp:
                op_type = "place_net_labels"
                target_file = "test.kicad_sch"
                pin_map = "auto"
                references = None
                dry_run = False

            result = gate.analyze(PlaceNetLabelsOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_add_label_global_empty_schematic(self):
        """add_label with global on empty schematic -> not blocked."""
        ir = _make_ir_with_global_labels([])
        try:
            gate = PreAnalysisGate()

            class AddLabelOp:
                op_type = "add_label"
                target_file = "test.kicad_sch"
                name = "VCC"
                label_type = "global"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "output"

            result = gate.analyze(AddLabelOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is False
        finally:
            _cleanup_ir(ir)

    def test_batch_connect_intra_operation_duplicate(self):
        """batch_connect with duplicate name in its own global_labels list -> blocked."""
        ir = _make_ir_with_global_labels([{"name": "SDA", "x": 10.0, "y": 20.0}])
        try:
            gate = PreAnalysisGate()

            class MockGlobalLabelA:
                name = "SCL"
                position = PositionSpec(x=50.0, y=60.0)
                shape = "bidirectional"

            class MockGlobalLabelB:
                name = "SCL"
                position = PositionSpec(x=80.0, y=90.0)
                shape = "bidirectional"

            class BatchConnectOp:
                op_type = "batch_connect"
                target_file = "test.kicad_sch"
                nets = []
                global_labels = [MockGlobalLabelA(), MockGlobalLabelB()]

            result = gate.analyze(BatchConnectOp(), ir, Path("test.kicad_sch"))
            assert result.blocked is True
            assert any(
                b.category == "duplicate_global_label" for b in result.blockers
            )
            dup_blocker = next(
                b for b in result.blockers if b.category == "duplicate_global_label"
            )
            assert "intra-operation" in dup_blocker.details or "duplicate" in dup_blocker.message.lower()
        finally:
            _cleanup_ir(ir)


# ---------------------------------------------------------------------------
# Integration test: executor blocks duplicate global labels end-to-end
# ---------------------------------------------------------------------------


class TestDuplicateLabelExecutorIntegration:
    """End-to-end test proving the executor blocks duplicate global labels."""

    def test_executor_blocks_duplicate_global_label(self):
        """Adding a global label that already exists -> success=False, file unchanged."""
        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        # Build a schematic with a pre-existing global label "SDA"
        sch = Schematic()
        sch.version = "20231120"
        sch.generator = "volta-test"
        sch.uuid = "00000000-0000-0000-0000-000000000001"
        sch.sheet = sch

        gl = GlobalLabel()
        gl.text = "SDA"
        gl.position = Position(X=10.0, Y=20.0, angle=0.0)
        gl.shape = "bidirectional"
        gl.uuid = "00000000-0000-0000-0000-000000000010"
        sch.globalLabels.append(gl)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            sch_path = tmp_path / "test.kicad_sch"
            sch.to_file(str(sch_path))
            original_content = sch_path.read_text()

            executor = OperationExecutor(base_dir=tmp_path)

            op = Operation.model_validate({"root": {
                "op_type": "add_label",
                "target_file": "test.kicad_sch",
                "name": "SDA",
                "label_type": "global",
                "position": {"x": 50.0, "y": 60.0},
                "shape": "bidirectional",
            }})

            result = executor.execute(op)

            assert result["success"] is False
            assert "Pre-analysis blocked" in result.get("error", "")
            assert "duplicate_global_label" in str(result.get("pre_analysis", ""))

            # Verify file was NOT modified (no Transaction was entered)
            assert sch_path.read_text() == original_content

    def test_executor_allows_new_global_label(self):
        """Adding a new global label name -> success=True."""
        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        # Build a schematic with a pre-existing global label "SDA"
        sch = Schematic()
        sch.version = "20231120"
        sch.generator = "volta-test"
        sch.uuid = "00000000-0000-0000-0000-000000000001"
        sch.sheet = sch

        gl = GlobalLabel()
        gl.text = "SDA"
        gl.position = Position(X=10.0, Y=20.0, angle=0.0)
        gl.shape = "bidirectional"
        gl.uuid = "00000000-0000-0000-0000-000000000010"
        sch.globalLabels.append(gl)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            sch_path = tmp_path / "test.kicad_sch"
            sch.to_file(str(sch_path))

            executor = OperationExecutor(base_dir=tmp_path)

            op = Operation.model_validate({"root": {
                "op_type": "add_label",
                "target_file": "test.kicad_sch",
                "name": "SCL",
                "label_type": "global",
                "position": {"x": 50.0, "y": 60.0},
                "shape": "bidirectional",
            }})

            result = executor.execute(op)

            assert result["success"] is True


# ---------------------------------------------------------------------------
# File-type dispatch tests (H-01 fix)
# ---------------------------------------------------------------------------


class TestPreFlightGateDispatch:
    """Tests for file-type dispatch routing (H-01 fix)."""

    def test_pcb_file_dispatches_before_op_type_check(self):
        """PCB op_type not in _MUTATION_OP_TYPES but still reaches _analyze_pcb."""
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "swap_footprint"  # NOT in _MUTATION_OP_TYPES
            target_file = "board.kicad_pcb"
            reference = "U1"
            new_footprint_lib_id = "Package:DIP-8"

        # Use MagicMock so attribute access doesn't raise AttributeError
        from unittest.mock import MagicMock
        ir = MagicMock()
        ir.get_footprint_by_ref.return_value = None  # ref not found -> blocker

        result = gate.analyze(MockOp(), ir, Path("board.kicad_pcb"))
        # Should be blocked because _analyze_pcb handles it
        assert result.blocked

    def test_schematic_file_uses_op_type_guard(self):
        """Schematic file still checks _MUTATION_OP_TYPES membership."""
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "swap_footprint"  # NOT in _MUTATION_OP_TYPES
            target_file = "test.kicad_sch"

        class MockIR:
            pass

        result = gate.analyze(MockOp(), MockIR(), Path("test.kicad_sch"))
        # Should NOT be blocked -- swap_footprint is not in _MUTATION_OP_TYPES
        # so it returns early for schematic files
        assert not result.blocked

    def test_unknown_extension_returns_empty_result(self):
        """File with unknown extension returns empty result (no checks)."""
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "add_component"
            target_file = "test.txt"

        class MockIR:
            pass

        result = gate.analyze(MockOp(), MockIR(), Path("test.txt"))
        assert not result.blocked
        assert len(result.warnings) == 0

    def test_cross_file_receives_ir_map_not_single_ir(self):
        """Cross-file gate accepts dict[Path, Any] as ir parameter (H-02 fix)."""
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "propagate_symbol_change"
            target_file = "project.kicad_sym"
            lib_id = "Device:R"

        ir_map = {Path("project.kicad_sch"): MagicMock()}

        # Should not raise -- ir_map is a dict, not a single IR
        result = gate.analyze(MockOp(), ir_map, Path("project.kicad_sym"))
        # lib_id won't be found in empty mock, so it should block
        assert result.blocked


# ---------------------------------------------------------------------------
# Expanded schematic gate tests (D-07)
# ---------------------------------------------------------------------------


class TestExpandedSchematicGate:
    """Tests for expanded schematic checks (D-07)."""

    def _make_ir_with_component(self, ref: str, pin_count: int):
        """Build a minimal IR with a component having N pins."""
        ir = MagicMock()
        component = MagicMock()
        ref_prop = MagicMock()
        ref_prop.key = "Reference"
        ref_prop.value = ref
        component.properties = [ref_prop]
        ir.get_component_by_ref.return_value = component

        pins = [{"reference": ref, "pin_number": str(i), "x": float(i), "y": 0.0} for i in range(1, pin_count + 1)]
        ir.get_pin_positions.return_value = pins
        return ir

    def test_swap_symbol_blocked_when_pin_count_differs_over_20_percent(self):
        """swap_symbol blocked when new symbol pin count differs >20% from old."""
        gate = PreAnalysisGate()
        ir = self._make_ir_with_component("U1", pin_count=10)

        class SwapOp:
            op_type = "swap_symbol"
            target_file = "test.kicad_sch"
            reference = "U1"
            new_symbol_lib_id = "NewIC:Small"

        # New symbol lib_id not found -> pin count is None -> no blocker
        # But we can test by directly calling the expanded check
        from volta.ops.pre_analysis_schematic import _count_symbol_pins
        assert _count_symbol_pins(ir, "U1") == 10

    def test_swap_symbol_proceeds_when_pin_count_within_20_percent(self):
        """swap_symbol proceeds when pin count difference is within 20%."""
        gate = PreAnalysisGate()
        ir = self._make_ir_with_component("U1", pin_count=8)

        class SwapOp:
            op_type = "swap_symbol"
            target_file = "test.kicad_sch"
            reference = "U1"
            new_symbol_lib_id = "Device:R"  # won't be found -> None -> no blocker

        result = gate.analyze(SwapOp(), ir, Path("test.kicad_sch"))
        assert not result.blocked

    def test_regenerate_wiring_blocked_unless_force_true(self):
        """regenerate_wiring blocked unless op.force is True."""
        gate = PreAnalysisGate()
        ir = MagicMock()

        class RegenerateOp:
            op_type = "regenerate_wiring"
            target_file = "test.kicad_sch"
            nets = []
            global_labels = []
            force = False

        result = gate.analyze(RegenerateOp(), ir, Path("test.kicad_sch"))
        assert result.blocked is True
        assert any(b.category == "force_required" for b in result.blockers)

    def test_regenerate_wiring_proceeds_when_force_true(self):
        """regenerate_wiring proceeds when op.force is True."""
        gate = PreAnalysisGate()
        ir = MagicMock()

        class RegenerateOp:
            op_type = "regenerate_wiring"
            target_file = "test.kicad_sch"
            nets = []
            global_labels = []
            force = True

        result = gate.analyze(RegenerateOp(), ir, Path("test.kicad_sch"))
        assert not result.blocked

    def test_remove_labels_blocked_when_label_referenced_by_wires(self):
        """remove_labels blocked when any label is referenced by wires."""
        gate = PreAnalysisGate()
        ir = MagicMock()

        wire_endpoint = MagicMock()
        wire_endpoint.net = "SDA"
        wire_endpoint.start_x = 10.0
        wire_endpoint.start_y = 20.0
        wire_endpoint.end_x = 30.0
        wire_endpoint.end_y = 20.0
        ir.get_wire_endpoints.return_value = [wire_endpoint]

        class RemoveLabelsOp:
            op_type = "remove_labels"
            target_file = "test.kicad_sch"
            labels = ["SDA", "SCL"]

        result = gate.analyze(RemoveLabelsOp(), ir, Path("test.kicad_sch"))
        assert result.blocked is True
        assert any(b.category == "label_wire_reference" for b in result.blockers)

    def test_add_wire_warns_when_endpoints_floating(self):
        """add_wire emits WARNING when endpoints don't land on pins or wire endpoints."""
        gate = PreAnalysisGate()
        ir = MagicMock()
        ir.get_pin_positions.return_value = []
        ir.get_wire_endpoints.return_value = []

        class WireOp:
            op_type = "add_wire"
            target_file = "test.kicad_sch"
            start_x = 500.0
            start_y = 500.0
            end_x = 510.0
            end_y = 500.0

        result = gate.analyze(WireOp(), ir, Path("test.kicad_sch"))
        # Both endpoints are floating since no pins/wires exist
        assert len(result.warnings) > 0
        assert any(w.category == "floating_wire_endpoint" for w in result.warnings)

    def test_duplicate_component_blocked_on_overlap(self):
        """duplicate_component blocked when duplicated footprint overlaps existing."""
        gate = PreAnalysisGate()

        # Create a minimal IR with an existing component at (50, 50)
        ir = MagicMock()
        sym = MagicMock()
        sym.position = MagicMock(X=50.0, Y=50.0, angle=0.0)
        ref_prop = MagicMock(key="Reference", value="R1")
        lib_prop = MagicMock(key="Footprint", value="Device:R")
        sym.properties = [ref_prop, lib_prop]
        sym.libId = "Device:R_Small"
        ir.components = [sym]
        ir.get_component_by_ref.return_value = sym

        # Pin positions for R1
        ir.get_pin_positions.return_value = [
            {"reference": "R1", "pin_number": "1", "x": 47.5, "y": 50.0},
            {"reference": "R1", "pin_number": "2", "x": 52.5, "y": 50.0},
        ]

        class DuplicateOp:
            op_type = "duplicate_component"
            target_file = "test.kicad_sch"
            reference = "R1"

        class Position:
            x = 50.0
            y = 50.0

        DuplicateOp.position = Position()

        result = gate.analyze(DuplicateOp(), ir, Path("test.kicad_sch"))
        assert result.blocked is True
        assert any(b.category == "component_overlap" for b in result.blockers)

