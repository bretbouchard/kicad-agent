"""Tests for constraint operation handlers (88-02).

SetConstraintsOp propagates to .kicad_dru and sidecar file.
GetConstraintsOp reads from sidecar file.
Gate blocks placement when critical nets lack constraints.
Path validation rejects unsafe values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kicad_agent.ops.handlers.constraint_handlers import (
    GetConstraintsOp,
    SetConstraintsOp,
    handle_get_constraints,
    handle_set_constraints,
)
from kicad_agent.validation.gates.constraint_schema import (
    DesignConstraints,
    ElectricalConstraints,
)
from kicad_agent.analysis.types import NetClassification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_constraints() -> DesignConstraints:
    """Create sample DesignConstraints for testing."""
    return DesignConstraints(
        electrical=[
            ElectricalConstraints(
                net_name="VCC3V3",
                current_ma=500,
                voltage_v=3.3,
                impedance_ohm=50.0,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Test: SetConstraintsOp propagates to .kicad_dru
# ---------------------------------------------------------------------------


class TestSetConstraintsPropagation:
    """SetConstraintsOp writes .kicad_dru via ConstraintPropagator."""

    def test_propagates_to_dru(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Constraint propagation creates .kicad_dru with net classes."""
        monkeypatch.chdir(tmp_path)
        op = SetConstraintsOp(constraints=_sample_constraints())
        result = handle_set_constraints(op)

        dru_path = tmp_path / "board.kicad_dru"
        assert dru_path.exists(), "Expected .kicad_dru to be created"
        dru_content = dru_path.read_text()
        assert "VCC3V3" in dru_content, "Expected net class in .kicad_dru"
        assert result["status"] == "written"
        assert result["electrical_count"] == 1
        assert str(dru_path) in result["written_paths"]

    def test_propagates_multiple_electrical_constraints(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Multiple electrical constraints all get propagated."""
        monkeypatch.chdir(tmp_path)
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="VCC5V", current_ma=1000),
                ElectricalConstraints(net_name="VCC3V3", impedance_ohm=50.0),
                ElectricalConstraints(
                    net_name="USB_DP",
                    diff_pair={"pair_name": "USB", "gap_mm": 0.15},
                ),
            ],
        )
        op = SetConstraintsOp(constraints=constraints)
        result = handle_set_constraints(op)

        dru_path = tmp_path / "board.kicad_dru"
        dru_content = dru_path.read_text()
        for net in ["VCC5V", "VCC3V3", "USB_DP"]:
            assert net in dru_content, f"Expected net class '{net}' in .kicad_dru"
        assert result["electrical_count"] == 3


# ---------------------------------------------------------------------------
# Test: SetConstraintsOp writes sidecar file
# ---------------------------------------------------------------------------


class TestSetConstraintsSidecar:
    """SetConstraintsOp writes canonical JSON to .kicad_agent/constraints.json."""

    def test_writes_sidecar_file(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Sidecar file is created with DesignConstraints JSON."""
        monkeypatch.chdir(tmp_path)
        op = SetConstraintsOp(constraints=_sample_constraints())
        result = handle_set_constraints(op)

        sidecar_path = tmp_path / ".kicad_agent" / "constraints.json"
        assert sidecar_path.exists(), "Expected sidecar file to be created"
        assert str(sidecar_path) in result["written_paths"]

        data = json.loads(sidecar_path.read_text())
        assert "electrical" in data
        assert len(data["electrical"]) == 1
        assert data["electrical"][0]["net_name"] == "VCC3V3"

    def test_sidecar_is_round_trip_valid(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Sidecar JSON can be deserialized back to DesignConstraints."""
        monkeypatch.chdir(tmp_path)
        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(
                    net_name="GND",
                    current_ma=2000,
                    voltage_v=0.1,
                ),
            ],
        )
        op = SetConstraintsOp(constraints=constraints)
        handle_set_constraints(op)

        sidecar_path = tmp_path / ".kicad_agent" / "constraints.json"
        raw = sidecar_path.read_text()
        data = json.loads(raw)
        restored = DesignConstraints.model_validate(data)
        assert restored.electrical[0].net_name == "GND"
        assert restored.electrical[0].current_ma == 2000


# ---------------------------------------------------------------------------
# Test: GetConstraintsOp reads from sidecar
# ---------------------------------------------------------------------------


class TestGetConstraintsSidecar:
    """GetConstraintsOp reads from .kicad_agent/constraints.json."""

    def test_reads_sidecar_file(self, tmp_path: Path, monkeypatch: Any) -> None:
        """GetConstraintsOp returns constraints written by SetConstraintsOp."""
        monkeypatch.chdir(tmp_path)
        # First set constraints
        set_op = SetConstraintsOp(constraints=_sample_constraints())
        handle_set_constraints(set_op)

        # Then get them back
        get_op = GetConstraintsOp()
        result = handle_get_constraints(get_op)

        assert result["status"] == "loaded"
        assert result["constraints"]["electrical"][0]["net_name"] == "VCC3V3"

    def test_raises_when_no_sidecar(self, tmp_path: Path, monkeypatch: Any) -> None:
        """GetConstraintsOp raises FileNotFoundError when sidecar missing."""
        monkeypatch.chdir(tmp_path)
        get_op = GetConstraintsOp()
        with pytest.raises(FileNotFoundError, match="Constraints sidecar file not found"):
            handle_get_constraints(get_op)


# ---------------------------------------------------------------------------
# Test: dry_run validates without writing
# ---------------------------------------------------------------------------


class TestDryRun:
    """dry_run mode validates constraints without writing any files."""

    def test_dry_run_no_files_written(self, tmp_path: Path, monkeypatch: Any) -> None:
        """No .kicad_dru or sidecar file created in dry_run mode."""
        monkeypatch.chdir(tmp_path)
        op = SetConstraintsOp(
            constraints=_sample_constraints(),
            dry_run=True,
        )
        result = handle_set_constraints(op)

        assert result["status"] == "validated"
        assert result["dry_run"] is True
        assert result["written_paths"] == []
        assert not (tmp_path / "board.kicad_dru").exists()
        assert not (tmp_path / ".kicad_agent" / "constraints.json").exists()


# ---------------------------------------------------------------------------
# Test: gate blocks placement when critical nets lack constraints
# ---------------------------------------------------------------------------


class TestConstraintCompletenessGate:
    """ConstraintCompletenessGate blocks PCB_SETUP -> PLACEMENT."""

    def test_gate_passes_when_all_nontrivial_constrained(self) -> None:
        """Gate passes when all nontrivial nets have constraints."""
        import kicad_agent.validation  # noqa: ensure gates registered
        from kicad_agent.validation.gate_runner import get_gate_runner

        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="VCC3V3", current_ma=500),
                ElectricalConstraints(net_name="USB_DP", diff_pair={"pair_name": "USB", "gap_mm": 0.15}),
            ],
        )

        runner = get_gate_runner()
        context = {
            "design_constraints": constraints,
            "net_intent": {
                "VCC3V3": NetClassification.POWER,
                "USB_DP": NetClassification.DIFFERENTIAL_PAIR,
                "Signal": NetClassification.SIGNAL,
            },
        }

        result = runner.run_gate("constraint_completeness", context)
        assert result.pass_bool is True

    def test_gate_blocks_missing_power_constraint(self) -> None:
        """Gate fails when a POWER net lacks electrical constraints."""
        import kicad_agent.validation  # noqa: ensure gates registered
        from kicad_agent.validation.gate_runner import get_gate_runner

        constraints = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="USB_DP", diff_pair={"pair_name": "USB", "gap_mm": 0.15}),
            ],
        )

        runner = get_gate_runner()
        context = {
            "design_constraints": constraints,
            "net_intent": {
                "VCC3V3": NetClassification.POWER,
                "USB_DP": NetClassification.DIFFERENTIAL_PAIR,
            },
        }

        result = runner.run_gate("constraint_completeness", context)
        assert result.pass_bool is False
        assert any("VCC3V3" in b for b in result.blockers)

    def test_gate_blocks_no_constraints_in_context(self) -> None:
        """Gate fails when no design_constraints present in context."""
        import kicad_agent.validation  # noqa: ensure gates registered
        from kicad_agent.validation.gate_runner import get_gate_runner

        runner = get_gate_runner()
        context = {"net_intent": {"VCC3V3": NetClassification.POWER}}

        result = runner.run_gate("constraint_completeness", context)
        assert result.pass_bool is False
        assert any("design_constraints" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# Test: path validation rejects unsafe values
# ---------------------------------------------------------------------------


class TestPathValidation:
    """Path validator rejects null bytes, absolute paths, and '..' traversal."""

    def test_rejects_null_bytes(self) -> None:
        with pytest.raises(ValueError, match="null bytes"):
            SetConstraintsOp(
                constraints=_sample_constraints(),
                project_dir="pro\x00ject",
            )

    def test_rejects_absolute_path(self) -> None:
        with pytest.raises(ValueError, match="relative path"):
            SetConstraintsOp(
                constraints=_sample_constraints(),
                project_dir="/absolute/path",
            )

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            SetConstraintsOp(
                constraints=_sample_constraints(),
                project_dir="safe/../../../etc",
            )

    def test_rejects_null_bytes_get(self) -> None:
        """GetConstraintsOp also rejects null bytes in project_dir."""
        with pytest.raises(ValueError, match="null bytes"):
            GetConstraintsOp(project_dir="pro\x00ject")

    def test_accepts_valid_relative_path(self) -> None:
        """Valid relative paths are accepted."""
        op = SetConstraintsOp(
            constraints=_sample_constraints(),
            project_dir="boards/my-project",
            dry_run=True,
        )
        assert op.project_dir == "boards/my-project"


# ---------------------------------------------------------------------------
# Test: invalid constraints rejected by DesignConstraints validation
# ---------------------------------------------------------------------------


class TestInvalidConstraints:
    """Invalid constraint data is rejected by Pydantic validation."""

    def test_negative_impedance_rejected(self) -> None:
        with pytest.raises(Exception):
            DesignConstraints(
                electrical=[
                    ElectricalConstraints(
                        net_name="VCC",
                        impedance_ohm=-10,
                    ),
                ],
            )

    def test_negative_voltage_rejected(self) -> None:
        with pytest.raises(Exception):
            DesignConstraints(
                electrical=[
                    ElectricalConstraints(
                        net_name="VCC",
                        voltage_v=-5,
                    ),
                ],
            )
