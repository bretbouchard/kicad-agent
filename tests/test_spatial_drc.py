"""Tests for spatial-grounded DRC/ERC enrichment pipeline (VP-07).

11 tests covering SpatialViolation, enrich_drc_result, enrich_erc_result,
and helper functions. Most tests use mock data; the nearest_footprint test
uses the real Arduino_Mega fixture.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from kicad_agent.spatial.primitives import SpatialPoint
from kicad_agent.validation.erc_drc import DrcResult, ErcResult, Severity, Violation
from kicad_agent.validation.spatial_drc import (
    SpatialViolation,
    _build_spatial_context,
    _find_nearest_footprint,
    enrich_drc_result,
    enrich_erc_result,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "Arduino_Mega"


def _make_drc_result(
    violations: tuple[Violation, ...] | None = None,
    passed: bool = False,
    error_message: str | None = None,
) -> DrcResult:
    """Helper to create a mock DrcResult for testing."""
    if violations is None:
        violations = (
            Violation(
                description="Clearance violation",
                severity=Severity.ERROR,
                type="clearance",
                items=(
                    {"pos": {"x": 10.5, "y": 22.1}, "uuid": "v1"},
                    {"pos": {"x": 10.8, "y": 22.3}, "uuid": "v2"},
                ),
            ),
        )
    return DrcResult(
        passed=passed,
        file_path=Path("test.kicad_pcb"),
        violations=violations,
        error_message=error_message,
    )


def _make_erc_result(
    violations: tuple[Violation, ...] | None = None,
    passed: bool = False,
    error_message: str | None = None,
) -> ErcResult:
    """Helper to create a mock ErcResult for testing."""
    if violations is None:
        violations = (
            Violation(
                description="Pin not connected",
                severity=Severity.ERROR,
                type="pin_not_connected",
                items=(
                    {"pos": {"x": 5.0, "y": 10.0}, "uuid": "erc1"},
                ),
            ),
        )
    return ErcResult(
        passed=passed,
        file_path=Path("test.kicad_sch"),
        violations=violations,
        error_message=error_message,
    )


class TestEnrichDrcResult:
    def test_enrich_drc_result_produces_spatial_violations(self):
        drc = _make_drc_result()
        results = enrich_drc_result(drc)
        assert len(results) == 1
        sv = results[0]
        assert isinstance(sv, SpatialViolation)
        assert len(sv.items) == 2
        assert all(isinstance(p, SpatialPoint) for p in sv.items)

    def test_spatial_violation_has_coordinates(self):
        drc = _make_drc_result()
        results = enrich_drc_result(drc)
        sv = results[0]
        assert sv.items[0].x == 10.5
        assert sv.items[0].y == 22.1
        assert sv.items[1].x == 10.8
        assert sv.items[1].y == 22.3

    def test_spatial_violation_format_report(self):
        drc = _make_drc_result()
        results = enrich_drc_result(drc)
        report = results[0].format_report()
        assert "[ERROR]" in report
        assert "Clearance violation" in report
        assert "<point>" in report
        assert "[10.5000, 22.1000]" in report
        assert "[10.8000, 22.3000]" in report

    def test_spatial_violation_to_json(self):
        drc = _make_drc_result()
        results = enrich_drc_result(drc)
        j = results[0].to_json()
        assert j["description"] == "Clearance violation"
        assert j["severity"] == "error"
        assert j["violation_type"] == "clearance"
        assert "items" in j
        assert "spatial_context" in j
        assert len(j["items"]) == 2
        assert j["items"][0]["x"] == 10.5
        assert j["items"][0]["y"] == 22.1

    def test_enrich_drc_empty_violations(self):
        drc = _make_drc_result(violations=(), passed=True)
        results = enrich_drc_result(drc)
        assert results == []

    def test_enrich_drc_with_error_message(self):
        drc = _make_drc_result(error_message="kicad-cli not found")
        results = enrich_drc_result(drc)
        assert results == []


class TestEnrichErcResult:
    def test_enrich_erc_result(self):
        erc = _make_erc_result()
        results = enrich_erc_result(erc)
        assert len(results) == 1
        sv = results[0]
        assert sv.items[0].x == 5.0
        assert sv.items[0].y == 10.0
        assert sv.items[0].entity_type == "erc_item"

    def test_enrich_erc_no_pos_data(self):
        """ERC items without pos key get SpatialPoint at (0, 0)."""
        violations = (
            Violation(
                description="Symbol pin not driven",
                severity=Severity.WARNING,
                type="pin_not_driven",
                items=(
                    {"uuid": "erc_no_pos"},
                ),
            ),
        )
        erc = _make_erc_result(violations=violations)
        results = enrich_erc_result(erc)
        assert len(results) == 1
        sv = results[0]
        assert sv.items[0].x == 0.0
        assert sv.items[0].y == 0.0
        assert sv.items[0].entity_type == "erc_item_no_pos"


class TestSpatialContext:
    def test_spatial_context_single_item(self):
        items = (SpatialPoint(45.2, 22.1, "drc_item", "v1"),)
        context = _build_spatial_context(items)
        assert "Violation at <point>" in context
        assert "[45.2000, 22.1000]" in context

    def test_spatial_context_multiple_items(self):
        items = (
            SpatialPoint(45.2, 22.1, "drc_item", "v1"),
            SpatialPoint(10.0, 5.0, "drc_item", "v2"),
        )
        context = _build_spatial_context(items)
        assert "Violation involves 2 items" in context
        assert "[45.2000, 22.1000]" in context
        assert "[10.0000, 5.0000]" in context


class TestFindNearestFootprint:
    def test_find_nearest_footprint(self):
        """Find nearest footprint using real Arduino_Mega fixture."""
        from kicad_agent.parser import parse_pcb
        from kicad_agent.parser.uuid_extractor import extract_uuids
        from kicad_agent.ir.pcb_ir import PcbIR

        pcb_path = FIXTURE_DIR / "Arduino_Mega.kicad_pcb"
        result = parse_pcb(pcb_path)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        pcb_ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

        # Query near the board center -- should find a real footprint
        ref = _find_nearest_footprint(50.0, 50.0, pcb_ir)
        assert ref is not None, "Expected to find at least one footprint"
        assert len(ref) > 0, "Reference designator should not be empty"
