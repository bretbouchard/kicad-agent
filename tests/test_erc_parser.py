"""Tests for ERC parser and violation position extractor.

SCHREPAIR-01, SCHREPAIR-02: Structured ERC violation parsing and filtering.
"""

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.ops.erc_parser import (
    ErcViolation,
    ViolationPosition,
    extract_violation_positions,
    parse_erc,
)
from volta.ops.schema import (
    ExtractViolationPositionsOp,
    Operation,
    ParseErcOp,
)
from volta.validation.erc_drc import Severity, Violation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch")


def _kicad_cli_available() -> bool:
    """Check if kicad-cli is available on PATH."""
    return shutil.which("kicad-cli") is not None


# ---------------------------------------------------------------------------
# parse_erc tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not available")
def test_parse_erc_with_fixture():
    """Parse ERC results from a real schematic fixture."""
    violations = parse_erc(FIXTURE_PATH)
    assert isinstance(violations, list)
    for v in violations:
        assert isinstance(v, ErcViolation)
        assert isinstance(v.type, str)
        assert isinstance(v.severity, str)
        assert isinstance(v.description, str)
        assert isinstance(v.sheet, str)
        assert isinstance(v.positions, list)


def test_parse_erc_missing_file():
    """parse_erc returns erc_error for nonexistent file."""
    violations = parse_erc(Path("/nonexistent.kicad_sch"))
    assert len(violations) == 1
    assert violations[0].type == "erc_error"
    assert violations[0].severity == "error"
    assert "not found" in violations[0].description.lower() or "File" in violations[0].description


# ---------------------------------------------------------------------------
# extract_violation_positions tests
# ---------------------------------------------------------------------------


def test_extract_violation_positions_type_filter():
    """extract_violation_positions filters by violation_type."""
    violations = [
        ErcViolation(
            sheet="/",
            type="pin_not_connected",
            severity="error",
            description="Pin not connected",
            positions=[(10.0, 20.0), (30.0, 40.0)],
        ),
        ErcViolation(
            sheet="/",
            type="power_pin_not_driven",
            severity="error",
            description="Power pin not driven",
            positions=[(50.0, 60.0)],
        ),
    ]

    with patch("volta.ops.erc_parser.parse_erc", return_value=violations):
        positions = extract_violation_positions(Path("test.kicad_sch"), "pin_not_connected")

    assert len(positions) == 2
    assert all(isinstance(p, ViolationPosition) for p in positions)
    assert positions[0].x == 10.0
    assert positions[0].y == 20.0
    assert positions[1].x == 30.0
    assert positions[1].y == 40.0
    # All positions should share the same description
    assert positions[0].description == "Pin not connected"


def test_extract_violation_positions_empty():
    """extract_violation_positions returns empty list when no violations."""
    with patch("volta.ops.erc_parser.parse_erc", return_value=[]):
        positions = extract_violation_positions(Path("test.kicad_sch"), "pin_not_connected")

    assert positions == []


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_parse_erc_op_schema():
    """ParseErcOp validates correctly."""
    op = ParseErcOp(op_type="parse_erc", target_file="test.kicad_sch")
    assert op.op_type == "parse_erc"
    assert op.target_file == "test.kicad_sch"

    # Validate through Operation discriminated union
    wrapped = Operation.model_validate({
        "root": {"op_type": "parse_erc", "target_file": "test.kicad_sch"}
    })
    assert wrapped.root.op_type == "parse_erc"


def test_extract_positions_op_schema():
    """ExtractViolationPositionsOp validates correctly."""
    op = ExtractViolationPositionsOp(
        op_type="extract_violation_positions",
        target_file="test.kicad_sch",
        violation_type="pin_not_connected",
    )
    assert op.violation_type == "pin_not_connected"

    # Validate through Operation discriminated union
    wrapped = Operation.model_validate({
        "root": {
            "op_type": "extract_violation_positions",
            "target_file": "test.kicad_sch",
            "violation_type": "pin_not_connected",
        }
    })
    assert wrapped.root.op_type == "extract_violation_positions"
