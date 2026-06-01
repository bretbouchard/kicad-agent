"""Tests for erc_auto_fix root cause mode (Phase 40, Plan 03).

Covers:
- ErcAutoFixOp schema with mode field (symptom/root_cause) and fix_classes
- Root cause mode: classify -> diagnose -> targeted repair pipeline
- Symptom mode: existing iteration-based repair preserved
- Mode dispatch in erc_auto_fix()
- Executor handler passes mode and fix_classes
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kicad_agent.ops._schema_erc_smart import (
    ClassifyViolationsOp,
    DiagnoseViolationsOp,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestErcAutoFixSchema:
    """Test ErcAutoFixOp schema with mode and fix_classes fields."""

    def test_default_mode_is_symptom(self):
        """ErcAutoFixOp with no mode specified defaults to 'symptom' (backward compatible)."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(target_file="test.kicad_sch")
        assert op.mode == "symptom"

    def test_root_cause_mode_validates(self):
        """ErcAutoFixOp with mode='root_cause' validates correctly."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(target_file="test.kicad_sch", mode="root_cause")
        assert op.mode == "root_cause"

    def test_symptom_mode_validates(self):
        """ErcAutoFixOp with mode='symptom' validates correctly."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(target_file="test.kicad_sch", mode="symptom")
        assert op.mode == "symptom"

    def test_fix_classes_default_none(self):
        """fix_classes defaults to None."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(target_file="test.kicad_sch")
        assert op.fix_classes is None

    def test_fix_classes_with_values(self):
        """fix_classes accepts a list of class names."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(
            target_file="test.kicad_sch",
            mode="root_cause",
            fix_classes=["fixable"],
        )
        assert op.fix_classes == ["fixable"]

    def test_max_iterations_default(self):
        """max_iterations defaults to 3."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(target_file="test.kicad_sch")
        assert op.max_iterations == 3

    def test_op_type_is_erc_auto_fix(self):
        """op_type discriminator is 'erc_auto_fix'."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp

        op = ErcAutoFixOp(target_file="test.kicad_sch")
        assert op.op_type == "erc_auto_fix"

    def test_invalid_mode_rejected(self):
        """Invalid mode value is rejected by Pydantic validation."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ErcAutoFixOp(target_file="test.kicad_sch", mode="invalid_mode")


# ---------------------------------------------------------------------------
# Root cause mode tests
# ---------------------------------------------------------------------------


class TestRootCauseMode:
    """Test erc_auto_fix_root_cause function behavior."""

    def _make_mock_ir(self):
        """Create a mock SchematicIR."""
        ir = MagicMock()
        ir.get_pin_positions.return_value = []
        ir.get_wire_endpoints.return_value = []
        ir.get_label_positions.return_value = []
        return ir

    def _mock_classify_return(self):
        """Standard mock return value for classify_violations."""
        return {
            "fixable": [
                {
                    "category": "FIXABLE",
                    "confidence": "high",
                    "root_cause": "unconnected_pin",
                    "details": "Pin not connected",
                    "violation": {
                        "sheet": "/",
                        "type": "pin_not_connected",
                        "severity": "error",
                        "description": "Pin not connected",
                        "positions": [(100.0, 50.0)],
                    },
                },
            ],
            "pre_existing": [
                {
                    "category": "PRE_EXISTING",
                    "confidence": "high",
                    "root_cause": "library_pin_type_mismatch",
                    "details": "Power pin not driven (power global)",
                    "violation": {
                        "sheet": "/",
                        "type": "power_pin_not_driven",
                        "severity": "warning",
                        "description": "Power pin not driven (power global)",
                        "positions": [(200.0, 100.0)],
                    },
                },
            ],
            "benign": [
                {
                    "category": "BENIGN",
                    "confidence": "high",
                    "root_cause": "cosmetic_duplicate",
                    "details": "Same local/global label",
                    "violation": {
                        "sheet": "/",
                        "type": "same_local_global_label",
                        "severity": "warning",
                        "description": "Same local/global label",
                        "positions": [],
                    },
                },
            ],
            "config_issues": [
                {
                    "category": "CONFIG_ISSUE",
                    "confidence": "high",
                    "root_cause": "missing_library",
                    "details": "Library not found",
                    "violation": {
                        "sheet": "/",
                        "type": "lib_symbol_issues",
                        "severity": "error",
                        "description": "Library not found",
                        "positions": [],
                    },
                },
            ],
            "summary": {
                "total": 4,
                "fixable": 1,
                "pre_existing": 1,
                "benign": 1,
                "config": 1,
            },
        }

    def _mock_diagnose_return(self):
        """Standard mock return value for diagnose_violations."""
        return {
            "diagnoses": [
                {
                    "violation_type": "pin_not_connected",
                    "position": (100.0, 50.0),
                    "root_cause": "unconnected_pin",
                    "details": "Pin not connected",
                    "fix_options": [
                        {
                            "action": "place_no_connect",
                            "params": {"position": [100.0, 50.0]},
                            "description": "Place no-connect marker.",
                            "side_effects": [],
                            "confidence": "high",
                        },
                    ],
                    "recommended_fix_index": 0,
                },
            ],
            "total_fixable": 1,
            "total_diagnosed": 1,
        }

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_returns_classified_summary(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode returns result with classification categories."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="pin_not_connected", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        # Mock the repair function
        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        assert result["mode"] == "root_cause"
        assert "summary" in result
        assert result["summary"]["total"] == 4

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_documents_pre_existing(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode result includes pre_existing_documented with root cause explanations."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="power_pin_not_driven", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        assert "pre_existing_documented" in result
        assert len(result["pre_existing_documented"]) == 1
        doc = result["pre_existing_documented"][0]
        assert doc["type"] == "power_pin_not_driven"
        assert doc["root_cause"] == "library_pin_type_mismatch"

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_suppresses_benign(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode result includes benign_suppressed count (not detailed list)."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="same_local_global_label", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        assert "benign_suppressed" in result
        assert result["benign_suppressed"] == 1
        # Benign violations should NOT appear in fixes_applied
        for fix in result["fixes_applied"]:
            assert fix["type"] != "same_local_global_label"

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_lists_config_issues(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode result includes config_issues list."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="lib_symbol_issues", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        assert "config_issues" in result
        assert len(result["config_issues"]) == 1
        assert result["config_issues"][0]["type"] == "lib_symbol_issues"

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_only_fixes_fixable(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode result includes fixes_applied for fixable violations only."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="pin_not_connected", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        assert "fixes_applied" in result
        assert len(result["fixes_applied"]) == 1
        assert result["fixes_applied"][0]["type"] == "pin_not_connected"

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_single_pass(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode is single-pass (iterations=1, diagnosis replaces iteration)."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="pin_not_connected", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        assert result["iterations"] == 1

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_does_not_fix_pre_existing(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode does NOT attempt to fix pre_existing violations."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="power_pin_not_driven", sheet="/")]
        mock_classify.return_value = self._mock_classify_return()
        mock_diagnose.return_value = self._mock_diagnose_return()

        with patch("kicad_agent.ops.erc_auto_fix._get_repair_function") as mock_repair:
            mock_repair.return_value = MagicMock(return_value={"placed": 1})
            result = erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="root_cause",
            )

        # Only the fixable violation should have a repair function call
        # The pre-existing power_pin_not_driven should NOT be in fixes_applied
        for fix in result["fixes_applied"]:
            assert fix["type"] != "power_pin_not_driven"

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    def test_root_cause_empty_violations(self, mock_parse_erc):
        """Root cause mode with no violations returns empty result structure."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = []
        result = erc_auto_fix(
            self._make_mock_ir(),
            Path("test.kicad_sch"),
            mode="root_cause",
        )

        assert result["mode"] == "root_cause"
        assert result["fixes_applied"] == []
        assert result["iterations"] == 0
        assert result["remaining_violations"] == 0
        assert result["pre_existing_documented"] == []
        assert result["benign_suppressed"] == 0
        assert result["config_issues"] == []


# ---------------------------------------------------------------------------
# Symptom mode tests
# ---------------------------------------------------------------------------


class TestSymptomMode:
    """Test that symptom mode preserves existing erc_auto_fix behavior."""

    def _make_mock_ir(self):
        ir = MagicMock()
        ir.get_pin_positions.return_value = []
        ir.get_wire_endpoints.return_value = []
        ir.get_label_positions.return_value = []
        return ir

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    def test_symptom_mode_returns_standard_structure(self, mock_parse_erc):
        """Symptom mode produces same result structure as before."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = []
        result = erc_auto_fix(
            self._make_mock_ir(),
            Path("test.kicad_sch"),
            mode="symptom",
        )

        assert "fixes_applied" in result
        assert "iterations" in result
        assert "remaining_violations" in result
        assert "unhandled_violations" in result

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    def test_symptom_mode_calls_original_logic(self, mock_parse_erc):
        """Symptom mode calls the original iteration-based repair logic."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        # No violations -- early exit, iterations=0
        mock_parse_erc.return_value = []
        result = erc_auto_fix(
            self._make_mock_ir(),
            Path("test.kicad_sch"),
            mode="symptom",
        )

        assert result["iterations"] == 0
        assert result["remaining_violations"] == 0

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    def test_default_mode_is_symptom(self, mock_parse_erc):
        """Calling erc_auto_fix without mode defaults to symptom mode."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = []
        result = erc_auto_fix(
            self._make_mock_ir(),
            Path("test.kicad_sch"),
        )

        # Symptom mode structure (no "mode" key in symptom result)
        assert "fixes_applied" in result
        assert "unhandled_violations" in result


# ---------------------------------------------------------------------------
# Mode dispatch tests
# ---------------------------------------------------------------------------


class TestModeDispatch:
    """Test that erc_auto_fix dispatches to correct mode."""

    def _make_mock_ir(self):
        ir = MagicMock()
        ir.get_pin_positions.return_value = []
        ir.get_wire_endpoints.return_value = []
        ir.get_label_positions.return_value = []
        return ir

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    @patch("kicad_agent.ops.violation_classifier.classify_violations")
    @patch("kicad_agent.ops.violation_diagnostic.diagnose_violations")
    def test_root_cause_calls_classify_then_diagnose(
        self, mock_diagnose, mock_classify, mock_parse_erc
    ):
        """Root cause mode calls classify_violations then diagnose_violations then targeted repair."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = [MagicMock(type="pin_not_connected", sheet="/")]
        mock_classify.return_value = {
            "fixable": [],
            "pre_existing": [],
            "benign": [],
            "config_issues": [],
            "summary": {"total": 1, "fixable": 0, "pre_existing": 0, "benign": 0, "config": 0},
        }
        mock_diagnose.return_value = {
            "diagnoses": [],
            "total_fixable": 0,
            "total_diagnosed": 0,
        }

        erc_auto_fix(
            self._make_mock_ir(),
            Path("test.kicad_sch"),
            mode="root_cause",
        )

        mock_classify.assert_called_once()
        mock_diagnose.assert_called_once()

    @patch("kicad_agent.ops.erc_auto_fix.parse_erc")
    def test_symptom_mode_does_not_call_classify(self, mock_parse_erc):
        """Symptom mode does NOT call classify_violations."""
        from kicad_agent.ops.erc_auto_fix import erc_auto_fix

        mock_parse_erc.return_value = []

        with patch("kicad_agent.ops.violation_classifier.classify_violations") as mock_classify:
            erc_auto_fix(
                self._make_mock_ir(),
                Path("test.kicad_sch"),
                mode="symptom",
            )
            mock_classify.assert_not_called()


# ---------------------------------------------------------------------------
# Executor handler dispatch tests
# ---------------------------------------------------------------------------


class TestExecutorHandlerDispatch:
    """Test that executor handler passes mode and fix_classes to erc_auto_fix."""

    def test_handler_passes_mode(self):
        """Executor handler passes op.mode to erc_auto_fix."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp
        from kicad_agent.ops.executor import _SCHEMATIC_HANDLERS

        assert "erc_auto_fix" in _SCHEMATIC_HANDLERS
        handler = _SCHEMATIC_HANDLERS["erc_auto_fix"]

        op = ErcAutoFixOp(
            target_file="test.kicad_sch",
            max_iterations=3,
            mode="root_cause",
            fix_classes=["fixable"],
            sheet_filter="/",
        )

        mock_ir = MagicMock()
        mock_file_path = Path("test.kicad_sch")

        with patch("kicad_agent.ops.erc_auto_fix.erc_auto_fix") as mock_auto_fix:
            mock_auto_fix.return_value = {"mode": "root_cause"}
            handler(op, mock_ir, mock_file_path)

            mock_auto_fix.assert_called_once_with(
                mock_ir,
                mock_file_path,
                max_iterations=3,
                mode="root_cause",
                fix_classes=["fixable"],
                sheet_filter="/",
            )

    def test_handler_default_symptom(self):
        """Executor handler uses schema defaults when only target_file provided."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixOp
        from kicad_agent.ops.executor import _SCHEMATIC_HANDLERS

        handler = _SCHEMATIC_HANDLERS["erc_auto_fix"]

        # Use real schema model to get proper defaults
        op = ErcAutoFixOp(target_file="test.kicad_sch")

        mock_ir = MagicMock()
        mock_file_path = Path("test.kicad_sch")

        with patch("kicad_agent.ops.erc_auto_fix.erc_auto_fix") as mock_auto_fix:
            mock_auto_fix.return_value = {"fixes_applied": []}
            handler(op, mock_ir, mock_file_path)

            call_kwargs = mock_auto_fix.call_args
            assert call_kwargs[1]["mode"] == "symptom"
            assert call_kwargs[1]["fix_classes"] is None
            assert call_kwargs[1]["sheet_filter"] == "/"

    def test_handler_hierarchical_dispatch(self):
        """erc_auto_fix_hierarchical handler is registered and dispatches correctly."""
        from kicad_agent.ops._schema_erc_smart import ErcAutoFixHierarchicalOp
        from kicad_agent.ops.executor import _SCHEMATIC_HANDLERS

        assert "erc_auto_fix_hierarchical" in _SCHEMATIC_HANDLERS
        handler = _SCHEMATIC_HANDLERS["erc_auto_fix_hierarchical"]

        op = ErcAutoFixHierarchicalOp(
            target_file="root.kicad_sch",
            max_iterations=5,
            mode="root_cause",
        )

        mock_ir = MagicMock()
        mock_file_path = Path("root.kicad_sch")

        with patch("kicad_agent.ops.erc_auto_fix.erc_auto_fix_hierarchical") as mock_hier:
            mock_hier.return_value = {"sheets_processed": 3}
            handler(op, mock_ir, mock_file_path)

            mock_hier.assert_called_once_with(
                mock_file_path,
                max_iterations=5,
                mode="root_cause",
            )


# ---------------------------------------------------------------------------
# Action mapping tests
# ---------------------------------------------------------------------------


class TestActionMapping:
    """Test _action_to_repair_name helper."""

    def test_place_no_connect_mapping(self):
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("place_no_connect") == "place_no_connects_from_erc"

    def test_break_wire_shorts_mapping(self):
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("break_wire_shorts") == "break_wire_shorts"

    def test_fix_shorted_nets_mapping(self):
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("fix_shorted_nets") == "fix_shorted_nets"

    def test_add_power_flag_mapping(self):
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("add_power_flag") == "add_power_flags"

    def test_unknown_action_returns_none(self):
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("unknown_action") is None

    def test_erc_auto_fix_action_returns_none(self):
        """erc_auto_fix action from generic fallback has no direct mapping."""
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("erc_auto_fix") is None

    def test_add_wire_action_returns_none(self):
        """add_wire action from pin_not_connected diagnosis has no direct mapping."""
        from kicad_agent.ops.erc_auto_fix import _action_to_repair_name

        assert _action_to_repair_name("add_wire") is None


# ---------------------------------------------------------------------------
# Empty result helper tests
# ---------------------------------------------------------------------------


class TestEmptyRootCauseResult:
    """Test _empty_root_cause_result helper."""

    def test_empty_result_structure(self):
        from kicad_agent.ops.erc_auto_fix import _empty_root_cause_result

        result = _empty_root_cause_result()
        assert result["mode"] == "root_cause"
        assert result["fixes_applied"] == []
        assert result["iterations"] == 0
        assert result["remaining_violations"] == 0
        assert result["pre_existing_documented"] == []
        assert result["benign_suppressed"] == 0
        assert result["config_issues"] == []
        assert result["summary"]["total"] == 0
