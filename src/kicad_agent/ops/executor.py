"""Operation executor -- dispatches validated Operation intents to handlers.

Establishes the pattern (executor dispatch, handler function, Transaction
wrapping, IR mutation, serialization) that all subsequent operations follow.

Handler functions are organized in the handlers/ sub-package by category:
  - handlers/schematic.py       -- schematic mutation operations
  - handlers/schematic_query.py -- read-only schematic queries
  - handlers/pcb.py             -- PCB mutation operations
  - handlers/project.py         -- project file operations
  - handlers/create.py          -- file creation operations
  - handlers/query.py           -- PCB query operations
  - handlers/crossfile.py       -- cross-file operations

File-type execution logic lives in execution.py:
  - execute_schematic / dispatch_schematic
  - execute_pcb / dispatch_pcb
  - execute_query / dispatch_query
  - execute_schematic_query
  - execute_create
  - execute_project / dispatch_project
  - execute_cross_file

Security (threat model):
- T-04-06: Dispatch uses exact op_type matching; unknown raises ValueError
- T-04-01: UUID generated server-side in handlers

Usage:
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute(op)
"""

import logging
from pathlib import Path
from typing import Any, Optional

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ops.schema import Operation
from kicad_agent.ops.ir_cache import IRCache
from kicad_agent.ops.undo_stack import UndoStack

# Re-export handler registries for backward compatibility with tests
from kicad_agent.ops.handlers import (  # noqa: F401
    _SCHEMATIC_HANDLERS,
    _SCHEMATIC_QUERY_HANDLERS,
    _PCB_HANDLERS,
    _PROJECT_HANDLERS,
    _CREATE_HANDLERS,
    _QUERY_HANDLERS,
    _CROSSFILE_HANDLERS,
)

# Import execution functions and constants
# Tests import these from kicad_agent.ops.executor for backward compatibility
from kicad_agent.ops.execution import (  # noqa: F401
    CROSS_FILE_OP_TYPES as _CROSS_FILE_OP_TYPES,
    CREATE_OP_TYPES as _CREATE_OP_TYPES,
    SELF_SERIALIZING_OPS as _SELF_SERIALIZING_OPS,
    is_project_file,
    dispatch_schematic,
    dispatch_pcb,
    dispatch_project,
    execute_create,
    execute_cross_file,
    execute_pcb,
    execute_project,
    execute_query,
    execute_schematic,
    execute_schematic_query,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Executor class
# ---------------------------------------------------------------------------


class OperationExecutor:
    """Dispatches validated Operation intents to mutation handlers.

    Each handler call is wrapped in a Transaction for rollback on failure.
    The executor parses the file, creates SchematicIR, calls the handler,
    serializes, normalizes, and commits.

    Args:
        base_dir: Base directory for resolving relative target_file paths.
    """

    def __init__(self, base_dir: Path, *, cache: Optional[IRCache] = None, undo_stack: Optional[UndoStack] = None) -> None:
        self._base_dir = base_dir
        self._cache = cache
        self._undo_stack = undo_stack

    def execute(self, op: Operation) -> dict[str, Any]:
        """Execute a validated operation with Transaction wrapping.

        Routes to schematic or PCB execution path based on file extension.

        Args:
            op: Validated Operation from the schema.

        Returns:
            Dict with: success, operation, target_file, details.

        Raises:
            ValueError: For unknown op_type (T-04-06).
            FileNotFoundError: If target_file does not exist.
        """
        root = op.root
        file_path = self._base_dir / root.target_file

        # Security (T-24-01): path confinement -- reject paths that escape project dir
        resolved = file_path.resolve()
        base_resolved = self._base_dir.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(
                f"Security: path escapes project directory: {root.target_file}"
            )

        # Cross-file operations: coordinate multiple files atomically
        if root.op_type in _CROSS_FILE_OP_TYPES:
            return execute_cross_file(op, file_path, self._base_dir, self._cache, self._undo_stack)

        # Create operations: file does not exist yet (bypass existence check)
        if root.op_type in _CREATE_OP_TYPES:
            return execute_create(op, file_path, self._base_dir)

        if not file_path.exists():
            raise FileNotFoundError(f"Target file not found: {file_path}")

        # Query operations: read-only, no Transaction, no serialization
        if root.op_type in _QUERY_HANDLERS:
            return execute_query(op, file_path, self._cache)

        # Schematic query operations: read-only, parse-only path for .kicad_sch
        if root.op_type in _SCHEMATIC_QUERY_HANDLERS:
            return execute_schematic_query(op, file_path, self._cache)

        # Clear IR registry to avoid stale registrations across operations
        _clear_registry()

        # Branch on file type
        if file_path.suffix == ".kicad_pcb":
            return execute_pcb(op, file_path, self._cache, self._undo_stack)
        elif is_project_file(file_path):
            return execute_project(op, file_path, self._undo_stack)
        else:
            return execute_schematic(op, file_path, self._cache, self._undo_stack)

    # ------------------------------------------------------------------
    # Batch execution: single parse/write per file
    # ------------------------------------------------------------------

    def execute_batch(self, ops: list[Operation]) -> dict[str, Any]:
        """Execute multiple operations with single parse/write per file.

        Delegates to batch_executor.execute_batch() to keep this file
        under the 800-line limit. See batch_executor.py for full docs.
        """
        from kicad_agent.ops.batch_executor import execute_batch as _execute_batch

        return _execute_batch(self, ops)

    # ------------------------------------------------------------------
    # Undo/redo methods
    # ------------------------------------------------------------------

    def undo(self, target_file: Optional[str] = None) -> dict[str, Any]:
        """Undo the most recent mutation for a file.

        Args:
            target_file: Relative path to the file. If None, undoes the latest
                mutation across all files.

        Returns:
            Dict with success, undone_op, target_file on success.
            Dict with success=False, error on failure.
        """
        if self._undo_stack is None:
            return {"success": False, "error": "Undo stack not enabled"}

        if target_file is not None:
            file_path = (self._base_dir / target_file).resolve()
            entry = self._undo_stack.pop_undo(file_path)
        else:
            entry = self._undo_stack.pop_latest_undo()

        if entry is None:
            return {"success": False, "error": "No operations to undo"}

        # H-04: Symlink protection (mirrors Transaction H-02 control)
        if entry.file_path.is_symlink():
            return {"success": False, "error": "Security: target file is a symlink"}

        # M-08: Check parent directory exists before writing
        if not entry.file_path.parent.exists():
            return {"success": False, "error": "Cannot undo: parent directory no longer exists"}

        # L-05: Warn if file was modified externally since snapshot
        if entry.post_mtime and entry.file_path.exists():
            current_mtime = entry.file_path.stat().st_mtime_ns
            if current_mtime != entry.post_mtime:
                logger.warning(
                    "Undo: file modified externally since snapshot: %s",
                    entry.file_path,
                )

        # L-04: Use newline="" to preserve exact byte content (LF line endings)
        try:
            entry.file_path.write_text(entry.pre_content, encoding="utf-8", newline="")
        except OSError as e:
            # Reverse: pop_redo moves entry back to undo so user can retry
            self._undo_stack.pop_redo(entry.file_path)
            return {"success": False, "error": f"Write error during undo: {e}"}

        # Invalidate cache for this file
        if self._cache:
            self._cache.invalidate(entry.file_path)

        return {
            "success": True,
            "undone_op": entry.op_type,
            "target_file": str(entry.file_path.relative_to(self._base_dir)),
        }

    def redo(self, target_file: Optional[str] = None) -> dict[str, Any]:
        """Redo the most recently undone mutation for a file.

        Args:
            target_file: Relative path to the file. If None, redoes the latest
                undone mutation across all files.

        Returns:
            Dict with success, redone_op, target_file on success.
            Dict with success=False, error on failure.
        """
        if self._undo_stack is None:
            return {"success": False, "error": "Undo stack not enabled"}

        if target_file is not None:
            file_path = (self._base_dir / target_file).resolve()
            entry = self._undo_stack.pop_redo(file_path)
        else:
            entry = self._undo_stack.pop_latest_redo()

        if entry is None:
            return {"success": False, "error": "No operations to redo"}

        # H-04: Symlink protection
        if entry.file_path.is_symlink():
            return {"success": False, "error": "Security: target file is a symlink"}

        # M-08: Check parent directory exists before writing
        if not entry.file_path.parent.exists():
            return {"success": False, "error": "Cannot redo: parent directory no longer exists"}

        # L-05: Warn if file was modified externally since snapshot
        if entry.post_mtime and entry.file_path.exists():
            current_mtime = entry.file_path.stat().st_mtime_ns
            if current_mtime != entry.post_mtime:
                logger.warning(
                    "Redo: file modified externally since snapshot: %s",
                    entry.file_path,
                )

        # L-04: Use newline="" to preserve exact byte content
        try:
            entry.file_path.write_text(entry.post_content, encoding="utf-8", newline="")
        except OSError as e:
            # Reverse: pop_undo moves entry back to redo so user can retry
            self._undo_stack.pop_undo(entry.file_path)
            return {"success": False, "error": f"Write error during redo: {e}"}

        # Invalidate cache for this file
        if self._cache:
            self._cache.invalidate(entry.file_path)

        return {
            "success": True,
            "redone_op": entry.op_type,
            "target_file": str(entry.file_path.relative_to(self._base_dir)),
        }
