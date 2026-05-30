"""Undo/redo stack for KiCad file mutations.

Stores file content snapshots (pre/post mutation) in bounded per-file deques.
Standard undo/redo semantics: new push clears the redo stack.

Thread-safe via threading.Lock. Bounded via collections.deque(maxlen=N).

Memory warning (M-07): Each UndoEntry stores two full file content strings.
With default max_size=50 and typical KiCad files of 100KB-1MB, memory usage
is ~10-50MB per file. For large PCB designs (>5MB), reduce max_size via
KICAD_UNDO_MAX_SIZE env var.

Usage:
    from kicad_agent.ops.undo_stack import UndoStack, UndoEntry

    stack = UndoStack(max_size=50)
    stack.push(file_path, pre_content, post_content, "add_component")
    entry = stack.pop_undo(file_path)
    # entry.pre_content has the content before mutation
"""

import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class UndoEntry:
    """Snapshot of a file mutation for undo/redo.

    Attributes:
        file_path: Resolved path to the mutated file.
        pre_content: File content before mutation.
        post_content: File content after mutation.
        op_type: Operation type for display/logging.
        post_mtime: mtime_ns after commit, for stale snapshot detection (L-05).
    """

    file_path: Path
    pre_content: str
    post_content: str
    op_type: str
    post_mtime: int = 0


class UndoStack:
    """Per-file undo/redo stack with bounded deques and thread-safe access.

    Each file gets its own undo and redo deque. Push clears the redo deque
    for that file (standard undo/redo semantics). Deques are bounded by
    max_size -- oldest entries are silently discarded when the limit is reached.

    Args:
        max_size: Maximum entries per file deque. Defaults to 50.

    Raises:
        ValueError: If max_size < 1.

    Memory warning (M-07): Each UndoEntry stores two full file content strings.
    With default max_size=50 and typical KiCad files of 100KB-1MB, memory usage
    is ~10-50MB per file. For large PCB designs (>5MB), reduce max_size.
    """

    def __init__(self, max_size: int = 50) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._undo: dict[Path, deque[UndoEntry]] = {}
        self._redo: dict[Path, deque[UndoEntry]] = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def push(
        self,
        file_path: Path,
        pre_content: str,
        post_content: str,
        op_type: str,
        post_mtime: int = 0,
    ) -> None:
        """Push a new undo entry, clearing the redo stack for this file.

        Args:
            file_path: Path to the mutated file (resolved internally).
            pre_content: File content before mutation.
            post_content: File content after mutation.
            op_type: Operation type string.
            post_mtime: mtime_ns after commit (0 if unknown).
        """
        resolved = file_path.resolve()
        entry = UndoEntry(
            file_path=resolved,
            pre_content=pre_content,
            post_content=post_content,
            op_type=op_type,
            post_mtime=post_mtime,
        )
        with self._lock:
            if resolved not in self._undo:
                self._undo[resolved] = deque(maxlen=self._max_size)
            self._undo[resolved].append(entry)
            # Clear redo for this file (pop key to remove entirely)
            self._redo.pop(resolved, None)

    def pop_undo(self, file_path: Path) -> Optional[UndoEntry]:
        """Pop the most recent undo entry and push to redo stack.

        Args:
            file_path: Path to the file (resolved internally).

        Returns:
            The most recent UndoEntry, or None if undo stack is empty.
        """
        resolved = file_path.resolve()
        with self._lock:
            dq = self._undo.get(resolved)
            if not dq:
                return None
            entry = dq.pop()
            if resolved not in self._redo:
                self._redo[resolved] = deque(maxlen=self._max_size)
            self._redo[resolved].append(entry)
            return entry

    def pop_redo(self, file_path: Path) -> Optional[UndoEntry]:
        """Pop the most recent redo entry and push back to undo stack.

        Args:
            file_path: Path to the file (resolved internally).

        Returns:
            The most recently undone UndoEntry, or None if redo stack is empty.
        """
        resolved = file_path.resolve()
        with self._lock:
            dq = self._redo.get(resolved)
            if not dq:
                return None
            entry = dq.pop()
            if resolved not in self._undo:
                self._undo[resolved] = deque(maxlen=self._max_size)
            self._undo[resolved].append(entry)
            return entry

    def can_undo(self, file_path: Path) -> bool:
        """Check if there are undo entries for a file (thread-safe peek).

        Args:
            file_path: Path to the file (resolved internally).

        Returns:
            True if at least one undo entry exists.
        """
        resolved = file_path.resolve()
        with self._lock:
            dq = self._undo.get(resolved)
            return bool(dq)

    def can_redo(self, file_path: Path) -> bool:
        """Check if there are redo entries for a file (thread-safe peek).

        Args:
            file_path: Path to the file (resolved internally).

        Returns:
            True if at least one redo entry exists.
        """
        resolved = file_path.resolve()
        with self._lock:
            dq = self._redo.get(resolved)
            return bool(dq)

    def clear(self) -> None:
        """Clear all undo and redo entries for all files."""
        with self._lock:
            self._undo.clear()
            self._redo.clear()

    @property
    def max_size(self) -> int:
        """Maximum entries per file deque."""
        return self._max_size

    def pop_latest_undo(self) -> Optional[UndoEntry]:
        """Pop an undo entry from any file, push to redo.

        Scans all undo deques to find one with entries. O(number of files)
        which is typically small (<10 files in a KiCad project).

        Returns:
            An UndoEntry from any file, or None if all stacks are empty.
        """
        with self._lock:
            for resolved, dq in self._undo.items():
                if dq:
                    entry = dq.pop()
                    if resolved not in self._redo:
                        self._redo[resolved] = deque(maxlen=self._max_size)
                    self._redo[resolved].append(entry)
                    return entry
        return None

    def pop_latest_redo(self) -> Optional[UndoEntry]:
        """Pop a redo entry from any file, push to undo.

        Scans all redo deques to find one with entries. O(number of files).

        Returns:
            An UndoEntry from any file, or None if all stacks are empty.
        """
        with self._lock:
            for resolved, dq in self._redo.items():
                if dq:
                    entry = dq.pop()
                    if resolved not in self._undo:
                        self._undo[resolved] = deque(maxlen=self._max_size)
                    self._undo[resolved].append(entry)
                    return entry
        return None
