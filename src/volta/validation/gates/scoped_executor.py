"""Scoped executor that enforces file-level operation boundaries.

ScopedExecutor wraps an OperationExecutor and rejects any operation
whose target_file is not in the allowed scope list. The scope check
happens BEFORE the operation is parsed or dispatched, preventing
any file mutation from out-of-scope proposals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ScopeViolationError(Exception):
    """Raised when an operation targets a file outside the allowed scope."""

    def __init__(self, target_file: Path, scope_files: list[Path]) -> None:
        self.target_file = target_file
        self.scope_files = scope_files
        scope_str = ", ".join(str(p) for p in scope_files)
        super().__init__(
            f"Operation targets {target_file} which is outside the allowed scope: [{scope_str}]"
        )


class ScopedExecutor:
    """Wraps OperationExecutor with file scope enforcement.

    The scope check is mechanical: the resolved target_file must be
    one of the scope_files paths. No parsing or execution occurs
    before this check.
    """

    def __init__(self, executor: Any, scope_files: list[Path]) -> None:
        self._executor = executor
        self._scope_files = tuple(scope_files)

    @property
    def scope_files(self) -> tuple[Path, ...]:
        return self._scope_files

    def execute(self, op: Any) -> dict[str, Any]:
        """Execute an operation only if its target is within scope.

        Raises:
            ScopeViolationError: If target_file is not in scope_files.
        """
        target = self._extract_target_file(op)
        if target not in self._scope_files:
            raise ScopeViolationError(target, list(self._scope_files))
        return self._executor.execute(op)

    @staticmethod
    def _extract_target_file(op: Any) -> Path:
        """Extract target_file from operation model."""
        target_file = getattr(op, "target_file", None)
        if target_file is None:
            # Also check in the op dict representation
            if hasattr(op, "model_dump"):
                target_file = op.model_dump().get("target_file")
            elif hasattr(op, "dict"):
                target_file = op.dict().get("target_file")
            elif isinstance(op, dict):
                target_file = op.get("target_file")
        return Path(target_file) if target_file else Path()
