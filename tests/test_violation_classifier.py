"""Tests for ERC violation classification (Phase 40, Plan 01).

Covers:
- ClassifyViolationsOp schema validation
- classify_violations classification logic (rule-based)
- Summary count consistency
- Executor registration
- Operation union wiring
"""

import pytest
from pathlib import Path
from dataclasses import dataclass
from unittest.mock import MagicMock
from typing import Any

from kicad_agent.ops.erc_parser import ErcViolation


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


# Mock IR that supports the methods classify_violations uses
def _mock_ir(
    pin_positions: list[dict[str, Any]] | None = None,
    wire_endpoints: list[dict[str, Any]] | None = None,
    label_positions: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Create a mock SchematicIR with the methods the classifier needs."""
    ir = MagicMock()
    ir.get_pin_positions.return_value = pin_positions or []
    ir.get_wire_endpoints.return_value = wire_endpoints or []
    ir.get_label_positions.return_value = label_positions or []
    return ir


# ===========================================================================
# Task 1 Tests: Schema + Classification Logic
# ===========================================================================


class TestClassifyViolationsSchema:
    """ClassifyViolationsOp Pydantic schema validation."""

    def test_schema_with_target_file_only(self):
        """Schema validates with target_file, erc_report_path defaults to None."""
        from kicad_agent.ops._schema_erc_smart import ClassifyViolationsOp
        op = ClassifyViolationsOp(target_file="test.kicad_sch")
        assert op.op_type == "classify_violations"
        assert op.target_file == "test.kicad_sch"
        assert op.erc_report_path is None

    def test_schema_with_erc_report_path(self):
        """Schema validates when erc_report_path is provided."""
        from kicad_agent.ops._schema_erc_smart import ClassifyViolationsOp
        op = ClassifyViolationsOp(
            target_file="test.kicad_sch",
            erc_report_path="/tmp/erc_report.rpt",
        )
        assert op.erc_report_path == "/tmp/erc_report.rpt"

    def test_schema_target_file_validation(self):
        """Invalid target_file is rejected by TargetFile type."""
        from kicad_agent.ops._schema_erc_smart import ClassifyViolationsOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ClassifyViolationsOp(target_file="../etc/passwd")


class TestClassifyViolations:
    """Classification logic tests using mock ErcViolation lists."""

    def test_empty_violations_returns_empty_categories(self):
        """Empty violation list produces empty categories and zero summary."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        result = classify_violations([], ir, Path("test.kicad_sch"))
        assert result["fixable"] == []
        assert result["pre_existing"] == []
        assert result["benign"] == []
        assert result["config_issues"] == []
        assert result["summary"]["total"] == 0
        assert result["summary"]["fixable"] == 0
        assert result["summary"]["pre_existing"] == 0
        assert result["summary"]["benign"] == 0
        assert result["summary"]["config"] == 0

    def test_power_pin_not_driven_power_global_is_pre_existing(self):
        """power_pin_not_driven with '(power global)' -> pre_existing, high confidence."""
        from kicad_agent.ops.violation_classifier import classify_violations, ViolationCategory
        ir = _mock_ir()
        violations = [
            _v(
                "power_pin_not_driven",
                description="Power pin not driven (power global)",
                positions=[(85.09, 62.23)],
            ),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["pre_existing"]) == 1
        cv = result["pre_existing"][0]
        assert cv["category"] == "PRE_EXISTING"
        assert cv["confidence"] == "high"
        assert cv["root_cause"] == "library_pin_type_mismatch"

    def test_pin_not_connected_pwr_symbol_is_pre_existing(self):
        """pin_not_connected on a #PWR symbol with no wire/label -> pre_existing."""
        from kicad_agent.ops.violation_classifier import classify_violations
        # Pin at position (85.09, 62.23) with a #PWR symbol at that location
        # but no wire or label connecting to it
        ir = _mock_ir(
            pin_positions=[{
                "ref": "#PWR0101",
                "pin_name": "VCC",
                "position": (85.09, 62.23),
            }],
        )
        violations = [
            _v(
                "pin_not_connected",
                description="Pin not connected (pin #PWR0101 VCC)",
                positions=[(85.09, 62.23)],
            ),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["pre_existing"]) == 1
        cv = result["pre_existing"][0]
        assert cv["category"] == "PRE_EXISTING"
        assert cv["confidence"] == "high"
        assert cv["root_cause"] == "orphaned_power_symbol"

    def test_same_local_global_label_is_benign(self):
        """same_local_global_label -> benign, cosmetic duplicate."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v("same_local_global_label", description="Same local and global label GND"),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["benign"]) == 1
        cv = result["benign"][0]
        assert cv["category"] == "BENIGN"
        assert cv["root_cause"] == "cosmetic_duplicate"

    def test_missing_unit_is_benign(self):
        """missing_unit -> benign, unused unit by design."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v("missing_unit", description="Missing unit U? unit 3"),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["benign"]) == 1
        cv = result["benign"][0]
        assert cv["category"] == "BENIGN"
        assert cv["root_cause"] == "unused_unit_by_design"

    def test_lib_symbol_issues_is_config_issue(self):
        """lib_symbol_issues -> config_issue, missing library."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v("lib_symbol_issues", description="Library symbol issues in U1"),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["config_issues"]) == 1
        cv = result["config_issues"][0]
        assert cv["category"] == "CONFIG_ISSUE"
        assert cv["root_cause"] == "missing_library"

    def test_multiple_net_names_is_fixable(self):
        """multiple_net_names at known overlap position -> fixable, high confidence."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v(
                "multiple_net_names",
                description="Multiple net names at same position",
                positions=[(100.0, 50.0)],
            ),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["fixable"]) == 1
        cv = result["fixable"][0]
        assert cv["category"] == "FIXABLE"
        assert cv["confidence"] == "high"
        assert cv["root_cause"] == "net_name_conflict"

    def test_pin_to_pin_unspecified_is_pre_existing(self):
        """pin_to_pin (Unspecified vs Power input) -> pre_existing."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v(
                "pin_to_pin",
                description="Pin to pin conflict (Unspecified vs Power input)",
            ),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["pre_existing"]) == 1
        cv = result["pre_existing"][0]
        assert cv["category"] == "PRE_EXISTING"
        assert cv["confidence"] == "high"
        assert cv["root_cause"] == "pin_type_in_library"

    def test_pin_not_connected_non_power_is_fixable(self):
        """pin_not_connected (non-power pin, no wire) -> fixable, high confidence."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir(
            pin_positions=[{
                "ref": "R1",
                "pin_name": "1",
                "position": (120.0, 80.0),
            }],
        )
        violations = [
            _v(
                "pin_not_connected",
                description="Pin not connected (pin R1.1)",
                positions=[(120.0, 80.0)],
            ),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["fixable"]) == 1
        cv = result["fixable"][0]
        assert cv["category"] == "FIXABLE"
        assert cv["confidence"] == "high"
        assert cv["root_cause"] == "unconnected_pin"

    def test_power_pin_not_driven_default_is_fixable(self):
        """power_pin_not_driven without '(power global)' -> fixable, missing power symbol."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v(
                "power_pin_not_driven",
                description="Power pin not driven",
                positions=[(50.0, 30.0)],
            ),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["fixable"]) == 1
        cv = result["fixable"][0]
        assert cv["category"] == "FIXABLE"
        assert cv["root_cause"] == "missing_power_symbol"

    def test_unknown_violation_type_is_fixable_low_confidence(self):
        """Any unmatched violation type -> fixable, low confidence, 'unknown' root cause."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v("some_unknown_type", description="Something weird happened"),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        assert len(result["fixable"]) == 1
        cv = result["fixable"][0]
        assert cv["category"] == "FIXABLE"
        assert cv["confidence"] == "low"
        assert cv["root_cause"] == "unknown"


class TestCategoryCounts:
    """Summary totals match sum of category counts."""

    def test_summary_totals_match(self):
        """Summary total = fixable + pre_existing + benign + config."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v("same_local_global_label", description="GND label dup"),
            _v("same_local_global_label", description="VCC label dup"),
            _v("missing_unit", description="Missing unit 3"),
            _v("lib_symbol_issues", description="Library issue"),
            _v(
                "power_pin_not_driven",
                description="Power pin not driven (power global)",
            ),
            _v("multiple_net_names", description="Net conflict"),
            _v("some_weird_type", description="Unknown violation"),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        summary = result["summary"]
        actual_total = (
            summary["fixable"]
            + summary["pre_existing"]
            + summary["benign"]
            + summary["config"]
        )
        assert summary["total"] == len(violations)
        assert summary["total"] == actual_total

    def test_each_classified_violation_has_required_fields(self):
        """Each classified violation dict has category, confidence, root_cause, details."""
        from kicad_agent.ops.violation_classifier import classify_violations
        ir = _mock_ir()
        violations = [
            _v("same_local_global_label", description="GND label dup"),
            _v(
                "power_pin_not_driven",
                description="Power pin not driven (power global)",
            ),
            _v("multiple_net_names", description="Net conflict"),
        ]
        result = classify_violations(violations, ir, Path("test.kicad_sch"))
        all_classified = (
            result["fixable"]
            + result["pre_existing"]
            + result["benign"]
            + result["config_issues"]
        )
        assert len(all_classified) == 3
        for cv in all_classified:
            assert "category" in cv
            assert "confidence" in cv
            assert "root_cause" in cv
            assert "details" in cv
            assert cv["confidence"] in ("high", "medium", "low")
            assert cv["category"] in (
                "FIXABLE",
                "PRE_EXISTING",
                "BENIGN",
                "CONFIG_ISSUE",
            )


# ===========================================================================
# Task 2 Tests: Executor Registration + Operation Union
# ===========================================================================


class TestExecutorRegistration:
    """Verify classify_violations handler is registered in executor."""

    def test_classify_violations_in_schematic_handlers(self):
        """'classify_violations' key exists in _SCHEMATIC_HANDLERS."""
        from kicad_agent.ops.executor import _SCHEMATIC_HANDLERS
        assert "classify_violations" in _SCHEMATIC_HANDLERS

    def test_operation_union_validates_classify_violations(self):
        """ClassifyViolationsOp validates through Operation discriminated union."""
        from kicad_agent.ops.schema import Operation
        op = Operation.model_validate({
            "root": {
                "op_type": "classify_violations",
                "target_file": "test.kicad_sch",
            }
        })
        assert op.root.op_type == "classify_violations"

    def test_existing_erc_auto_fix_tests_still_pass(self):
        """Verify no regression -- import and validate ErcAutoFixOp."""
        from kicad_agent.ops._schema_repair import ErcAutoFixOp
        op = ErcAutoFixOp(target_file="test.kicad_sch")
        assert op.op_type == "erc_auto_fix"
        assert op.max_iterations == 3
