"""Tests for FillZonesOp schema validation (ae-20).

TDD RED phase: these tests define the expected behavior of FillZonesOp
before the implementation exists.
"""

import pytest
from pydantic import ValidationError

from volta.ops._schema_gap import FillZonesOp


class TestFillZonesOpValid:
    """Verify that structurally valid fill_zones intents are accepted."""

    def test_fill_zones_minimal(self) -> None:
        """fill_zones with only required fields validates."""
        op = FillZonesOp(target_file="board.kicad_pcb")
        assert op.op_type == "fill_zones"
        assert op.target_file == "board.kicad_pcb"
        assert op.dry_run is False

    def test_fill_zones_full(self) -> None:
        """fill_zones with all fields specified."""
        op = FillZonesOp(
            target_file="board.kicad_pcb",
            dry_run=True,
        )
        assert op.op_type == "fill_zones"
        assert op.dry_run is True

    def test_discriminator_value(self) -> None:
        """op_type discriminator must be exactly 'fill_zones'."""
        op = FillZonesOp(target_file="test.kicad_pcb")
        assert op.op_type == "fill_zones"

    def test_dry_run_default_false(self) -> None:
        """Default dry_run is False."""
        op = FillZonesOp(target_file="test.kicad_pcb")
        assert op.dry_run is False


class TestFillZonesOpInvalid:
    """Verify that invalid fill_zones intents are rejected."""

    def test_missing_target_file_raises(self) -> None:
        """target_file is required and must be a valid KiCad file."""
        with pytest.raises(ValidationError):
            FillZonesOp()

    def test_target_file_path_traversal_rejected(self) -> None:
        """Path traversal in target_file must be rejected."""
        with pytest.raises(ValidationError):
            FillZonesOp(target_file="../board.kicad_pcb")

    def test_target_file_absolute_path_rejected(self) -> None:
        """Absolute paths in target_file must be rejected."""
        with pytest.raises(ValidationError):
            FillZonesOp(target_file="/tmp/board.kicad_pcb")
