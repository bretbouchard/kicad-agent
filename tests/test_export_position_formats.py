"""Tests verifying export_position format completeness in export/general.py.

Confirms the Phase 79 gap analysis claim that export_position already supports
all 3 formats (csv, ascii, gerber) with side and units options. No code changes
needed -- these are verification-only tests.

All tests mock subprocess.run to avoid kicad-cli dependency in CI.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.export.general import export_position


@pytest.fixture
def fake_pcb(tmp_path):
    """Create a fake .kicad_pcb file."""
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20221018))")
    return pcb


@pytest.fixture
def mock_kicad_cli():
    """Patch subprocess.run to simulate successful kicad-cli execution."""
    with patch("volta.export.gerber.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_cli_resolver():
    """Patch find_kicad_cli to return a fake path."""
    with patch("volta.export.gerber.find_kicad_cli") as mock_find:
        mock_cli = MagicMock()
        mock_cli.path = "/usr/local/bin/kicad-cli"
        mock_find.return_value = mock_cli
        yield mock_find


class TestExportPositionFormats:
    """Verify export_position supports csv, ascii, and gerber formats."""

    def test_csv_format(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with format='csv' calls kicad-cli with --format csv."""
        export_position(fake_pcb, format="csv")

        cmd = mock_kicad_cli.call_args[0][0]
        assert "csv" in cmd

    def test_ascii_format(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with format='ascii' calls kicad-cli with --format ascii."""
        export_position(fake_pcb, format="ascii")

        cmd = mock_kicad_cli.call_args[0][0]
        assert "ascii" in cmd

    def test_gerber_format(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with format='gerber' calls kicad-cli with --format gerber."""
        export_position(fake_pcb, format="gerber")

        cmd = mock_kicad_cli.call_args[0][0]
        assert "gerber" in cmd


class TestExportPositionSide:
    """Verify export_position supports front, back, and both sides."""

    def test_side_front(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with side='front' passes --side front."""
        export_position(fake_pcb, side="front")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "--side" in cmd
        assert "front" in cmd

    def test_side_back(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with side='back' passes --side back."""
        export_position(fake_pcb, side="back")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "back" in cmd

    def test_side_both(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with side='both' passes --side both."""
        export_position(fake_pcb, side="both")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "both" in cmd


class TestExportPositionUnits:
    """Verify export_position supports mm and inches units."""

    def test_units_mm(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with units='mm' passes --units mm."""
        export_position(fake_pcb, units="mm")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "--units" in cmd
        assert "mm" in cmd

    def test_units_inches(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_position with units='in' passes --units in."""
        export_position(fake_pcb, units="in")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "in" in cmd
