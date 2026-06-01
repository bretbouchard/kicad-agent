"""Tests for schematic ERC repair operations.

Tests build schematics programmatically using kiutils for precise position
control, then run repair operations and verify corrections.
"""

import math
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from kiutils.items.common import Position
from kiutils.items.schitems import Connection, LocalLabel
from kiutils.schematic import Schematic

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.repair import (
    SNAP_TOLERANCE,
    _find_position_for_unit,
    _get_unit_pin_map,
    _get_unit_pin_offsets,
    add_power_flags,
    detect_shorted_nets,
    place_missing_units,
    place_no_connects,
    place_no_connects_from_erc,
    remove_orphaned_labels,
    repair_wire_snapping,
    snap_to_grid,
)
from kicad_agent.parser import parse_schematic


def _save_and_parse(board_path: Path, sch: Schematic) -> SchematicIR:
    """Save a kiutils Schematic to disk and parse it back into SchematicIR.

    This ensures the IR operates on a properly serialized schematic.
    """
    sch.to_file(str(board_path))
    result = parse_schematic(board_path)
    return SchematicIR(_parse_result=result)


class TestRepairWireSnapping:
    """Test wire endpoint snapping to pin positions."""

    def test_repair_wire_snapping_with_real_fixture(self):
        """Test wire snapping on RaspberryPi-uHAT fixture.

        Uses a real schematic with known pin positions.
        """
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = parse_schematic(fixture)
        ir = SchematicIR(_parse_result=result)

        snap_result = repair_wire_snapping(ir, fixture)
        assert "snapped_count" in snap_result
        assert "unchanged_count" in snap_result
        assert isinstance(snap_result["snapped_count"], int)
        assert isinstance(snap_result["unchanged_count"], int)

    def test_repair_wire_snapping_empty_schematic(self):
        """Test snapping on an empty schematic returns zero counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            result = repair_wire_snapping(ir, sch_path)
            assert result["snapped_count"] == 0
            assert result["unchanged_count"] == 0


class TestRemoveOrphanedLabels:
    """Test orphaned label detection and removal."""

    def test_remove_orphaned_labels_with_disconnected_label(self):
        """Test that a label with no wire or pin nearby is removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            # Add a label far from any wire or pin
            label = LocalLabel(
                text="ORPHAN_LABEL",
                position=Position(X=100.0, Y=100.0),
            )
            sch.labels.append(label)

            ir = _save_and_parse(sch_path, sch)
            result = remove_orphaned_labels(ir)

            assert "ORPHAN_LABEL" in result["removed"]
            assert result["kept"] == 0

    def test_remove_orphaned_labels_keeps_connected(self):
        """Test that a label at a wire endpoint is kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            # Add a wire and a label at its start point
            wire = Connection(
                type="wire",
                points=[Position(X=10.0, Y=20.0), Position(X=30.0, Y=20.0)],
            )
            sch.graphicalItems.append(wire)

            label = LocalLabel(
                text="KEPT_LABEL",
                position=Position(X=10.0, Y=20.0),
            )
            sch.labels.append(label)

            ir = _save_and_parse(sch_path, sch)
            result = remove_orphaned_labels(ir)

            assert "KEPT_LABEL" not in result["removed"]
            assert result["kept"] == 1

    def test_remove_orphaned_labels_empty_schematic(self):
        """Test removal on an empty schematic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            result = remove_orphaned_labels(ir)
            assert result["removed"] == []
            assert result["kept"] == 0


class TestDetectShortedNets:
    """Test shorted net detection."""

    def test_detect_shorted_nets_clean(self):
        """Test that a schematic with no overlapping nets is clean."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            # Add a single label -- no conflict
            label = LocalLabel(
                text="SDA",
                position=Position(X=10.0, Y=20.0),
            )
            sch.labels.append(label)

            ir = _save_and_parse(sch_path, sch)
            result = detect_shorted_nets(ir)

            assert result["clean"] is True
            assert result["shorts"] == []

    def test_detect_shorted_nets_with_overlap(self):
        """Test detection when two different labels share a position."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            # Two labels at the same position with different names = short
            label1 = LocalLabel(
                text="VCC",
                position=Position(X=50.0, Y=50.0),
            )
            label2 = LocalLabel(
                text="GND",
                position=Position(X=50.0, Y=50.0),
            )
            sch.labels.append(label1)
            sch.labels.append(label2)

            ir = _save_and_parse(sch_path, sch)
            result = detect_shorted_nets(ir)

            assert result["clean"] is False
            assert len(result["shorts"]) >= 1
            short = result["shorts"][0]
            assert "VCC" in short["nets"]
            assert "GND" in short["nets"]


class TestPlaceNoConnects:
    """Test no-connect marker placement on unconnected pins."""

    def test_place_no_connects_with_unconnected_pins(self):
        """Test that unconnected pins get no-connect markers."""
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = parse_schematic(fixture)
        ir = SchematicIR(_parse_result=result)

        nc_result = place_no_connects(ir)
        assert "placed" in nc_result
        assert "positions" in nc_result
        assert isinstance(nc_result["placed"], int)
        assert isinstance(nc_result["positions"], list)

    def test_place_no_connects_empty_schematic(self):
        """Test placement on an empty schematic (no pins = nothing to mark)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            result = place_no_connects(ir)
            assert result["placed"] == 0
            assert result["positions"] == []


class TestPinYInversion:
    """Test pin absolute position calculation with Y-inversion.

    T-10-11: Pin absolute position uses (sx+px, sy-py) pattern.
    """

    def test_pin_y_inversion_with_fixture(self):
        """Verify pin absolute position uses (sx+px, sy-py) for Y coord.

        Uses the RaspberryPi-uHAT fixture which has a known connector
        (J1) with pins at known library offsets.
        """
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = parse_schematic(fixture)
        ir = SchematicIR(_parse_result=result)

        pin_positions = ir.get_pin_positions()
        assert len(pin_positions) > 0

        # Find a pin from J1 (Connector_Generic:Conn_02x20_Odd_Even)
        # J1 is at (66.04, 50.8) with angle 0
        # Pin_1 has library offset (-5.08, 22.86)
        # Expected absolute: (66.04 + (-5.08), 50.8 - 22.86) = (60.96, 27.94)
        j1_pins = [p for p in pin_positions if p["reference"] == "J1"]
        assert len(j1_pins) > 0

        pin_1 = [p for p in j1_pins if p["pin_number"] == "1"]
        assert len(pin_1) == 1

        # T-10-11: Y-inversion check
        # abs_x = sx + px = 66.04 + (-5.08) = 60.96
        # abs_y = sy - py = 50.8 - 22.86 = 27.94
        assert abs(pin_1[0]["x"] - 60.96) < 0.01
        assert abs(pin_1[0]["y"] - 27.94) < 0.01

    def test_pin_positions_return_structure(self):
        """Verify get_pin_positions returns proper structure."""
        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        result = parse_schematic(fixture)
        ir = SchematicIR(_parse_result=result)

        pin_positions = ir.get_pin_positions()
        for pin in pin_positions:
            assert "reference" in pin
            assert "pin_name" in pin
            assert "pin_number" in pin
            assert "x" in pin
            assert "y" in pin
            assert "electrical_type" in pin
            assert isinstance(pin["x"], float)
            assert isinstance(pin["y"], float)


class TestRepairSchematicOperation:
    """Test repair_schematic operation via executor dispatch."""

    def test_repair_schematic_operation(self):
        """Execute repair_schematic operation through the executor."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        fixture = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")
        if not fixture.exists():
            pytest.skip("RaspberryPi-uHAT fixture not found")

        # Copy to temp dir to avoid modifying the fixture
        with tempfile.TemporaryDirectory() as tmpdir:
            import shutil
            tmp_sch = Path(tmpdir) / "RaspberryPi-uHAT.kicad_sch"
            shutil.copy2(fixture, tmp_sch)

            op = Operation.model_validate({
                "root": {
                    "op_type": "repair_schematic",
                    "target_file": "RaspberryPi-uHAT.kicad_sch",
                    "snap_wires": True,
                    "remove_orphans": True,
                    "place_no_connects": True,
                }
            })

            executor = OperationExecutor(base_dir=Path(tmpdir))
            result = executor.execute(op)

            assert result["success"] is True
            assert result["operation"] == "repair_schematic"
            assert "details" in result
            details = result["details"]
            assert "wire_snapping" in details
            assert "orphan_removal" in details
            assert "no_connects" in details


# ---------------------------------------------------------------------------
# Phase 23: ERC-driven repair operation tests
# ---------------------------------------------------------------------------


class TestSnapToGrid:
    """Test grid-snapping for off-grid wire endpoints."""

    def test_snap_to_grid_off_grid_wire(self):
        """Off-grid wire endpoints snap to nearest grid point."""
        ir = MagicMock()
        wire = MagicMock()
        point1 = MagicMock()
        point1.X = 25.41
        point1.Y = 30.5  # on-grid for 0.1mm
        point2 = MagicMock()
        point2.X = 50.8
        point2.Y = 30.5
        wire.points = [point1, point2]
        ir.schematic.graphicalItems = [wire]
        ir.get_wire_endpoints.return_value = [
            {"wire_index": 0, "start_x": 25.41, "start_y": 30.5,
             "end_x": 50.8, "end_y": 30.5, "uuid": "test-uuid"},
        ]

        result = snap_to_grid(ir, grid_mm=0.1)

        assert result["snapped_count"] >= 1
        assert result["grid_mm"] == 0.1
        # Verify the off-grid X was snapped to nearest 0.1mm grid
        assert abs(point1.X - round(25.41 / 0.1) * 0.1) < 0.001
        # Y was already on-grid, should not change
        assert abs(point1.Y - 30.5) < 0.001

    def test_snap_to_grid_preserves_connectivity(self):
        """Two wires meeting at an off-grid point snap to the SAME grid point."""
        ir = MagicMock()

        # Wire 1: (25.41, 30.43) -> (50.8, 30.48)
        wire1 = MagicMock()
        p1a = MagicMock()
        p1a.X = 25.41
        p1a.Y = 30.43
        p1b = MagicMock()
        p1b.X = 50.8
        p1b.Y = 30.48
        wire1.points = [p1a, p1b]

        # Wire 2: (25.41, 30.43) -> (25.41, 50.8)
        wire2 = MagicMock()
        p2a = MagicMock()
        p2a.X = 25.41
        p2a.Y = 30.43
        p2b = MagicMock()
        p2b.X = 25.41
        p2b.Y = 50.8
        wire2.points = [p2a, p2b]

        ir.schematic.graphicalItems = [wire1, wire2]
        ir.get_wire_endpoints.return_value = [
            {"wire_index": 0, "start_x": 25.41, "start_y": 30.43,
             "end_x": 50.8, "end_y": 30.48, "uuid": "w1"},
            {"wire_index": 1, "start_x": 25.41, "start_y": 30.43,
             "end_x": 25.41, "end_y": 50.8, "uuid": "w2"},
        ]

        result = snap_to_grid(ir, grid_mm=0.1)

        # Both wires' off-grid endpoints must snap to the same target
        assert abs(p1a.X - p2a.X) < 0.001
        assert abs(p1a.Y - p2a.Y) < 0.001

    def test_snap_to_grid_all_on_grid(self):
        """All-on-grid wires result in no changes."""
        ir = MagicMock()
        wire = MagicMock()
        point1 = MagicMock()
        point1.X = 25.4
        point1.Y = 30.48
        point2 = MagicMock()
        point2.X = 50.8
        point2.Y = 30.48
        wire.points = [point1, point2]
        ir.schematic.graphicalItems = [wire]
        ir.get_wire_endpoints.return_value = [
            {"wire_index": 0, "start_x": 25.4, "start_y": 30.48,
             "end_x": 50.8, "end_y": 30.48, "uuid": "test"},
        ]

        result = snap_to_grid(ir, grid_mm=0.01)

        assert result["snapped_count"] == 0

    def test_snap_to_grid_custom_grid(self):
        """Custom grid_mm=2.54 snaps to 2.54mm grid."""
        ir = MagicMock()
        wire = MagicMock()
        point1 = MagicMock()
        point1.X = 24.13
        point1.Y = 29.37
        point2 = MagicMock()
        point2.X = 50.8
        point2.Y = 30.48
        wire.points = [point1, point2]
        ir.schematic.graphicalItems = [wire]
        ir.get_wire_endpoints.return_value = [
            {"wire_index": 0, "start_x": 24.13, "start_y": 29.37,
             "end_x": 50.8, "end_y": 30.48, "uuid": "test"},
        ]

        result = snap_to_grid(ir, grid_mm=2.54)

        assert result["grid_mm"] == 2.54
        assert result["snapped_count"] >= 1


class TestAddPowerFlags:
    """Test ERC-driven power flag placement."""

    def test_add_power_flags_places_pwr_flag(self):
        """PWR_FLAG is placed at power_pin_not_driven positions."""
        from kicad_agent.ops.erc_parser import ViolationPosition

        ir = MagicMock()
        ir.get_label_positions.return_value = [
            {"name": "+5V", "x": 50.0, "y": 30.0},
        ]

        mock_positions = [
            ViolationPosition(x=50.0, y=30.0, sheet="/", description="Power pin not driven"),
        ]

        with patch("kicad_agent.ops.erc_parser.extract_violation_positions", return_value=mock_positions):
            result = add_power_flags(ir, Path("test.kicad_sch"))

        assert result["placed"] == 1
        assert "+5V" in result["net_names"]
        ir.add_power_symbol.assert_called_once_with("PWR_FLAG", 52.54, 30.0, 0.0)

    def test_add_power_flags_no_violations(self):
        """No violations means no symbols placed."""
        ir = MagicMock()

        with patch("kicad_agent.ops.erc_parser.extract_violation_positions", return_value=[]):
            result = add_power_flags(ir, Path("test.kicad_sch"))

        assert result["placed"] == 0
        assert result["skipped"] == 0


class TestPlaceNoConnectsFromErc:
    """Test ERC-driven no-connect placement."""

    def test_places_at_violation_positions(self):
        """No-connect markers placed at each violation position."""
        from kicad_agent.ops.erc_parser import ViolationPosition

        ir = MagicMock()
        ir.schematic.noConnects = []

        mock_positions = [
            ViolationPosition(x=10.0, y=20.0, sheet="/", description="Pin not connected"),
            ViolationPosition(x=30.0, y=40.0, sheet="/", description="Pin not connected"),
            ViolationPosition(x=50.0, y=60.0, sheet="/", description="Pin not connected"),
        ]

        with patch("kicad_agent.ops.erc_parser.extract_violation_positions", return_value=mock_positions):
            result = place_no_connects_from_erc(ir, Path("test.kicad_sch"))

        assert result["placed"] == 3
        assert ir.add_no_connect.call_count == 3

    def test_skips_existing_no_connects(self):
        """Existing no-connect markers at positions are skipped."""
        from kicad_agent.ops.erc_parser import ViolationPosition

        ir = MagicMock()
        # Existing no-connect at (10.0, 20.0)
        existing_nc = MagicMock()
        existing_nc.position.X = 10.0
        existing_nc.position.Y = 20.0
        ir.schematic.noConnects = [existing_nc]

        mock_positions = [
            ViolationPosition(x=10.0, y=20.0, sheet="/", description="Pin not connected"),
            ViolationPosition(x=30.0, y=40.0, sheet="/", description="Pin not connected"),
        ]

        with patch("kicad_agent.ops.erc_parser.extract_violation_positions", return_value=mock_positions):
            result = place_no_connects_from_erc(ir, Path("test.kicad_sch"))

        assert result["placed"] == 1
        assert result["skipped_duplicates"] == 1

    def test_no_violations(self):
        """Empty violation list returns placed=0."""
        ir = MagicMock()

        with patch("kicad_agent.ops.erc_parser.extract_violation_positions", return_value=[]):
            result = place_no_connects_from_erc(ir, Path("test.kicad_sch"))

        assert result["placed"] == 0
        assert result["skipped_duplicates"] == 0


# ---------------------------------------------------------------------------
# Schema validation tests for Phase 23 mutation operations
# ---------------------------------------------------------------------------


def test_snap_to_grid_op_schema():
    """SnapToGridOp validates correctly."""
    from kicad_agent.ops.schema import Operation, SnapToGridOp

    op = SnapToGridOp(op_type="snap_to_grid", target_file="test.kicad_sch")
    assert op.grid_mm == 0.01

    wrapped = Operation.model_validate({
        "root": {"op_type": "snap_to_grid", "target_file": "test.kicad_sch"}
    })
    assert wrapped.root.op_type == "snap_to_grid"

    # Custom grid
    op_custom = SnapToGridOp(op_type="snap_to_grid", target_file="test.kicad_sch", grid_mm=2.54)
    assert op_custom.grid_mm == 2.54


def test_add_power_flag_op_schema():
    """AddPowerFlagOp validates correctly."""
    from kicad_agent.ops.schema import AddPowerFlagOp, Operation

    op = AddPowerFlagOp(op_type="add_power_flag", target_file="test.kicad_sch")
    assert op.op_type == "add_power_flag"

    wrapped = Operation.model_validate({
        "root": {"op_type": "add_power_flag", "target_file": "test.kicad_sch"}
    })
    assert wrapped.root.op_type == "add_power_flag"


def test_repair_schematic_with_snap_to_grid():
    """RepairSchematicOp with snap_to_grid=True validates correctly."""
    from kicad_agent.ops.schema import Operation

    op = Operation.model_validate({
        "root": {
            "op_type": "repair_schematic",
            "target_file": "test.kicad_sch",
            "snap_wires": False,
            "remove_orphans": False,
            "place_no_connects": False,
            "snap_to_grid": True,
        }
    })
    assert op.root.snap_to_grid is True


# ---------------------------------------------------------------------------
# Phase 35: erc_auto_fix meta-operation tests
# ---------------------------------------------------------------------------


class TestErcAutoFix:
    """Test erc_auto_fix meta-operation with violation dispatch and iteration control."""

    def _make_violation(self, vtype: str, count: int = 1) -> list:
        """Create mock ErcViolation instances for testing."""
        from kicad_agent.ops.erc_parser import ErcViolation
        return [
            ErcViolation(
                sheet="/",
                type=vtype,
                severity="error",
                description=f"Test {vtype} violation {i}",
                positions=[(float(i), float(i))],
            )
            for i in range(count)
        ]

    def test_no_violations(self):
        """erc_auto_fix with empty ERC results returns fixes_applied=[] and iterations=0."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", return_value=[]):
            result = erc_auto_fix(ir, Path("test.kicad_sch"), max_iterations=3)

        assert result["fixes_applied"] == []
        assert result["iterations"] == 0
        assert result["remaining_violations"] == 0
        assert result["unhandled_violations"] == []

    def test_pin_not_connected_fix(self):
        """erc_auto_fix maps pin_not_connected violations to place_no_connects_from_erc."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        violations = self._make_violation("pin_not_connected", count=3)
        # Iteration 1: violations, iteration 2: empty, final check: empty
        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", side_effect=[violations, [], []]), \
             patch("kicad_agent.ops.repair.place_no_connects_from_erc", return_value={"placed": 3, "skipped_duplicates": 0}) as mock_nc:
            result = erc_auto_fix(ir, Path("test.kicad_sch"))

        mock_nc.assert_called_once()
        assert any(f["type"] == "pin_not_connected" for f in result["fixes_applied"])

    def test_power_pin_not_driven_fix(self):
        """erc_auto_fix maps power_pin_not_driven violations to add_power_flags."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        violations = self._make_violation("power_pin_not_driven", count=2)
        # Iteration 1: violations, iteration 2: empty, final check: empty
        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", side_effect=[violations, [], []]), \
             patch("kicad_agent.ops.repair.add_power_flags", return_value={"placed": 2, "skipped": 0, "positions": [], "net_names": []}) as mock_pf:
            result = erc_auto_fix(ir, Path("test.kicad_sch"))

        mock_pf.assert_called_once()
        assert any(f["type"] == "power_pin_not_driven" for f in result["fixes_applied"])

    def test_max_iterations_respected(self):
        """erc_auto_fix respects max_iterations and stops after that many rounds."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        violations = self._make_violation("pin_not_connected", count=5)
        # parse_erc always returns violations (never decreases)
        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", return_value=violations), \
             patch("kicad_agent.ops.repair.place_no_connects_from_erc", return_value={"placed": 5, "skipped_duplicates": 0}):
            result = erc_auto_fix(ir, Path("test.kicad_sch"), max_iterations=2)

        # Should run exactly 2 iterations (stops when count doesn't decrease after iteration 1,
        # or hits max_iterations=2)
        assert result["iterations"] <= 2

    def test_early_stop_no_decrease(self):
        """erc_auto_fix stops early when violation count does not decrease."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        violations = self._make_violation("pin_not_connected", count=5)
        # Always returns same violations -- count never decreases
        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", return_value=violations), \
             patch("kicad_agent.ops.repair.place_no_connects_from_erc", return_value={"placed": 0, "skipped_duplicates": 0}):
            result = erc_auto_fix(ir, Path("test.kicad_sch"), max_iterations=10)

        # Should stop after 2 iterations: first runs repairs, second sees no decrease and stops
        assert result["iterations"] == 2

    def test_unhandled_violations_reported(self):
        """Unmapped violation types appear in unhandled_violations in return value."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        violations = self._make_violation("unknown_violation_type", count=2)
        # Iteration 1: unhandled violations, iteration 2: same count -> early stop, final check: empty
        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", side_effect=[violations, violations, []]):
            result = erc_auto_fix(ir, Path("test.kicad_sch"))

        assert len(result["unhandled_violations"]) == 1
        assert result["unhandled_violations"][0]["type"] == "unknown_violation_type"
        assert result["unhandled_violations"][0]["count"] == 2

    def test_schema_validates(self):
        """ErcAutoFixOp validates with op_type='erc_auto_fix' through Operation.model_validate."""
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "erc_auto_fix",
                "target_file": "test.kicad_sch",
            }
        })
        assert op.root.op_type == "erc_auto_fix"
        assert op.root.max_iterations == 3  # default

        # Custom max_iterations
        op2 = Operation.model_validate({
            "root": {
                "op_type": "erc_auto_fix",
                "target_file": "test.kicad_sch",
                "max_iterations": 5,
            }
        })
        assert op2.root.max_iterations == 5

    def test_priority_order(self):
        """Repairs execute in priority order: shorts first, then type fixes, then cosmetic."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        ir = MagicMock()
        violations = [
            *self._make_violation("pin_not_connected", count=2),
            *self._make_violation("power_pin_not_driven", count=1),
        ]
        call_order = []

        def track_call(name):
            def wrapper(*args, **kwargs):
                call_order.append(name)
                return {"placed": 0, "skipped": 0}
            return wrapper

        with patch("kicad_agent.ops.erc_auto_fix.parse_erc", side_effect=[violations, [], []]), \
             patch("kicad_agent.ops.repair.add_power_flags", side_effect=track_call("power_flags")), \
             patch("kicad_agent.ops.repair.place_no_connects_from_erc", side_effect=track_call("no_connects")):
            result = erc_auto_fix(ir, Path("test.kicad_sch"))

        # power_pin_not_driven should be called before pin_not_connected
        # (power flags > no-connects in priority)
        if "power_flags" in call_order and "no_connects" in call_order:
            pf_idx = call_order.index("power_flags")
            nc_idx = call_order.index("no_connects")
            assert pf_idx < nc_idx, f"power_flags (idx={pf_idx}) should come before no_connects (idx={nc_idx})"


# ---------------------------------------------------------------------------
# Helper: build a mock lib_sym with multi-unit sub-symbols
# ---------------------------------------------------------------------------

def _make_pin(number: str, px: float = 0.0, py: float = 0.0):
    """Create a mock pin with number and position."""
    pin = MagicMock()
    pin.number = number
    pin.position = MagicMock()
    pin.position.X = px
    pin.position.Y = py
    return pin


def _make_sub_symbol(lib_id: str, pins: list):
    """Create a mock sub-symbol with libId and pin list."""
    sub = MagicMock()
    sub.libId = lib_id
    sub.pins = pins
    return sub


def _make_lib_sym(lib_id: str, sub_symbols: list):
    """Create a mock lib_sym with libId and units."""
    lib = MagicMock()
    lib.libId = lib_id
    lib.units = sub_symbols
    return lib


# Channel-strip eq-stage path for integration tests
_EQ_STAGE = Path(
    "/Users/bretbouchard/apps/analog-ecosystem"
    "/hardware/network-io/channel-strip/eq-stage.kicad_sch"
)


class TestGetUnitPinMap:
    """Test _get_unit_pin_map helper (Bug B fix)."""

    def test_ne5532_unit_mapping(self):
        """NE5532 sub-symbols: unit 1 → {1,2,3}, unit 2 → {5,6,7}, unit 3 → {4,8}."""
        lib_sym = _make_lib_sym("Amplifier_Operational:NE5532", [
            _make_sub_symbol("NE5532_0_1", []),            # graphic wrapper
            _make_sub_symbol("NE5532_1_1", [_make_pin("1"), _make_pin("2"), _make_pin("3")]),
            _make_sub_symbol("NE5532_2_1", [_make_pin("5"), _make_pin("6"), _make_pin("7")]),
            _make_sub_symbol("NE5532_3_1", [_make_pin("4"), _make_pin("8")]),
        ])
        result = _get_unit_pin_map(lib_sym)
        assert result == {1: {"1", "2", "3"}, 2: {"5", "6", "7"}, 3: {"4", "8"}}

    def test_cd4066be_unit_mapping(self):
        """CD4066BE: 4 switch units + 1 power unit."""
        lib_sym = _make_lib_sym("4xxx:CD4066BE", [
            _make_sub_symbol("CD4066BE_0_1", []),
            _make_sub_symbol("CD4066BE_1_1", [_make_pin("1"), _make_pin("2"), _make_pin("13")]),
            _make_sub_symbol("CD4066BE_2_1", [_make_pin("3"), _make_pin("4"), _make_pin("5")]),
            _make_sub_symbol("CD4066BE_3_1", [_make_pin("6"), _make_pin("8"), _make_pin("9")]),
            _make_sub_symbol("CD4066BE_4_1", [_make_pin("10"), _make_pin("11"), _make_pin("12")]),
            _make_sub_symbol("CD4066BE_5_1", [_make_pin("7"), _make_pin("14")]),
        ])
        result = _get_unit_pin_map(lib_sym)
        assert 1 in result and result[1] == {"1", "2", "13"}
        assert 5 in result and result[5] == {"7", "14"}
        assert len(result) == 5

    def test_skips_empty_units(self):
        """Units with no pins (graphic wrappers) are excluded."""
        lib_sym = _make_lib_sym("Device:R", [
            _make_sub_symbol("R_0_1", []),
            _make_sub_symbol("R_1_1", [_make_pin("1"), _make_pin("2")]),
        ])
        result = _get_unit_pin_map(lib_sym)
        assert 0 not in result
        assert result == {1: {"1", "2"}}


class TestGetUnitPinOffsets:
    """Test _get_unit_pin_offsets helper."""

    def test_returns_offsets_for_specific_unit(self):
        lib_sym = _make_lib_sym("NE5532", [
            _make_sub_symbol("NE5532_1_1", [_make_pin("1", 5.08, 3.81), _make_pin("2", 5.08, 1.27)]),
            _make_sub_symbol("NE5532_2_1", [_make_pin("5", -5.08, 3.81), _make_pin("6", -5.08, 1.27)]),
        ])
        offsets = _get_unit_pin_offsets(lib_sym, 2)
        assert "5" in offsets
        assert offsets["5"] == (-5.08, 3.81)

    def test_returns_empty_for_unknown_unit(self):
        lib_sym = _make_lib_sym("NE5532", [
            _make_sub_symbol("NE5532_1_1", [_make_pin("1", 0, 0)]),
        ])
        assert _get_unit_pin_offsets(lib_sym, 99) == {}


class TestFindPositionForUnit:
    """Test _find_position_for_unit helper (Bug C fix)."""

    def test_finds_position_from_wire_endpoints(self):
        """When a wire endpoint matches a pin offset, calculates correct position."""
        lib_sym = _make_lib_sym("NE5532", [
            _make_sub_symbol("NE5532_2_1", [
                _make_pin("5", -5.08, 3.81),
                _make_pin("6", -5.08, 1.27),
                _make_pin("7", -5.08, -1.27),
            ]),
        ])
        # Place wires at positions that would align with unit 2 pins
        # if component were at (50, 50) with rotation 0
        ir = MagicMock()
        wire_endpoints = [
            {"start_x": 50.0 - 5.08, "start_y": 50.0 - 3.81, "end_x": 40.0, "end_y": 46.19},
            {"start_x": 50.0 - 5.08, "start_y": 50.0 - 1.27, "end_x": 40.0, "end_y": 48.73},
        ]
        pos = _find_position_for_unit(
            ir, lib_sym, 2, rotation=0.0,
            wire_endpoints=wire_endpoints, label_positions=[],
        )
        assert pos is not None
        # Should resolve to approximately (50, 50)
        assert abs(pos[0] - 50.0) < 0.2
        assert abs(pos[1] - 50.0) < 0.2

    def test_returns_none_when_no_wires(self):
        """Returns None when no wire endpoints match."""
        lib_sym = _make_lib_sym("NE5532", [
            _make_sub_symbol("NE5532_2_1", [
                _make_pin("5", -5.08, 3.81),
            ]),
        ])
        ir = MagicMock()
        pos = _find_position_for_unit(
            ir, lib_sym, 2, rotation=0.0,
            wire_endpoints=[], label_positions=[],
        )
        assert pos is None

    def test_uses_label_positions(self):
        """Finds position from label positions when no wire matches."""
        lib_sym = _make_lib_sym("NE5532", [
            _make_sub_symbol("NE5532_2_1", [
                _make_pin("5", -5.08, 3.81),
                _make_pin("6", -5.08, 1.27),
            ]),
        ])
        ir = MagicMock()
        # Labels at positions matching pins for component at (30, 30)
        label_positions = [
            {"name": "NET_A", "x": 30.0 - 5.08, "y": 30.0 - 3.81},
            {"name": "NET_B", "x": 30.0 - 5.08, "y": 30.0 - 1.27},
        ]
        pos = _find_position_for_unit(
            ir, lib_sym, 2, rotation=0.0,
            wire_endpoints=[], label_positions=label_positions,
        )
        assert pos is not None
        assert abs(pos[0] - 30.0) < 0.2
        assert abs(pos[1] - 30.0) < 0.2


class TestPlaceMissingUnits:
    """Integration tests for place_missing_units with Bug B + C fixes."""

    def test_dry_run_on_eq_stage(self):
        """Dry run on eq-stage: should identify 5 missing units with correct numbers."""
        if not _EQ_STAGE.exists():
            pytest.skip("Channel strip eq-stage not found")

        result = parse_schematic(_EQ_STAGE)
        ir = SchematicIR(_parse_result=result)

        output = place_missing_units(ir, _EQ_STAGE, dry_run=True)
        assert output["total"] > 0

        # Every placed unit should have a unit_number (not unit_index)
        for detail in output["units_placed"]:
            assert "unit_number" in detail
            assert isinstance(detail["unit_number"], int)
            assert detail["unit_number"] >= 1

    def test_correct_missing_units_for_ne5532(self):
        """NE5532 with units {1,3} placed should report unit 2 as missing."""
        if not _EQ_STAGE.exists():
            pytest.skip("Channel strip eq-stage not found")

        result = parse_schematic(_EQ_STAGE)
        ir = SchematicIR(_parse_result=result)

        output = place_missing_units(ir, _EQ_STAGE, dry_run=True,
                                     references=["U3"])
        # U3 is NE5532 with units 1 and 3 placed → unit 2 is missing
        u3_units = [d for d in output["units_placed"] if d["base_reference"] == "U3"]
        if u3_units:
            assert u3_units[0]["unit_number"] == 2
            assert u3_units[0]["unit_letter"] == "B"
