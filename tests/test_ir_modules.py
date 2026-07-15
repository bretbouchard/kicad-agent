"""Tests for IR module: intermediate representation types."""

import pytest

from volta.ir.transaction import (
    Transaction,
    TransactionResult,
)


class TestTransaction:
    """Tests for Transaction class."""

    def test_import(self):
        """Transaction is importable."""
        assert Transaction is not None

    def test_nonexistent_file_raises(self):
        """Transaction raises FileNotFoundError for missing file."""
        from pathlib import Path
        with pytest.raises(FileNotFoundError):
            Transaction(Path("/nonexistent/file.kicad_sch")).__enter__()


class TestTransactionResult:
    """Tests for TransactionResult."""

    def test_creation(self):
        """TransactionResult can be created."""
        from pathlib import Path
        result = TransactionResult(success=True, target_file=Path("/tmp/test.kicad_sch"))
        assert result.success is True


class TestSchematicIR:
    """Tests for schematic IR module."""

    def test_import(self):
        """Schematic IR is importable."""
        from volta.ir import schematic_ir
        assert hasattr(schematic_ir, "SchematicIR")


class TestPcbIR:
    """Tests for PCB IR module."""

    def test_import(self):
        """PCB IR is importable."""
        from volta.ir import pcb_ir
        assert hasattr(pcb_ir, "PcbIR")


class TestFootprintIR:
    """Tests for footprint IR module."""

    def test_import(self):
        """Footprint IR is importable."""
        from volta.ir import footprint_ir
        assert hasattr(footprint_ir, "FootprintIR")
