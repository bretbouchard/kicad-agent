"""Tests for net class lifecycle, new zone schemas, and conflict detection.

TDD RED phase: Tests for:
- RefillCopperZoneOp, ModifyZonePolygonOp, AddKeepoutAreaOp, RemoveKeepoutAreaOp schemas
- pcb_ops new functions: modify_zone_polygon, refill_copper_zone, add_keepout_area, remove_keepout_area
- detect_net_class_conflicts() in design_rules.py
- _handle_remove_net_class net reassignment logging
- Schema registration in schema.py
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestNewZoneSchemas:
    """Test new Pydantic operation schemas validate correctly."""

    def test_refill_copper_zone_with_uuid(self):
        """RefillCopperZoneOp validates with zone_uuid."""
        from kicad_agent.ops._schema_pcb import RefillCopperZoneOp
        op = RefillCopperZoneOp(
            target_file="board.kicad_pcb",
            zone_uuid="12345678-1234-1234-1234-123456789abc",
        )
        assert op.zone_uuid == "12345678-1234-1234-1234-123456789abc"
        assert op.op_type == "refill_copper_zone"

    def test_refill_copper_zone_with_index(self):
        """RefillCopperZoneOp validates with zone_index."""
        from kicad_agent.ops._schema_pcb import RefillCopperZoneOp
        op = RefillCopperZoneOp(
            target_file="board.kicad_pcb",
            zone_index=0,
        )
        assert op.zone_index == 0

    def test_refill_copper_zone_rejects_no_identifier(self):
        """RefillCopperZoneOp rejects when neither uuid nor index provided."""
        from kicad_agent.ops._schema_pcb import RefillCopperZoneOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RefillCopperZoneOp(target_file="board.kicad_pcb")

    def test_modify_zone_polygon_validates(self):
        """ModifyZonePolygonOp validates with uuid and polygon points."""
        from kicad_agent.ops._schema_pcb import ModifyZonePolygonOp
        op = ModifyZonePolygonOp(
            target_file="board.kicad_pcb",
            zone_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            polygon=[(0, 0), (10, 0), (10, 10)],
        )
        assert len(op.polygon) == 3
        assert op.op_type == "modify_zone_polygon"

    def test_modify_zone_polygon_rejects_less_than_3_points(self):
        """ModifyZonePolygonOp rejects polygon with < 3 points."""
        from kicad_agent.ops._schema_pcb import ModifyZonePolygonOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ModifyZonePolygonOp(
                target_file="board.kicad_pcb",
                zone_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                polygon=[(0, 0), (10, 0)],
            )

    def test_add_keepout_area_validates(self):
        """AddKeepoutAreaOp validates with layer, keepout_type, polygon."""
        from kicad_agent.ops._schema_pcb import AddKeepoutAreaOp
        op = AddKeepoutAreaOp(
            target_file="board.kicad_pcb",
            layer="F.Cu",
            keepout_type="through_hole",
            polygon=[(0, 0), (5, 0), (5, 5), (0, 5)],
        )
        assert op.keepout_type == "through_hole"
        assert op.op_type == "add_keepout_area"

    def test_add_keepout_area_rejects_invalid_type(self):
        """AddKeepoutAreaOp rejects invalid keepout_type."""
        from kicad_agent.ops._schema_pcb import AddKeepoutAreaOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AddKeepoutAreaOp(
                target_file="board.kicad_pcb",
                keepout_type="invalid_type",
                polygon=[(0, 0), (5, 0), (5, 5)],
            )

    def test_remove_keepout_area_with_uuid(self):
        """RemoveKeepoutAreaOp validates with zone_uuid."""
        from kicad_agent.ops._schema_pcb import RemoveKeepoutAreaOp
        op = RemoveKeepoutAreaOp(
            target_file="board.kicad_pcb",
            zone_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        assert op.zone_uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_remove_keepout_area_rejects_no_identifier(self):
        """RemoveKeepoutAreaOp rejects when neither uuid nor index provided."""
        from kicad_agent.ops._schema_pcb import RemoveKeepoutAreaOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RemoveKeepoutAreaOp(target_file="board.kicad_pcb")


# ---------------------------------------------------------------------------
# pcb_ops function tests
# ---------------------------------------------------------------------------

ZONE_UUID = "11111111-2222-3333-4444-555555555555"

# Minimal PCB content with a zone containing filled data
PCB_WITH_FILLED_ZONE = f"""\
(kicad_pcb
  (version 20260206)

  (zone
    (net 0 "")
    (layer "F.Cu")
    (uuid "{ZONE_UUID}")
    (hatch edge 0.5)
    (connect_pads
      (clearance 0.5)
    )
    (min_thickness 0.25)
    (fill yes
      (thermal_gap 0.5)
      (thermal_bridge_width 0.5)
    )
    (filled_polygon
      (pts
        (xy 10 10)
        (xy 90 10)
        (xy 90 90)
      )
    )
    (filled_areas
      (filled_area_hash_value "abc123")
    )
    (polygon
      (pts
        (xy 10 10)
        (xy 90 10)
        (xy 90 90)
        (xy 10 90)
      )
    )
  )
)
"""


class TestPcbOpsZoneFunctions:
    """Test new pcb_ops functions for zone operations."""

    def test_modify_zone_polygon_updates_via_raw_writer(self):
        """modify_zone_polygon() delegates to PcbRawWriter.modify_zone_polygon()."""
        from kicad_agent.ops.pcb_ops import modify_zone_polygon
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

        ir = MagicMock()
        ir.raw_content = PCB_WITH_FILLED_ZONE
        new_polygon = [(1, 2), (3, 4), (5, 6)]

        result = modify_zone_polygon(ir, "board.kicad_pcb", ZONE_UUID, new_polygon)

        assert result["modified"] is True
        assert ir.commit_raw_content.called

    def test_refill_copper_zone_strips_filled_data(self):
        """refill_copper_zone() strips filled_polygon and filled_areas from zone."""
        from kicad_agent.ops.pcb_ops import refill_copper_zone
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

        ir = MagicMock()
        ir.raw_content = PCB_WITH_FILLED_ZONE

        result = refill_copper_zone(ir, "board.kicad_pcb", zone_uuid=ZONE_UUID)

        assert result["refilled"] is True
        assert ir.commit_raw_content.called
        # Verify filled_polygon and filled_areas removed from committed content
        committed = ir.commit_raw_content.call_args[0][0]
        assert "filled_polygon" not in committed
        assert "filled_areas" not in committed

    def test_refill_copper_zone_by_index(self):
        """refill_copper_zone() works with zone_index fallback."""
        from kicad_agent.ops.pcb_ops import refill_copper_zone

        ir = MagicMock()
        ir.raw_content = PCB_WITH_FILLED_ZONE

        result = refill_copper_zone(ir, "board.kicad_pcb", zone_index=0)

        assert result["refilled"] is True

    def test_add_keepout_area_inserts_zone(self):
        """add_keepout_area() builds and inserts a keepout zone."""
        from kicad_agent.ops.pcb_ops import add_keepout_area

        ir = MagicMock()
        ir.raw_content = "(kicad_pcb\n)\n"

        result = add_keepout_area(
            ir, "board.kicad_pcb",
            layer="F.Cu",
            keepout_type="through_hole",
            polygon=[(0, 0), (5, 0), (5, 5), (0, 5)],
        )

        assert result["keepout_added"] is True
        assert ir.commit_raw_content.called
        committed = ir.commit_raw_content.call_args[0][0]
        assert "keepout" in committed

    def test_remove_keepout_area_removes_by_uuid(self):
        """remove_keepout_area() removes keepout zone via PcbRawWriter."""
        from kicad_agent.ops.pcb_ops import remove_keepout_area

        ir = MagicMock()
        ir.raw_content = PCB_WITH_FILLED_ZONE

        result = remove_keepout_area(
            ir, "board.kicad_pcb", zone_uuid=ZONE_UUID,
        )

        assert result["removed"] is True
        assert ir.commit_raw_content.called


# ---------------------------------------------------------------------------
# Net class conflict detection tests
# ---------------------------------------------------------------------------

class TestNetClassConflictDetection:
    """Test detect_net_class_conflicts() in design_rules.py."""

    def test_conflict_when_clearance_violates_other_class(self):
        """detect_net_class_conflicts() returns conflicts when clearance < other."""
        from kicad_agent.project.design_rules import (
            DesignRulesFile,
            NetClassDef,
            detect_net_class_conflicts,
        )

        dru = DesignRulesFile(
            net_classes=[
                NetClassDef(name="Default", clearance=0.2, track_width=0.25),
                NetClassDef(name="HighSpeed", clearance=0.15, track_width=0.1),
            ]
        )

        conflicts = detect_net_class_conflicts(
            dru, "Default", clearance=0.1,
        )

        assert len(conflicts) > 0
        # At minimum, lowering Default clearance below HighSpeed should warn
        types = [c["type"] for c in conflicts]
        assert any("clearance" in t.lower() for t in types)

    def test_no_conflicts_when_clearance_ok(self):
        """detect_net_class_conflicts() returns empty list when no conflicts."""
        from kicad_agent.project.design_rules import (
            DesignRulesFile,
            NetClassDef,
            detect_net_class_conflicts,
        )

        dru = DesignRulesFile(
            net_classes=[
                NetClassDef(name="Default", clearance=0.2, track_width=0.25),
                NetClassDef(name="Power", clearance=0.3, track_width=0.5),
            ]
        )

        # Raising Default clearance to >= Power clearance: no conflict
        conflicts = detect_net_class_conflicts(
            dru, "Default", clearance=0.3,
        )

        assert conflicts == []

    def test_no_conflicts_for_single_class(self):
        """detect_net_class_conflicts() returns empty list with only one class."""
        from kicad_agent.project.design_rules import (
            DesignRulesFile,
            NetClassDef,
            detect_net_class_conflicts,
        )

        dru = DesignRulesFile(
            net_classes=[
                NetClassDef(name="Default", clearance=0.2),
            ]
        )

        conflicts = detect_net_class_conflicts(
            dru, "Default", clearance=0.1,
        )

        assert conflicts == []


# ---------------------------------------------------------------------------
# RemoveNetClassOp handler tests (net reassignment)
# ---------------------------------------------------------------------------

class TestRemoveNetClassHandler:
    """Test _handle_remove_net_class reassignment behavior."""

    def test_remove_net_class_includes_nets_warning(self):
        """_handle_remove_net_class logs nets reverting to Default."""
        from kicad_agent.ops.handlers.project import _handle_remove_net_class

        # Create a real dru file with a net class that has nets
        dru_content = """\
(version 20240517)

(net_class "Power" "Power nets"
  (clearance 0.3)
  (trace_width 0.5)
  (add_net "VCC")
  (add_net "+3.3V")
)
"""
        op = MagicMock()
        op.name = "Power"

        tmp_path = Path("/tmp/test_dru_79_03.kicad_dru")
        tmp_path.write_text(dru_content)

        try:
            result = _handle_remove_net_class(op, tmp_path)

            assert result["action"] == "removed"
            assert "reassigned_nets" in result
            assert len(result["reassigned_nets"]) == 2
            assert "VCC" in result["reassigned_nets"]
            assert "+3.3V" in result["reassigned_nets"]
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Schema registration tests
# ---------------------------------------------------------------------------

class TestSchemaRegistration:
    """Test new schemas are registered in schema.py."""

    def test_refill_copper_zone_in_all(self):
        """RefillCopperZoneOp is in schema.py __all__."""
        from kicad_agent.ops.schema import __all__
        assert "RefillCopperZoneOp" in __all__

    def test_modify_zone_polygon_in_all(self):
        """ModifyZonePolygonOp is in schema.py __all__."""
        from kicad_agent.ops.schema import __all__
        assert "ModifyZonePolygonOp" in __all__

    def test_add_keepout_area_in_all(self):
        """AddKeepoutAreaOp is in schema.py __all__."""
        from kicad_agent.ops.schema import __all__
        assert "AddKeepoutAreaOp" in __all__

    def test_remove_keepout_area_in_all(self):
        """RemoveKeepoutAreaOp is in schema.py __all__."""
        from kicad_agent.ops.schema import __all__
        assert "RemoveKeepoutAreaOp" in __all__

    def test_new_schemas_importable_from_schema(self):
        """All new schemas can be imported from kicad_agent.ops.schema."""
        from kicad_agent.ops.schema import (
            RefillCopperZoneOp,
            ModifyZonePolygonOp,
            AddKeepoutAreaOp,
            RemoveKeepoutAreaOp,
        )
        # Verify they are real classes with op_type discriminators
        assert RefillCopperZoneOp.model_fields["op_type"].default == "refill_copper_zone"
        assert ModifyZonePolygonOp.model_fields["op_type"].default == "modify_zone_polygon"
        assert AddKeepoutAreaOp.model_fields["op_type"].default == "add_keepout_area"
        assert RemoveKeepoutAreaOp.model_fields["op_type"].default == "remove_keepout_area"

    def test_new_schemas_in_operation_union(self):
        """All new schemas are in the Operation discriminated union."""
        from kicad_agent.ops.schema import Operation
        # Try to validate each op type through the union
        for op_type in ["refill_copper_zone", "modify_zone_polygon",
                        "add_keepout_area", "remove_keepout_area"]:
            # This would raise if not in the union
            Operation.model_validate({"root": {
                "op_type": op_type,
                "target_file": "board.kicad_pcb",
                "zone_uuid": "11111111-2222-3333-4444-555555555555",
                "polygon": [(0, 0), (10, 0), (10, 10)],
            }})
