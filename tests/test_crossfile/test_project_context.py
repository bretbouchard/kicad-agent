"""Tests for project context detection and auto-discovery.

XFILE-04: Detect KiCad project root, find library paths, discover all project files.
"""

import dataclasses
from pathlib import Path

import pytest

from volta.crossfile.project_context import (
    ProjectContext,
    detect_project_root,
    discover_project,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
ARDUINO_MEGA = FIXTURE_DIR / "Arduino_Mega"


class TestDetectProjectRoot:
    """Tests for detect_project_root function."""

    def test_finds_root_from_schematic_file(self) -> None:
        """Given a .kicad_sch path, find the project root directory."""
        sch_path = ARDUINO_MEGA / "Arduino_Mega.kicad_sch"
        root = detect_project_root(sch_path)
        assert root == ARDUINO_MEGA

    def test_finds_root_from_pcb_file(self) -> None:
        """Given a .kicad_pcb path, find the project root directory."""
        pcb_path = ARDUINO_MEGA / "Arduino_Mega.kicad_pcb"
        root = detect_project_root(pcb_path)
        assert root == ARDUINO_MEGA

    def test_finds_root_from_project_directory(self) -> None:
        """Given the project directory itself, find it as root."""
        root = detect_project_root(ARDUINO_MEGA)
        assert root == ARDUINO_MEGA

    def test_finds_root_from_nested_footprint(self) -> None:
        """Given a nested .kicad_mod in a .pretty dir, find the project root."""
        mod_path = (
            ARDUINO_MEGA
            / "Arduino_MountingHole.pretty"
            / "MountingHole_3.2mm.kicad_mod"
        )
        root = detect_project_root(mod_path)
        assert root == ARDUINO_MEGA

    def test_raises_for_path_outside_project(self, tmp_path: Path) -> None:
        """Paths with no .kicad_pro ancestor raise FileNotFoundError."""
        orphan = tmp_path / "orphan.kicad_sch"
        orphan.touch()
        with pytest.raises(FileNotFoundError, match="No .kicad_pro found"):
            detect_project_root(orphan)

    def test_resolves_symlinks(self, tmp_path: Path) -> None:
        """Symlinked paths resolve to the real project root."""
        link_dir = tmp_path / "link_to_project"
        link_dir.symlink_to(ARDUINO_MEGA)
        sch_via_link = link_dir / "Arduino_Mega.kicad_sch"
        root = detect_project_root(sch_via_link)
        assert root.resolve() == ARDUINO_MEGA.resolve()


class TestDiscoverProject:
    """Tests for discover_project function."""

    def test_discovers_all_kicad_files(self) -> None:
        """discover_project finds all KiCad file types in Arduino_Mega."""
        ctx = discover_project(ARDUINO_MEGA)
        assert isinstance(ctx, ProjectContext)

        # Schematic files
        assert len(ctx.schematic_files) >= 1
        sch_names = [f.name for f in ctx.schematic_files]
        assert "Arduino_Mega.kicad_sch" in sch_names

        # PCB files
        assert len(ctx.pcb_files) >= 1
        pcb_names = [f.name for f in ctx.pcb_files]
        assert "Arduino_Mega.kicad_pcb" in pcb_names

        # Footprint files
        assert len(ctx.footprint_files) >= 1
        mod_names = [f.name for f in ctx.footprint_files]
        assert "MountingHole_3.2mm.kicad_mod" in mod_names

    def test_finds_pro_file(self) -> None:
        """discover_project finds the .kicad_pro file."""
        ctx = discover_project(ARDUINO_MEGA)
        assert ctx.pro_file is not None
        assert ctx.pro_file.name == "Arduino_Mega.kicad_pro"

    def test_parses_library_paths(self) -> None:
        """discover_project extracts lib_dir from .kicad_pro."""
        ctx = discover_project(ARDUINO_MEGA)
        assert "lib" in ctx.library_paths

    def test_project_root_is_set(self) -> None:
        """ProjectContext.project_root matches the input directory."""
        ctx = discover_project(ARDUINO_MEGA)
        assert ctx.project_root == ARDUINO_MEGA

    def test_raises_for_non_directory(self, tmp_path: Path) -> None:
        """discover_project raises ValueError for non-directory input."""
        file_path = tmp_path / "not_a_dir.kicad_sch"
        file_path.touch()
        with pytest.raises(ValueError, match="not a directory"):
            discover_project(file_path)

    def test_empty_directory_returns_empty_lists(self, tmp_path: Path) -> None:
        """discover_project on empty dir returns empty lists and no pro_file."""
        ctx = discover_project(tmp_path)
        assert ctx.schematic_files == []
        assert ctx.pcb_files == []
        assert ctx.sym_lib_files == []
        assert ctx.footprint_files == []
        assert ctx.pro_file is None
        assert ctx.library_paths == []

    def test_file_lists_are_sorted(self) -> None:
        """File lists are sorted by path for deterministic output."""
        ctx = discover_project(ARDUINO_MEGA)
        assert ctx.schematic_files == sorted(ctx.schematic_files)
        assert ctx.pcb_files == sorted(ctx.pcb_files)
        assert ctx.footprint_files == sorted(ctx.footprint_files)

    def test_sym_lib_files_empty_when_none_present(self) -> None:
        """sym_lib_files is empty when no .kicad_sym files exist."""
        ctx = discover_project(ARDUINO_MEGA)
        assert ctx.sym_lib_files == []


class TestProjectContextImmutable:
    """Tests for ProjectContext frozen dataclass immutability."""

    def test_cannot_set_attribute(self) -> None:
        """ProjectContext is frozen -- setting attributes raises."""
        ctx = discover_project(ARDUINO_MEGA)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.project_root = Path("/some/other/path")  # type: ignore[misc]

    def test_cannot_set_list_attribute(self) -> None:
        """ProjectContext list fields cannot be reassigned."""
        ctx = discover_project(ARDUINO_MEGA)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.schematic_files = []  # type: ignore[misc]
