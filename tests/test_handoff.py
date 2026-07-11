"""Tests for the manufacturer handoff package (Phase 208).

Covers:
- export_bom_profile (profile-driven BOM formatter) -- Task 2
- export_handoff orchestrator -- Tasks 3 & 4
- build_handoff_export op wiring -- Task 5

Unit tests use monkeypatch stubs (NOT kicad-cli skips) so they run in CI.
"""

from __future__ import annotations

import csv
import shutil
import zipfile
from pathlib import Path

import pytest

from kicad_agent.export.bom import BomResult, export_bom_profile
from kicad_agent.dfm.profiles import load_profile
from kicad_agent.export.gerber import ExportResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _create_pcb_with_title_block(tmpdir: Path, title: str = "Handoff Test", rev: str = "1.0") -> Path:
    """Create a minimal PCB with a title_block carrying rev/title/company."""
    pcb_path = tmpdir / "test_board.kicad_pcb"
    content = f'''(kicad_pcb (version 20241229) (generator "test")
  (general (thickness 1.6) (layers 2))
  (paper "A4")
  (title_block
    (title "{title}")
    (date "2026-07-10")
    (rev "{rev}")
    (company "Test Co")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
)
'''
    pcb_path.write_text(content, encoding="utf-8")
    return pcb_path


def _create_minimal_sch(tmpdir: Path, stem: str = "test_board") -> Path:
    """Create a minimal .kicad_sch fixture (no real components)."""
    sch_path = tmpdir / f"{stem}.kicad_sch"
    sch_path.write_text(
        '(kicad_sch (version 20241229) (generator "test")\n'
        '  (symbol (lib_id "Device:R")\n'
        '    (property "Reference" "R1" (at 0 0))\n'
        '    (property "Value" "10k" (at 0 0))\n'
        '    (property "Footprint" "R_0402" (at 0 0))\n'
        '  )\n'
        ')\n',
        encoding="utf-8",
    )
    return sch_path


def _create_minimal_sch_with_value(tmpdir: Path, value: str, stem: str = "test_board") -> Path:
    """Create a minimal .kicad_sch with a specific Value on R1."""
    sch_path = tmpdir / f"{stem}.kicad_sch"
    sch_path.write_text(
        '(kicad_sch (version 20241229) (generator "test")\n'
        '  (symbol (lib_id "Device:R")\n'
        '    (property "Reference" "R1" (at 0 0))\n'
        f'    (property "Value" "{value}" (at 0 0))\n'
        '    (property "Footprint" "R_0402" (at 0 0))\n'
        '  )\n'
        ')\n',
        encoding="utf-8",
    )
    return sch_path


def _stub_export_bom_with_csv(output_path: Path, rows: list[dict], fieldnames: list[str]):
    """Return a fake export_bom that writes a CSV with the given rows."""

    def _fake(sch_path: Path, output_path: Path | None = None, **kwargs):
        out = output_path or sch_path.parent / f"{sch_path.stem}-BOM.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return BomResult(
            success=True,
            output_path=out,
            component_count=len(rows),
            unique_components=len(rows),
            command="stub-kicad-cli sch export bom",
            stderr="",
        )

    return _fake


# ---------------------------------------------------------------------------
# Task 2: export_bom_profile
# ---------------------------------------------------------------------------


class TestExportBomProfileGeneric:
    """Generic (profile=None) path delegates to export_bom unchanged."""

    def test_bom_profile_generic_columns(self, tmp_path: Path, monkeypatch) -> None:
        """profile=None produces the generic kicad-cli default CSV."""
        sch_path = _create_minimal_sch(tmp_path)
        captured: dict = {}

        def _fake_export_bom(sch_path, output_path=None, **kwargs):
            captured["output_path"] = output_path
            out = output_path or sch_path.parent / f"{sch_path.stem}-BOM.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                '"Reference","Value","Footprint","Qty","DNP"\n'
                '"R1","10k","R_0402","1",""\n',
                encoding="utf-8",
            )
            return BomResult(True, out, 1, 1, "stub", "")

        monkeypatch.setattr("kicad_agent.export.bom.export_bom", _fake_export_bom)

        result = export_bom_profile(sch_path, tmp_path, profile=None)

        assert result.success
        assert result.output_path.exists()
        # Generic default filename: {stem}-BOM.csv
        assert result.output_path.name == "test_board-BOM.csv"
        # Header is the kicad-cli default (untouched)
        header = result.output_path.read_text(encoding="utf-8").splitlines()[0]
        assert "Reference" in header


class TestExportBomProfileJlcpcb:
    """Profile-driven column rewriting (JLCPCB layout)."""

    def test_bom_profile_jlcpcb_columns(self, tmp_path: Path, monkeypatch) -> None:
        """JLCPCB profile produces a CSV whose header is Comment,Designator,Footprint,LCSC."""
        sch_path = _create_minimal_sch(tmp_path)
        std_rows = [
            {"Reference": "R1", "Value": "10k", "Footprint": "R_0402", "Qty": "1", "DNP": ""},
        ]
        monkeypatch.setattr(
            "kicad_agent.export.bom.export_bom",
            _stub_export_bom_with_csv(sch_path.parent / "ignore.csv", std_rows, ["Reference", "Value", "Footprint", "Qty", "DNP"]),
        )

        profile = load_profile("jlcpcb")
        result = export_bom_profile(sch_path, tmp_path, profile=profile)

        assert result.success
        # Filename derived from profile.bom_filename_pattern
        assert result.output_path.name == "test_board_JLCPCB-BOM.csv"

        with open(result.output_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            data_row = next(reader)

        # Header is exactly the JLCPCB column layout
        assert header == ["Comment", "Designator", "Footprint", "LCSC"]
        # Value -> Comment, Reference -> Designator, Footprint passthrough
        assert data_row[0] == "10k"
        assert data_row[1] == "R1"
        assert data_row[2] == "R_0402"

    def test_bom_profile_filename_pattern(self, tmp_path: Path, monkeypatch) -> None:
        """bom_filename_pattern formats {stem} placeholder."""
        sch_path = _create_minimal_sch(tmp_path, stem="custom_board")
        std_rows = [{"Reference": "C1", "Value": "100nF", "Footprint": "C_0402", "Qty": "1", "DNP": ""}]
        monkeypatch.setattr(
            "kicad_agent.export.bom.export_bom",
            _stub_export_bom_with_csv(tmp_path / "ignore.csv", std_rows, ["Reference", "Value", "Footprint", "Qty", "DNP"]),
        )
        profile = load_profile("jlcpcb")
        result = export_bom_profile(sch_path, tmp_path, profile=profile)
        assert result.output_path.name == "custom_board_JLCPCB-BOM.csv"

    def test_bom_profile_formula_injection_defense(self, tmp_path: Path, monkeypatch) -> None:
        """TM-5: cell values starting with formula chars are single-quote-prefixed."""
        sch_path = _create_minimal_sch_with_value(tmp_path, value="=cmd|evil")
        std_rows = [{"Reference": "R1", "Value": "=cmd|evil", "Footprint": "R_0402", "Qty": "1", "DNP": ""}]
        monkeypatch.setattr(
            "kicad_agent.export.bom.export_bom",
            _stub_export_bom_with_csv(tmp_path / "ignore.csv", std_rows, ["Reference", "Value", "Footprint", "Qty", "DNP"]),
        )
        profile = load_profile("jlcpcb")
        result = export_bom_profile(sch_path, tmp_path, profile=profile)
        with open(result.output_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["Comment"] == "'=cmd|evil"

    def test_bom_profile_skips_unreferenced_components(self, tmp_path: Path, monkeypatch) -> None:
        """Components with Reference='?' or empty are dropped from the vendor BOM."""
        sch_path = _create_minimal_sch(tmp_path)
        std_rows = [
            {"Reference": "R1", "Value": "10k", "Footprint": "R_0402", "Qty": "1", "DNP": ""},
            {"Reference": "?", "Value": "unknown", "Footprint": "", "Qty": "1", "DNP": ""},
        ]
        monkeypatch.setattr(
            "kicad_agent.export.bom.export_bom",
            _stub_export_bom_with_csv(tmp_path / "ignore.csv", std_rows, ["Reference", "Value", "Footprint", "Qty", "DNP"]),
        )
        profile = load_profile("jlcpcb")
        result = export_bom_profile(sch_path, tmp_path, profile=profile)
        with open(result.output_path, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # header + 1 data row (the "?" row dropped)
        assert len(rows) == 2
