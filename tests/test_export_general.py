"""Tests for general export wrappers and board statistics.

GEN-02: Tests for position, STEP, PDF exports and get_board_statistics.
All kicad-cli tests skip gracefully when kicad-cli is unavailable.
Board statistics tests always run (no kicad-cli dependency).
"""

import shutil
from pathlib import Path

import pytest

from volta.export.general import (
    export_position,
    export_schematic_pdf,
    export_step,
    get_board_statistics,
)

# Skip kicad-cli tests if not available
kicad_cli_available = shutil.which("kicad-cli") is not None
skip_reason = "kicad-cli not found on PATH -- install KiCad 10+"


@pytest.mark.skipif(not kicad_cli_available, reason=skip_reason)
class TestExportPosition:
    """Tests for export_position."""

    def test_export_position_creates_file(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Export position file and verify it exists."""
        result = export_position(
            arduino_mega_pcb, output_dir=tmp_output_dir, format="csv"
        )

        assert result.success
        assert len(result.files) > 0
        for f in result.files:
            assert f.exists()
            assert f.stat().st_size > 0


@pytest.mark.skipif(not kicad_cli_available, reason=skip_reason)
class TestExportStep:
    """Tests for export_step."""

    def test_export_step_creates_file(
        self, arduino_mega_pcb: Path, tmp_output_dir: Path
    ) -> None:
        """Export STEP file and verify it exists."""
        output_path = tmp_output_dir / "board.step"
        result = export_step(arduino_mega_pcb, output_path=output_path)

        assert result.success
        assert len(result.files) == 1
        assert result.files[0].suffix == ".step"
        assert result.files[0].exists()
        assert result.files[0].stat().st_size > 0


@pytest.mark.skipif(not kicad_cli_available, reason=skip_reason)
class TestExportSchematicPdf:
    """Tests for export_schematic_pdf."""

    def test_export_schematic_pdf(
        self, raspberry_pi_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Export schematic PDF and verify it exists."""
        output_path = tmp_output_dir / "schematic.pdf"
        result = export_schematic_pdf(
            raspberry_pi_sch, output_path=output_path
        )

        assert result.success
        assert len(result.files) == 1
        assert result.files[0].suffix == ".pdf"
        assert result.files[0].exists()
        assert result.files[0].stat().st_size > 0


class TestGetBoardStatistics:
    """Tests for get_board_statistics (no kicad-cli needed)."""

    def test_get_board_statistics(
        self, arduino_mega_pcb: Path
    ) -> None:
        """Get stats from Arduino_Mega PCB and verify counts."""
        stats = get_board_statistics(arduino_mega_pcb)

        assert stats["component_count"] > 0
        assert stats["net_count"] > 0
        assert stats["layer_count"] > 0
        assert stats["has_drc_errors"] is None  # Not checked by this function

    def test_get_board_statistics_dimensions(
        self, arduino_mega_pcb: Path
    ) -> None:
        """Verify board dimensions are positive."""
        stats = get_board_statistics(arduino_mega_pcb)

        assert stats["board_width_mm"] > 0
        assert stats["board_height_mm"] > 0

    def test_get_board_statistics_unique_footprints(
        self, arduino_mega_pcb: Path
    ) -> None:
        """Verify unique footprints count is populated."""
        stats = get_board_statistics(arduino_mega_pcb)

        assert stats["unique_footprints"] > 0
        assert stats["unique_footprints"] <= stats["component_count"]
