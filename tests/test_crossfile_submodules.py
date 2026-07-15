"""Tests for crossfile sub-modules: diff, propagation, project_context."""

from pathlib import Path
import tempfile

import pytest


class TestDiffModule:
    """Tests for structural diff module."""

    def test_import(self):
        """structural_diff is importable and callable."""
        from volta.crossfile.diff import structural_diff
        assert callable(structural_diff)

    def test_diff_type_values(self):
        """DiffType enum has all expected values."""
        from volta.crossfile.diff import DiffType
        assert DiffType.ADDED.value == "added"
        assert DiffType.REMOVED.value == "removed"
        assert DiffType.MODIFIED.value == "modified"
        assert DiffType.MOVED.value == "moved"


class TestPropagationModule:
    """Tests for library reference propagation."""

    def test_import(self):
        """Propagation module is importable."""
        from volta.crossfile.propagation import (
            PropagationResult,
            propagate_footprint_ref,
            propagate_symbol_ref,
        )
        assert PropagationResult is not None
        assert callable(propagate_footprint_ref)
        assert callable(propagate_symbol_ref)


class TestProjectContextModule:
    """Tests for project context detection."""

    def test_import(self):
        """Project context types are importable."""
        from volta.crossfile.project_context import (
            ProjectContext,
            detect_project_root,
            discover_project,
        )
        assert ProjectContext is not None
        assert callable(detect_project_root)
        assert callable(discover_project)

    def test_discover_real_project(self):
        """discover_project works on a real KiCad project directory."""
        from volta.crossfile.project_context import discover_project
        with tempfile.TemporaryDirectory() as tmp:
            # Create minimal project structure
            pro_file = Path(tmp) / "test.kicad_pro"
            pro_file.write_text(
                '{\n  "version": "8",\n  "generator": "kicad-agent"\n}\n'
            )
            ctx = discover_project(Path(tmp))
            assert ctx is not None

    def test_discover_project_finds_build_spec_and_builds_dir(self):
        """discover_project populates build_spec_files + builds_dir (INTEG-03/04)."""
        from volta.crossfile.project_context import discover_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test.kicad_pro").write_text(
                '{\n  "version": "8",\n  "generator": "kicad-agent"\n}\n'
            )
            (root / "test.kicad_pcb").write_text("(kicad_pcb)")
            # Project-scoped builds/ directory (INTEG-04)
            builds_dir = root / "builds"
            builds_dir.mkdir()
            # .kicad_build_spec.json sidecar next to the .kicad_pcb (INTEG-03)
            (root / "test.kicad_build_spec.json").write_text("{}")
            ctx = discover_project(root)
            # discover_project resolves() the root, so compare resolved paths.
            assert ctx.builds_dir == builds_dir.resolve()
            assert len(ctx.build_spec_files) == 1
            assert ctx.build_spec_files[0].name == "test.kicad_build_spec.json"

    def test_discover_project_no_builds_is_backward_compat(self):
        """A project with no builds/ + no sidecar defaults cleanly (INTEG-03/04)."""
        from volta.crossfile.project_context import discover_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test.kicad_pro").write_text(
                '{\n  "version": "8",\n  "generator": "kicad-agent"\n}\n'
            )
            ctx = discover_project(root)
            assert ctx.build_spec_files == []
            assert ctx.builds_dir is None
