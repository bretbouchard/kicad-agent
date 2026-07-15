"""Tests for ae-23 auto_route_freerouting pipeline operation.

TDD RED phase: These tests should fail until the schema and handler are implemented.
"""

import pytest


class TestAutoRouteFreeroutingSchema:
    """Tests for AutoRouteFreeroutingOp Pydantic schema."""

    def test_default_values(self):
        """AutoRouteFreeroutingOp should validate with correct defaults."""
        from volta.ops._schema_gap import AutoRouteFreeroutingOp

        op = AutoRouteFreeroutingOp(target_file="test.kicad_pcb")
        assert op.op_type == "auto_route_freerouting"
        assert op.passes == 25
        assert op.cleanup_shorts is True
        assert op.cleanup_dangling is True

    def test_custom_passes(self):
        """Should accept custom passes value."""
        from volta.ops._schema_gap import AutoRouteFreeroutingOp

        op = AutoRouteFreeroutingOp(target_file="test.kicad_pcb", passes=50)
        assert op.passes == 50

    def test_custom_cleanup_flags(self):
        """Should accept custom cleanup flags."""
        from volta.ops._schema_gap import AutoRouteFreeroutingOp

        op = AutoRouteFreeroutingOp(
            target_file="test.kicad_pcb",
            passes=10,
            cleanup_shorts=False,
            cleanup_dangling=False,
        )
        assert op.cleanup_shorts is False
        assert op.cleanup_dangling is False

    def test_passes_bounds(self):
        """Should reject passes outside 1-200 range."""
        from volta.ops._schema_gap import AutoRouteFreeroutingOp
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AutoRouteFreeroutingOp(target_file="test.kicad_pcb", passes=0)

        with pytest.raises(ValidationError):
            AutoRouteFreeroutingOp(target_file="test.kicad_pcb", passes=201)

    def test_operation_union_accepts(self):
        """Operation discriminated union should accept auto_route_freerouting."""
        from volta.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "auto_route_freerouting",
                "target_file": "test.kicad_pcb",
            }
        })
        assert op.root.op_type == "auto_route_freerouting"


class TestAutoRouteFreeroutingRegistry:
    """Tests for auto_route_freerouting registry and handler wiring."""

    def test_registry_entry(self):
        """auto_route_freerouting should be in the operation registry."""
        from volta.ops.registry import _RAW_CATALOG

        assert "auto_route_freerouting" in _RAW_CATALOG
        entry = _RAW_CATALOG["auto_route_freerouting"]
        assert entry["category"] == "pcb"
        assert ".kicad_pcb" in entry["file_types"]
        assert entry["is_readonly"] is False
        assert "auto_route" in entry["conflicts"]

    def test_handler_registered(self):
        """auto_route_freerouting handler should be in _PCB_HANDLERS."""
        from volta.ops.handlers import _PCB_HANDLERS

        assert "auto_route_freerouting" in _PCB_HANDLERS

    def test_all_ae20_through_ae23_registered(self):
        """All ae-20 through ae-23 operations should be registered."""
        from volta.ops.registry import _RAW_CATALOG
        from volta.ops.handlers import _PCB_HANDLERS

        for ot in ["fill_zones", "strip_shorts", "remove_dangling_tracks", "auto_route_freerouting"]:
            assert ot in _RAW_CATALOG, f"{ot} missing from registry"
            assert ot in _PCB_HANDLERS, f"{ot} handler not registered"
