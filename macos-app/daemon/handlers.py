"""
handlers.py — RPC method handlers for the bundled daemon.

Phase 162 — Python Daemon Bundling.

Extracted from daemon_entry.py so each handler is independently testable
(`tests/test_handlers.py`). Handlers are sync functions — the daemon's
async dispatch runs them in a thread executor so the event loop stays
live during slow operations.

Phase 162 ships four handlers:
    ping               — liveness probe, returns {"pong": true, ...}
    list_operations    — returns the kicad_agent.ops.registry operation list
    health_check       — executor + registry sanity check
    shutdown           — request graceful exit

Phase 168 adds the full execute/<op> dispatch surface.

Handler signature: (params: Any, ctx: HandlerContext) -> Any
    params: JSON-decoded params object from the request (may be dict or None)
    ctx:    Shared context — executor, audit logger, shutdown flag

Handlers raise RpcError for protocol-level errors (invalid params, method
not found). Unhandled exceptions become INTERNAL_ERROR in the dispatch
layer — handlers do not need to catch their own bugs.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from protocol import RpcError, INVALID_PARAMS

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from audit_log import AuditLogger


# =============================================================================
# Handler context
# =============================================================================

class HandlerContext:
    """Shared state passed to every handler invocation.

    Holds lazy-initialized executor and process-wide concerns (audit log,
    shutdown flag). Constructed once per daemon process by daemon_entry.amain.
    """

    def __init__(
        self,
        executor_factory: "Any | None" = None,
        audit: "AuditLogger | None" = None,
    ) -> None:
        # executor_factory is a zero-arg callable that returns an
        # OperationExecutor. Lazy import keeps the import-time surface
        # small and isolates registry failures so ping still works.
        self._executor_factory = executor_factory
        self._executor: Any | None = None
        self.audit = audit
        self.shutdown_requested = False

    # -- executor -------------------------------------------------------------
    def executor(self) -> Any:
        """Return the lazily-constructed OperationExecutor."""
        if self._executor is None and self._executor_factory is not None:
            self._executor = self._executor_factory()
        return self._executor

    def register_executor_factory(self, factory: Any) -> None:
        """Set the executor factory. Used by daemon_entry to defer import."""
        self._executor_factory = factory

    # -- shutdown -------------------------------------------------------------
    def request_shutdown(self) -> None:
        self.shutdown_requested = True


# =============================================================================
# Built-in handlers
# =============================================================================

def ping(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Liveness probe. Returns {"pong": true, "epoch": <float>}.

    Ignores params — callers may pass {} or omit entirely. This is the
    primary health check used by the Swift ProcessManager.
    """
    return {"pong": True, "epoch": time.time()}


def health_check(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Comprehensive health probe.

    Returns:
        {"ok": true, "ops_registered": <int>, "executor_loaded": <bool>}
        or {"ok": false, "error": "<msg>"} on failure.

    This never raises — it catches all exceptions so the Swift side
    always gets a structured response. A failed health check is itself
    the failure signal.
    """
    try:
        ops = _registered_operations()
        executor_loaded = ctx._executor is not None
        return {
            "ok": True,
            "ops_registered": len(ops),
            "executor_loaded": executor_loaded,
            "operations": ops[:10],  # first 10 as a smoke sample
        }
    except Exception as exc:  # noqa: BLE001 — health probe must not raise
        return {"ok": False, "error": str(exc), "type": type(exc).__name__}


def list_operations(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Return the full registry of operations exposed by the bundled library.

    Phase 168 wires each of these to the dispatcher; Phase 162 returns
    the static list so the Swift UI can render an operation browser.
    """
    ops = _registered_operations()
    return {
        "count": len(ops),
        "operations": ops,
    }


def shutdown(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Request graceful shutdown. Sets the ctx.shutdown_requested flag.

    The main loop polls this flag between iterations and exits cleanly.
    Returns an immediate ack; the actual exit happens on the next loop
    iteration after any in-flight RPC completes.
    """
    ctx.request_shutdown()
    return {"shutting_down": True}


# =============================================================================
# Handler registry — maps method names to callables
# =============================================================================

# Method → handler callable. The dispatch layer (daemon_entry.py) looks
# up this table for each incoming request. Methods not listed here return
# METHOD_NOT_FOUND.
HANDLERS: dict[str, Any] = {
    "ping": ping,
    "health": health_check,
    "health_check": health_check,  # alias — Swift uses both interchangeably
    "list_operations": list_operations,
    "shutdown": shutdown,
}


def get_handler(method: str) -> Any | None:
    """Look up a handler by method name. Returns None if unknown."""
    return HANDLERS.get(method)


def registered_methods() -> list[str]:
    """Return the sorted list of registered method names."""
    return sorted(HANDLERS.keys())


# =============================================================================
# Internal helpers
# =============================================================================

def _registered_operations() -> list[str]:
    """Best-effort import of the kicad_agent operations registry.

    Returns an empty list if the package isn't importable (e.g. broken
    PyInstaller bundle). Health checks should not raise on import
    failures — they should report them.

    The registry is exposed as `OPERATION_REGISTRY` (a dict keyed by op
    name) in current kicad_agent. We also tolerate `OPERATIONS` (older
    alias) and list-shaped registries for forward compatibility.
    """
    try:
        from kicad_agent.ops import registry as reg  # type: ignore[import-not-found]
    except Exception:
        return []

    # Preferred: OPERATION_REGISTRY dict.
    ops = getattr(reg, "OPERATION_REGISTRY", None)
    if isinstance(ops, dict):
        return sorted(ops.keys())

    # Legacy alias.
    ops = getattr(reg, "OPERATIONS", None)
    if isinstance(ops, dict):
        return sorted(ops.keys())
    if isinstance(ops, (list, tuple)):
        return sorted(str(op) for op in ops)

    return []


# =============================================================================
# Param validation helpers (used by Phase 168 execute handler, exported here
# so tests can exercise them in Phase 162 already).
# =============================================================================

def require_dict(params: Any, method: str) -> dict[str, Any]:
    """Coerce params to dict or raise INVALID_PARAMS."""
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise RpcError(
            INVALID_PARAMS,
            f"{method}: params must be an object, got {type(params).__name__}",
        )
    return params


def require_field(params: dict[str, Any], field: str, method: str) -> Any:
    """Extract a required field or raise INVALID_PARAMS."""
    if field not in params:
        raise RpcError(
            INVALID_PARAMS,
            f"{method}: missing required field '{field}'",
        )
    return params[field]
