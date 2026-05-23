"""Tests for BOM export wrapper.

GEN-02: Tests for export_bom and parse_bom_csv functions.
All tests skip gracefully when kicad-cli is unavailable.
"""

import shutil
from pathlib import Path

import pytest

from kicad_agent.export.bom import BomResult, export_bom, parse_bom_csv

# Skip all tests if kicad-cli is not available
kicad_cli_available = shutil.which("kicad-cli") is not None
skip_reason = "kicad-cli not found on PATH -- install KiCad 10+"

pytestmark = pytest.mark.skipif(not kicad_cli_available, reason=skip_reason)


class TestExportBom:
    """Tests for export_bom."""

    def test_export_bom_creates_file(
        self, raspberry_pi_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Export BOM from RaspberryPi schematic and verify file exists."""
        output_path = tmp_output_dir / "bom.csv"
        result = export_bom(raspberry_pi_sch, output_path=output_path)

        assert result.success
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 0

    def test_export_bom_returns_result(
        self, raspberry_pi_sch: Path, tmp_output_dir: Path
    ) -> None:
        """Verify BomResult has component counts > 0."""
        result = export_bom(
            raspberry_pi_sch,
            output_path=tmp_output_dir / "bom.csv",
        )

        assert isinstance(result, BomResult)
        assert result.success
        assert result.component_count > 0
        assert result.unique_components > 0
        assert "kicad-cli" in result.command


class TestParseBomCsv:
    """Tests for parse_bom_csv (no kicad-cli needed, but module-level skip applies)."""

    def test_parse_bom_csv(self, tmp_output_dir: Path) -> None:
        """Parse a manually created BOM CSV and verify component list."""
        csv_content = (
            '"Refs","Value","Footprint","Qty","DNP"\n'
            '"R1,R2,R3","10k","Resistor_SMD:R_0402","3",""\n'
            '"C1","100nF","Capacitor_SMD:C_0402","1",""\n'
            '"U1","ATmega2560","Package_QFP:TQFP-100","1",""\n'
        )
        csv_path = tmp_output_dir / "test_bom.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        rows = parse_bom_csv(csv_path)

        assert len(rows) == 3
        assert rows[0]["Refs"] == "R1,R2,R3"
        assert rows[0]["Value"] == "10k"
        assert rows[1]["Qty"] == "1"
        assert rows[2]["Footprint"] == "Package_QFP:TQFP-100"
