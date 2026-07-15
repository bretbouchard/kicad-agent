"""Tests for fix providers (Phase 92)."""

from __future__ import annotations

import pytest

from volta.validation.gates.fix_providers import (
    ManufacturingExportFixProvider,
    PlacementBoundsFixProvider,
    RoutingManualMarkFixProvider,
    SchematicFootprintFixProvider,
)


class TestSchematicFootprintFixProvider:
    def test_classifies_missing_footprint(self) -> None:
        p = SchematicFootprintFixProvider()
        assert p.classify_blocker("missing footprint for R1") == "schematic_footprint"

    def test_classifies_footprint_not_found(self) -> None:
        p = SchematicFootprintFixProvider()
        assert p.classify_blocker("footprint not found: LM7805") == "schematic_footprint"

    def test_proposes_fix(self) -> None:
        p = SchematicFootprintFixProvider()
        result = p.propose_fix("missing footprint", {"target_file": "test.kicad_sch"})
        assert result is not None
        assert result.proposed_op["op_type"] == "add_component"
        assert result.source.value == "deterministic"
        assert result.confidence == 1.0

    def test_returns_none_for_unrecognized(self) -> None:
        p = SchematicFootprintFixProvider()
        assert p.propose_fix("some other blocker", {}) is None


class TestPlacementBoundsFixProvider:
    def test_classifies_outside_outline(self) -> None:
        p = PlacementBoundsFixProvider()
        assert p.classify_blocker("Component R1 outside board outline") == "placement_bounds"

    def test_classifies_out_of_bounds(self) -> None:
        p = PlacementBoundsFixProvider()
        assert p.classify_blocker("U1 is out of bounds") == "placement_bounds"

    def test_proposes_fix(self) -> None:
        p = PlacementBoundsFixProvider()
        result = p.propose_fix("outside board outline", {
            "target_file": "test.kicad_pcb",
            "component_ref": "R1",
        })
        assert result is not None
        assert result.proposed_op["op_type"] == "move_component"
        assert result.confidence == 1.0

    def test_returns_none_for_unrecognized(self) -> None:
        p = PlacementBoundsFixProvider()
        assert p.propose_fix("DRC error", {}) is None


class TestRoutingManualMarkFixProvider:
    def test_classifies_unrouted_net(self) -> None:
        p = RoutingManualMarkFixProvider()
        assert p.classify_blocker("Unrouted net NET_VCC") == "routing_manual"

    def test_classifies_unconnected(self) -> None:
        p = RoutingManualMarkFixProvider()
        assert p.classify_blocker("unconnected pad on U1") == "routing_manual"

    def test_proposes_fix(self) -> None:
        p = RoutingManualMarkFixProvider()
        result = p.propose_fix("unrouted net NET_VCC", {
            "target_file": "test.kicad_pcb",
            "net_name": "NET_VCC",
        })
        assert result is not None
        assert result.proposed_op["op_type"] == "add_net_flag"

    def test_returns_none_for_unrecognized(self) -> None:
        p = RoutingManualMarkFixProvider()
        assert p.propose_fix("missing footprint", {}) is None


class TestManufacturingExportFixProvider:
    def test_classifies_missing_export(self) -> None:
        p = ManufacturingExportFixProvider()
        assert p.classify_blocker("Missing export artifact: gerbers") == "manufacturing_export"

    def test_classifies_missing_required(self) -> None:
        p = ManufacturingExportFixProvider()
        assert p.classify_blocker("Missing required export: drill") == "manufacturing_export"

    def test_proposes_fix(self) -> None:
        p = ManufacturingExportFixProvider()
        result = p.propose_fix("missing export", {
            "target_file": "test.kicad_pcb",
            "missing_artifact": "gerbers",
        })
        assert result is not None
        assert result.proposed_op["op_type"] == "export"

    def test_returns_none_for_unrecognized(self) -> None:
        p = ManufacturingExportFixProvider()
        assert p.propose_fix("unrouted net", {}) is None
