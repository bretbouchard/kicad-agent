"""Tests for ManufacturingReadinessGate and ManufacturingManifest (Phase 91)."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from volta.dfm.checker import DfmFinding, DfmReport, DfmSeverity
from volta.validation.erc_drc import DrcResult
from volta.validation.gate_types import GateResult
from volta.validation.gates.manufacturing_gate import (
    ManufacturingReadinessGate,
    _2LAYER_LAYERS,
    _4LAYER_LAYERS,
)
from volta.validation.gates.manufacturing_manifest import (
    ManufacturingArtifact,
    ManufacturingManifest,
    generate_manifest,
    validate_manifest,
)


@pytest.fixture
def gate() -> ManufacturingReadinessGate:
    return ManufacturingReadinessGate()


# ---------------------------------------------------------------------------
# ManufacturingManifest tests
# ---------------------------------------------------------------------------


class TestManufacturingManifest:
    def test_generate_manifest(self) -> None:
        """generate_manifest creates a manifest with correct fields."""
        artifacts = [
            ManufacturingArtifact(
                name="gerbers", path="/tmp/gerbers", sha256="abc123",
                size_bytes=1024, generated_by="kicad-cli pcb export gerbers",
                timestamp="2024-01-01T00:00:00Z",
            ),
        ]
        m = generate_manifest("proj", "board", "2-layer", artifacts, bom_rows=5, total_components=10)
        assert m.project_name == "proj"
        assert m.board_name == "board"
        assert m.fab_profile == "2-layer"
        assert len(m.artifacts) == 1
        assert m.bom_rows == 5
        assert m.total_components == 10

    def test_validate_manifest_complete(self) -> None:
        """validate_manifest returns empty blockers for complete manifest."""
        artifacts = [
            ManufacturingArtifact(
                name=n, path=f"/tmp/{n}", sha256="hash", size_bytes=100,
                generated_by="cmd", timestamp="2024-01-01T00:00:00Z",
            )
            for n in ("gerbers", "drill", "bom", "cpl")
        ]
        m = generate_manifest("proj", "board", "2-layer", artifacts)
        blockers = validate_manifest(m, "2-layer")
        assert blockers == []

    def test_validate_manifest_missing(self) -> None:
        """validate_manifest returns blockers for missing artifacts."""
        m = generate_manifest("proj", "board", "2-layer", [])
        blockers = validate_manifest(m, "2-layer")
        assert any("gerbers" in b for b in blockers)
        assert any("drill" in b for b in blockers)

    def test_artifact_sha256_hash(self, tmp_path: Path) -> None:
        """ManufacturingArtifact.from_file computes correct SHA256."""
        test_file = tmp_path / "test_gerber.gbr"
        content = b"GERBER DATA HERE"
        test_file.write_bytes(content)
        expected_hash = hashlib.sha256(content).hexdigest()

        artifact = ManufacturingArtifact.from_file(
            "gerbers", str(test_file), "kicad-cli pcb export gerbers test.kicad_pcb -o dir"
        )
        assert artifact.sha256 == expected_hash
        assert artifact.size_bytes == len(content)
        assert artifact.generated_by == "kicad-cli pcb export gerbers test.kicad_pcb -o dir"

    def test_artifact_frozen(self) -> None:
        """ManufacturingArtifact is immutable."""
        a = ManufacturingArtifact(
            name="gerbers", path="/tmp/gerbers", sha256="abc",
            size_bytes=100, generated_by="cmd", timestamp="2024-01-01T00:00:00Z",
        )
        with pytest.raises(Exception):
            a.sha256 = "different"


# ---------------------------------------------------------------------------
# DRC checks
# ---------------------------------------------------------------------------


class TestDrcChecks:
    def test_clean_drc_passes(self, gate: ManufacturingReadinessGate) -> None:
        """Clean DRC result passes the check."""
        drc = DrcResult(passed=True, file_path=Path("/tmp/test.kicad_pcb"))
        ctx = {"drc_result": drc}
        assert gate._check_drc_clean(ctx) == []

    def test_drc_failure_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """Failed DRC blocks the gate."""
        drc = DrcResult(
            passed=False,
            file_path=Path("/tmp/test.kicad_pcb"),
            error_message="2 violations found",
        )
        ctx = {"drc_result": drc}
        blockers = gate._check_drc_clean(ctx)
        assert any("failed" in b for b in blockers)

    def test_no_drc_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """Missing DRC result blocks the gate."""
        assert any("No DRC" in b for b in gate._check_drc_clean({}))

    def test_error_violations_block(self, gate: ManufacturingReadinessGate) -> None:
        """Error-severity DRC violations block the gate."""
        # Create a mock violation with error severity
        sev = MagicMock()
        sev.value = "error"
        viol = MagicMock()
        viol.severity = sev

        drc = DrcResult(
            passed=True,
            file_path=Path("/tmp/test.kicad_pcb"),
            violations=(viol, viol),
        )
        blockers = gate._check_drc_clean({"drc_result": drc})
        assert any("error-severity" in b for b in blockers)


# ---------------------------------------------------------------------------
# DFM checks
# ---------------------------------------------------------------------------


class TestDfmChecks:
    def test_dfm_pass_no_critical(self, gate: ManufacturingReadinessGate) -> None:
        """DFM with no CRITICAL findings passes."""
        report = DfmReport(
            findings=(
                DfmFinding(check_id="DFM01", description="Minor issue", severity=DfmSeverity.WARNING),
                DfmFinding(check_id="DFM02", description="Info note", severity=DfmSeverity.INFO),
            ),
        )
        blockers, warnings = gate._check_dfm_pass({"dfm_report": report})
        assert blockers == []
        assert len(warnings) == 2

    def test_dfm_critical_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """DFM with CRITICAL finding blocks the gate."""
        report = DfmReport(
            findings=(
                DfmFinding(check_id="DFM01", description="Critical issue", severity=DfmSeverity.CRITICAL),
            ),
        )
        blockers, warnings = gate._check_dfm_pass({"dfm_report": report})
        assert any("CRITICAL" in b for b in blockers)

    def test_no_dfm_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """Missing DFM report blocks the gate."""
        blockers, _ = gate._check_dfm_pass({})
        assert any("No DFM" in b for b in blockers)


# ---------------------------------------------------------------------------
# Required exports
# ---------------------------------------------------------------------------


class TestRequiredExports:
    def _make_artifact(self, name: str) -> ManufacturingArtifact:
        return ManufacturingArtifact(
            name=name, path=f"/tmp/{name}", sha256="hash", size_bytes=100,
            generated_by="cmd", timestamp="2024-01-01T00:00:00Z",
        )

    def test_all_exports_pass(self, gate: ManufacturingReadinessGate) -> None:
        """All required exports present passes the check."""
        artifacts = [self._make_artifact(n) for n in ("gerbers", "drill", "bom", "cpl")]
        ctx = {"export_artifacts": artifacts}
        assert gate._check_required_exports(ctx) == []

    def test_missing_gerbers_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """Missing gerbers blocks the gate."""
        artifacts = [self._make_artifact(n) for n in ("drill", "bom", "cpl")]
        ctx = {"export_artifacts": artifacts}
        blockers = gate._check_required_exports(ctx)
        assert any("gerbers" in b for b in blockers)

    def test_missing_drill_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """Missing drill blocks the gate."""
        artifacts = [self._make_artifact(n) for n in ("gerbers", "bom", "cpl")]
        ctx = {"export_artifacts": artifacts}
        blockers = gate._check_required_exports(ctx)
        assert any("drill" in b for b in blockers)

    def test_step_not_required_no_mech(self, gate: ManufacturingReadinessGate) -> None:
        """STEP not required when no mechanical constraints."""
        artifacts = [self._make_artifact(n) for n in ("gerbers", "drill", "bom", "cpl")]
        ctx = {"export_artifacts": artifacts, "has_mechanical_constraints": False}
        blockers = gate._check_required_exports(ctx)
        assert not any("STEP" in b for b in blockers)

    def test_step_required_with_mech(self, gate: ManufacturingReadinessGate) -> None:
        """STEP required when mechanical constraints exist."""
        artifacts = [self._make_artifact(n) for n in ("gerbers", "drill", "bom", "cpl")]
        ctx = {"export_artifacts": artifacts, "has_mechanical_constraints": True}
        blockers = gate._check_required_exports(ctx)
        assert any("STEP" in b for b in blockers)


# ---------------------------------------------------------------------------
# Layer completeness
# ---------------------------------------------------------------------------


class TestLayerCompleteness:
    def test_2layer_complete(self, gate: ManufacturingReadinessGate) -> None:
        """All 2-layer required layers present."""
        ctx = {"export_layers": list(_2LAYER_LAYERS), "fab_profile": "2-layer"}
        assert gate._check_layer_completeness(ctx) == []

    def test_2layer_missing(self, gate: ManufacturingReadinessGate) -> None:
        """Missing 2-layer layers produces blocker."""
        ctx = {"export_layers": ["F.Cu", "B.Cu"], "fab_profile": "2-layer"}
        blockers = gate._check_layer_completeness(ctx)
        assert len(blockers) == 1
        assert "2-layer" in blockers[0]

    def test_4layer_complete(self, gate: ManufacturingReadinessGate) -> None:
        """All 4-layer required layers present."""
        ctx = {"export_layers": list(_4LAYER_LAYERS), "fab_profile": "4-layer"}
        assert gate._check_layer_completeness(ctx) == []

    def test_4layer_missing_inner(self, gate: ManufacturingReadinessGate) -> None:
        """4-layer profile missing inner layers produces blocker."""
        ctx = {"export_layers": list(_2LAYER_LAYERS), "fab_profile": "4-layer"}
        blockers = gate._check_layer_completeness(ctx)
        assert any("In1.Cu" in b for b in blockers)
        assert any("In2.Cu" in b for b in blockers)


# ---------------------------------------------------------------------------
# BOM completeness
# ---------------------------------------------------------------------------


class TestBomCompleteness:
    def test_complete_bom_passes(self, gate: ManufacturingReadinessGate) -> None:
        """BOM with MPN on all rows passes."""
        bom = [
            {"Reference": "R1", "Value": "1k", "MPN": "RC0402FR-071KL", "Vendor": "DigiKey"},
            {"Reference": "C1", "Value": "100nF", "MPN": "GRM155R71C104KA88D", "Vendor": "Mouser"},
        ]
        ctx = {"bom_data": bom}
        blockers, _ = gate._check_bom_completeness(ctx)
        assert blockers == []

    def test_missing_mpn_blocks(self, gate: ManufacturingReadinessGate) -> None:
        """BOM row missing MPN and vendor blocks."""
        bom = [
            {"Reference": "R1", "Value": "1k"},
        ]
        ctx = {"bom_data": bom}
        blockers, _ = gate._check_bom_completeness(ctx)
        assert any("R1" in b for b in blockers)
        assert any("MPN" in b for b in blockers)

    def test_dnp_excluded_from_check(self, gate: ManufacturingReadinessGate) -> None:
        """DNP components excluded from BOM check."""
        bom = [
            {"Reference": "R1", "Value": "1k", "DNP": "yes"},
            {"Reference": "C1", "Value": "100nF", "Excluded": "true"},
        ]
        ctx = {"bom_data": bom}
        blockers, _ = gate._check_bom_completeness(ctx)
        assert blockers == []

    def test_empty_bom_no_blockers(self, gate: ManufacturingReadinessGate) -> None:
        """Empty BOM produces no blockers."""
        blockers, _ = gate._check_bom_completeness({"bom_data": []})
        assert blockers == []


# ---------------------------------------------------------------------------
# Cleanup on failure
# ---------------------------------------------------------------------------


class TestCleanupOnFailure:
    def test_cleanup_deletes_directory(self, gate: ManufacturingReadinessGate, tmp_path: Path) -> None:
        """Partial export directory is deleted when gate fails."""
        export_dir = tmp_path / "partial_exports"
        export_dir.mkdir()
        (export_dir / "gerbers").write_text("data")

        gate._cleanup_partial_exports(str(export_dir))
        assert not export_dir.exists()

    def test_cleanup_nonexistent_ok(self, gate: ManufacturingReadinessGate) -> None:
        """Cleanup on nonexistent directory does not raise."""
        gate._cleanup_partial_exports("/tmp/nonexistent_dir_12345")


# ---------------------------------------------------------------------------
# Integration: Full gate
# ---------------------------------------------------------------------------


class TestGateIntegration:
    def _make_passing_context(self) -> dict:
        """Create a context that passes all checks."""
        drc = DrcResult(passed=True, file_path=Path("/tmp/test.kicad_pcb"))
        dfm = DfmReport(findings=())

        artifacts = [
            ManufacturingArtifact(
                name=n, path=f"/tmp/{n}", sha256="hash", size_bytes=100,
                generated_by="cmd", timestamp="2024-01-01T00:00:00Z",
            )
            for n in ("gerbers", "drill", "bom", "cpl")
        ]

        bom = [
            {"Reference": "R1", "Value": "1k", "MPN": "RC0402FR-071KL", "Vendor": "DigiKey"},
        ]

        return {
            "pcb_ir": MagicMock(),
            "drc_result": drc,
            "dfm_report": dfm,
            "export_artifacts": artifacts,
            "export_layers": list(_2LAYER_LAYERS),
            "fab_profile": "2-layer",
            "bom_data": bom,
            "has_mechanical_constraints": False,
            "board_name": "test_board",
            "project_name": "test_proj",
        }

    def test_all_passes(self, gate: ManufacturingReadinessGate) -> None:
        """Fully valid context passes the gate."""
        ctx = self._make_passing_context()
        result = gate.run(ctx)
        assert result.pass_ is True
        assert any("artifact" in a.lower() for a in result.artifacts)

    def test_drc_failure_fails(self, gate: ManufacturingReadinessGate) -> None:
        """DRC failure fails the gate."""
        ctx = self._make_passing_context()
        ctx["drc_result"] = DrcResult(
            passed=False,
            file_path=Path("/tmp/test.kicad_pcb"),
            error_message="violation",
        )
        result = gate.run(ctx)
        assert result.pass_ is False
        assert any("DRC" in b for b in result.blockers)

    def test_dfm_critical_fails(self, gate: ManufacturingReadinessGate) -> None:
        """DFM CRITICAL finding fails the gate."""
        ctx = self._make_passing_context()
        ctx["dfm_report"] = DfmReport(
            findings=(DfmFinding(check_id="DFM01", description="Bad", severity=DfmSeverity.CRITICAL),)
        )
        result = gate.run(ctx)
        assert result.pass_ is False
        assert any("CRITICAL" in b for b in result.blockers)

    def test_dfm_warning_passes(self, gate: ManufacturingReadinessGate) -> None:
        """DFM WARNING finding does not block, produces warning."""
        ctx = self._make_passing_context()
        ctx["dfm_report"] = DfmReport(
            findings=(DfmFinding(check_id="DFM01", description="Meh", severity=DfmSeverity.WARNING),)
        )
        result = gate.run(ctx)
        assert result.pass_ is True
        assert any("DFM" in w for w in result.warnings)

    def test_missing_bom_fails(self, gate: ManufacturingReadinessGate) -> None:
        """Missing BOM export fails the gate."""
        ctx = self._make_passing_context()
        ctx["export_artifacts"] = [
            a for a in ctx["export_artifacts"] if a.name != "bom"
        ]
        result = gate.run(ctx)
        assert result.pass_ is False
        assert any("bom" in b for b in result.blockers)

    def test_incomplete_bom_fails(self, gate: ManufacturingReadinessGate) -> None:
        """BOM row missing MPN fails the gate."""
        ctx = self._make_passing_context()
        ctx["bom_data"] = [{"Reference": "R1", "Value": "1k"}]
        result = gate.run(ctx)
        assert result.pass_ is False
        assert any("MPN" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# Gate registration
# ---------------------------------------------------------------------------


class TestGateRegistration:
    def test_manufacturing_readiness_registered(self) -> None:
        import volta.validation  # noqa: ensure gates registered
        from volta.validation.gate_runner import get_gate_runner

        runner = get_gate_runner()
        assert runner.get_gate("manufacturing_readiness") is not None
