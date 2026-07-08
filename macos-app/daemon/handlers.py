"""
handlers.py — RPC method handlers for the bundled daemon.

Phase 162 — Python Daemon Bundling.
Phase 163 — KiCad CLI Integration (kicad_cli_check, external_http_*).

Extracted from daemon_entry.py so each handler is independently testable
(`tests/test_handlers.py`). Handlers are sync functions — the daemon's
async dispatch runs them in a thread executor so the event loop stays
live during slow operations.

Phase 162 ships four handlers:
    ping               — liveness probe, returns {"pong": true, ...}
    list_operations    — returns the kicad_agent.ops.registry operation list
    health_check       — executor + registry sanity check
    shutdown           — request graceful exit

Phase 163 adds:
    kicad_cli_check                — detects external kicad-cli install
    external_http_status           — returns current HTTP MCP opt-in state
    external_http_regenerate_token — rotates the HTTP MCP auth token

Phase 168 adds the full execute/<op> dispatch surface.

Handler signature: (params: Any, ctx: HandlerContext) -> Any
    params: JSON-decoded params object from the request (may be dict or None)
    ctx:    Shared context — executor, audit logger, shutdown flag

Handlers raise RpcError for protocol-level errors (invalid params, method
not found). Unhandled exceptions become INTERNAL_ERROR in the dispatch
layer — handlers do not need to catch their own bugs.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
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
    shutdown flag, external HTTP MCP state). Constructed once per daemon
    process by daemon_entry.amain.
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
        # Phase 163: External HTTP MCP opt-in state (DAEM-07, DAEM-08).
        # Defaults: disabled, no token. Token is lazily generated on first
        # enable or on regenerate_token handler.
        self.external_http_enabled = False
        self.external_http_port = 8080
        self.external_http_token: str | None = None
        self.external_http_failed_auth_count = 0
        self.external_http_auto_revoked = False

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

    # -- external HTTP MCP (Phase 163, DAEM-07/DAEM-08) -----------------------
    def regenerate_external_http_token(self) -> str:
        """Generate a new 32-byte URL-safe auth token. Returns the new token.

        Resets the failed-auth counter (DAEM-08: token rotation invalidates
        any prior brute-force progress).
        """
        # 32 bytes → 43 chars base64url. secrets.token_urlsafe is CSPRNG.
        self.external_http_token = secrets.token_urlsafe(32)
        self.external_http_failed_auth_count = 0
        return self.external_http_token

    def record_external_http_auth_failure(self) -> None:
        """DAEM-08: count failed auths. At 10+, auto-revoke + disable."""
        self.external_http_failed_auth_count += 1
        if self.external_http_failed_auth_count >= 10:
            # Capture the failure count BEFORE regenerate resets it.
            failure_count_at_revoke = self.external_http_failed_auth_count
            # Auto-revoke: rotate token + disable server.
            self.external_http_auto_revoked = True
            self.external_http_enabled = False
            self.regenerate_external_http_token()
            if self.audit is not None:
                self.audit.log_event(
                    "external_http_auto_revoke",
                    failures=failure_count_at_revoke,
                )

    def reset_external_http_auth_failures(self) -> None:
        """Reset failed-auth counter on successful auth."""
        self.external_http_failed_auth_count = 0


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
# Phase 163 — KiCad CLI detection + External HTTP MCP handlers
# =============================================================================

# Minimum supported KiCad version (PROJECT.md: KiCad 10+ only).
KICAD_MINIMUM_VERSION = (10, 0, 0)

# Well-known paths to probe for kicad-cli in addition to PATH.
KICAD_CANDIDATE_PATHS = (
    "/Applications/KiCad/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/opt/homebrew/bin/kicad-cli",
)


def kicad_cli_check(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Detect external KiCad CLI install (APP-04).

    Probes `which kicad-cli`, then well-known absolute paths. On hit,
    runs `<path> --version` and parses the version. Returns one of:

        {"status": "ready", "path": "...", "version": "10.0.3"}
        {"status": "wrong_version", "found": "9.0.2", "minimum": "10.0.0"}
        {"status": "not_installed"}

    This never raises — detection failures map to `not_installed`.
    """
    path = _find_kicad_cli()
    if path is None:
        return {"status": "not_installed"}

    raw_version = _run_version_check(path)
    if raw_version is None:
        # kicad-cli exists but couldn't be executed. Treat as not installed
        # so the onboarding UI keeps prompting.
        return {"status": "not_installed"}

    parsed = _parse_version(raw_version)
    if parsed is None:
        return {"status": "not_installed"}

    if parsed >= KICAD_MINIMUM_VERSION:
        return {
            "status": "ready",
            "path": path,
            "version": ".".join(str(c) for c in parsed),
        }
    return {
        "status": "wrong_version",
        "found": ".".join(str(c) for c in parsed),
        "minimum": ".".join(str(c) for c in KICAD_MINIMUM_VERSION),
    }


def external_http_status(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Return current External HTTP MCP server state (DAEM-07).

    Surfaces opt-in flag, port, whether token exists (never the token
    itself — the Swift UI reads the token from Keychain), and failed-auth
    counter for the DAEM-08 auto-revoke banner.
    """
    return {
        "enabled": ctx.external_http_enabled,
        "port": ctx.external_http_port,
        "has_token": ctx.external_http_token is not None,
        "failed_auth_count": ctx.external_http_failed_auth_count,
        "auto_revoked": ctx.external_http_auto_revoked,
        # Localhost-only binding is documented for the Swift UI.
        "bind": "127.0.0.1",
    }


def external_http_regenerate_token(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Generate a new External HTTP MCP auth token (DAEM-08).

    Returns the new token so the Swift UI can display it / generate a QR
    pairing code. Resets the failed-auth counter.
    """
    new_token = ctx.regenerate_external_http_token()
    if ctx.audit is not None:
        ctx.audit.log_event("external_http_token_regen")
    return {"token": new_token, "length": len(new_token)}


def external_http_set_enabled(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Toggle the External HTTP MCP server on/off (DAEM-07 opt-in).

    Params:
        {"enabled": true|false}

    Enabling auto-generates a token if none exists yet.
    """
    params = require_dict(params, "external_http_set_enabled")
    enabled = require_field(params, "enabled", "external_http_set_enabled")
    if not isinstance(enabled, bool):
        raise RpcError(
            INVALID_PARAMS,
            "external_http_set_enabled: 'enabled' must be bool",
        )
    ctx.external_http_enabled = enabled
    if enabled and ctx.external_http_token is None:
        ctx.regenerate_external_http_token()
    if ctx.audit is not None:
        ctx.audit.log_event("external_http_toggle", enabled=enabled)
    return {"enabled": ctx.external_http_enabled}


# =============================================================================
# Phase 163 internal helpers (KiCad CLI detection)
# =============================================================================

def _find_kicad_cli() -> str | None:
    """Locate kicad-cli via PATH or well-known paths.

    Returns the absolute path, or None if not found.
    """
    # 1. shutil.which honors PATH (works in dev, may not work in sandboxed app).
    found = shutil.which("kicad-cli")
    if found:
        return found
    # 2. Well-known absolute paths.
    for candidate in KICAD_CANDIDATE_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _run_version_check(path: str) -> str | None:
    """Run `<path> --version`, capture output. Returns None on spawn failure."""
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        # Combine stdout + stderr — kicad-cli prints to either depending on version.
        return (proc.stdout or "") + "\n" + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return None


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse a version tuple out of arbitrary text (kicad-cli --version output).

    Tolerates "KiCad CLI 10.0.3", "10.0.3", "v10.0.3", etc.
    Returns (major, minor, patch) or None if no version-like substring found.
    """
    if not text:
        return None
    # Scan for first digit, then consume digit-dot runs.
    i = 0
    n = len(text)
    while i < n:
        if text[i].isdigit():
            start = i
            while i < n and (text[i].isdigit() or text[i] == "."):
                i += 1
            candidate = text[start:i]
            parsed = _split_version(candidate)
            if parsed is not None:
                return parsed
            # Else keep scanning.
        else:
            i += 1
    return None


def _split_version(s: str) -> tuple[int, int, int] | None:
    """Convert '10.0.3' → (10, 0, 3). Returns None if no leading int."""
    parts = s.split(".")
    nums: list[int] = []
    for part in parts[:3]:
        # Stop at non-digit suffix ("10.0.3+debug" → [10, 0, 3]).
        digits = ""
        for c in part:
            if c.isdigit():
                digits += c
            else:
                break
        if not digits:
            break
        nums.append(int(digits))
    if not nums:
        return None
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


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
    # Phase 163 — KiCad CLI integration + External HTTP MCP opt-in
    "kicad_cli_check": kicad_cli_check,
    "external_http_status": external_http_status,
    "external_http_regenerate_token": external_http_regenerate_token,
    "external_http_set_enabled": external_http_set_enabled,
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
