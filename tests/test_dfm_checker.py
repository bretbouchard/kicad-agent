"""Tests for DFM checker, profiles, and built-in checks.

Covers:
- ManufacturerProfile (loading, validation, built-in profiles)
- DfmReport (score computation, summary)
- DfmChecker (orchestration, error handling, disabled checks)
- Built-in checks (annular ring, solder mask, thermal relief, min trace, min drill)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Task 1 imports — will fail until implementation exists (TDD RED)
# ---------------------------------------------------------------------------
from kicad_agent.dfm.checker import (
    DfmCheck,
    DfmChecker,
    DfmFinding,
    DfmReport,
    DfmSeverity,
)
from kicad_agent.dfm.profiles import (
    ManufacturerProfile,
    get_builtin_profiles,
    load_profile,
)


# ===========================================================================
# Helpers — lightweight mocks for spatial model / primitives
# ===========================================================================


class _MockSpatialModel:
    """Minimal spatial model mock for DFM check tests."""

    def __init__(self, primitives=None):
        self._primitives = primitives or []

    @property
    def all_primitives(self):
        return list(self._primitives)

    def layer_primitives(self, layer_name: str):
        return [p for p in self._primitives if getattr(p, "layer", "") == layer_name]

    def copper_layer_primitives(self):
        return {"F.Cu": self.layer_primitives("F.Cu"), "B.Cu": self.layer_primitives("B.Cu")}


# ===========================================================================
# TestManufacturerProfile
# ===========================================================================


class TestManufacturerProfile:
    """ManufacturerProfile loading, validation, and built-in profiles."""

    def test_builtin_profiles_exist(self):
        profiles = get_builtin_profiles()
        assert set(profiles.keys()) == {"jlcpcb", "pcbway", "osh_park", "generic"}
        assert len(profiles) == 4

    def test_jlcpcb_values(self):
        p = get_builtin_profiles()["jlcpcb"]
        assert p.name == "JLCPCB Standard 2-Layer"
        assert p.min_trace_width_mm == pytest.approx(0.127)
        assert p.min_drill_mm == pytest.approx(0.2)
        assert p.min_annular_ring_mm == pytest.approx(0.1)
        assert p.min_solder_mask_sliver_mm == pytest.approx(0.1)
        assert p.supports_castellated is True
        assert p.supports_blind_vias is False

    def test_pcbway_values(self):
        p = get_builtin_profiles()["pcbway"]
        assert p.name == "PCBWay Standard 2-Layer"
        assert p.min_trace_width_mm == pytest.approx(0.1)
        assert p.min_drill_mm == pytest.approx(0.2)
        assert p.supports_blind_vias is True
        assert p.supports_castellated is True

    def test_osh_park_values(self):
        p = get_builtin_profiles()["osh_park"]
        assert p.name == "OSH Park 2-Layer"
        assert p.min_drill_mm == pytest.approx(0.3556)
        assert p.min_annular_ring_mm == pytest.approx(0.1524)
        assert p.supports_blind_vias is False
        assert p.supports_castellated is False

    def test_generic_values(self):
        p = get_builtin_profiles()["generic"]
        assert p.name == "Generic Conservative 2-Layer"
        assert p.min_trace_width_mm == pytest.approx(0.2)
        assert p.min_drill_mm == pytest.approx(0.4)
        assert p.min_annular_ring_mm == pytest.approx(0.15)
        assert p.min_solder_mask_sliver_mm == pytest.approx(0.15)

    def test_from_yaml_string(self):
        yaml_str = yaml.dump({
            "name": "TestFab",
            "min_trace_width_mm": 0.15,
            "min_drill_mm": 0.3,
            "min_annular_ring_mm": 0.1,
            "min_solder_mask_sliver_mm": 0.1,
            "min_clearance_mm": 0.15,
            "min_via_diameter_mm": 0.5,
        })
        profile = ManufacturerProfile.from_yaml(yaml_str)
        assert profile.name == "TestFab"
        assert profile.min_trace_width_mm == pytest.approx(0.15)

    def test_from_json_string(self):
        json_str = json.dumps({
            "name": "TestFabJSON",
            "min_trace_width_mm": 0.18,
            "min_drill_mm": 0.35,
            "min_annular_ring_mm": 0.12,
            "min_solder_mask_sliver_mm": 0.08,
            "min_clearance_mm": 0.18,
            "min_via_diameter_mm": 0.55,
        })
        profile = ManufacturerProfile.from_json(json_str)
        assert profile.name == "TestFabJSON"
        assert profile.min_trace_width_mm == pytest.approx(0.18)

    def test_load_profile_by_name(self):
        profile = load_profile("jlcpcb")
        assert profile.name == "JLCPCB Standard 2-Layer"

    def test_load_profile_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            load_profile("unknown_fab")

    def test_validation_rejects_zero_trace_width(self):
        with pytest.raises(ValidationError):
            ManufacturerProfile(
                name="Bad",
                min_trace_width_mm=0,
                min_drill_mm=0.2,
                min_via_diameter_mm=0.4,
            )

    def test_validation_rejects_negative_drill(self):
        with pytest.raises(ValidationError):
            ManufacturerProfile(
                name="Bad",
                min_trace_width_mm=0.1,
                min_drill_mm=-0.1,
                min_via_diameter_mm=0.4,
            )


# ===========================================================================
# TestDfmReport
# ===========================================================================


class TestDfmReport:
    """DfmReport score computation and summary counts."""

    def _make_finding(self, severity: DfmSeverity, check_id: str = "TEST_01") -> DfmFinding:
        return DfmFinding(
            check_id=check_id,
            description=f"Test finding {severity.value}",
            severity=severity,
            location="U1.1",
            suggestion="Fix it",
            affected_entities=("U1",),
        )

    def test_empty_report_score_is_1(self):
        report = DfmReport(
            findings=(),
            board_path="test.kicad_pcb",
            profile_name="generic",
            checks_run=0,
            checks_passed=0,
            checks_failed=0,
            elapsed_ms=1.0,
        )
        assert report.manufacturability_score == pytest.approx(1.0)
        assert report.summary == {"PASS": 0, "INFO": 0, "WARNING": 0, "CRITICAL": 0}

    def test_critical_findings_reduce_score(self):
        findings = tuple(self._make_finding(DfmSeverity.CRITICAL) for _ in range(5))
        report = DfmReport(
            findings=findings,
            board_path="test.kicad_pcb",
            profile_name="generic",
            checks_run=1,
            checks_passed=0,
            checks_failed=1,
            elapsed_ms=1.0,
        )
        assert report.manufacturability_score <= 0.5
        assert report.summary["CRITICAL"] == 5

    def test_warning_findings_reduce_score_slightly(self):
        findings = tuple(self._make_finding(DfmSeverity.WARNING) for _ in range(10))
        report = DfmReport(
            findings=findings,
            board_path="test.kicad_pcb",
            profile_name="generic",
            checks_run=1,
            checks_passed=0,
            checks_failed=1,
            elapsed_ms=1.0,
        )
        # 10 warnings * 0.02 = 0.2 penalty, score = 0.8
        assert report.manufacturability_score > 0.5
        assert report.manufacturability_score == pytest.approx(0.8)

    def test_score_clamped_to_zero(self):
        findings = tuple(self._make_finding(DfmSeverity.CRITICAL) for _ in range(20))
        report = DfmReport(
            findings=findings,
            board_path="test.kicad_pcb",
            profile_name="generic",
            checks_run=1,
            checks_passed=0,
            checks_failed=1,
            elapsed_ms=1.0,
        )
        assert report.manufacturability_score == pytest.approx(0.0)

    def test_summary_counts(self):
        findings = (
            self._make_finding(DfmSeverity.CRITICAL),
            self._make_finding(DfmSeverity.CRITICAL),
            self._make_finding(DfmSeverity.WARNING),
            self._make_finding(DfmSeverity.INFO),
        )
        report = DfmReport(
            findings=findings,
            board_path="test.kicad_pcb",
            profile_name="generic",
            checks_run=1,
            checks_passed=0,
            checks_failed=1,
            elapsed_ms=1.0,
        )
        assert report.summary == {"PASS": 0, "INFO": 1, "WARNING": 1, "CRITICAL": 2}


# ===========================================================================
# TestDfmChecker
# ===========================================================================


class TestDfmChecker:
    """DfmChecker orchestration: run, disable, error handling."""

    def _mock_check(self, name: str, findings=None, raise_error=False):
        """Create a mock DfmCheck subclass."""
        check = MagicMock(spec=DfmCheck)
        check.name = name
        check.description = f"Mock {name}"
        if raise_error:
            check.check.side_effect = RuntimeError("boom")
        else:
            check.check.return_value = findings or []
        return check

    def test_no_checks_returns_perfect_score(self):
        checker = DfmChecker(checks=[])
        model = _MockSpatialModel()
        profile = get_builtin_profiles()["generic"]
        report = checker.run(model, profile)
        assert report.manufacturability_score == pytest.approx(1.0)
        assert report.checks_run == 0
        assert len(report.findings) == 0

    def test_runs_check_and_collects_findings(self):
        findings = [
            DfmFinding(
                check_id="TEST_01",
                description="issue A",
                severity=DfmSeverity.WARNING,
                location="U1",
                suggestion="Fix A",
                affected_entities=("U1",),
            ),
            DfmFinding(
                check_id="TEST_02",
                description="issue B",
                severity=DfmSeverity.CRITICAL,
                location="U2",
                suggestion="Fix B",
                affected_entities=("U2",),
            ),
        ]
        check = self._mock_check("MOCK_CHECK", findings=findings)
        checker = DfmChecker(checks=[check])
        model = _MockSpatialModel()
        profile = get_builtin_profiles()["generic"]
        report = checker.run(model, profile)
        assert len(report.findings) == 2
        assert report.checks_run == 1
        assert report.checks_failed == 1

    def test_disabled_check_is_skipped(self):
        check = self._mock_check("SKIP_ME", findings=[])
        checker = DfmChecker(checks=[check], disabled_checks={"SKIP_ME"})
        model = _MockSpatialModel()
        profile = get_builtin_profiles()["generic"]
        report = checker.run(model, profile)
        assert report.checks_run == 0
        check.check.assert_not_called()

    def test_exception_in_check_creates_meta_finding(self):
        check = self._mock_check("CRASH_CHECK", raise_error=True)
        checker = DfmChecker(checks=[check])
        model = _MockSpatialModel()
        profile = get_builtin_profiles()["generic"]
        report = checker.run(model, profile)
        assert len(report.findings) == 1
        assert report.findings[0].severity == DfmSeverity.WARNING
        assert "CRASH_CHECK" in report.findings[0].description
        assert report.checks_failed == 1

    def test_check_names_property(self):
        c1 = self._mock_check("CHECK_A")
        c2 = self._mock_check("CHECK_B")
        checker = DfmChecker(checks=[c1, c2])
        assert checker.check_names == ["CHECK_A", "CHECK_B"]

    def test_add_check(self):
        checker = DfmChecker(checks=[])
        new_check = self._mock_check("ADDED_CHECK", findings=[])
        checker.add_check(new_check)
        assert "ADDED_CHECK" in checker.check_names
        model = _MockSpatialModel()
        profile = get_builtin_profiles()["generic"]
        report = checker.run(model, profile)
        assert report.checks_run == 1


# ===========================================================================
# TestBuiltinDfmChecks — Task 2 tests (will be added to this file)
# ===========================================================================


class TestBuiltinDfmChecks:
    """Tests for 5 built-in DFM checks using mock spatial model."""

    # -- Helper to create mock primitives -----------------------------------

    @staticmethod
    def _make_box(
        x1=0, y1=0, x2=1, y2=1,
        entity_type="pad", entity_id="p1",
        layer="F.Cu", reference="U1",
    ):
        box = MagicMock()
        box.x1 = x1
        box.y1 = y1
        box.x2 = x2
        box.y2 = y2
        box.entity_type = entity_type
        box.entity_id = entity_id
        box.layer = layer
        box.reference = reference
        box.net = ""
        from shapely.geometry import box as shapely_box
        box.to_shapely.return_value = shapely_box(x1, y1, x2, y2)
        return box

    @staticmethod
    def _make_point(
        x=0, y=0,
        entity_type="via_drill", entity_id="v1",
        layer="", net="",
    ):
        pt = MagicMock()
        pt.x = x
        pt.y = y
        pt.entity_type = entity_type
        pt.entity_id = entity_id
        pt.layer = layer
        pt.net = net
        from shapely.geometry import Point
        pt.to_shapely.return_value = Point(x, y)
        return pt

    @staticmethod
    def _make_path(
        points=((0, 0), (10, 0)),
        entity_type="trace", entity_id="t1",
        layer="F.Cu", net="", width=0.2,
    ):
        path = MagicMock()
        path.points = points
        path.entity_type = entity_type
        path.entity_id = entity_id
        path.layer = layer
        path.net = net
        path.width = width
        from shapely.geometry import LineString
        path.to_shapely.return_value = LineString(points)
        return path

    @staticmethod
    def _make_region(
        boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
        entity_type="zone", entity_id="z1",
        layer="F.Cu", net="GND", region_type="fill",
    ):
        region = MagicMock()
        region.boundary = boundary
        region.entity_type = entity_type
        region.entity_id = entity_id
        region.layer = layer
        region.net = net
        region.region_type = region_type
        from shapely.geometry import Polygon
        region.to_shapely.return_value = Polygon(boundary)
        return region

    # -- AnnularRingCheck ---------------------------------------------------

    def test_annular_ring_flags_violation(self):
        """AnnularRingCheck flags pad with annular ring below JLCPCB minimum."""
        from kicad_agent.dfm.checks import AnnularRingCheck

        # Pad with 0.5mm diameter, drill 0.4mm -> annular ring = (0.5 - 0.4) / 2 = 0.05mm
        # JLCPCB minimum is 0.1mm -> should flag
        pad = self._make_box(
            x1=-0.25, y1=-0.25, x2=0.25, y2=0.25,
            entity_type="pad", entity_id="p1", reference="U1",
        )
        drill = self._make_point(
            x=0, y=0, entity_type="drill", entity_id="p1_drill",
        )
        model = _MockSpatialModel(primitives=[pad, drill])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AnnularRingCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any(f.severity == DfmSeverity.CRITICAL for f in findings)

    def test_annular_ring_passes_adequate(self):
        """AnnularRingCheck passes pad with adequate annular ring."""
        from kicad_agent.dfm.checks import AnnularRingCheck

        # Pad with 1.0mm diameter, drill 0.4mm -> annular ring = (1.0 - 0.4) / 2 = 0.3mm
        pad = self._make_box(
            x1=-0.5, y1=-0.5, x2=0.5, y2=0.5,
            entity_type="pad", entity_id="p2", reference="R1",
        )
        drill = self._make_point(
            x=0, y=0, entity_type="drill", entity_id="p2_drill",
        )
        model = _MockSpatialModel(primitives=[pad, drill])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AnnularRingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_annular_ring_no_drill_data_skips(self):
        """AnnularRingCheck skips pad when no drill data available."""
        from kicad_agent.dfm.checks import AnnularRingCheck

        pad = self._make_box(
            x1=-0.25, y1=-0.25, x2=0.25, y2=0.25,
            entity_type="pad", entity_id="p3", reference="C1",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AnnularRingCheck()
        findings = check.check(model, profile)
        # No drill data -> no finding (skip, not flag)
        assert len(findings) == 0

    # -- SolderMaskCheck ----------------------------------------------------

    def test_solder_mask_flags_close_pads(self):
        """SolderMaskCheck flags two pads closer than min solder mask sliver."""
        from kicad_agent.dfm.checks import SolderMaskCheck

        # Two pads very close together on F.Mask layer
        pad1 = self._make_box(
            x1=0, y1=0, x2=0.5, y2=0.5,
            entity_type="pad", entity_id="sm1", layer="F.Mask", reference="U1",
        )
        pad2 = self._make_box(
            x1=0.55, y1=0, x2=1.05, y2=0.5,
            entity_type="pad", entity_id="sm2", layer="F.Mask", reference="U1",
        )
        # Distance between boxes: 0.55 - 0.5 = 0.05mm < 0.1mm JLCPCB minimum
        model = _MockSpatialModel(primitives=[pad1, pad2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderMaskCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any(f.severity == DfmSeverity.WARNING for f in findings)

    def test_solder_mask_passes_adequate_spacing(self):
        """SolderMaskCheck passes pads with adequate solder mask bridge."""
        from kicad_agent.dfm.checks import SolderMaskCheck

        # Two pads far apart on F.Mask layer
        pad1 = self._make_box(
            x1=0, y1=0, x2=0.5, y2=0.5,
            entity_type="pad", entity_id="sm3", layer="F.Mask", reference="U2",
        )
        pad2 = self._make_box(
            x1=2.0, y1=0, x2=2.5, y2=0.5,
            entity_type="pad", entity_id="sm4", layer="F.Mask", reference="U2",
        )
        # Distance: 2.0 - 0.5 = 1.5mm >> 0.1mm
        model = _MockSpatialModel(primitives=[pad1, pad2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderMaskCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    # -- ThermalReliefCheck -------------------------------------------------

    def test_thermal_relief_flags_no_spokes(self):
        """ThermalReliefCheck flags pad on copper zone without thermal spokes."""
        from kicad_agent.dfm.checks import ThermalReliefCheck

        # Pad inside a zone with same net, no traces connecting them
        pad = self._make_box(
            x1=4, y1=4, x2=6, y2=6,
            entity_type="pad", entity_id="tp1", layer="F.Cu",
            reference="U3",
        )
        pad.net = "GND"
        zone = self._make_region(
            boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        model = _MockSpatialModel(primitives=[pad, zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ThermalReliefCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any(f.severity == DfmSeverity.WARNING for f in findings)

    def test_thermal_relief_passes_with_spokes(self):
        """ThermalReliefCheck passes pad with thermal relief traces."""
        from kicad_agent.dfm.checks import ThermalReliefCheck

        # Pad inside a zone with same net, traces connecting them (thermal spokes)
        pad = self._make_box(
            x1=4, y1=4, x2=6, y2=6,
            entity_type="pad", entity_id="tp2", layer="F.Cu",
            reference="U4",
        )
        pad.net = "GND"
        zone = self._make_region(
            boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
            entity_type="zone", entity_id="z2", layer="F.Cu",
            net="GND",
        )
        # Add a trace connecting pad to zone (thermal spoke)
        spoke = self._make_path(
            points=((4.5, 4.5), (2, 2)),
            entity_type="trace", entity_id="spoke1", layer="F.Cu",
            net="GND", width=0.3,
        )
        model = _MockSpatialModel(primitives=[pad, zone, spoke])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ThermalReliefCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    # -- MinTraceWidthCheck -------------------------------------------------

    def test_min_trace_flags_thin_trace(self):
        """MinTraceWidthCheck flags trace with width below profile minimum."""
        from kicad_agent.dfm.checks import MinTraceWidthCheck

        thin_trace = self._make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.08,  # Below JLCPCB 0.127mm minimum
        )
        model = _MockSpatialModel(primitives=[thin_trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinTraceWidthCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any(f.severity == DfmSeverity.CRITICAL for f in findings)

    def test_min_trace_passes_adequate_width(self):
        """MinTraceWidthCheck passes trace with adequate width."""
        from kicad_agent.dfm.checks import MinTraceWidthCheck

        wide_trace = self._make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG", width=0.25,  # Well above JLCPCB 0.127mm
        )
        model = _MockSpatialModel(primitives=[wide_trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinTraceWidthCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_min_trace_skips_zero_width(self):
        """MinTraceWidthCheck skips traces with width=0 (unextracted)."""
        from kicad_agent.dfm.checks import MinTraceWidthCheck

        zero_trace = self._make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t3", layer="F.Cu",
            net="SIG", width=0.0,
        )
        model = _MockSpatialModel(primitives=[zero_trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinTraceWidthCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    # -- MinDrillCheck ------------------------------------------------------

    def test_min_drill_flags_small_via(self):
        """MinDrillCheck flags via with drill below profile minimum."""
        from kicad_agent.dfm.checks import MinDrillCheck

        via_drill = self._make_point(
            x=5, y=5, entity_type="via_drill", entity_id="v1",
            layer="", net="",
        )
        # Attach drill_diameter attribute for the check to read
        via_drill.drill_diameter = 0.15  # Below JLCPCB 0.2mm
        model = _MockSpatialModel(primitives=[via_drill])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinDrillCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any(f.severity == DfmSeverity.CRITICAL for f in findings)

    def test_min_drill_passes_adequate(self):
        """MinDrillCheck passes via with adequate drill size."""
        from kicad_agent.dfm.checks import MinDrillCheck

        via_drill = self._make_point(
            x=5, y=5, entity_type="via_drill", entity_id="v2",
            layer="", net="",
        )
        via_drill.drill_diameter = 0.3  # Above JLCPCB 0.2mm
        model = _MockSpatialModel(primitives=[via_drill])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinDrillCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    # -- All checks work with different profiles ----------------------------

    def test_annular_ring_generic_vs_jlcpcb(self):
        """Check that different profiles produce different results."""
        from kicad_agent.dfm.checks import AnnularRingCheck

        # Pad with annular ring of 0.12mm: passes JLCPCB (0.1mm) but might differ with generic (0.15mm)
        pad = self._make_box(
            x1=-0.32, y1=-0.32, x2=0.32, y2=0.32,
            entity_type="pad", entity_id="p_xr", reference="X1",
        )
        drill = self._make_point(
            x=0, y=0, entity_type="drill", entity_id="p_xr_drill",
        )
        model = _MockSpatialModel(primitives=[pad, drill])

        check = AnnularRingCheck()

        # JLCPCB (0.1mm min) -> 0.12mm passes
        jlcpcb = get_builtin_profiles()["jlcpcb"]
        findings_jlcpcb = check.check(model, jlcpcb)
        assert len(findings_jlcpcb) == 0

        # Generic (0.15mm min) -> 0.12mm fails
        generic = get_builtin_profiles()["generic"]
        findings_generic = check.check(model, generic)
        assert len(findings_generic) >= 1

    # -- get_builtin_dfm_checks ---------------------------------------------

    def test_get_builtin_dfm_checks_returns_five(self):
        """get_builtin_dfm_checks returns list of 5 checks."""
        from kicad_agent.dfm.checks import get_builtin_dfm_checks

        checks = get_builtin_dfm_checks()
        assert len(checks) == 5
        names = [c.name for c in checks]
        assert "ANNULAR_RING_01" in names
        assert "SOLDER_MASK_01" in names
        assert "THERMAL_RELIEF_01" in names
        assert "MIN_TRACE_01" in names
        assert "MIN_DRILL_01" in names


# ===========================================================================
# TestBuiltinDfmChecksIntegration
# ===========================================================================


class TestBuiltinDfmChecksIntegration:
    """End-to-end integration: all 5 checks through DfmChecker."""

    def test_full_check_with_jlcpcb(self):
        """Run all 5 checks through DfmChecker with JLCPCB profile."""
        from kicad_agent.dfm.checks import get_builtin_dfm_checks

        checker = DfmChecker(checks=get_builtin_dfm_checks())
        profile = get_builtin_profiles()["jlcpcb"]

        # Create a mix of passing and failing primitives
        thin_trace = TestBuiltinDfmChecks._make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t_thin", layer="F.Cu",
            net="SIG", width=0.08,  # Below JLCPCB 0.127mm
        )
        small_drill = TestBuiltinDfmChecks._make_point(
            x=5, y=5, entity_type="via_drill", entity_id="v_small",
        )
        small_drill.drill_diameter = 0.15  # Below JLCPCB 0.2mm

        wide_trace = TestBuiltinDfmChecks._make_path(
            points=((0, 5), (10, 5)),
            entity_type="trace", entity_id="t_wide", layer="F.Cu",
            net="PWR", width=0.5,  # Above JLCPCB
        )

        model = _MockSpatialModel(primitives=[thin_trace, small_drill, wide_trace])
        report = checker.run(model, profile)

        assert report.checks_run == 5
        assert report.checks_failed >= 2  # At least trace + drill failures
        assert len(report.findings) >= 2
        assert report.manufacturability_score < 1.0

    def test_full_check_clean_board(self):
        """Run all 5 checks on a clean board (no violations)."""
        from kicad_agent.dfm.checks import get_builtin_dfm_checks

        checker = DfmChecker(checks=get_builtin_dfm_checks())
        profile = get_builtin_profiles()["generic"]

        # Generous dimensions with generic conservative profile
        wide_trace = TestBuiltinDfmChecks._make_path(
            points=((0, 0), (20, 0)),
            entity_type="trace", entity_id="t_ok", layer="F.Cu",
            net="SIG", width=0.5,
        )
        large_pad = TestBuiltinDfmChecks._make_box(
            x1=-1, y1=-1, x2=1, y2=1,
            entity_type="pad", entity_id="p_ok", reference="U10",
        )
        drill = TestBuiltinDfmChecks._make_point(
            x=0, y=0, entity_type="drill", entity_id="p_ok_drill",
        )
        large_via = TestBuiltinDfmChecks._make_point(
            x=10, y=10, entity_type="via_drill", entity_id="v_ok",
        )
        large_via.drill_diameter = 0.8  # Well above generic 0.4mm

        model = _MockSpatialModel(primitives=[wide_trace, large_pad, drill, large_via])
        report = checker.run(model, profile)
        assert report.checks_run == 5
        assert report.manufacturability_score == pytest.approx(1.0)
