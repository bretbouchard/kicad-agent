"""Tests for crossfile module: atomic operations, diff, propagation, project context."""

import tempfile
from pathlib import Path

import pytest

from kicad_agent.crossfile import (
    AtomicOperation,
    AtomicResult,
    DiffEntry,
    DiffResult,
    DiffType,
    ProjectContext,
    detect_project_root,
    discover_project,
    propagate_footprint_ref,
    propagate_symbol_ref,
    structural_diff,
)
from kicad_agent.crossfile.atomic import AtomicOperation as AtomicOp


class TestAtomicOperation:
    """Tests for AtomicOperation multi-file transaction coordinator."""

    def test_empty_paths_raises_value_error(self):
        """AtomicOperation with empty file_paths raises ValueError."""
        with pytest.raises(ValueError, match="at least one"):
            AtomicOp([])

    def test_symlink_rejected(self):
        """AtomicOperation rejects symlinks."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            real_file = tmp_path / "real.kicad_sch"
            real_file.write_text("(kicad_sch)")
            symlink = tmp_path / "link.kicad_sch"
            symlink.symlink_to(real_file)

            with pytest.raises(ValueError, match="symlink"):
                AtomicOp([symlink])

    def test_nonexistent_file_raises(self):
        """AtomicOperation raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="file not found"):
            AtomicOp([Path("/nonexistent/file.kicad_sch")])

    def test_atomic_result_frozen(self):
        """AtomicResult is frozen (immutable)."""
        result = AtomicResult(success=True, results=[])
        with pytest.raises(AttributeError):
            result.success = False


class TestDiff:
    """Tests for structural diff types."""

    def test_diff_entry_creation(self):
        """DiffEntry can be created with all fields."""
        entry = DiffEntry(
            diff_type=DiffType.ADDED,
            element_type="symbol",
            identifier="uuid-abc",
            old_value=None,
            new_value="(footprint ...)",
            path_in_file="/symbol/uuid-abc",
        )
        assert entry.diff_type == DiffType.ADDED
        assert entry.element_type == "symbol"

    def test_diff_result_creation(self):
        """DiffResult can be created."""
        result = DiffResult(
            entries=[],
            file_a_path=Path("before.kicad_sch"),
            file_b_path=Path("after.kicad_sch"),
            difftastic_available=False,
            difftastic_output=None,
        )
        assert result.entries == []
        assert result.difftastic_available is False

    def test_diff_type_enum(self):
        """DiffType enum has all expected values."""
        assert hasattr(DiffType, "ADDED")
        assert hasattr(DiffType, "REMOVED")
        assert hasattr(DiffType, "MODIFIED")


class TestPropagation:
    """Tests for library reference propagation functions."""

    def test_propagate_footprint_ref_import(self):
        """propagate_footprint_ref is importable."""
        assert callable(propagate_footprint_ref)

    def test_propagate_symbol_ref_import(self):
        """propagate_symbol_ref is importable."""
        assert callable(propagate_symbol_ref)


class TestProjectContext:
    """Tests for project context detection."""

    def test_detect_project_root_nonexistent(self):
        """detect_project_root raises FileNotFoundError for nonexistent paths."""
        with pytest.raises(FileNotFoundError):
            detect_project_root(Path("/nonexistent/path"))

    def test_discover_project_nonexistent(self):
        """discover_project raises ValueError for nonexistent paths."""
        with pytest.raises(ValueError):
            discover_project(Path("/nonexistent/path"))

    def test_detect_project_root_tempdir(self):
        """detect_project_root raises FileNotFoundError for plain temp dir (no kicad_pro)."""
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(FileNotFoundError):
                detect_project_root(Path(tmp))


class TestCrossfileImports:
    """Verify all crossfile module exports are importable."""

    def test_all_exports_importable(self):
        """All __all__ exports can be imported from crossfile."""
        from kicad_agent import crossfile
        for name in crossfile.__all__:
            assert hasattr(crossfile, name), f"Missing export: {name}"
