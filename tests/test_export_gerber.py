"""Tests for Gerber and drill export wrappers.

GEN-02: Tests for export_gerber and export_drill functions.
All tests skip gracefully when kicad-cli is unavailable.
"""

import shutil
from pathlib import Path

import pytest

from volta.export.gerber import ExportResult, export_drill, export_gerber

# Skip all tests if kicad-cli is not available
kicad_cli_available = shutil.which("kicad-cli") is not None
skip_reason = "kicad-cli not found on PATH -- install KiCad 10+"

pytestmark = pytest.mark.skipif(not kicad_cli_available, reason=skip_reason)


class TestExportGerber:
    """Tests for export_gerber."""

    def test_export_gerber_creates_files(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Export Gerber from Arduino_Mega and verify output files exist."""
        output_dir = tmp_output_dir / "gerber"
        result = export_gerber(arduino_mega_pcb, output_dir=output_dir)

        assert result.success
        assert result.output_dir == output_dir
        assert len(result.files) > 0

        for f in result.files:
            assert f.exists()
            assert f.stat().st_size > 0
            # Gerber files use various extensions (.gbr, .gtl, .gbl, .gbrjob, etc.)
            assert f.suffix.startswith(".g") or f.suffix == ".gm1"

    def test_export_gerber_returns_result(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Verify ExportResult fields are populated correctly."""
        result = export_gerber(
            arduino_mega_pcb, output_dir=tmp_output_dir / "gerber"
        )

        assert isinstance(result, ExportResult)
        assert result.success is True
        assert len(result.files) > 0
        assert "kicad-cli" in result.command

    def test_export_gerber_custom_layers(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Export only specific layers and verify file count."""
        result = export_gerber(
            arduino_mega_pcb,
            output_dir=tmp_output_dir / "gerber",
            layers=["F.Cu", "B.Cu"],
        )

        assert result.success
        # Should have at least 2 .gbr files for the two requested layers
        assert len(result.files) >= 2

    def test_export_gerber_invalid_path_raises(self) -> None:
        """Non-.kicad_pcb path raises ValueError."""
        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            export_gerber(Path("some_file.txt"))

    def test_export_nonexistent_file_raises(self) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            export_gerber(Path("/nonexistent/board.kicad_pcb"))


class TestExportDrill:
    """Tests for export_drill."""

    def test_export_drill_creates_files(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Export drill files and verify output."""
        output_dir = tmp_output_dir / "drill"
        result = export_drill(arduino_mega_pcb, output_dir=output_dir)

        assert result.success
        assert result.output_dir == output_dir
        assert len(result.files) > 0

        # Should have at least one .drl file (Excellon format)
        drl_files = [f for f in result.files if f.suffix == ".drl"]
        assert len(drl_files) > 0
        for f in drl_files:
            assert f.exists()
            assert f.stat().st_size > 0
