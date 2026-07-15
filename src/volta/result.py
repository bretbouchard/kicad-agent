"""Structured result types for operation outcomes.

Provides frozen dataclasses for successful and failed operation results,
each with a ``to_text()`` method that renders a human-readable string
suitable for Claude to display to the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationResult:
    """Result of a successfully validated and processed operation.

    Attributes:
        success: Always ``True``.
        operation_type: The ``op_type`` string (e.g. ``"add_component"``).
        target_file: The ``target_file`` path from the operation.
        message: Human-readable summary of what happened.
        details: Operation-specific key/value details.
    """

    success: bool
    operation_type: str
    target_file: str
    message: str
    details: dict[str, Any]

    def to_text(self) -> str:
        """Render a human-readable summary for display."""
        lines: list[str] = [
            f"[OK] {self.operation_type} on {self.target_file}",
            f"  {self.message}",
        ]
        if self.details:
            for key, value in self.details.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)


@dataclass(frozen=True)
class OperationError:
    """Result of a failed operation validation or execution.

    Attributes:
        success: Always ``False``.
        operation_type: The ``op_type`` if known, or ``"unknown"``.
        error: Description of what went wrong.
        suggestion: Actionable next step for the user.
    """

    success: bool
    operation_type: str
    error: str
    suggestion: str

    def to_text(self) -> str:
        """Render a human-readable error with suggestion."""
        lines: list[str] = [
            f"[ERROR] {self.operation_type}: {self.error}",
            f"  Suggestion: {self.suggestion}",
        ]
        return "\n".join(lines)
