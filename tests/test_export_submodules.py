"""Tests for export sub-modules: gerber, bom, general, CLI wrappers, render."""

from pathlib import Path

import pytest

from kicad_agent.export.gerber import ExportResult, COPPER_LAYERS_2, COPPER_LAYERS_4
from kicad_agent.export.bom import BomResult, parse_bom_csv
from kicad_agent.export.render import RenderResult


class TestGerberConstants:
    """Tests for Gerber layer constants."""

    def test_copper_layers_2(self):
        """COPPER_LAYERS_2 has exactly 2 layers."""
        assert len(COPPER_LAYERS_2) == 2
        assert "F.Cu" in COPPER_LAYERS_2
        assert "B.Cu" in COPPER_LAYERS_2

    def test_copper_layers_4(self):
        """COPPER_LAYERS_4 has exactly 4 layers."""
        assert len(COPPER_LAYERS_4) == 4
        assert "In1.Cu" in COPPER_LAYERS_4


class TestBomResult:
    """Tests for BOM result types."""

    def test_import(self):
        """BomResult is importable."""
        assert BomResult is not None

    def test_parse_bom_csv_callable(self):
        """parse_bom_csv is callable."""
        assert callable(parse_bom_csv)


class TestGeneralExport:
    """Tests for general export functions."""

    def test_import(self):
        """General export functions are importable."""
        from kicad_agent.export.general import (
            export_netlist,
            export_position,
            export_step,
            get_board_statistics,
        )
        assert callable(export_netlist)
        assert callable(export_position)
        assert callable(export_step)
        assert callable(get_board_statistics)
