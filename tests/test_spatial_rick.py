"""Tests for Rick agent integration module (VP-08).

11 tests covering RickDomain enum, RickFinding and SpatialRickReport
dataclasses, generate_spatial_report(), generate_all_reports(), and
helper functions. All pure unit tests with no external dependencies.
"""

from __future__ import annotations

import pytest

from kicad_agent.spatial.primitives import SpatialBox, SpatialPath, SpatialPoint
from kicad_agent.spatial.rick_integration import (
    RickDomain,
    RickFinding,
    SpatialRickReport,
    _calculate_path_length,
    _classify_net_type,
    generate_all_reports,
    generate_spatial_report,
)
from kicad_agent.validation.spatial_drc import SpatialViolation


@pytest.fixture
def test_board_primitives():
    """A known set of spatial primitives matching a small test board."""
    return [
        # Two parallel traces (crosstalk candidate)
        SpatialPath(((0, 10), (30, 10)), "segment", "t1", "F.Cu", "SDA", 0.2),
        SpatialPath(((0, 11), (30, 11)), "segment", "t2", "F.Cu", "SCL", 0.2),
        # A long trace (EMC antenna candidate)
        SpatialPath(((0, 0), (60, 0)), "segment", "t3", "F.Cu", "CLK", 0.15),
        # Footprints
        SpatialBox(10, 20, 15, 25, "footprint", "U1", "F.Cu", "U1"),
        SpatialBox(30, 20, 35, 25, "footprint", "C1", "F.Cu", "C1"),  # decoupling cap
        # Vias
        SpatialPoint(10, 10, "via", "v1", "F.Cu", "SDA"),
        SpatialPoint(60, 0, "via", "v2", "F.Cu", "CLK"),
        # Power net trace (wide -> SI impedance flag)
        SpatialPath(((0, 30), (40, 30)), "segment", "t4", "F.Cu", "VCC", 0.5),
        # Narrow trace (DFM concern)
        SpatialPath(((0, 40), (20, 40)), "segment", "t5", "F.Cu", "SIG", 0.1),
    ]


# ---------------------------------------------------------------------------
# SI Rick tests
# ---------------------------------------------------------------------------


class TestSIReport:
    def test_si_report_detects_crosstalk(self, test_board_primitives):
        """SI report flags parallel traces (t1 and t2) as crosstalk."""
        report = generate_spatial_report(RickDomain.SI, test_board_primitives)
        crosstalk = [f for f in report.findings if f.category == "crosstalk"]
        assert len(crosstalk) > 0
        # Crosstalk findings should have coordinates of both parallel traces
        for finding in crosstalk:
            assert len(finding.coordinates) == 2
            assert all(isinstance(c, tuple) and len(c) == 2 for c in finding.coordinates)

    def test_si_report_domain_is_si(self, test_board_primitives):
        """SI report has domain='si'."""
        report = generate_spatial_report(RickDomain.SI, test_board_primitives)
        assert report.domain == "si"


# ---------------------------------------------------------------------------
# PI Rick tests
# ---------------------------------------------------------------------------


class TestPIReport:
    def test_pi_report_checks_power_nets(self, test_board_primitives):
        """PI report finds power net primitives (VCC net)."""
        report = generate_spatial_report(RickDomain.PI, test_board_primitives)
        power_findings = [f for f in report.findings if f.category == "power_net"]
        assert len(power_findings) > 0
        # At least one finding should reference VCC
        vcc_findings = [f for f in power_findings if "VCC" in f.description]
        assert len(vcc_findings) > 0


# ---------------------------------------------------------------------------
# EMC Rick tests
# ---------------------------------------------------------------------------


class TestEMCReport:
    def test_emc_report_flags_long_traces(self, test_board_primitives):
        """EMC report flags trace > 50mm (CLK trace t3 at 60mm)."""
        report = generate_spatial_report(RickDomain.EMC, test_board_primitives)
        length_findings = [f for f in report.findings if f.category == "trace_length"]
        assert len(length_findings) > 0
        # The CLK trace (t3) is 60mm, which should be flagged as warning
        clk_findings = [f for f in length_findings if "t3" in f.description]
        assert len(clk_findings) > 0
        assert clk_findings[0].severity == "warning"  # 60mm is >50 but <=100

    def test_emc_report_flags_narrow_clearance(self, test_board_primitives):
        """EMC report includes clearance findings from spatial violations."""
        violations = [
            SpatialViolation(
                description="Clearance violation between traces",
                severity="error",
                violation_type="clearance",
                items=(
                    SpatialPoint(25.0, 10.5, "drc_item", "drc_0"),
                    SpatialPoint(25.0, 11.5, "drc_item", "drc_1"),
                ),
                spatial_context="Clearance issue at <point> [25.0000, 10.5000]",
            )
        ]
        report = generate_spatial_report(
            RickDomain.EMC, test_board_primitives, spatial_violations=violations
        )
        clearance_findings = [
            f for f in report.findings if f.category == "clearance"
        ]
        assert len(clearance_findings) > 0
        assert clearance_findings[0].domain == "emc"


# ---------------------------------------------------------------------------
# DFM Rick tests
# ---------------------------------------------------------------------------


class TestDFMReport:
    def test_dfm_report_checks_trace_width(self, test_board_primitives):
        """DFM report flags trace width < 0.15mm (SIG trace t5 at 0.1mm)."""
        report = generate_spatial_report(RickDomain.DFM, test_board_primitives)
        feature_findings = [
            f for f in report.findings if f.category == "minimum_feature_size"
        ]
        assert len(feature_findings) > 0
        # The SIG trace (t5) has width 0.1mm which is < 0.15mm DFM minimum
        sig_findings = [f for f in feature_findings if "t5" in f.description]
        assert len(sig_findings) > 0


# ---------------------------------------------------------------------------
# Multi-domain and all-reports tests
# ---------------------------------------------------------------------------


class TestAllReports:
    def test_generate_all_reports_returns_four_domains(self, test_board_primitives):
        """generate_all_reports returns dict with si, pi, emc, dfm keys."""
        reports = generate_all_reports(test_board_primitives)
        assert set(reports.keys()) == {"si", "pi", "emc", "dfm"}
        for key, report in reports.items():
            assert isinstance(report, SpatialRickReport)
            assert report.domain == key


# ---------------------------------------------------------------------------
# Dataclass formatting tests
# ---------------------------------------------------------------------------


class TestRickFindingFormat:
    def test_rick_finding_format_output(self):
        """format_finding() produces expected output format."""
        finding = RickFinding(
            domain="si",
            category="crosstalk",
            severity="warning",
            description="Parallel traces detected",
            coordinates=((10.0, 20.0), (10.0, 21.0)),
            affected_entities=({"type": "point", "x": 10.0, "y": 20.5},),
            spatial_context="Traces at <point> [10.0000, 20.0000]; <point> [10.0000, 21.0000]",
            recommendation="Increase spacing to >2mm",
        )
        output = finding.format_finding()
        assert "[SI]" in output
        assert "[WARNING]" in output
        assert "<point>" in output
        assert "10.0000" in output
        assert "20.0000" in output
        assert "1 primitives nearby" in output
        assert "Recommendation:" in output

    def test_spatial_rick_report_format_report(self):
        """format_report() contains domain header, findings, and summary."""
        findings = (
            RickFinding(
                domain="emc",
                category="trace_length",
                severity="warning",
                description="Long trace",
                coordinates=((0.0, 0.0),),
                affected_entities=(),
                spatial_context="At <point> [0.0000, 0.0000]",
                recommendation="Shorten trace",
            ),
            RickFinding(
                domain="emc",
                category="ground_plane_coverage",
                severity="info",
                description="No ground plane",
                coordinates=((0.0, 0.0),),
                affected_entities=(),
                spatial_context="No ground primitives",
                recommendation="Add ground plane",
            ),
        )
        report = SpatialRickReport(
            domain="emc",
            board_path="test.kicad_pcb",
            findings=findings,
            summary="2 findings: 0 critical, 1 warning, 1 info",
        )
        output = report.format_report()
        assert "=== EMC Rick Report ===" in output
        assert "2 findings" in output
        assert "Long trace" in output
        assert "No ground plane" in output


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


class TestRickFindingJson:
    def test_rick_finding_to_json(self):
        """to_json() produces expected keys and values."""
        finding = RickFinding(
            domain="dfm",
            category="minimum_feature_size",
            severity="warning",
            description="Trace too narrow",
            coordinates=((5.0, 10.0),),
            affected_entities=(),
            spatial_context="Narrow trace at <point> [5.0000, 10.0000]",
            recommendation="Increase width",
        )
        data = finding.to_json()
        assert data["domain"] == "dfm"
        assert data["category"] == "minimum_feature_size"
        assert data["severity"] == "warning"
        assert data["description"] == "Trace too narrow"
        assert data["coordinates"] == [(5.0, 10.0)]
        assert data["affected_entities"] == []
        assert data["spatial_context"] == "Narrow trace at <point> [5.0000, 10.0000]"
        assert data["recommendation"] == "Increase width"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_calculate_path_length(self):
        """3-4-5 triangle: distance from (0,0) to (3,4) is 5.0."""
        result = _calculate_path_length(((0, 0), (3, 4)))
        assert result == 5.0

    def test_classify_net_type(self):
        """Net classification: VCC -> power, SDA -> signal, '' -> unknown."""
        assert _classify_net_type("VCC") == "power"
        assert _classify_net_type("SDA") == "signal"
        assert _classify_net_type("") == "unknown"
        assert _classify_net_type("+5V") == "power"
        assert _classify_net_type("GND") == "power"
        assert _classify_net_type("VDD") == "power"
        assert _classify_net_type("VIN") == "power"
        assert _classify_net_type("+3V3") == "power"
