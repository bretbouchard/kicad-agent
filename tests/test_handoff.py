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

from volta.export.bom import BomResult, export_bom_profile
from volta.dfm.profiles import load_profile
from volta.export.gerber import ExportResult


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

        monkeypatch.setattr("volta.export.bom.export_bom", _fake_export_bom)

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
            "volta.export.bom.export_bom",
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
            "volta.export.bom.export_bom",
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
            "volta.export.bom.export_bom",
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
            "volta.export.bom.export_bom",
            _stub_export_bom_with_csv(tmp_path / "ignore.csv", std_rows, ["Reference", "Value", "Footprint", "Qty", "DNP"]),
        )
        profile = load_profile("jlcpcb")
        result = export_bom_profile(sch_path, tmp_path, profile=profile)
        with open(result.output_path, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # header + 1 data row (the "?" row dropped)
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Tasks 3 & 4: export_handoff orchestrator + readme generation
# ---------------------------------------------------------------------------


def _stub_export_single(category: str, build_dir: Path, name: str):
    """Return a fake export that writes one file into build_dir."""

    def _fake(*args, **kwargs):
        # output_dir OR output_path kwarg
        target_dir = build_dir
        if "output_dir" in kwargs and kwargs["output_dir"] is not None:
            target_dir = Path(kwargs["output_dir"])
        elif "output_path" in kwargs and kwargs["output_path"] is not None:
            target_dir = Path(kwargs["output_path"]).parent
            Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        f = target_dir / name
        f.write_text(f"dummy {category}")
        return ExportResult(
            success=True,
            output_dir=target_dir,
            files=(f,),
            command=f"stub-{category}",
            stderr="",
        )

    return _fake


def _install_export_stubs(monkeypatch, build_dir: Path) -> None:
    """Install stub export wrappers on the handoff module namespace."""
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_gerber",
        _stub_export_single("gerbers", build_dir, "board-F_Cu.gbr"),
    )
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_drill",
        _stub_export_single("drill", build_dir, "board.drl"),
    )
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_position",
        _stub_export_single("cpl", build_dir, "board-pos.csv"),
    )
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_netlist",
        _stub_export_single("netlist", build_dir, "board.net"),
    )
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_step",
        _stub_export_single("step", build_dir, "board.step"),
    )
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_pcb_pdf",
        _stub_export_single("pcb_pdf", build_dir, "board.pdf"),
    )
    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_schematic_pdf",
        _stub_export_single("schematic_pdf", build_dir, "board_schematic.pdf"),
    )

    def _fake_bom_profile(sch_path, output_dir, profile=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        f = output_dir / "board-BOM.csv"
        f.write_text("dummy bom")
        return BomResult(True, f, 1, 1, "stub-bom", "")

    monkeypatch.setattr(
        "volta.manufacturing.handoff.export_bom_profile", _fake_bom_profile
    )


def _stub_board_stats(monkeypatch, stats=None) -> None:
    """Stub get_board_statistics so tests run without a parseable PCB."""
    if stats is None:
        stats = {
            "layer_count": 2,
            "board_width_mm": 50.0,
            "board_height_mm": 30.0,
            "component_count": 5,
            "net_count": 3,
        }
    monkeypatch.setattr(
        "volta.manufacturing.handoff.get_board_statistics",
        lambda pcb_path: stats,
    )


class TestExportHandoff:
    """Tests for the export_handoff orchestrator (Tasks 3 & 4)."""

    def test_handoff_creates_zip(self, tmp_path: Path, monkeypatch) -> None:
        """skip_validation=True + stubbed exports -> zip exists on disk."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )

        assert result.success is True
        assert result.zip_path != ""
        # The zip file exists on disk under builds/handoff_*/handoff.zip
        full_zip = tmp_path / result.zip_path
        assert full_zip.is_file()

    def test_handoff_blocks_on_drc_failure(self, tmp_path: Path, monkeypatch) -> None:
        """DRC fail (passed=False, error_message=None) -> no zip created (HANDOFF-06)."""
        from volta.manufacturing.handoff import export_handoff
        from volta.validation.erc_drc import DrcResult

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        # Stub run_drc on the handoff module's imported reference (lazy import).
        import volta.validation.erc_drc as erc_drc_mod

        def _fail_drc(pcb_path, **kwargs):
            return DrcResult(
                passed=False, file_path=pcb_path, error_message=None
            )

        monkeypatch.setattr(erc_drc_mod, "run_drc", _fail_drc)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
        )

        assert result.success is False
        assert "DRC" in result.error_message
        # No handoff.zip anywhere under the project dir.
        zips = list((tmp_path / "builds").glob("**/handoff.zip")) if (tmp_path / "builds").exists() else []
        assert zips == []

    def test_handoff_includes_all_artifacts(self, tmp_path: Path, monkeypatch) -> None:
        """Zip contains gerber, drill, bom, cpl, manifest.json, readme.md."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        sch_path = _create_minimal_sch(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=sch_path,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        full_zip = tmp_path / result.zip_path
        names = zipfile.ZipFile(full_zip).namelist()
        names_lower = " ".join(names).lower()
        assert "manifest.json" in names
        assert "readme.md" in names
        # gerber / drill / bom / cpl categories present (by filename fragments)
        assert "board-f_cu.gbr" in names_lower or ".gbr" in names_lower
        assert ".drl" in names_lower
        assert "bom" in names_lower
        assert "pos" in names_lower

    def test_handoff_step_excluded_when_flag_false(self, tmp_path: Path, monkeypatch) -> None:
        """include_step=False -> no .step file in the zip (HANDOFF-07)."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            include_step=False,
            skip_validation=True,
        )
        assert result.success
        names = zipfile.ZipFile(tmp_path / result.zip_path).namelist()
        assert not any(n.lower().endswith(".step") for n in names)

    def test_handoff_step_included_when_flag_true(self, tmp_path: Path, monkeypatch) -> None:
        """include_step=True (default) -> .step file present in the zip."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            include_step=True,
            skip_validation=True,
        )
        assert result.success
        names = zipfile.ZipFile(tmp_path / result.zip_path).namelist()
        assert any(n.lower().endswith(".step") for n in names)

    def test_handoff_no_partial_state_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        """After a validation failure, no builds/handoff_* dir remains."""
        from volta.manufacturing.handoff import export_handoff
        from volta.validation.erc_drc import DrcResult

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        import volta.validation.erc_drc as erc_drc_mod

        monkeypatch.setattr(
            erc_drc_mod,
            "run_drc",
            lambda pcb_path, **kw: DrcResult(passed=False, file_path=pcb_path, error_message=None),
        )

        result = export_handoff(pcb_path=pcb_path, sch_path=None, project_dir=tmp_path)
        assert result.success is False
        handoff_dirs = list((tmp_path / "builds").glob("handoff_*")) if (tmp_path / "builds").exists() else []
        assert handoff_dirs == []

    def test_handoff_arcname_no_path_separator(self, tmp_path: Path, monkeypatch) -> None:
        """Every name in the zip namelist has no / or \\ (TM-2)."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        names = zipfile.ZipFile(tmp_path / result.zip_path).namelist()
        for n in names:
            assert "/" not in n, f"arcname contains '/': {n}"
            assert "\\" not in n, f"arcname contains '\\': {n}"

    def test_target_file_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        """The .kicad_pcb bytes are identical before and after export_handoff."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        before = pcb_path.read_bytes()
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        after = pcb_path.read_bytes()
        assert before == after

    def test_handoff_drc_inconclusive_does_not_block(self, tmp_path: Path, monkeypatch) -> None:
        """kicad-cli absent (error_message set) -> None -> does NOT block (graceful degradation)."""
        from volta.manufacturing.handoff import export_handoff
        from volta.validation.erc_drc import DrcResult

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        import volta.validation.erc_drc as erc_drc_mod

        monkeypatch.setattr(
            erc_drc_mod,
            "run_drc",
            lambda pcb_path, **kw: DrcResult(
                passed=False, file_path=pcb_path, error_message="kicad-cli not found"
            ),
        )

        result = export_handoff(pcb_path=pcb_path, sch_path=None, project_dir=tmp_path)
        assert result.success is True
        assert result.validation.drc_passed is None

    def test_handoff_manifest_has_validation_proof(self, tmp_path: Path, monkeypatch) -> None:
        """Manifest records drc_passed/erc_passed/violation counts (HANDOFF-09)."""
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        m = result.manifest
        # skip_validation -> all None
        assert m.drc_passed is None
        assert m.erc_passed is None
        assert m.vendor_drc_passed is None

    def test_handoff_vendor_drc_blocks_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        """Vendor DRC fail (passed=False, no error_message) -> no zip."""
        from volta.manufacturing.handoff import export_handoff
        from volta.validation.erc_drc import DrcResult, ErcResult
        from volta.manufacturing.vendor_drc import VendorDrcResult

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        import volta.validation.erc_drc as erc_drc_mod
        import volta.manufacturing.vendor_drc as vdrc_mod

        monkeypatch.setattr(
            erc_drc_mod, "run_drc",
            lambda pcb_path, **kw: DrcResult(passed=True, file_path=pcb_path),
        )
        monkeypatch.setattr(
            vdrc_mod, "run_vendor_drc",
            lambda board, profile: VendorDrcResult(
                vendor="jlcpcb", passed=False, error_message=None
            ),
        )

        result = export_handoff(
            pcb_path=pcb_path, sch_path=None, project_dir=tmp_path, vendor="jlcpcb"
        )
        assert result.success is False
        assert "vendor DRC" in result.error_message


class TestReadmeGeneration:
    """Tests for _generate_readme (Task 4)."""

    def _make_title_block(self, title="My Board", rev="2.0", company="Acme"):
        from volta.parser.pcb_native_types import NativeTitleBlock

        return NativeTitleBlock(title=title, rev=rev, company=company)

    def test_readme_has_board_name(self, tmp_path: Path, monkeypatch) -> None:
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path, title="Unique Board Name")
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        full_zip = tmp_path / result.zip_path
        with zipfile.ZipFile(full_zip) as zf:
            readme = zf.read("readme.md").decode("utf-8")
        assert "Unique Board Name" in readme

    def test_readme_has_surface_finish(self, tmp_path: Path, monkeypatch) -> None:
        """When a BoardSpec sidecar exists with surface_finish=ENIG, readme contains ENIG."""
        from volta.manufacturing.handoff import export_handoff
        from volta.manufacturing.board_spec import (
            BoardSpec,
            SurfaceFinish,
            save_board_spec,
        )

        pcb_path = _create_pcb_with_title_block(tmp_path)
        spec = BoardSpec(surface_finish=SurfaceFinish.ENIG)
        save_board_spec(pcb_path, spec)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        with zipfile.ZipFile(tmp_path / result.zip_path) as zf:
            readme = zf.read("readme.md").decode("utf-8")
        assert "ENIG" in readme

    def test_readme_has_validation_results(self, tmp_path: Path, monkeypatch) -> None:
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(monkeypatch)

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        with zipfile.ZipFile(tmp_path / result.zip_path) as zf:
            readme = zf.read("readme.md").decode("utf-8")
        assert "DRC" in readme
        assert any(w in readme for w in ("passed", "failed", "inconclusive"))

    def test_readme_has_dimensions(self, tmp_path: Path, monkeypatch) -> None:
        from volta.manufacturing.handoff import export_handoff

        pcb_path = _create_pcb_with_title_block(tmp_path)
        _install_export_stubs(monkeypatch, tmp_path)
        _stub_board_stats(
            monkeypatch,
            {
                "layer_count": 4,
                "board_width_mm": 75.5,
                "board_height_mm": 42.25,
                "component_count": 12,
                "net_count": 7,
            },
        )

        result = export_handoff(
            pcb_path=pcb_path,
            sch_path=None,
            project_dir=tmp_path,
            skip_validation=True,
        )
        assert result.success
        with zipfile.ZipFile(tmp_path / result.zip_path) as zf:
            readme = zf.read("readme.md").decode("utf-8")
        assert "75.5" in readme
        assert "42.25" in readme

    def test_readme_handles_missing_board_spec(self, tmp_path: Path, monkeypatch) -> None:
        """No sidecar -> readme still generates with 'not specified' placeholders."""
        from volta.manufacturing.handoff import _generate_readme, HandoffValidation

        readme = _generate_readme(
            title_block=self._make_title_block(),
            board_spec=None,
            board_stats={"layer_count": 2, "board_width_mm": 50.0, "board_height_mm": 30.0},
            validation=HandoffValidation(None, None, None, 0, 0, 0),
            vendor=None,
            generated_at="2026-07-10T00:00:00+00:00",
            board_name="test",
        )
        assert "not specified" in readme
        assert "My Board" in readme
