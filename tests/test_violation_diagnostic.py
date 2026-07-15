"""Tests for ERC violation diagnosis (Phase 40, Plan 02).

Covers:
- DiagnoseViolationsOp schema validation
- diagnose_violations diagnosis logic (fix options, root cause analysis)
- FixOption structure validation
- Executor registration
- Operation union wiring
"""

import pytest
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import MagicMock
from typing import Any

from volta.ops.erc_parser import ErcViolation


# ---------------------------------------------------------------------------
# Fixtures -- build ErcViolation instances directly (no kicad-cli dependency)
# ---------------------------------------------------------------------------

def _v(
    vtype: str,
    description: str = "",
    sheet: str = "/",
    severity: str = "error",
    positions: list[tuple[float, float]] | None = None,
) -> ErcViolation:
    """Helper to build an ErcViolation for testing."""
    return ErcViolation(
        sheet=sheet,
        type=vtype,
        severity=severity,
        description=description,
        positions=positions or [],
    )


# Mock IR that supports the methods diagnose_violations uses
def _mock_ir(
    pin_positions: list[dict[str, Any]] | None = None,
    wire_endpoints: list[dict[str, Any]] | None = None,
    label_positions: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Create a mock SchematicIR with the methods the diagnostic module needs."""
    ir = MagicMock()
    ir.get_pin_positions.return_value = pin_positions or []
    ir.get_wire_endpoints.return_value = wire_endpoints or []
    ir.get_label_positions.return_value = label_positions or []
    return ir


def _classified_fixable(
    vtype: str,
    description: str = "",
    root_cause: str = "test_root_cause",
    positions: list[tuple[float, float]] | None = None,
    confidence: str = "high",
) -> dict[str, Any]:
    """Build a classified violation dict as if from classify_violations['fixable']."""
    return {
        "category": "FIXABLE",
        "confidence": confidence,
        "root_cause": root_cause,
        "details": description,
        "violation": {
            "sheet": "/",
            "type": vtype,
            "severity": "error",
            "description": description,
            "positions": positions or [],
        },
    }


# ===========================================================================
# Task 1 Tests: Schema + Diagnosis Logic
# ===========================================================================


class TestDiagnoseViolationsSchema:
    """DiagnoseViolationsOp Pydantic schema validation."""

    def test_schema_with_target_file_only(self):
        """Schema validates with target_file, violation_types defaults to None."""
        from volta.ops._schema_erc_smart import DiagnoseViolationsOp
        op = DiagnoseViolationsOp(target_file="test.kicad_sch")
        assert op.op_type == "diagnose_violations"
        assert op.target_file == "test.kicad_sch"
        assert op.violation_types is None

    def test_schema_with_specific_violation_types(self):
        """Schema validates when violation_types list is provided."""
        from volta.ops._schema_erc_smart import DiagnoseViolationsOp
        op = DiagnoseViolationsOp(
            target_file="test.kicad_sch",
            violation_types=["pin_not_connected", "multiple_net_names"],
        )
        assert op.violation_types == ["pin_not_connected", "multiple_net_names"]

    def test_schema_target_file_validation(self):
        """Invalid target_file is rejected by TargetFile type."""
        from volta.ops._schema_erc_smart import DiagnoseViolationsOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DiagnoseViolationsOp(target_file="../etc/passwd")


class TestDiagnoseViolations:
    """Diagnosis logic tests using classified violation fixtures."""

    def test_empty_fixable_returns_empty_diagnoses(self):
        """Empty fixable violation list produces empty diagnoses."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        result = diagnose_violations([], ir, Path("test.kicad_sch"))
        assert result["diagnoses"] == []
        assert result["total_fixable"] == 0
        assert result["total_diagnosed"] == 0

    def test_pin_not_connected_produces_place_no_connect_fix(self):
        """Diagnosing pin_not_connected (non-power) includes 'place_no_connect' fix option."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "pin_not_connected",
                description="Pin not connected (pin R1.1)",
                root_cause="unconnected_pin",
                positions=[(120.0, 80.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        assert len(result["diagnoses"]) == 1
        diag = result["diagnoses"][0]
        actions = [fo["action"] for fo in diag["fix_options"]]
        assert "place_no_connect" in actions

    def test_multiple_net_names_produces_break_and_fix_options(self):
        """Diagnosing multiple_net_names produces 'break_wire_shorts' and 'fix_shorted_nets' fix options."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "multiple_net_names",
                description="Multiple net names at position",
                root_cause="net_name_conflict",
                positions=[(100.0, 50.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        assert len(result["diagnoses"]) == 1
        diag = result["diagnoses"][0]
        actions = [fo["action"] for fo in diag["fix_options"]]
        assert "break_wire_shorts" in actions
        assert "fix_shorted_nets" in actions

    def test_power_pin_not_driven_produces_add_power_flag(self):
        """power_pin_not_driven (non-power-global) produces 'add_power_flag' fix option."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "power_pin_not_driven",
                description="Power pin not driven",
                root_cause="missing_power_symbol",
                positions=[(50.0, 30.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        assert len(result["diagnoses"]) == 1
        diag = result["diagnoses"][0]
        actions = [fo["action"] for fo in diag["fix_options"]]
        assert "add_power_flag" in actions

    def test_unknown_violation_type_returns_low_confidence(self):
        """Unknown violation type returns a diagnosis with 'low' confidence."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "some_unknown_type",
                description="Something weird",
                root_cause="unknown",
                positions=[(10.0, 20.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        assert len(result["diagnoses"]) == 1
        diag = result["diagnoses"][0]
        # The generic fix option should have low confidence
        assert any(
            fo["confidence"] == "low" for fo in diag["fix_options"]
        )

    def test_diagnosis_result_has_required_fields(self):
        """Each diagnosis result has violation_type, position, root_cause, details, fix_options, recommended_fix_index."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "pin_not_connected",
                description="Pin not connected",
                root_cause="unconnected_pin",
                positions=[(120.0, 80.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        diag = result["diagnoses"][0]
        assert "violation_type" in diag
        assert "position" in diag
        assert "root_cause" in diag
        assert "details" in diag
        assert "fix_options" in diag
        assert "recommended_fix_index" in diag


class TestFixOptions:
    """Verify fix option structure and constraints."""

    def test_each_fix_option_has_required_fields(self):
        """Each fix option has action, params, description, side_effects, confidence."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "pin_not_connected",
                description="Pin not connected",
                root_cause="unconnected_pin",
                positions=[(120.0, 80.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        for fo in result["diagnoses"][0]["fix_options"]:
            assert "action" in fo
            assert "params" in fo
            assert "description" in fo
            assert "side_effects" in fo
            assert "confidence" in fo
            assert fo["confidence"] in ("high", "medium", "low")
            assert isinstance(fo["params"], dict)
            assert isinstance(fo["side_effects"], list)

    def test_recommended_fix_index_is_valid(self):
        """recommended_fix_index points to a valid index in fix_options."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "pin_not_connected",
                description="Pin not connected",
                root_cause="unconnected_pin",
                positions=[(120.0, 80.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        diag = result["diagnoses"][0]
        idx = diag["recommended_fix_index"]
        assert 0 <= idx < len(diag["fix_options"])

    def test_multiple_violations_each_get_diagnosed(self):
        """Multiple fixable violations each get their own diagnosis."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "pin_not_connected",
                description="Pin not connected R1",
                root_cause="unconnected_pin",
                positions=[(120.0, 80.0)],
            ),
            _classified_fixable(
                "multiple_net_names",
                description="Net name conflict",
                root_cause="net_name_conflict",
                positions=[(100.0, 50.0)],
            ),
            _classified_fixable(
                "power_pin_not_driven",
                description="Power pin not driven",
                root_cause="missing_power_symbol",
                positions=[(50.0, 30.0)],
            ),
        ]
        result = diagnose_violations(classified, ir, Path("test.kicad_sch"))
        assert result["total_fixable"] == 3
        assert result["total_diagnosed"] == 3
        assert len(result["diagnoses"]) == 3
        # Each diagnosis has the correct violation type
        types = [d["violation_type"] for d in result["diagnoses"]]
        assert "pin_not_connected" in types
        assert "multiple_net_names" in types
        assert "power_pin_not_driven" in types

    def test_violation_types_filter(self):
        """When violation_types is provided, only those types are diagnosed."""
        from volta.ops.violation_diagnostic import diagnose_violations
        ir = _mock_ir()
        classified = [
            _classified_fixable(
                "pin_not_connected",
                description="Pin not connected",
                root_cause="unconnected_pin",
                positions=[(120.0, 80.0)],
            ),
            _classified_fixable(
                "multiple_net_names",
                description="Net name conflict",
                root_cause="net_name_conflict",
                positions=[(100.0, 50.0)],
            ),
        ]
        result = diagnose_violations(
            classified, ir, Path("test.kicad_sch"),
            violation_types=["pin_not_connected"],
        )
        assert len(result["diagnoses"]) == 1
        assert result["diagnoses"][0]["violation_type"] == "pin_not_connected"


# ===========================================================================
# Task 2 Tests: Executor Registration + Operation Union
# ===========================================================================


class TestExecutorRegistration:
    """Verify diagnose_violations handler is registered in executor."""

    def test_diagnose_violations_in_schematic_handlers(self):
        """'diagnose_violations' key exists in _SCHEMATIC_QUERY_HANDLERS."""
        from volta.ops.executor import _SCHEMATIC_QUERY_HANDLERS
        assert "diagnose_violations" in _SCHEMATIC_QUERY_HANDLERS

    def test_operation_union_validates_diagnose_violations(self):
        """DiagnoseViolationsOp validates through Operation discriminated union."""
        from volta.ops.schema import Operation
        op = Operation.model_validate({
            "root": {
                "op_type": "diagnose_violations",
                "target_file": "test.kicad_sch",
            }
        })
        assert op.root.op_type == "diagnose_violations"

    def test_operation_union_validates_with_violation_types(self):
        """DiagnoseViolationsOp with violation_types validates through Operation union."""
        from volta.ops.schema import Operation
        op = Operation.model_validate({
            "root": {
                "op_type": "diagnose_violations",
                "target_file": "test.kicad_sch",
                "violation_types": ["pin_not_connected"],
            }
        })
        assert op.root.violation_types == ["pin_not_connected"]
