"""Test suite for project context renderer.

Tests discover_kicad_files, enrich_summary, render_project_context,
and the ProjectSummary dataclass.

TDD RED phase: these tests define the expected behavior of context.py.
"""

import tempfile
from pathlib import Path

import pytest

from volta.context import (
    ProjectSummary,
    discover_kicad_files,
    enrich_summary,
    render_project_context,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestDiscoverKiCadFiles:
    """Tests for discover_kicad_files()."""

    def test_empty_directory_returns_empty_summary(self, tmp_path: Path):
        """Test 1: Empty directory returns summary with zero counts and no files."""
        summary = discover_kicad_files(tmp_path)
        assert summary.schematic_files == ()
        assert summary.pcb_files == ()
        assert summary.symbol_lib_files == ()
        assert summary.footprint_files == ()
        assert summary.component_count == 0
        assert summary.net_count == 0
        assert summary.footprint_count == 0

    def test_nonexistent_directory_raises_file_not_found(self):
        """Test 2: Nonexistent directory raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            discover_kicad_files(Path("/nonexistent/path/that/does/not/exist"))

    def test_finds_kicad_sch_files(self, tmp_path: Path):
        """Test 3: Discovers .kicad_sch files in a directory."""
        (tmp_path / "test.kicad_sch").touch()
        summary = discover_kicad_files(tmp_path)
        assert len(summary.schematic_files) == 1
        assert summary.schematic_files[0] == "test.kicad_sch"

    def test_finds_kicad_pcb_files(self, tmp_path: Path):
        """Test 4: Discovers .kicad_pcb files in a directory."""
        (tmp_path / "board.kicad_pcb").touch()
        summary = discover_kicad_files(tmp_path)
        assert len(summary.pcb_files) == 1
        assert summary.pcb_files[0] == "board.kicad_pcb"

    def test_finds_multiple_file_types(self, tmp_path: Path):
        """Test 5: Discovers multiple KiCad file types."""
        (tmp_path / "test.kicad_sch").touch()
        (tmp_path / "board.kicad_pcb").touch()
        (tmp_path / "symbols.kicad_sym").touch()
        (tmp_path / "footprint.kicad_mod").touch()
        summary = discover_kicad_files(tmp_path)
        assert len(summary.schematic_files) == 1
        assert len(summary.pcb_files) == 1
        assert len(summary.symbol_lib_files) == 1
        assert len(summary.footprint_files) == 1

    def test_discovers_files_recursively(self, tmp_path: Path):
        """Test 5b: Discovers files in subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.kicad_sch").touch()
        (tmp_path / "top.kicad_pcb").touch()
        summary = discover_kicad_files(tmp_path)
        assert len(summary.schematic_files) == 1
        assert str(summary.schematic_files[0]).endswith("nested.kicad_sch")
        assert len(summary.pcb_files) == 1

    def test_files_sorted_alphabetically(self, tmp_path: Path):
        """Test 5c: File lists are sorted."""
        (tmp_path / "zebra.kicad_sch").touch()
        (tmp_path / "alpha.kicad_sch").touch()
        (tmp_path / "middle.kicad_sch").touch()
        summary = discover_kicad_files(tmp_path)
        assert summary.schematic_files == ("alpha.kicad_sch", "middle.kicad_sch", "zebra.kicad_sch")

    def test_ignores_non_kicad_files(self, tmp_path: Path):
        """Test 5d: Non-KiCad files are ignored."""
        (tmp_path / "readme.txt").touch()
        (tmp_path / "main.py").touch()
        (tmp_path / "data.json").touch()
        summary = discover_kicad_files(tmp_path)
        assert not summary.has_kicad_files

    def test_path_not_directory_raises_error(self, tmp_path: Path):
        """Test 5e: File path (not directory) raises FileNotFoundError."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.touch()
        with pytest.raises(FileNotFoundError):
            discover_kicad_files(file_path)


class TestRenderProjectContext:
    """Tests for render_project_context()."""

    def test_empty_dir_shows_no_files_found(self, tmp_path: Path):
        """Test 6: Empty directory returns 'No KiCad files found'."""
        result = render_project_context(tmp_path)
        assert "No KiCad files found" in result

    def test_includes_file_list_when_files_found(self, tmp_path: Path):
        """Test 7: File names appear in rendered output."""
        (tmp_path / "test.kicad_sch").touch()
        (tmp_path / "board.kicad_pcb").touch()
        result = render_project_context(tmp_path, enrich=False)
        assert "test.kicad_sch" in result
        assert "board.kicad_pcb" in result
        assert "Schematics:" in result
        assert "PCBs:" in result

    def test_includes_project_dir_name(self, tmp_path: Path):
        """Test 7b: Output includes the project directory name."""
        result = render_project_context(tmp_path)
        assert tmp_path.name in result

    def test_includes_total_file_count(self, tmp_path: Path):
        """Test 7c: Output includes total file count."""
        (tmp_path / "a.kicad_sch").touch()
        (tmp_path / "b.kicad_pcb").touch()
        result = render_project_context(tmp_path, enrich=False)
        assert "Files: 2 total" in result

    def test_hides_empty_sections(self, tmp_path: Path):
        """Test 7d: Sections with no files are not shown."""
        (tmp_path / "test.kicad_sch").touch()
        result = render_project_context(tmp_path, enrich=False)
        assert "Schematics:" in result
        assert "Symbol Libraries:" not in result
        assert "Footprint Libraries:" not in result


class TestProjectSummary:
    """Tests for ProjectSummary dataclass."""

    def test_has_kicad_files_false_when_empty(self):
        """Test 8: has_kicad_files returns False when no files."""
        summary = ProjectSummary(
            project_dir=Path("/tmp"),
            schematic_files=(),
            pcb_files=(),
            symbol_lib_files=(),
            footprint_files=(),
        )
        assert summary.has_kicad_files is False

    def test_has_kicad_files_true_when_files_exist(self):
        """Test 9: has_kicad_files returns True when files exist."""
        summary = ProjectSummary(
            project_dir=Path("/tmp"),
            schematic_files=("test.kicad_sch",),
            pcb_files=(),
            symbol_lib_files=(),
            footprint_files=(),
        )
        assert summary.has_kicad_files is True

    def test_total_files_returns_correct_count(self):
        """Test 10: total_files returns sum of all file lists."""
        summary = ProjectSummary(
            project_dir=Path("/tmp"),
            schematic_files=("a.kicad_sch", "b.kicad_sch"),
            pcb_files=("c.kicad_pcb",),
            symbol_lib_files=("d.kicad_sym",),
            footprint_files=(),
        )
        assert summary.total_files == 4

    def test_total_files_zero_when_empty(self):
        """Test 10b: total_files returns 0 when no files."""
        summary = ProjectSummary(
            project_dir=Path("/tmp"),
            schematic_files=(),
            pcb_files=(),
            symbol_lib_files=(),
            footprint_files=(),
        )
        assert summary.total_files == 0

    def test_frozen_dataclass_immutable(self):
        """Test 10c: ProjectSummary is frozen (immutable)."""
        summary = ProjectSummary(
            project_dir=Path("/tmp"),
            schematic_files=(),
            pcb_files=(),
            symbol_lib_files=(),
            footprint_files=(),
        )
        with pytest.raises(AttributeError):
            summary.component_count = 42  # type: ignore[misc]


class TestEnrichSummary:
    """Tests for enrich_summary()."""

    def test_enrich_with_schematic_counts_components(self, tmp_path: Path):
        """Test 11: Enrichment counts components from schematics."""
        fixture_sch = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        if not fixture_sch.exists():
            pytest.skip("RaspberryPi-uHAT fixture not available")

        # Copy the fixture to temp dir
        import shutil
        dest = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(fixture_sch, dest)

        summary = discover_kicad_files(tmp_path)
        enriched = enrich_summary(summary)
        assert enriched.component_count > 0

    def test_enrich_with_pcb_counts_nets_and_footprints(self, tmp_path: Path):
        """Test 11b: Enrichment counts nets and footprints from PCBs."""
        fixture_pcb = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"
        if not fixture_pcb.exists():
            pytest.skip("RaspberryPi-uHAT PCB fixture not available")

        import shutil
        dest = tmp_path / "RaspberryPi-uHAT.kicad_pcb"
        shutil.copy2(fixture_pcb, dest)

        summary = discover_kicad_files(tmp_path)
        enriched = enrich_summary(summary)
        assert enriched.footprint_count > 0
        assert enriched.net_count > 0

    def test_enrich_with_unparseable_file_no_crash(self, tmp_path: Path):
        """Test 12: Unparseable files are handled gracefully (no crash)."""
        bad_file = tmp_path / "bad.kicad_sch"
        bad_file.write_text("not valid kicad content at all")
        summary = discover_kicad_files(tmp_path)
        # Should not raise -- just skip with a warning
        enriched = enrich_summary(summary)
        assert enriched.component_count == 0

    def test_render_with_enrichment_includes_counts(self, tmp_path: Path):
        """Test 11c: render_project_context includes counts after enrichment."""
        fixture_sch = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        if not fixture_sch.exists():
            pytest.skip("RaspberryPi-uHAT fixture not available")

        import shutil
        dest = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(fixture_sch, dest)

        result = render_project_context(tmp_path, enrich=True)
        assert "Components:" in result
