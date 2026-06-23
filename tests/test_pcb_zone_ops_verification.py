"""Tests for zone ops verification (Phase 101-06).

Verifies:
- ``add_copper_zone`` produces correct KiCad 10 format with paired
  ``(net N)`` + ``(net_name "NAME")`` tokens, ``(filled_areas_thickness no)``,
  and ``(fill ...)`` without the legacy ``yes`` argument.
- ``delete_copper_zone`` (Phase 101-06 alias) delegates to remove_copper_zone
  and deletes by UUID.
- ``add_zone_keepout`` (Phase 101-06 alias) produces a ``(rule (clearance N))``
  wrapper when ``rule_clearance_mm`` is set.
- ``add_keepout_area`` still works without rule_clearance_mm (backward compat).
- UUIDs generated per invocation are unique.
- Handler dispatch via OperationExecutor writes correct content to disk.

Plan 101-06 covers Council C1 (kicad-rick) and routing-rick M5 findings.
"""

import re
import tempfile
import uuid as _uuid
from pathlib import Path

import pytest

from kicad_agent.ops.pcb_raw_writer import PcbRawWriter


# ---------------------------------------------------------------------------
# Minimal PCB fixture
# ---------------------------------------------------------------------------

MINIMAL_PCB = """(kicad_pcb
  (version 20260206)
  (generator "kicad-agent-test")
  (general (thickness 1.6))
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
  (net 0 "")
  (net 1 "GND")
)
"""


@pytest.fixture
def pcb_path():
    """Write a minimal PCB file to a temp dir and return its Path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.kicad_pcb"
        path.write_text(MINIMAL_PCB, encoding="utf-8")
        yield path


# ---------------------------------------------------------------------------
# PcbRawWriter.build_zone_sexp — KiCad 10 format verification
# ---------------------------------------------------------------------------

class TestBuildZoneSexpKiCad10:
    """Verify build_zone_sexp produces KiCad 10 ground-truth format."""

    def test_add_copper_zone_kicad10_format(self):
        """Zone output contains all KiCad 10 required tokens."""
        result = PcbRawWriter.build_zone_sexp(
            net_number=1,
            net_name="GND",
            layer="F.Cu",
            polygon=[(0, 0), (50, 0), (50, 50), (0, 50)],
        )
        # Required: paired (net N) + (net_name "NAME") (Phase 101-06, Council C1)
        assert re.search(r'\(net\s+1\s*\)', result), \
            "Zone must have (net 1) numbered form"
        assert '(net_name "GND")' in result, \
            "Zone must have (net_name \"GND\") paired with (net N)"
        # Required: (filled_areas_thickness no) (KiCad 10 rule)
        assert "(filled_areas_thickness no)" in result
        # Required: (fill ...) without legacy "yes" argument
        assert "(fill" in result
        assert "(fill yes" not in result
        # Required: (pts xy X Y) outline format, NOT legacy (vertex ...)
        assert "(pts" in result
        assert "(xy 0 0)" in result
        assert "(xy 50 50)" in result
        assert "(vertex" not in result

    def test_add_copper_zone_uuid_generated(self):
        """Each invocation generates a unique UUID."""
        uuid1 = str(_uuid.uuid4())
        uuid2 = str(_uuid.uuid4())
        assert uuid1 != uuid2  # sanity check

        result1 = PcbRawWriter.build_zone_sexp(
            net_number=1, net_name="GND", layer="F.Cu",
            polygon=[(0, 0), (10, 10)], uuid=uuid1,
        )
        result2 = PcbRawWriter.build_zone_sexp(
            net_number=1, net_name="GND", layer="F.Cu",
            polygon=[(0, 0), (10, 10)], uuid=uuid2,
        )
        assert f'(uuid "{uuid1}")' in result1
        assert f'(uuid "{uuid2}")' in result2
        assert uuid1 not in result2
        assert uuid2 not in result1

    def test_zone_no_legacy_yes_fill(self):
        """(fill yes) is legacy -- KiCad 10 uses (fill (thermal_gap ...) ...)."""
        result = PcbRawWriter.build_zone_sexp(
            net_number=0, net_name="", layer="B.Cu",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        )
        # Must NOT contain legacy (fill yes ...) form
        assert "(fill yes" not in result
        # Must contain thermal_gap and thermal_bridge_width inside fill
        assert "(thermal_gap" in result
        assert "(thermal_bridge_width" in result

    def test_zone_unconnected_net_zero_format(self):
        """Unconnected zone uses (net 0) + (net_name \"\") pair."""
        result = PcbRawWriter.build_zone_sexp(
            net_number=0, net_name="", layer="F.Cu",
            polygon=[(0, 0), (10, 10)],
        )
        assert "(net 0)" in result
        assert '(net_name "")' in result

    def test_zone_priority_emitted_when_nonzero(self):
        """Priority token emitted only when > 0 (matches KiCad writer behavior)."""
        result_default = PcbRawWriter.build_zone_sexp(
            net_number=1, net_name="GND", layer="F.Cu",
            polygon=[(0, 0), (10, 10)],
        )
        result_priority = PcbRawWriter.build_zone_sexp(
            net_number=1, net_name="GND", layer="F.Cu",
            polygon=[(0, 0), (10, 10)], priority=5,
        )
        # Default priority (0) should NOT emit the priority line
        assert "(priority" not in result_default
        # Non-zero priority emits (priority N)
        assert "(priority 5)" in result_priority


# ---------------------------------------------------------------------------
# Handler dispatch: delete_copper_zone alias
# ---------------------------------------------------------------------------

class TestDeleteCopperZoneAlias:
    """Verify delete_copper_zone op delegates to remove_copper_zone."""

    def test_delete_copper_zone_schema_validates(self):
        """DeleteCopperZoneOp schema accepts required fields."""
        from kicad_agent.ops._schema_pcb import DeleteCopperZoneOp
        op = DeleteCopperZoneOp(
            target_file="board.kicad_pcb",
            zone_uuid="abc123",
        )
        assert op.op_type == "delete_copper_zone"
        assert op.zone_uuid == "abc123"

    def test_delete_copper_zone_schema_requires_uuid(self):
        """DeleteCopperZoneOp requires zone_uuid (not optional like remove)."""
        from kicad_agent.ops._schema_pcb import DeleteCopperZoneOp
        with pytest.raises(Exception):
            DeleteCopperZoneOp(target_file="board.kicad_pcb")

    def test_delete_copper_zone_handler_registered(self):
        """Handler is registered under the delete_copper_zone name."""
        from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
        assert "delete_copper_zone" in _PCB_HANDLERS
        # Alias points to a callable (the wrapper around remove_copper_zone)
        assert callable(_PCB_HANDLERS["delete_copper_zone"])

    def test_delete_copper_zone_by_uuid_via_executor(self, pcb_path):
        """delete_copper_zone end-to-end: add zone, then delete by UUID."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        # First, add a zone
        test_uuid = str(_uuid.uuid4())
        zone_sexp = PcbRawWriter.build_zone_sexp(
            net_number=1, net_name="GND", layer="F.Cu",
            polygon=[(0, 0), (50, 0), (50, 50), (0, 50)],
            uuid=test_uuid,
        )
        original = pcb_path.read_text(encoding="utf-8")
        updated = PcbRawWriter.insert_zone(original, zone_sexp)
        pcb_path.write_text(updated, encoding="utf-8")

        # Verify zone is present
        content = pcb_path.read_text(encoding="utf-8")
        assert test_uuid in content

        # Now delete via the alias op
        op = Operation.model_validate({
            "root": {
                "op_type": "delete_copper_zone",
                "target_file": pcb_path.name,
                "zone_uuid": test_uuid,
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        # Zone UUID no longer in PCB content
        final = pcb_path.read_text(encoding="utf-8")
        assert test_uuid not in final


# ---------------------------------------------------------------------------
# Handler dispatch: add_zone_keepout alias
# ---------------------------------------------------------------------------

class TestAddZoneKeepoutAlias:
    """Verify add_zone_keepout op delegates to add_keepout_area."""

    def test_add_zone_keepout_schema_validates(self):
        """AddZoneKeepoutOp schema accepts rule_clearance_mm."""
        from kicad_agent.ops._schema_pcb import AddZoneKeepoutOp
        op = AddZoneKeepoutOp(
            target_file="board.kicad_pcb",
            layer="*",
            keepout_type="through_hole",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
            rule_clearance_mm=3.0,
        )
        assert op.op_type == "add_zone_keepout"
        assert op.rule_clearance_mm == 3.0

    def test_add_zone_keepout_schema_rule_clearance_optional(self):
        """AddZoneKeepoutOp rule_clearance_mm is optional (backward compat)."""
        from kicad_agent.ops._schema_pcb import AddZoneKeepoutOp
        op = AddZoneKeepoutOp(
            target_file="board.kicad_pcb",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        )
        assert op.rule_clearance_mm is None

    def test_add_zone_keepout_handler_registered(self):
        """Handler is registered under the add_zone_keepout name."""
        from kicad_agent.ops.handlers.pcb import _PCB_HANDLERS
        assert "add_zone_keepout" in _PCB_HANDLERS
        assert callable(_PCB_HANDLERS["add_zone_keepout"])

    def test_add_zone_keepout_with_rule_clearance_via_executor(self, pcb_path):
        """add_zone_keepout end-to-end: produces (rule (clearance N)) wrapper."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_zone_keepout",
                "target_file": pcb_path.name,
                "layer": "*",
                "keepout_type": "through_hole",
                "polygon": [[0, 0], [50, 0], [50, 50], [0, 50]],
                "rule_clearance_mm": 3.0,
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        content = pcb_path.read_text(encoding="utf-8")
        # Must contain (rule (clearance 3)) per routing-rick M5
        assert re.search(r'\(rule\s*\(\s*clearance\s+3\)', content), \
            "add_zone_keepout must emit (rule (clearance N)) wrapper"
        # Must contain (keepout ...) and (polygon (pts ...))
        assert "(keepout through_hole)" in content
        assert "(pts" in content
        # Must NOT contain legacy (fill yes)
        assert "(fill yes" not in content

    def test_add_zone_keepout_without_rule_clearance(self, pcb_path):
        """add_zone_keepout without rule_clearance_mm omits (rule ...) wrapper."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_zone_keepout",
                "target_file": pcb_path.name,
                "polygon": [[0, 0], [50, 0], [50, 50], [0, 50]],
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        content = pcb_path.read_text(encoding="utf-8")
        assert "(keepout through_hole)" in content
        # No rule wrapper when rule_clearance_mm is None
        assert "(rule" not in content


# ---------------------------------------------------------------------------
# Backward compat: add_keepout_area + add_copper_zone still work
# ---------------------------------------------------------------------------

class TestExistingOpsBackwardCompat:
    """Verify existing add_copper_zone and add_keepout_area still function."""

    def test_add_copper_zone_via_executor(self, pcb_path):
        """add_copper_zone produces KiCad 10 zone in the PCB file."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_copper_zone",
                "target_file": pcb_path.name,
                "net_name": "GND",
                "layer": "F.Cu",
                "clearance": 0.5,
                "min_width": 0.25,
                "priority": 0,
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        content = pcb_path.read_text(encoding="utf-8")
        # KiCad 10 zone markers
        assert '(net_name "GND")' in content
        assert "(filled_areas_thickness no)" in content
        assert "(pts" in content
        assert "(xy" in content

    def test_add_keepout_area_alias_works(self, pcb_path):
        """add_keepout_area still works (backward compat with new schema)."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_keepout_area",
                "target_file": pcb_path.name,
                "layer": "*",
                "keepout_type": "via",
                "polygon": [[0, 0], [30, 0], [30, 30], [0, 30]],
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        content = pcb_path.read_text(encoding="utf-8")
        assert "(keepout via)" in content
        assert '(net_name "")' in content
        assert "(filled_areas_thickness no)" in content


# ---------------------------------------------------------------------------
# Schema exports
# ---------------------------------------------------------------------------

class TestSchemaExports:
    """Verify DeleteCopperZoneOp and AddZoneKeepoutOp are exported."""

    def test_delete_copper_zone_op_in_schema_all(self):
        """DeleteCopperZoneOp is in schema.py __all__."""
        from kicad_agent.ops import schema
        assert "DeleteCopperZoneOp" in schema.__all__

    def test_add_zone_keepout_op_in_schema_all(self):
        """AddZoneKeepoutOp is in schema.py __all__."""
        from kicad_agent.ops import schema
        assert "AddZoneKeepoutOp" in schema.__all__

    def test_delete_copper_zone_op_in_union(self):
        """Operation union includes DeleteCopperZoneOp."""
        from kicad_agent.ops._schema_pcb import DeleteCopperZoneOp
        from kicad_agent.ops.schema import Operation
        # Verify the discriminated union accepts the new op_type
        op = Operation.model_validate({
            "root": {
                "op_type": "delete_copper_zone",
                "target_file": "x.kicad_pcb",
                "zone_uuid": "abc",
            }
        })
        assert isinstance(op.root, DeleteCopperZoneOp)

    def test_add_zone_keepout_op_in_union(self):
        """Operation union includes AddZoneKeepoutOp."""
        from kicad_agent.ops._schema_pcb import AddZoneKeepoutOp
        from kicad_agent.ops.schema import Operation
        op = Operation.model_validate({
            "root": {
                "op_type": "add_zone_keepout",
                "target_file": "x.kicad_pcb",
                "polygon": [[0, 0], [1, 0], [1, 1]],
            }
        })
        assert isinstance(op.root, AddZoneKeepoutOp)
