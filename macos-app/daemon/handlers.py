"""
handlers.py — RPC method handlers for the bundled daemon.

Phase 162 — Python Daemon Bundling.
Phase 163 — KiCad CLI Integration (kicad_cli_check, external_http_*).
Phase 167 — MCP lifecycle (initialize, initialized, tools/list, tools/call).

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

Phase 167 adds (per MCP spec — modelcontextprotocol.io/specification):
    initialize          — MCP handshake (capability exchange)
    initialized         — MCP handshake completion (notification, no reply)
    tools/list          — returns all 151 kicad-agent ops as MCP tools
    tools/call          — dispatches a kicad-agent op via OperationExecutor

Phase 168 adds the full execute/<op> dispatch surface.

Phase 170 adds verification handlers (GOV-03, GOV-04, GOV-05):
    kicad.pre_check    — pre-op intent + file-type validation
    kicad.post_check   — post-op ERC/DRC + structured result
    kicad.snapshot     — capture file snapshot for rollback
    kicad.restore      — restore files from a prior snapshot

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
from pathlib import Path
from typing import Any, TYPE_CHECKING

from protocol import RpcError, INVALID_PARAMS
from snapshot import Snapshot, SnapshotError

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
# Phase 167 — MCP lifecycle handlers (initialize, tools/list, tools/call)
# =============================================================================
#
# Per MCP spec: https://modelcontextprotocol.io/specification
#
# These four handlers bring the bundled daemon into MCP compliance so any
# MCP-compatible client (Claude Code, Cursor, etc.) can connect via stdio
# and discover/invoke all 151 kicad-agent operations as MCP tools.
#
# Wire format examples:
#   initialize:
#     {"jsonrpc":"2.0","id":1,"method":"initialize",
#      "params":{"protocolVersion":"2024-11-05","capabilities":{},
#                "clientInfo":{"name":"KiCadAgent","version":"1.0"}}}
#     → {"jsonrpc":"2.0","id":1,"result":{
#          "protocolVersion":"2024-11-05",
#          "serverInfo":{"name":"kicad-agent-daemon","version":"0.1.0"},
#          "capabilities":{"tools":{}}}}
#
#   tools/list:
#     {"jsonrpc":"2.0","id":2,"method":"tools/list"}
#     → {"jsonrpc":"2.0","id":2,"result":{"tools":[
#          {"name":"kicad.add_component","description":"...","inputSchema":{...}},
#          ...151 entries...
#       ]}}
#
#   tools/call:
#     {"jsonrpc":"2.0","id":3,"method":"tools/call",
#      "params":{"name":"kicad.add_component",
#                "arguments":{"root":{"op_type":"add_component",...}}}}
#     → {"jsonrpc":"2.0","id":3,"result":{"content":[
#          {"type":"text","text":"{\"success\":true,...}"}
#       ]}}

# MCP protocol version we advertise in initialize response.
MCP_PROTOCOL_VERSION = "2024-11-05"

# Daemon identity (used in initialize response serverInfo).
MCP_SERVER_NAME = "kicad-agent-daemon"
MCP_SERVER_VERSION = "0.1.0"


def initialize(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """MCP handshake — capability exchange (server response).

    The client sends `initialize` with its protocol version, capabilities,
    and client info. We respond with ours. After this round-trip, the
    client SHOULD send the `initialized` notification to complete the
    handshake (see `initialized` handler below).

    Params:
        {"protocolVersion": "<str>", "capabilities": {...}, "clientInfo": {...}}

    Returns:
        {"protocolVersion": "2024-11-05",
         "serverInfo": {"name": "kicad-agent-daemon", "version": "0.1.0"},
         "capabilities": {"tools": {}}}
    """
    # Params are informational — we don't downgrade based on client version.
    # The handler is permissive: even malformed params return our capabilities.
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {
            "name": MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION,
        },
        "capabilities": {
            "tools": {
                # Per MCP spec, servers can advertise tools.changed support.
                # Phase 167 does not implement tool list change notifications.
            },
        },
    }


def initialized(params: Any, ctx: HandlerContext) -> None:
    """MCP handshake completion notification (no reply expected).

    The client sends `initialized` after receiving the `initialize` response.
    Per MCP spec, this is a notification: dispatch returns None and the
    daemon's main loop does NOT emit a JSON-RPC response.

    Returns None — see daemon_entry.dispatch() for how None is handled
    (it skips the emit step, so the client gets no reply).

    Phase 167 behavior: no-op. Hook exists so future versions can log
    handshake completion for audit trails.
    """
    if ctx.audit is not None:
        ctx.audit.log_event("mcp_initialized")
    return None


def tools_list(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """MCP tools/list — enumerate all kicad-agent operations as MCP tools.

    Returns each operation as an MCP tool descriptor:
        {"name": "kicad.add_component",
         "description": "<op description from registry>",
         "inputSchema": <JSON schema from Pydantic model>}

    Per MCP spec, tool names are namespaced as `kicad.<op_type>` so they
    don't collide with other MCP servers the client may have connected.
    """
    tools = []
    op_names = _registered_operations()
    for op_name in op_names:
        descriptor = _build_tool_descriptor(op_name)
        if descriptor is not None:
            tools.append(descriptor)
    return {"tools": tools}


def tools_call(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """MCP tools/call — dispatch a kicad-agent operation by name.

    Params:
        {"name": "kicad.add_component",
         "arguments": {"root": {"op_type": "add_component", ...}}}

    The `name` is validated against the registry. `arguments` is passed
    straight to OperationExecutor.execute(Operation.model_validate(args)).

    Returns the MCP-style content envelope:
        {"content": [{"type": "text", "text": "<JSON-encoded result>"}],
         "isError": false}

    On error, returns:
        {"content": [{"type": "text", "text": "<error message>"}],
         "isError": true}

    MCP convention is to wrap operation results in a `content` array so
    clients can render text/images/etc uniformly. kicad-agent ops return
    JSON dicts, so we JSON-encode and wrap as a single text content item.
    """
    import json as _json

    params = require_dict(params, "tools/call")
    name = require_field(params, "name", "tools/call")
    if not isinstance(name, str):
        raise RpcError(INVALID_PARAMS, "tools/call: 'name' must be a string")
    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise RpcError(INVALID_PARAMS, "tools/call: 'arguments' must be an object")

    # Validate name against the kicad.* namespace.
    if not name.startswith("kicad."):
        raise RpcError(
            INVALID_PARAMS,
            f"tools/call: unknown tool '{name}'. Expected 'kicad.<op_type>'.",
        )
    op_type = name[len("kicad."):]
    registered = set(_registered_operations())
    if op_type not in registered:
        raise RpcError(
            INVALID_PARAMS,
            f"tools/call: unknown operation '{op_type}'. "
            f"Use tools/list to see available operations.",
        )

    # Lazy-load the executor and dispatch.
    try:
        executor = ctx.executor()
        if executor is None:
            # No factory wired — Phase 162 dev mode without kicad_agent installed.
            return {
                "content": [{
                    "type": "text",
                    "text": _json.dumps({
                        "success": False,
                        "error": "OperationExecutor unavailable (kicad_agent not bundled)",
                    }),
                }],
                "isError": True,
            }
        # Validate the operation through Pydantic, then execute.
        from kicad_agent.ops.schema import Operation  # type: ignore[import-not-found]
        op = Operation.model_validate(arguments)
        # Patch the op_type if the caller passed name=kicad.X but arguments
        # didn't include op_type. MCP clients may rely solely on `name`.
        if op.root.op_type != op_type:
            # Re-validate with the name-derived op_type to ensure consistency.
            arguments_with_type = dict(arguments)
            arguments_with_type.setdefault("root", {})
            arguments_with_type["root"]["op_type"] = op_type
            op = Operation.model_validate(arguments_with_type)
        result = executor.execute(op)
        return {
            "content": [{
                "type": "text",
                "text": _json.dumps(result, default=str),
            }],
            "isError": False,
        }
    except Exception as exc:  # noqa: BLE001 — wrap every executor failure
        if ctx.audit is not None:
            ctx.audit.log_event(
                "tools_call_error",
                op_type=op_type,
                error=f"{type(exc).__name__}: {exc}",
            )
        return {
            "content": [{
                "type": "text",
                "text": _json.dumps({
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "op_type": op_type,
                }),
            }],
            "isError": True,
        }


# =============================================================================
# Phase 170 — Verification handlers (GOV-03, GOV-04, GOV-05)
# =============================================================================
#
# These handlers wrap the existing Python validation_gates.py infrastructure
# for Swift consumption via MCP. The Swift VerificationLoop drives them:
#
#   1. kicad.snapshot   → Snapshot files before op executes (GOV-05)
#   2. kicad.pre_check  → Validate op + args against registry (GOV-03)
#   3. <op executes via tools/call>
#   4. kicad.post_check → Run ERC/DRC on affected files (GOV-04)
#   5. kicad.restore    → On post_check failure, restore snapshot (GOV-05)
#
# All four return structured dicts so the Swift side can render a
# VerificationOutcome with full stage history.

# File type → suffix mapping. Mirrors IntentGate catalog.
_KICAD_FILE_SUFFIXES = {
    "kicad_sch": ".kicad_sch",
    "kicad_pcb": ".kicad_pcb",
    "kicad_sym": ".kicad_sym",
    "kicad_mod": ".kicad_mod",
    "kicad_pro": ".kicad_pro",
    "kicad_dru": ".kicad_dru",
    "kicad_prj": ".kicad_prj",
}


def kicad_pre_check(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Pre-op verification gate (GOV-03).

    Validates that the op:
      - Exists in the registry
      - Target file types match allowed types for the op
      - Required arguments are present

    Params:
        {"op_type": "add_component",
         "args": {"target_file": "board.kicad_sch", ...}}

    Returns:
        {"decision": "allow" | "warn" | "block",
         "reasons": [str, ...],
         "op_type": str,
         "checks": {"op_known": bool, "file_type_ok": bool, "args_present": bool}}

    The Swift side maps decisions: allow → execute, warn → execute+journal,
    block → reject the call.
    """
    params = require_dict(params, "kicad.pre_check")
    op_type = require_field(params, "op_type", "kicad.pre_check")
    if not isinstance(op_type, str):
        raise RpcError(INVALID_PARAMS, "kicad.pre_check: 'op_type' must be a string")
    args = params.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "kicad.pre_check: 'args' must be an object")

    checks: dict[str, bool] = {
        "op_known": True,
        "file_type_ok": True,
        "args_present": True,
    }
    reasons: list[str] = []

    # 1. Op known?
    registered = set(_registered_operations())
    if op_type not in registered:
        checks["op_known"] = False
        reasons.append(f"unknown op_type '{op_type}'")

    # 2. Target file type matches op category.
    target_file = args.get("target_file") or args.get("target_files")
    files_to_check: list[str] = []
    if isinstance(target_file, str):
        files_to_check = [target_file]
    elif isinstance(target_file, list):
        files_to_check = [str(f) for f in target_file if isinstance(f, str)]
    if files_to_check:
        # Path traversal check (T-170-01 mitigation).
        for f in files_to_check:
            if ".." in Path(f).parts:
                checks["file_type_ok"] = False
                reasons.append(f"refused path with '..' segment: {f}")
                break
        # File-type check: only kicad-native suffixes allowed.
        if checks["file_type_ok"]:
            for f in files_to_check:
                suffix = Path(f).suffix.lower()
                if suffix and suffix not in _KICAD_FILE_SUFFIXES.values():
                    checks["file_type_ok"] = False
                    reasons.append(
                        f"target_file '{f}' has unsupported suffix '{suffix}' "
                        f"(expected one of {sorted(set(_KICAD_FILE_SUFFIXES.values()))})"
                    )
                    break

    # 3. Required args present (target_file or target_files for mutating ops).
    readonly_ops = {
        "query_components", "query_nets", "query_drc", "query_erc",
        "generate_bom", "parse_erc", "list_operations", "list_lib_symbols",
        "kicad_cli_check", "health_check", "ping",
    }
    if op_type not in readonly_ops and not target_file:
        # Some ops legitimately take target_files plural; check args_present.
        if not args.get("target_files"):
            checks["args_present"] = False
            reasons.append(
                f"mutating op '{op_type}' requires target_file or target_files"
            )

    # Decision: block if any check failed.
    if all(checks.values()):
        decision = "allow"
    elif checks["op_known"] and checks["file_type_ok"]:
        # Soft fail (missing arg on a mutating op that the executor might
        # accept for other reasons) — warn but allow.
        decision = "warn"
    else:
        decision = "block"

    if ctx.audit is not None:
        ctx.audit.log_event(
            "pre_check",
            op_type=op_type,
            decision=decision,
            reasons=reasons,
        )

    return {
        "decision": decision,
        "reasons": reasons,
        "op_type": op_type,
        "checks": checks,
    }


def kicad_post_check(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Post-op verification gate (GOV-04).

    Runs deterministic validation checks on the affected files:
      - Schematic ops → ERC via kicad-cli
      - PCB ops → DRC via kicad-cli
      - Cross-file ops → both

    Params:
        {"op_type": "add_component",
         "files": ["board.kicad_sch"],
         "require_erc": true,
         "require_drc": false,
         "semantic_check": true}

    Returns:
        {"decision": "passed" | "failed" | "indeterminate",
         "erc": {...} | null,
         "drc": {...} | null,
         "failures": [str, ...]}

    The Swift side treats `failed` as a rollback trigger (GOV-05).
    `indeterminate` means we couldn't run a check (kicad-cli missing,
    file disappeared) — the journal records it but no rollback fires.
    """
    params = require_dict(params, "kicad.post_check")
    op_type = require_field(params, "op_type", "kicad.post_check")
    if not isinstance(op_type, str):
        raise RpcError(INVALID_PARAMS, "kicad.post_check: 'op_type' must be a string")
    files = params.get("files", [])
    if files is None:
        files = []
    if not isinstance(files, list):
        raise RpcError(INVALID_PARAMS, "kicad.post_check: 'files' must be an array")
    require_erc = bool(params.get("require_erc", True))
    require_drc = bool(params.get("require_drc", True))

    failures: list[str] = []
    erc_result: dict[str, Any] | None = None
    drc_result: dict[str, Any] | None = None

    sch_files = [str(f) for f in files if str(f).endswith(".kicad_sch")]
    pcb_files = [str(f) for f in files if str(f).endswith(".kicad_pcb")]

    # ERC for schematic files.
    if require_erc and sch_files:
        erc_result = _run_erc_safe(sch_files)
        if erc_result is None:
            # kicad-cli unavailable or exception — indeterminate.
            pass
        elif not erc_result.get("clean", False):
            err_count = erc_result.get("error_count", 0)
            failures.append(
                f"ERC failed on {len(sch_files)} file(s): {err_count} errors"
            )

    # DRC for PCB files.
    if require_drc and pcb_files:
        drc_result = _run_drc_safe(pcb_files)
        if drc_result is None:
            pass
        elif not drc_result.get("clean", False):
            err_count = drc_result.get("error_count", 0)
            failures.append(
                f"DRC failed on {len(pcb_files)} file(s): {err_count} errors"
            )

    # Decision.
    if not failures:
        # If both checks were skipped or returned None, indeterminate.
        ran_a_check = (
            (require_erc and sch_files and erc_result is not None)
            or (require_drc and pcb_files and drc_result is not None)
        )
        decision = "passed" if ran_a_check else "indeterminate"
    else:
        decision = "failed"

    if ctx.audit is not None:
        ctx.audit.log_event(
            "post_check",
            op_type=op_type,
            decision=decision,
            failures=failures,
        )

    return {
        "decision": decision,
        "erc": erc_result,
        "drc": drc_result,
        "failures": failures,
    }


def kicad_snapshot(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Capture a file snapshot for rollback (GOV-05).

    Params:
        {"files": ["/abs/path/to/file.kicad_sch", ...],
         "base_dir": "/abs/path/to/project"}  # optional traversal defense

    Returns:
        {"snapshot_id": "<uuid>",
         "files_snapshotted": int,
         "snapshot_dir": "<path>"}

    The Swift side holds the snapshot_id and passes it to kicad.restore
    if the post-op verification fails.
    """
    import uuid as _uuid

    params = require_dict(params, "kicad.snapshot")
    files = require_field(params, "files", "kicad.snapshot")
    if not isinstance(files, list) or not all(
        isinstance(f, str) for f in files
    ):
        raise RpcError(
            INVALID_PARAMS,
            "kicad.snapshot: 'files' must be an array of strings",
        )
    base_dir = params.get("base_dir")
    if base_dir is not None and not isinstance(base_dir, str):
        raise RpcError(
            INVALID_PARAMS,
            "kicad.snapshot: 'base_dir' must be a string if provided",
        )

    try:
        snapshot = Snapshot.create(files=files, base_dir=base_dir)
    except SnapshotError as exc:
        if ctx.audit is not None:
            ctx.audit.log_event("snapshot_failed", error=str(exc), files=files)
        raise RpcError(INVALID_PARAMS, f"kicad.snapshot: {exc}") from exc

    snapshot_id = str(_uuid.uuid4())
    # Stash on ctx so kicad.restore can find it.
    if not hasattr(ctx, "_verification_snapshots"):
        ctx._verification_snapshots = {}  # type: ignore[attr-defined]
    ctx._verification_snapshots[snapshot_id] = snapshot  # type: ignore[attr-defined]

    if ctx.audit is not None:
        ctx.audit.log_event(
            "snapshot_captured",
            snapshot_id=snapshot_id,
            files=files,
        )

    return {
        "snapshot_id": snapshot_id,
        "files_snapshotted": len(snapshot.manifest),
        "snapshot_dir": str(snapshot.snapshot_dir),
    }


def kicad_restore(params: Any, ctx: HandlerContext) -> dict[str, Any]:
    """Restore files from a snapshot (GOV-05).

    Params:
        {"snapshot_id": "<uuid>"}

    Returns:
        {"restored": int, "removed": int, "skipped": int}

    Raises RpcError if the snapshot_id is unknown or restore fails.
    """
    params = require_dict(params, "kicad.restore")
    snapshot_id = require_field(params, "snapshot_id", "kicad.restore")
    if not isinstance(snapshot_id, str):
        raise RpcError(
            INVALID_PARAMS,
            "kicad.restore: 'snapshot_id' must be a string",
        )

    snapshots = getattr(ctx, "_verification_snapshots", {})
    snapshot = snapshots.get(snapshot_id)
    if snapshot is None:
        raise RpcError(
            INVALID_PARAMS,
            f"kicad.restore: unknown snapshot_id '{snapshot_id}'",
        )

    try:
        summary = snapshot.restore()
    except SnapshotError as exc:
        if ctx.audit is not None:
            ctx.audit.log_event(
                "restore_failed",
                snapshot_id=snapshot_id,
                error=str(exc),
            )
        raise RpcError(INVALID_PARAMS, f"kicad.restore: {exc}") from exc

    # Cleanup the snapshot directory after a successful restore.
    snapshot.close()
    snapshots.pop(snapshot_id, None)

    if ctx.audit is not None:
        ctx.audit.log_event(
            "restore_completed",
            snapshot_id=snapshot_id,
            summary=summary,
        )

    return summary


# =============================================================================
# Phase 170 internal helpers (ERC/DRC wrappers)
# =============================================================================

def _run_erc_safe(sch_files: list[str]) -> dict[str, Any] | None:
    """Run ERC on each schematic file. Aggregates errors across files.

    Returns None if kicad-cli unavailable or every file errored.
    Returns aggregated dict:
        {"clean": bool, "error_count": int, "warning_count": int,
         "per_file": [{path, clean, error_count, error_message}, ...]}
    """
    try:
        from kicad_agent.validation.erc_drc import run_erc  # type: ignore[import-not-found]
    except Exception:
        return None

    per_file: list[dict[str, Any]] = []
    total_errors = 0
    total_warnings = 0
    all_clean = True
    for sch in sch_files:
        try:
            result = run_erc(Path(sch))
        except Exception as exc:  # noqa: BLE001 — best-effort per file
            per_file.append({
                "path": sch,
                "clean": False,
                "error_count": 0,
                "error_message": f"{type(exc).__name__}: {exc}",
            })
            all_clean = False
            continue
        per_file.append({
            "path": sch,
            "clean": result.passed,
            "error_count": result.error_count,
            "warning_count": result.warning_count,
            "error_message": result.error_message,
        })
        total_errors += result.error_count
        total_warnings += result.warning_count
        if not result.passed:
            all_clean = False

    return {
        "clean": all_clean,
        "error_count": total_errors,
        "warning_count": total_warnings,
        "per_file": per_file,
    }


def _run_drc_safe(pcb_files: list[str]) -> dict[str, Any] | None:
    """Run DRC on each PCB file. Aggregates errors across files.

    Returns None if kicad-cli unavailable or every file errored.
    """
    try:
        from kicad_agent.validation.erc_drc import run_drc  # type: ignore[import-not-found]
    except Exception:
        return None

    per_file: list[dict[str, Any]] = []
    total_errors = 0
    total_violations = 0
    all_clean = True
    for pcb in pcb_files:
        try:
            result = run_drc(Path(pcb))
        except Exception as exc:  # noqa: BLE001 — best-effort per file
            per_file.append({
                "path": pcb,
                "clean": False,
                "error_count": 0,
                "error_message": f"{type(exc).__name__}: {exc}",
            })
            all_clean = False
            continue
        # DrcResult.passed / .error_count / .violation_count / .error_message
        error_count = getattr(result, "error_count", 0) or 0
        violation_count = getattr(result, "violation_count", 0) or 0
        per_file.append({
            "path": pcb,
            "clean": result.passed,
            "error_count": error_count,
            "violation_count": violation_count,
            "error_message": getattr(result, "error_message", None),
        })
        total_errors += error_count
        total_violations += violation_count
        if not result.passed:
            all_clean = False

    return {
        "clean": all_clean,
        "error_count": total_errors,
        "violation_count": total_violations,
        "per_file": per_file,
    }


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
    # Phase 167 — MCP lifecycle (per modelcontextprotocol.io/specification)
    "initialize": initialize,
    "initialized": initialized,
    "tools/list": tools_list,
    "tools/call": tools_call,
    # Phase 170 — Verification loop integration (GOV-03, GOV-04, GOV-05)
    "kicad.pre_check": kicad_pre_check,
    "kicad.post_check": kicad_post_check,
    "kicad.snapshot": kicad_snapshot,
    "kicad.restore": kicad_restore,
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


def _build_tool_descriptor(op_name: str) -> dict[str, Any] | None:
    """Construct an MCP tool descriptor for a kicad-agent operation.

    Returns None if the operation isn't importable (skip silently — the
    tools/list response should be robust to individual op failures).

    Descriptor shape (per MCP spec):
        {"name": "kicad.<op>",
         "description": "<one-line description>",
         "inputSchema": <JSON schema>}
    """
    try:
        from kicad_agent.ops import registry as reg  # type: ignore[import-not-found]
    except Exception:
        # No registry — return a minimal descriptor with the op name only.
        return {
            "name": f"kicad.{op_name}",
            "description": f"kicad-agent operation: {op_name}",
            "inputSchema": {"type": "object", "additionalProperties": True},
        }

    # Look up the op metadata in the registry. The registry values are
    # OpMeta dataclass/pydantic instances (not dicts), so use getattr.
    registry_dict = getattr(reg, "OPERATION_REGISTRY", {}) or {}
    op_meta = registry_dict.get(op_name)

    if op_meta is not None:
        description = (
            getattr(op_meta, "description", None)
            or getattr(op_meta, "summary", None)
            or f"kicad-agent operation: {op_name}"
        )
    else:
        description = f"kicad-agent operation: {op_name}"

    # Try to extract JSON schema from the Pydantic model for this op.
    input_schema: dict[str, Any]
    try:
        from kicad_agent.ops.schema import Operation  # type: ignore[import-not-found]
        # Pydantic v2: construct a minimal validated Operation with this op_type,
        # then export its JSON schema. This is heavy (validates the discriminated
        # union), so we cache it via the op's model_json_schema() instead.
        # Phase 167: return a permissive schema; Phase 168+ will tighten.
        input_schema = _op_input_schema(op_name) or {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "root": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": f"Operation root for {op_name}",
                }
            },
        }
    except Exception:
        input_schema = {"type": "object", "additionalProperties": True}

    return {
        "name": f"kicad.{op_name}",
        "description": description,
        "inputSchema": input_schema,
    }


def _op_input_schema(op_name: str) -> dict[str, Any] | None:
    """Best-effort JSON schema extraction for an op's input model.

    Pydantic v2 supports model_json_schema() per model. We look up the
    specific model class for the op (via the Operation discriminated
    union) and extract its schema. Returns None on any failure — callers
    fall back to a permissive schema.
    """
    try:
        from kicad_agent.ops.schema import Operation  # type: ignore[import-not-found]
        # The discriminated union lives in Operation.model_fields['root'].annotation.
        # Walk the union to find the matching model by op_type literal.
        annotation = Operation.model_fields["root"].annotation
        # Annotated[Union[...], ...] — extract the Union members.
        from typing import get_args, get_origin, Union  # type: ignore[import-not-found]
        args = get_args(annotation)
        # Some Python versions wrap in Annotated; flatten.
        candidates = []
        for a in args:
            origin = get_origin(a)
            if origin is None:
                candidates.append(a)
        for model_cls in candidates:
            # Skip NoneType (the | None in Optional).
            if model_cls is type(None):
                continue
            # Each candidate is a Pydantic model. Inspect its root.op_type Literal.
            try:
                root_field = model_cls.model_fields.get("root")
                if root_field is None:
                    continue
                root_annotation = root_field.annotation
                root_args = get_args(root_annotation)
                for inner in root_args:
                    if get_origin(inner) is type(None):
                        continue
                    inner_args = get_args(inner)
                    # Find the Literal[...] for op_type.
                    for sub in inner_args:
                        sub_args = get_args(sub)
                        for lit in sub_args:
                            lit_args = get_args(lit)
                            for val in lit_args:
                                if val == op_name:
                                    return inner.model_json_schema()
            except Exception:
                continue
        return None
    except Exception:
        return None


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
