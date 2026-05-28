"""Tests for hierarchical label validation guard.

SCHREPAIR-03: Validates hlabel set comparison logic.
"""

from unittest.mock import MagicMock

import pytest

from kicad_agent.ops.hlabel_guard import HlabelValidationResult, validate_hlabels
from kicad_agent.ops.schema import Operation, ValidateHlabelsOp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ir_with_hlabels(names: list[str]) -> MagicMock:
    """Create a mock SchematicIR with hierarchical labels."""
    ir = MagicMock()
    labels = []
    for name in names:
        lbl = MagicMock()
        lbl.text = name
        labels.append(lbl)
    ir.schematic.hierarchicalLabels = labels
    return ir


# ---------------------------------------------------------------------------
# validate_hlabels tests
# ---------------------------------------------------------------------------


def test_validate_hlabels_matching():
    """Matching labels pass validation."""
    ir = _make_ir_with_hlabels(["SDA", "SCL", "VCC"])
    result = validate_hlabels(ir, {"SDA", "SCL", "VCC"})

    assert isinstance(result, HlabelValidationResult)
    assert result.passed is True
    assert result.expected_count == 3
    assert result.actual_count == 3
    assert result.missing == ()
    assert result.extra == ()


def test_validate_hlabels_missing():
    """Missing labels cause validation failure."""
    ir = _make_ir_with_hlabels(["SDA", "SCL", "VCC"])
    result = validate_hlabels(ir, {"SDA", "SCL", "VCC", "GND"})

    assert result.passed is False
    assert result.missing == ("GND",)
    assert result.actual_count == 3
    assert result.expected_count == 4


def test_validate_hlabels_extra():
    """Extra labels reported but do not cause failure on their own."""
    ir = _make_ir_with_hlabels(["SDA", "SCL", "VCC"])
    result = validate_hlabels(ir, {"SDA", "SCL"})

    # passed=False because missing is empty but the check is for missing only
    # Actually, missing = expected - actual = {} (nothing missing)
    assert result.passed is True
    assert result.extra == ("VCC",)
    assert result.actual_count == 3
    assert result.expected_count == 2


def test_validate_hlabels_snapshot_mode():
    """Snapshot mode (expected_labels=None) always passes."""
    ir = _make_ir_with_hlabels(["SDA", "SCL", "VCC"])
    result = validate_hlabels(ir, expected_labels=None)

    assert result.passed is True
    assert result.actual_count == 3
    assert result.expected_count == 0
    assert result.missing == ()
    assert result.extra == ()


def test_validate_hlabels_empty():
    """Empty IR with empty expected set passes."""
    ir = _make_ir_with_hlabels([])
    result = validate_hlabels(ir, set())

    assert result.passed is True
    assert result.actual_count == 0
    assert result.expected_count == 0
    assert result.missing == ()
    assert result.extra == ()


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_validate_hlabels_op_schema():
    """ValidateHlabelsOp validates correctly with labels."""
    op = ValidateHlabelsOp(
        op_type="validate_hlabels",
        target_file="test.kicad_sch",
        expected_labels=["SDA", "SCL"],
    )
    assert op.op_type == "validate_hlabels"
    assert op.expected_labels == ["SDA", "SCL"]

    # Validate through Operation discriminated union
    wrapped = Operation.model_validate({
        "root": {
            "op_type": "validate_hlabels",
            "target_file": "test.kicad_sch",
            "expected_labels": ["SDA", "SCL"],
        }
    })
    assert wrapped.root.op_type == "validate_hlabels"

    # Empty expected_labels is accepted
    op_empty = ValidateHlabelsOp(
        op_type="validate_hlabels",
        target_file="test.kicad_sch",
        expected_labels=[],
    )
    assert op_empty.expected_labels == []
