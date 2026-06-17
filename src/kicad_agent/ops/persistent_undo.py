"""Persistent undo stack that survives process restarts.

Issue #7: The in-memory UndoStack is lost between process invocations.
This module provides a file-based persistence layer that stores undo entries
in ``.kicad-agent/undo/`` within the project directory.

Storage format: One JSON file per entry, named by timestamp and sequence number.
Atomic writes via temp-file-and-rename. Thread-safe via the parent class lock.

Usage:
    from kicad_agent.ops.persistent_undo import PersistentUndoStack

    stack = PersistentUndoStack(project_dir=Path("/path/to/project"))
    stack.push(file_path, pre_content, post_content, "add_component")
    # ... process restarts ...
    stack = PersistentUndoStack(project_dir=Path("/path/to/project"))
    entry = stack.pop_undo(file_path)
    # entry.pre_content has the content before mutation
"""

import json
import logging
import os
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Any, Optional

from kicad_agent.ops.undo_stack import UndoEntry, UndoStack

logger = logging.getLogger(__name__)

_UNDO_DIR_NAME = ".kicad-agent"
_UNDO_SUBDIR = "undo"
_MANIFEST_FILE = "manifest.json"

# Maximum filename length for safety
_MAX_SAFE_NAME = 60


class PersistentUndoStack(UndoStack):
    """UndoStack with file-based persistence in the project directory.

    Stores undo entries as JSON files in ``<project_dir>/.kicad-agent/undo/``.
    A manifest.json tracks the ordered list of entry files per path.

    On init, loads any existing entries from disk. On push/pop, updates
    both the in-memory deques and the disk store.

    The ``.kicad-agent/`` directory should be gitignored.

    Args:
        project_dir: Root directory of the KiCad project.
        max_size: Maximum entries per file deque (default 50).
    """

    def __init__(self, project_dir: Path, max_size: int = 50) -> None:
        super().__init__(max_size=max_size)
        self._project_dir = project_dir.resolve()
        self._undo_dir = self._project_dir / _UNDO_DIR_NAME / _UNDO_SUBDIR
        self._manifest_path = self._undo_dir / _MANIFEST_FILE
        self._manifest_lock = threading.Lock()
        self._next_seq = 0

        # Track entry -> filename mapping for precise deletion
        self._entry_filenames: dict[int, str] = {}

        # Ensure directory exists
        self._undo_dir.mkdir(parents=True, exist_ok=True)

        # Auto-add .kicad-agent/ to .gitignore
        self._ensure_gitignore()

        # Load existing entries from disk
        self._load_from_disk()

    def _ensure_gitignore(self) -> None:
        """Add .kicad-agent/ to .gitignore if not already present."""
        gitignore = self._project_dir / ".gitignore"
        entry = ".kicad-agent/"
        try:
            if gitignore.exists():
                content = gitignore.read_text(encoding="utf-8")
                if entry not in content:
                    gitignore.write_text(content.rstrip() + "\n" + entry + "\n", encoding="utf-8")
            else:
                gitignore.write_text(entry + "\n", encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not update .gitignore: %s", exc)

    def _validate_entry_path(self, entry_file: str) -> Optional[Path]:
        """Validate an entry file path from the manifest, preventing path traversal.

        Returns the resolved path if safe, or None if the path is invalid.
        """
        if "\x00" in entry_file:
            logger.warning("Rejecting manifest entry with null byte: %s", entry_file)
            return None
        if "/" in entry_file or "\\" in entry_file:
            logger.warning("Rejecting manifest entry with path separator: %s", entry_file)
            return None
        entry_path = (self._undo_dir / entry_file).resolve()
        if not entry_path.is_relative_to(self._undo_dir.resolve()):
            logger.warning("Rejecting manifest entry escaping undo dir: %s", entry_file)
            return None
        return entry_path

    def _load_from_disk(self) -> None:
        """Load undo entries from the manifest file."""
        if not self._manifest_path.exists():
            return

        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load undo manifest: %s", exc)
            return

        entries = data.get("entries", [])
        if not entries:
            # Restore next_seq even with no entries
            persisted_seq = data.get("next_seq", 0)
            if persisted_seq > self._next_seq:
                self._next_seq = persisted_seq
            return

        # Restore next_seq from manifest
        persisted_seq = data.get("next_seq", 0)
        if persisted_seq > self._next_seq:
            self._next_seq = persisted_seq

        loaded = 0
        for entry_data in entries:
            try:
                file_path_str = entry_data.get("file_path", "")
                entry_file = entry_data.get("entry_file", "")
                if not file_path_str or not entry_file:
                    continue

                # Security: validate path before reading
                entry_path = self._validate_entry_path(entry_file)
                if entry_path is None or not entry_path.exists():
                    continue

                entry_json = json.loads(entry_path.read_text(encoding="utf-8"))
                entry = UndoEntry(
                    file_path=Path(file_path_str),
                    pre_content=entry_json.get("pre_content", ""),
                    post_content=entry_json.get("post_content", ""),
                    op_type=entry_json.get("op_type", ""),
                    post_mtime=entry_json.get("post_mtime", 0),
                )

                # Push to in-memory stack (bypasses persistence to avoid write loop)
                resolved = Path(file_path_str).resolve()
                if resolved not in self._undo:
                    self._undo[resolved] = deque(maxlen=self._max_size)
                self._undo[resolved].append(entry)
                loaded += 1

                # Track entry id -> filename for precise deletion
                entry_id = id(entry)
                self._entry_filenames[entry_id] = entry_file

            except Exception as exc:
                # D-11: Log failure at WARNING instead of debug
                logger.warning(
                    "Failed to load undo entry %s: %s (data may be incomplete)",
                    entry_file, exc,
                )
                continue

        if loaded:
            logger.info("Loaded %d undo entries from disk", loaded)

    def _save_manifest(self) -> None:
        """Write the manifest file atomically."""
        manifest: dict[str, Any] = {"next_seq": 0, "entries": []}

        with self._lock:
            manifest["next_seq"] = self._next_seq
            for resolved, dq in self._undo.items():
                for entry in dq:
                    entry_file = self._entry_filenames.get(id(entry))
                    if entry_file is None:
                        # Entry was pushed without persisting filename — generate one
                        entry_file = self._make_entry_filename(entry)
                        self._entry_filenames[id(entry)] = entry_file
                    manifest["entries"].append({
                        "file_path": str(entry.file_path),
                        "entry_file": entry_file,
                        "op_type": entry.op_type,
                    })

        # Atomic write via temp file
        try:
            content = json.dumps(manifest, indent=2)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._undo_dir), suffix=".tmp"
            )
            try:
                os.write(fd, content.encode("utf-8"))
                os.close(fd)
                os.rename(tmp_path, str(self._manifest_path))
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.warning("Failed to save undo manifest: %s", exc)

    def _sanitize_filename(self, entry: UndoEntry) -> str:
        """Sanitize a file path into a safe filename (no separators, length-limited)."""
        safe_name = str(entry.file_path).replace("/", "_").replace(".", "-")
        return safe_name[:_MAX_SAFE_NAME]

    def _make_entry_filename(self, entry: UndoEntry) -> str:
        """Generate a safe filename for an undo entry (no path separators)."""
        safe_name = self._sanitize_filename(entry)
        return f"{self._next_seq:06d}_{safe_name}.json"

    def _write_entry(self, entry: UndoEntry) -> None:
        """Write a single undo entry to disk.

        The entire seq allocation + file write happens under the manifest
        lock to prevent race conditions (concurrent pushes getting the same seq).
        """
        with self._manifest_lock:
            seq = self._next_seq
            self._next_seq += 1

            safe_name = self._sanitize_filename(entry)
            entry_file = f"{seq:06d}_{safe_name}.json"

            # Store filename for precise deletion later
            self._entry_filenames[id(entry)] = entry_file

            entry_path = self._undo_dir / entry_file

            data = {
                "file_path": str(entry.file_path),
                "op_type": entry.op_type,
                "post_mtime": entry.post_mtime,
                "pre_content": entry.pre_content,
                "post_content": entry.post_content,
            }

            try:
                content = json.dumps(data)
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(self._undo_dir), suffix=".tmp"
                )
                try:
                    os.write(fd, content.encode("utf-8"))
                    os.close(fd)
                    os.rename(tmp_path, str(entry_path))
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
            except OSError as exc:
                logger.warning("Failed to write undo entry: %s", exc)

    def _remove_entry_file(self, entry: UndoEntry) -> None:
        """Remove the disk file for a specific entry using tracked filename."""
        entry_file = self._entry_filenames.pop(id(entry), None)
        if entry_file is None:
            return

        entry_path = self._undo_dir / entry_file
        try:
            entry_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Failed to remove undo entry file: %s", exc)

    def push(
        self,
        file_path: Path,
        pre_content: str,
        post_content: str,
        op_type: str,
        post_mtime: int = 0,
    ) -> None:
        """Push a new undo entry, persisting to disk."""
        resolved = file_path.resolve()
        entry = UndoEntry(
            file_path=resolved,
            pre_content=pre_content,
            post_content=post_content,
            op_type=op_type,
            post_mtime=post_mtime,
        )

        # Write entry to disk
        self._write_entry(entry)

        # Push to in-memory stack
        with self._lock:
            if resolved not in self._undo:
                self._undo[resolved] = deque(maxlen=self._max_size)
            self._undo[resolved].append(entry)
            # Clear redo for this file
            self._redo.pop(resolved, None)

        # Update manifest
        with self._manifest_lock:
            self._save_manifest()

    def pop_undo(self, file_path: Path) -> Optional[UndoEntry]:
        """Pop undo entry, updating disk."""
        entry = super().pop_undo(file_path)
        if entry is not None:
            self._remove_entry_file(entry)
            with self._manifest_lock:
                self._save_manifest()
        return entry

    def clear(self) -> None:
        """Clear all entries and remove disk files."""
        super().clear()
        # Remove all entry files
        if self._undo_dir.exists():
            for f in self._undo_dir.glob("*.json"):
                f.unlink(missing_ok=True)
        self._next_seq = 0
        self._entry_filenames.clear()
        # Persist cleared state to manifest (O-BUG-005)
        with self._manifest_lock:
            self._save_manifest()

    def prune_old_entries(self) -> int:
        """Remove entry files that are no longer in any in-memory stack.

        Uses the manifest to identify tracked files, then removes any
        JSON files on disk not referenced by the manifest.

        Returns count of pruned files.
        """
        if not self._manifest_path.exists():
            return 0

        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0

        manifest_entries = data.get("entries", [])
        manifest_files = {e.get("entry_file", "") for e in manifest_entries}

        # Find files on disk not in manifest
        pruned = 0
        for f in list(self._undo_dir.glob("*.json")):
            if f.name == _MANIFEST_FILE:
                continue
            if f.name not in manifest_files:
                f.unlink(missing_ok=True)
                pruned += 1

        return pruned
