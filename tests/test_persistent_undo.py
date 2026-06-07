"""Tests for PersistentUndoStack — file-based undo persistence.

Issue #7: Verify that undo entries survive process restarts, crash recovery
works, manifest corruption is handled, and concurrent access is safe.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from kicad_agent.ops.persistent_undo import PersistentUndoStack
from kicad_agent.ops.undo_stack import UndoStack


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory."""
    return tmp_path / "test_project"


@pytest.fixture
def stack(project_dir):
    """Create a PersistentUndoStack with a clean project directory."""
    project_dir.mkdir(parents=True, exist_ok=True)
    return PersistentUndoStack(project_dir=project_dir, max_size=10)


class TestPersistentUndoStack:

    def test_push_pop_survives_restart(self, project_dir):
        """Push entry in one stack instance, pop from a new one."""
        stack1 = PersistentUndoStack(project_dir=project_dir, max_size=10)
        stack1.push(
            Path("test.kicad_sch"),
            "pre content",
            "post content",
            "add_component",
        )

        # New instance loading from disk
        stack2 = PersistentUndoStack(project_dir=project_dir, max_size=10)
        entry = stack2.pop_undo(Path("test.kicad_sch"))

        assert entry is not None
        assert entry.pre_content == "pre content"
        assert entry.post_content == "post content"
        assert entry.op_type == "add_component"

    def test_multiple_entries_lifo_order(self, stack, project_dir):
        """Push 3 entries, verify LIFO order across restart."""
        stack.push(Path("test.kicad_sch"), "pre1", "post1", "op1")
        stack.push(Path("test.kicad_sch"), "pre2", "post2", "op2")
        stack.push(Path("test.kicad_sch"), "pre3", "post3", "op3")

        # Restart
        stack2 = PersistentUndoStack(project_dir=project_dir, max_size=10)

        entry = stack2.pop_undo(Path("test.kicad_sch"))
        assert entry.op_type == "op3"

        entry = stack2.pop_undo(Path("test.kicad_sch"))
        assert entry.op_type == "op2"

        entry = stack2.pop_undo(Path("test.kicad_sch"))
        assert entry.op_type == "op1"

    def test_multi_file_isolation(self, stack, project_dir):
        """Each file has its own undo stack."""
        stack.push(Path("a.kicad_sch"), "pre_a", "post_a", "op_a")
        stack.push(Path("b.kicad_sch"), "pre_b", "post_b", "op_b")

        stack2 = PersistentUndoStack(project_dir=project_dir, max_size=10)

        entry_a = stack2.pop_undo(Path("a.kicad_sch"))
        assert entry_a.op_type == "op_a"

        entry_b = stack2.pop_undo(Path("b.kicad_sch"))
        assert entry_b.op_type == "op_b"

    def test_max_size_prunes_old_entries(self, project_dir):
        """Push more entries than max_size, verify oldest are discarded."""
        stack = PersistentUndoStack(project_dir=project_dir, max_size=3)

        for i in range(5):
            stack.push(Path("test.kicad_sch"), f"pre{i}", f"post{i}", f"op{i}")

        stack2 = PersistentUndoStack(project_dir=project_dir, max_size=3)

        # Should only have last 3 entries
        entries = []
        for _ in range(5):
            entry = stack2.pop_undo(Path("test.kicad_sch"))
            if entry:
                entries.append(entry)

        assert len(entries) == 3
        assert entries[0].op_type == "op4"
        assert entries[1].op_type == "op3"
        assert entries[2].op_type == "op2"

    def test_manifest_corruption_handled_gracefully(self, project_dir):
        """Garbage in manifest.json doesn't crash init."""
        project_dir.mkdir(parents=True, exist_ok=True)
        undo_dir = project_dir / ".kicad-agent" / "undo"
        undo_dir.mkdir(parents=True, exist_ok=True)
        (undo_dir / "manifest.json").write_text("NOT VALID JSON{{{")

        # Should not raise
        stack = PersistentUndoStack(project_dir=project_dir, max_size=10)
        assert stack.pop_undo(Path("test.kicad_sch")) is None

    def test_missing_entry_file_handled(self, project_dir):
        """Entry in manifest but file deleted → skip gracefully."""
        project_dir.mkdir(parents=True, exist_ok=True)
        undo_dir = project_dir / ".kicad-agent" / "undo"
        undo_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest referencing a non-existent file
        manifest = {
            "entries": [{
                "file_path": "/tmp/test.kicad_sch",
                "entry_file": "000001_nonexistent.json",
                "op_type": "add_component",
            }]
        }
        (undo_dir / "manifest.json").write_text(json.dumps(manifest))

        stack = PersistentUndoStack(project_dir=project_dir, max_size=10)
        assert stack.pop_undo(Path("/tmp/test.kicad_sch")) is None

    def test_atomic_write_valid_json(self, stack):
        """Each entry file is valid JSON."""
        stack.push(Path("test.kicad_sch"), "pre", "post", "op")

        undo_dir = stack._undo_dir
        json_files = [f for f in undo_dir.glob("*.json") if f.name != "manifest.json"]
        assert len(json_files) == 1

        data = json.loads(json_files[0].read_text())
        assert data["pre_content"] == "pre"
        assert data["post_content"] == "post"
        assert data["op_type"] == "op"

    def test_prune_old_entries(self, stack):
        """prune_old_entries removes orphaned files."""
        undo_dir = stack._undo_dir

        # Push a real entry so the manifest is created
        stack.push(Path("test.kicad_sch"), "pre", "post", "op")

        # Create an orphaned file (not referenced in manifest)
        orphan = undo_dir / "orphan_000.json"
        orphan.write_text('{"orphan": true}')

        pruned = stack.prune_old_entries()
        assert pruned == 1
        assert not orphan.exists()

    def test_clear_removes_all_files(self, stack):
        """clear() removes all entry files; manifest persists with empty state."""
        stack.push(Path("a.kicad_sch"), "pre", "post", "op")
        stack.push(Path("b.kicad_sch"), "pre", "post", "op")

        stack.clear()

        undo_dir = stack._undo_dir
        json_files = [f for f in undo_dir.glob("*.json") if f.name != "manifest.json"]
        assert len(json_files) == 0, "All entry files should be removed"
        # Manifest should exist with empty entries (O-BUG-005 fix)
        manifest = undo_dir / "manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert len(data["entries"]) == 0

    def test_path_traversal_rejected(self, stack):
        """Entries with .. in filename are rejected."""
        assert stack._validate_entry_path("../etc/passwd") is None
        assert stack._validate_entry_path("foo/bar.json") is None
        assert stack._validate_entry_path("foo\\bar.json") is None

    def test_concurrent_push(self, project_dir):
        """Concurrent pushes don't corrupt the stack."""
        stack = PersistentUndoStack(project_dir=project_dir, max_size=100)
        errors = []

        def push_entries(start):
            try:
                for i in range(20):
                    stack.push(
                        Path("test.kicad_sch"),
                        f"pre_{start}_{i}",
                        f"post_{start}_{i}",
                        f"op_{start}_{i}",
                    )
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=push_entries, args=(0,))
        t2 = threading.Thread(target=push_entries, args=(20,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors

        # Verify all 40 entries are present
        count = 0
        while stack.pop_undo(Path("test.kicad_sch")) is not None:
            count += 1
        assert count == 40

    def test_redo_not_persisted(self, stack, project_dir):
        """Redo stack is NOT persisted (session-scoped)."""
        stack.push(Path("test.kicad_sch"), "pre", "post", "op")
        stack.pop_undo(Path("test.kicad_sch"))  # Moves to redo

        # Restart
        stack2 = PersistentUndoStack(project_dir=project_dir, max_size=10)
        assert stack2.pop_redo(Path("test.kicad_sch")) is None

    def test_post_mtime_preserved(self, stack, project_dir):
        """post_mtime survives restart."""
        stack.push(
            Path("test.kicad_sch"), "pre", "post", "op",
            post_mtime=1234567890,
        )

        stack2 = PersistentUndoStack(project_dir=project_dir, max_size=10)
        entry = stack2.pop_undo(Path("test.kicad_sch"))
        assert entry is not None
        assert entry.post_mtime == 1234567890

    def test_empty_project_dir(self, tmp_path):
        """Stack creates .kicad-agent/undo/ automatically."""
        empty_dir = tmp_path / "new_project"
        # Don't create the directory — let PersistentUndoStack handle it
        stack = PersistentUndoStack(project_dir=empty_dir, max_size=5)
        assert (empty_dir / ".kicad-agent" / "undo").is_dir()

    def test_fallback_to_in_memory(self):
        """UndoStack works as standalone in-memory fallback."""
        stack = UndoStack(max_size=5)
        stack.push(Path("test.kicad_sch"), "pre", "post", "op")

        entry = stack.pop_undo(Path("test.kicad_sch"))
        assert entry is not None
        assert entry.pre_content == "pre"
