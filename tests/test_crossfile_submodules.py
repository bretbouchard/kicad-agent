"""Tests for crossfile sub-modules: diff, propagation, project_context."""

from pathlib import Path
import tempfile

import pytest


class TestDiffModule:
    """Tests for structural diff module."""

    def test_import(self):
        """structural_diff is importable and callable."""
        from kicad_agent.crossfile.diff import structural_diff
        assert callable(structural_diff)

    def test_diff_type_values(self):
        """DiffType enum has all expected values."""
        from kicad_agent.crossfile.diff import DiffType
        assert DiffType.ADDED.value == "added"
        assert DiffType.REMOVED.value == "removed"
        assert DiffType.MODIFIED.value == "modified"
        assert DiffType.MOVED.value == "moved"


class TestPropagationModule:
    """Tests for library reference propagation."""

    def test_import(self):
        """Propagation module is importable."""
        from kicad_agent.crossfile.propagation import (
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
        from kicad_agent.crossfile.project_context import (
            ProjectContext,
            detect_project_root,
            discover_project,
        )
        assert ProjectContext is not None
        assert callable(detect_project_root)
        assert callable(discover_project)

    def test_discover_real_project(self):
        """discover_project works on a real KiCad project directory."""
        from kicad_agent.crossfile.project_context import discover_project
        with tempfile.TemporaryDirectory() as tmp:
            # Create minimal project structure
            pro_file = Path(tmp) / "test.kicad_pro"
            pro_file.write_text(
                '{\n  "version": "8",\n  "generator": "kicad-agent"\n}\n'
            )
            ctx = discover_project(Path(tmp))
            assert ctx is not None
