"""Tests for CLI undo/redo commands and .gitignore integration.

Issue #7: Verify volta undo/redo CLI commands work end-to-end
and .volta/ is auto-added to .gitignore.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from volta.cli import main
from volta.ops.persistent_undo import PersistentUndoStack


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory with a schematic file."""
    p = tmp_path / "project"
    p.mkdir()
    sch = p / "test.kicad_sch"
    sch.write_text("(kicad_sch (version 20250114) (generator \"test\"))\n")
    return p


class TestCliUndo:

    def test_undo_no_history_exits_1(self, project_dir):
        """Undo with no history exits with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            main(["undo", "-p", str(project_dir)])
        assert exc_info.value.code == 1

    def test_undo_with_history_reverts_file(self, project_dir):
        """Push an entry via PersistentUndoStack, then undo via CLI."""
        stack = PersistentUndoStack(project_dir=project_dir)
        sch = project_dir / "test.kicad_sch"
        original = sch.read_text()
        modified = original + "  (wire ...)\n"
        sch.write_text(modified)
        stack.push(sch, original, modified, "add_wire")

        # CLI undo should revert the file
        main(["undo", "-p", str(project_dir)])
        assert sch.read_text() == original

    def test_redo_after_undo_restores_file(self, project_dir):
        """Undo then redo restores the modified content via single stack."""
        stack = PersistentUndoStack(project_dir=project_dir)
        sch = project_dir / "test.kicad_sch"
        original = sch.read_text()
        modified = original + "  (wire ...)\n"
        sch.write_text(modified)
        stack.push(sch, original, modified, "add_wire")

        # Undo via executor (same stack instance)
        from volta.ops.executor import OperationExecutor
        executor = OperationExecutor(base_dir=project_dir, undo_stack=stack)
        undo_result = executor.undo(target_file="test.kicad_sch")
        assert undo_result["success"]
        assert sch.read_text() == original

        # Redo via same executor
        redo_result = executor.redo(target_file="test.kicad_sch")
        assert redo_result["success"]
        assert sch.read_text() == modified

    def test_undo_specific_file(self, project_dir):
        """Undo targets a specific file when given."""
        stack = PersistentUndoStack(project_dir=project_dir)

        sch_a = project_dir / "a.kicad_sch"
        sch_b = project_dir / "b.kicad_sch"
        sch_a.write_text("content_a_old")
        sch_b.write_text("content_b_old")

        stack.push(sch_a, "content_a_old", "content_a_new", "op_a")
        stack.push(sch_b, "content_b_old", "content_b_new", "op_b")

        # Undo only file b
        main(["undo", "b.kicad_sch", "-p", str(project_dir)])


class TestGitignore:

    def test_gitignore_created(self, tmp_path):
        """PersistentUndoStack creates .gitignore with .volta/."""
        project_dir = tmp_path / "new_project"
        project_dir.mkdir()

        PersistentUndoStack(project_dir=project_dir, max_size=5)

        gitignore = project_dir / ".gitignore"
        assert gitignore.exists()
        assert ".volta/" in gitignore.read_text()

    def test_gitignore_no_duplicate(self, tmp_path):
        """Second init doesn't duplicate the entry."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        PersistentUndoStack(project_dir=project_dir, max_size=5)
        PersistentUndoStack(project_dir=project_dir, max_size=5)

        gitignore = project_dir / ".gitignore"
        content = gitignore.read_text()
        assert content.count(".volta/") == 1

    def test_gitignore_appends_to_existing(self, tmp_path):
        """Appends to existing .gitignore without clobbering."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        gitignore = project_dir / ".gitignore"
        gitignore.write_text("*.bak\nbuild/\n")

        PersistentUndoStack(project_dir=project_dir, max_size=5)

        content = gitignore.read_text()
        assert "*.bak" in content
        assert "build/" in content
        assert ".volta/" in content

    def test_subprocess_undo_no_history(self, project_dir):
        """Undo via subprocess exits 1 when no history exists."""
        import os
        env = dict(os.environ)
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "volta.cli", "undo", "-p", str(project_dir)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 1
        assert "Cannot undo" in result.stderr
