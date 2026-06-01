"""Tests for DRC Intelligence: IntelligentDrcAnalyzer, EnrichedViolation, FixSuggester.

Plan 53-01 TDD tests. All tests use mock DrcResult objects constructed with
Violation tuples -- no kicad-cli dependency.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from kicad_agent.spatial.primitives import SpatialPoint
from kicad_agent.validation.erc_drc import DrcResult, Severity, Violation
from kicad_agent.validation.drc_intel import (
    EnrichedViolation,
    FixSuggester,
    IntelligentDrcAnalyzer,
    IntelligentDrcReport,
    SpatialFixSuggestion,
    ViolationClassification,
    _check_drc_version,
    _classify_violation,
)
from kicad_agent.validation.spatial_drc import SpatialViolation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sp(x: float, y: float, entity_type: str = "drc_item", eid: str = "item1") -> SpatialPoint:
    return SpatialPoint(x=x, y=y, entity_type=entity_type, entity_id=eid)


def _make_drc_result(
    violations: tuple[Violation, ...] = (),
    unconnected: tuple[Violation, ...] = (),
    kicad_version: str = "10.0.1",
    error_message: str | None = None,
) -> DrcResult:
    return DrcResult(
        passed=len(violations) == 0 and error_message is None,
        file_path=Path("/fake/board.kicad_pcb"),
        violations=violations,
        unconnected_items=unconnected,
        kicad_version=kicad_version,
        error_message=error_message,
    )


def _make_violation(
    desc: str = "test violation",
    severity: Severity = Severity.ERROR,
    vtype: str = "clearance",
    items: tuple[dict[str, Any], ...] = (),
) -> Violation:
    return Violation(
        description=desc,
        severity=severity,
        type=vtype,
        items=items,
    )


# ---------------------------------------------------------------------------
# Test 1: Clearance violation -> CONSTRAINT_VIOLATION, spatial_items, suggestions
# ---------------------------------------------------------------------------

class TestEnrichedViolationClearance:
    def test_classification_constraint(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(
                    desc="Clearance violation between copper features",
                    vtype="clearance",
                    items=(
                        {"pos": {"x": 10.0, "y": 20.0}, "uuid": "a1"},
                        {"pos": {"x": 11.0, "y": 21.0}, "uuid": "a2"},
                    ),
                ),
            ),
        )
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        assert len(report.enriched_violations) == 1
        ev = report.enriched_violations[0]
        assert ev.classification == ViolationClassification.CONSTRAINT_VIOLATION
        assert len(ev.items) == 2
        assert ev.items[0].x == 10.0
        assert ev.items[1].y == 21.0
        assert len(ev.fix_suggestions) > 0


# ---------------------------------------------------------------------------
# Test 2: Silk screen cosmetic violation -> COSMETIC
# ---------------------------------------------------------------------------

class TestEnrichedViolationCosmetic:
    def test_classification_cosmetic(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(
                    desc="Silkscreen overlap",
                    vtype="silk",
                    items=(
                        {"pos": {"x": 5.0, "y": 5.0}, "uuid": "b1"},
                    ),
                ),
            ),
        )
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        ev = report.enriched_violations[0]
        assert ev.classification == ViolationClassification.COSMETIC


# ---------------------------------------------------------------------------
# Test 3: Unconnected item -> MANUFACTURING
# ---------------------------------------------------------------------------

class TestEnrichedViolationManufacturing:
    def test_classification_manufacturing(self):
        drc = _make_drc_result(
            unconnected=(
                _make_violation(
                    desc="Unconnected pad",
                    vtype="unconnected",
                    severity=Severity.WARNING,
                    items=(
                        {"pos": {"x": 30.0, "y": 40.0}, "uuid": "c1"},
                    ),
                ),
            ),
        )
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        ev = report.enriched_violations[0]
        assert ev.classification == ViolationClassification.MANUFACTURING


# ---------------------------------------------------------------------------
# Test 4: FixSuggester clearance -> increase_clearance
# ---------------------------------------------------------------------------

class TestFixSuggesterClearance:
    def test_increase_clearance(self):
        items = (_sp(10.0, 20.0), _sp(11.0, 21.0))
        suggester = FixSuggester()
        results = suggester.suggest("clearance", "Clearance violation", items, "near")
        assert len(results) > 0
        s = results[0]
        assert s.action == "increase_clearance"
        assert s.confidence >= 0.0
        assert len(s.rationale) > 0


# ---------------------------------------------------------------------------
# Test 5: FixSuggester courtyard -> move_component
# ---------------------------------------------------------------------------

class TestFixSuggesterCourtyard:
    def test_move_component(self):
        items = (_sp(10.0, 20.0),)
        suggester = FixSuggester()
        results = suggester.suggest("courtyard", "Courtyard overlap", items, "")
        assert len(results) > 0
        assert results[0].action == "move_component"


# ---------------------------------------------------------------------------
# Test 6: FixSuggester via -> add_teardrop
# ---------------------------------------------------------------------------

class TestFixSuggesterVia:
    def test_add_teardrop(self):
        items = (_sp(15.0, 25.0),)
        suggester = FixSuggester()
        results = suggester.suggest("via_issue", "via pad too small", items, "")
        assert len(results) > 0
        assert results[0].action == "add_teardrop"


# ---------------------------------------------------------------------------
# Test 7: FixSuggester pad -> resize_pad
# ---------------------------------------------------------------------------

class TestFixSuggesterPad:
    def test_resize_pad(self):
        items = (_sp(15.0, 25.0),)
        suggester = FixSuggester()
        results = suggester.suggest("pad_issue", "pad annular ring too small", items, "")
        assert len(results) > 0
        assert results[0].action == "resize_pad"


# ---------------------------------------------------------------------------
# Test 8: FixSuggester unknown -> empty list
# ---------------------------------------------------------------------------

class TestFixSuggesterUnknown:
    def test_empty_for_unknown(self):
        items = (_sp(0.0, 0.0),)
        suggester = FixSuggester()
        results = suggester.suggest("totally_unknown_type_xyz", "mystery", items, "")
        assert results == []


# ---------------------------------------------------------------------------
# Test 9: Analyzer with 3 violations returns 3 enriched
# ---------------------------------------------------------------------------

class TestAnalyzerThreeViolations:
    def test_three_enriched(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(desc="v1", vtype="clearance", items=({"pos": {"x": 1.0, "y": 1.0}, "uuid": "d1"},)),
                _make_violation(desc="v2", vtype="courtyard", items=({"pos": {"x": 2.0, "y": 2.0}, "uuid": "d2"},)),
                _make_violation(desc="v3", vtype="silk", items=({"pos": {"x": 3.0, "y": 3.0}, "uuid": "d3"},)),
            ),
        )
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        assert len(report.enriched_violations) == 3


# ---------------------------------------------------------------------------
# Test 10: Analyzer with error_message returns empty report
# ---------------------------------------------------------------------------

class TestAnalyzerError:
    def test_empty_on_error(self):
        drc = _make_drc_result(error_message="kicad-cli failed")
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        assert len(report.enriched_violations) == 0
        assert report.total == 0


# ---------------------------------------------------------------------------
# Test 11: Report has total, by_classification, by_severity, kicad_version
# ---------------------------------------------------------------------------

class TestReportMetadata:
    def test_summary_stats(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(desc="v1", vtype="clearance", items=({"pos": {"x": 1.0, "y": 1.0}, "uuid": "e1"},)),
                _make_violation(
                    desc="v2", vtype="silk", severity=Severity.WARNING,
                    items=({"pos": {"x": 2.0, "y": 2.0}, "uuid": "e2"},),
                ),
            ),
            kicad_version="10.0.1",
        )
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        assert report.total == 2
        assert report.kicad_version == "10.0.1"
        assert report.by_classification.get("constraint_violation", 0) >= 1
        assert report.by_classification.get("cosmetic", 0) >= 1
        assert report.by_severity.get("error", 0) >= 1
        assert report.by_severity.get("warning", 0) >= 1


# ---------------------------------------------------------------------------
# Test 12: Version check - no warning for 10.x, warning for empty
# ---------------------------------------------------------------------------

class TestVersionCheck:
    def test_ok_for_v10(self):
        assert _check_drc_version("10.0.1") == []

    def test_warn_on_empty(self):
        warnings = _check_drc_version("")
        assert len(warnings) > 0
        assert "no kicad_version" in warnings[0].lower() or "missing" in warnings[0].lower()


# ---------------------------------------------------------------------------
# Test 13: Version check - warn on pre-10 versions
# ---------------------------------------------------------------------------

class TestVersionCheckLegacy:
    def test_warn_on_v7(self):
        warnings = _check_drc_version("7.99")
        assert len(warnings) > 0
        assert "7" in warnings[0]

    def test_warn_on_v8(self):
        warnings = _check_drc_version("8.0.1")
        assert len(warnings) > 0

    def test_warn_on_v9(self):
        warnings = _check_drc_version("9.0.0")
        assert len(warnings) > 0

    def test_ok_for_v11(self):
        assert _check_drc_version("11.0.0") == []


# ---------------------------------------------------------------------------
# Test 14: Analyzer with optional spatial_model parameter
# ---------------------------------------------------------------------------

class TestAnalyzerSpatialModel:
    def test_backward_compatible(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(
                    desc="clearance", vtype="clearance",
                    items=({"pos": {"x": 10.0, "y": 10.0}, "uuid": "f1"},),
                ),
            ),
        )
        mock_model = object()
        analyzer = IntelligentDrcAnalyzer(spatial_model=mock_model)
        report = analyzer.analyze(drc)
        assert len(report.enriched_violations) == 1


# ---------------------------------------------------------------------------
# Test 15: Analyzer with constraints links related_constraint
# ---------------------------------------------------------------------------

class TestAnalyzerConstraints:
    def test_links_constraint(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(
                    desc="clearance", vtype="clearance",
                    items=({"pos": {"x": 10.0, "y": 10.0}, "uuid": "g1"},),
                ),
            ),
        )
        # Mock constraint object with type name matching
        class MockConstraint:
            constraint_type = "clearance"
        constraints = [MockConstraint()]
        analyzer = IntelligentDrcAnalyzer(constraints=constraints)
        report = analyzer.analyze(drc)
        ev = report.enriched_violations[0]
        assert ev.related_constraint is not None


# ---------------------------------------------------------------------------
# Test 16: IntelligentDrcReport.to_json() produces serializable dict
# ---------------------------------------------------------------------------

class TestReportToJson:
    def test_to_json(self):
        drc = _make_drc_result(
            violations=(
                _make_violation(desc="v1", vtype="clearance", items=({"pos": {"x": 1.0, "y": 2.0}, "uuid": "h1"},)),
            ),
            kicad_version="10.0.1",
        )
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        j = report.to_json()
        assert isinstance(j, dict)
        assert "enriched_violations" in j
        assert "total" in j
        assert "by_classification" in j
        assert "by_severity" in j
        assert "kicad_version" in j
        assert j["total"] == 1
        assert j["kicad_version"] == "10.0.1"
        # Verify violation is serializable
        ev_json = j["enriched_violations"][0]
        assert "classification" in ev_json
        assert "fix_suggestions" in ev_json


# ---------------------------------------------------------------------------
# Test 17: EnrichedViolation.from_spatial_violation factory
# ---------------------------------------------------------------------------

class TestEnrichedViolationFactory:
    def test_from_spatial_violation(self):
        sv = SpatialViolation(
            description="test desc",
            severity="error",
            violation_type="clearance",
            items=(_sp(10.0, 20.0),),
            spatial_context="near U1",
            raw_items=({"pos": {"x": 10.0, "y": 20.0}},),
        )
        suggestions = (
            SpatialFixSuggestion(
                action="increase_clearance",
                confidence=0.85,
                rationale="Test rationale",
                target_items=sv.items,
            ),
        )
        ev = EnrichedViolation.from_spatial_violation(
            sv,
            classification=ViolationClassification.CONSTRAINT_VIOLATION,
            fix_suggestions=suggestions,
            kicad_version="10.0.1",
        )
        assert ev.description == "test desc"
        assert ev.severity == "error"
        assert ev.violation_type == "clearance"
        assert ev.items == sv.items
        assert ev.spatial_context == "near U1"
        assert ev.raw_items == sv.raw_items
        assert ev.classification == ViolationClassification.CONSTRAINT_VIOLATION
        assert len(ev.fix_suggestions) == 1
        assert ev.kicad_version == "10.0.1"


# ---------------------------------------------------------------------------
# Additional: SpatialFixSuggestion.to_json
# ---------------------------------------------------------------------------

class TestSpatialFixSuggestionToJson:
    def test_to_json(self):
        s = SpatialFixSuggestion(
            action="increase_clearance",
            confidence=0.85,
            rationale="Clearance too small",
            target_items=(_sp(10.0, 20.0),),
        )
        j = s.to_json()
        assert j["action"] == "increase_clearance"
        assert j["confidence"] == 0.85
        assert j["rationale"] == "Clearance too small"
        assert len(j["target_items"]) == 1


# ---------------------------------------------------------------------------
# Additional: EnrichedViolation.format_report
# ---------------------------------------------------------------------------

class TestEnrichedViolationFormatReport:
    def test_format_report(self):
        sv = SpatialViolation(
            description="Clearance violation",
            severity="error",
            violation_type="clearance",
            items=(_sp(10.0, 20.0),),
            spatial_context="near U1",
        )
        ev = EnrichedViolation.from_spatial_violation(
            sv,
            classification=ViolationClassification.CONSTRAINT_VIOLATION,
            fix_suggestions=(),
        )
        report = ev.format_report()
        assert "[ERROR]" in report
        assert "Clearance violation" in report
        assert "constraint_violation" in report


# ---------------------------------------------------------------------------
# Additional: _classify_violation pure function
# ---------------------------------------------------------------------------

class TestClassifyViolation:
    def test_clearance(self):
        assert _classify_violation("clearance", "") == ViolationClassification.CONSTRAINT_VIOLATION

    def test_width(self):
        assert _classify_violation("track_width", "") == ViolationClassification.CONSTRAINT_VIOLATION

    def test_unconnected(self):
        assert _classify_violation("unconnected", "") == ViolationClassification.MANUFACTURING

    def test_drill(self):
        assert _classify_violation("drill", "") == ViolationClassification.MANUFACTURING

    def test_silk(self):
        assert _classify_violation("silk", "") == ViolationClassification.COSMETIC

    def test_text(self):
        assert _classify_violation("text", "") == ViolationClassification.COSMETIC

    def test_unknown_defaults_constraint(self):
        assert _classify_violation("unknown_xyz", "") == ViolationClassification.CONSTRAINT_VIOLATION


# ---------------------------------------------------------------------------
# Additional: Version check logging
# ---------------------------------------------------------------------------

class TestVersionLogging:
    def test_logs_warning_on_empty_version(self, caplog):
        drc = _make_drc_result(kicad_version="")
        analyzer = IntelligentDrcAnalyzer()
        with caplog.at_level(logging.WARNING, logger="kicad_agent.validation.drc_intel"):
            analyzer.analyze(drc)
        assert any("no kicad_version" in r.message.lower() or "missing" in r.message.lower() for r in caplog.records)

    def test_logs_warning_on_old_version(self, caplog):
        drc = _make_drc_result(kicad_version="8.0.0")
        analyzer = IntelligentDrcAnalyzer()
        with caplog.at_level(logging.WARNING, logger="kicad_agent.validation.drc_intel"):
            analyzer.analyze(drc)
        assert any("8" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Additional: Empty DRC result (no violations, no error)
# ---------------------------------------------------------------------------

class TestEmptyDrcResult:
    def test_zero_violations(self):
        drc = _make_drc_result()
        analyzer = IntelligentDrcAnalyzer()
        report = analyzer.analyze(drc)
        assert report.total == 0
        assert report.enriched_violations == ()
