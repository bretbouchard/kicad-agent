"""Tests for schematic ERC repair operations.

Tests build schematics programmatically using kiutils for precise position
control, then run repair operations and verify corrections.
"""

import math
import tempfile
from pathlib import Path

import pytest
from kiutils.items.common import Position
from kiutils.items.schitems import Connection, LocalLabel
from kiutils.schematic import Schematic

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.repair import (
    SNAP_TOLERANCE,
    detect_shorted_nets,
    place_no_connects,
    remove_orphaned_labels,
    repair_wire_snapping,
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
