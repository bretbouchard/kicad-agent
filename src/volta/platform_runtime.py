"""Bootable Volta-side platform runtime for Phase 2 governance adoption.

Provides a concrete runtime boundary that can be booted once per project,
scope a shared governed execution context across operation handling, and
export diagnostics/feed snapshots for adopter-side proof.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volta.governance import GovernedExecutionContext
from volta.result import OperationError, OperationResult

_ACTIVE_GOVERNED_CONTEXT: ContextVar[GovernedExecutionContext | None] = ContextVar(
    "volta_active_governed_context",
    default=None,
)


def get_active_governed_context() -> GovernedExecutionContext | None:
    """Return the runtime-scoped governed execution context, if any."""

    return _ACTIVE_GOVERNED_CONTEXT.get()


@dataclass(frozen=True)
class RuntimeEvent:
    """Single runtime event emitted by the booted platform wrapper."""

    timestamp: str
    operation_type: str
    success: bool
    target_file: str
    governed_capabilities: tuple[str, ...] = ()
    evidence_count: int = 0
    object_count: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event for diagnostics/export surfaces."""

        return {
            "timestamp": self.timestamp,
            "operation_type": self.operation_type,
            "success": self.success,
            "target_file": self.target_file,
            "governed_capabilities": list(self.governed_capabilities),
            "evidence_count": self.evidence_count,
            "object_count": self.object_count,
            "error": self.error,
        }


@dataclass
class VoltaPlatformRuntime:
    """Minimal bootable runtime that aggregates governed execution state."""

    project_dir: Path
    governed_context: GovernedExecutionContext = field(default_factory=GovernedExecutionContext)
    booted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    _events: list[RuntimeEvent] = field(default_factory=list)

    @classmethod
    def boot(cls, project_dir: Path | str) -> "VoltaPlatformRuntime":
        """Boot the runtime for a specific project directory."""

        return cls(project_dir=Path(project_dir))

    def execute_operation(self, json_str: str) -> OperationResult | OperationError:
        """Execute an operation with the runtime-scoped governed context active."""

        from volta.handler import handle_operation

        token = _ACTIVE_GOVERNED_CONTEXT.set(self.governed_context)
        try:
            result = handle_operation(json_str, project_dir=self.project_dir)
        finally:
            _ACTIVE_GOVERNED_CONTEXT.reset(token)

        self._events.append(self._event_from_result(result))
        return result

    def diagnostics(self) -> dict[str, Any]:
        """Return a stable diagnostics snapshot for the booted runtime."""

        success_count = len([event for event in self._events if event.success])
        failure_count = len(self._events) - success_count
        return {
            "project_dir": str(self.project_dir),
            "booted_at": self.booted_at,
            "operation_count": len(self._events),
            "success_count": success_count,
            "failure_count": failure_count,
            "evidence_count": len(self.governed_context.evidence.all_records()),
            "governed_object_count": len(self.governed_context.world.all_records()),
            "last_operation": self._events[-1].to_dict() if self._events else None,
        }

    def diagnostics_feed(self) -> list[dict[str, Any]]:
        """Return the runtime event feed in execution order."""

        return [event.to_dict() for event in self._events]

    def export(self) -> dict[str, Any]:
        """Export the runtime state for adopter-side proof and handoff."""

        return {
            "diagnostics": self.diagnostics(),
            "events": self.diagnostics_feed(),
            "evidence": [
                {
                    "kind": record.kind.value,
                    "subject_id": record.subject_id,
                    "passed": record.passed,
                    "summary": record.summary,
                    "payload": record.payload,
                }
                for record in self.governed_context.evidence.all_records()
            ],
            "governed_objects": [
                {
                    "object_id": record.object_id,
                    "object_type": record.object_type.value,
                    "locator": record.path,
                    "revision": record.revision,
                    "metadata": record.metadata,
                }
                for record in self.governed_context.world.all_records()
            ],
        }

    def _event_from_result(self, result: OperationResult | OperationError) -> RuntimeEvent:
        """Normalize handler results into runtime event records."""

        timestamp = datetime.now(timezone.utc).isoformat()
        if isinstance(result, OperationError):
            return RuntimeEvent(
                timestamp=timestamp,
                operation_type=result.operation_type,
                success=False,
                target_file="",
                error=result.error,
            )

        governed_capabilities: list[str] = []
        evidence_count = 0
        object_count = 0
        for value in result.details.values():
            if not isinstance(value, dict):
                continue
            capability_name = value.get("capability_name")
            if isinstance(capability_name, str):
                governed_capabilities.append(capability_name)
            if isinstance(value.get("evidence_count"), int):
                evidence_count += value["evidence_count"]
            if isinstance(value.get("object_count"), int):
                object_count += value["object_count"]

        return RuntimeEvent(
            timestamp=timestamp,
            operation_type=result.operation_type,
            success=result.success,
            target_file=result.target_file,
            governed_capabilities=tuple(governed_capabilities),
            evidence_count=evidence_count,
            object_count=object_count,
        )
