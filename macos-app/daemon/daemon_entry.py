"""
daemon_entry.py — PyInstaller entry point for the bundled volta daemon.

Phase 162 — Python Daemon Bundling.

This is the single entry point PyInstaller packages into the standalone
macOS app bundle. It wires stdio JSON-RPC over stdin/stdout (Phase 167
upgrades to full MCP).

Module split (Phase 162 refactor):
    protocol.py   — JSON-RPC envelopes, RpcError, parse_request, serialize
    handlers.py   — ping, list_operations, health_check, shutdown + registry
    audit_log.py  — append-only JSONL audit trail with fsync
    daemon_entry.py (this file) — asyncio main loop, signal handling, IPC

Hardening (per PITFALLS.md Pitfall 2 — stdio buffering deadlock):
    - PYTHONUNBUFFERED=1 enforced programmatically; callers do not need
      to set it externally. stdout is reconfigured to line buffering.
    - Heartbeat line emitted every 10 seconds so the Swift ProcessManager
      watchdog can detect a live daemon without a full RPC round-trip.

Lifecycle:
    - Construct HandlerContext (lazy executor, audit logger).
    - Install SIGTERM/SIGINT handlers → graceful shutdown, exit 0.
    - Loop reading line-delimited JSON-RPC 2.0 requests from stdin.

Exit codes:
    0 = clean shutdown (SIGTERM/SIGINT/EOF on stdin)
    1 = unrecoverable error during startup
    2 = I/O error on stdio pipes

JSON-RPC wire format (line-delimited, UTF-8, \\n separator):

    Request:
        {"jsonrpc":"2.0","id":"<uuid>","method":"ping","params":{}}

    Response:
        {"jsonrpc":"2.0","id":"<uuid>","result":{"pong":true}}

    Error:
        {"jsonrpc":"2.0","id":"<uuid>","error":{"code":-32601,"message":"..."}}
"""

from __future__ import annotations

import asyncio
import io
import os
import signal
import sys
import time
from typing import Any

# --- PYTHONUNBUFFERED enforcement (Pitfall 2 prevention) ---------------------
# Force line buffering on stdout. Belt + suspenders: callers SHOULD set
# PYTHONUNBUFFERED=1 too (and ProcessManager.spawn does), but we cannot trust
# the environment alone.
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    # Python 3.7+. reconfigure is the supported way to flip buffering.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    # Fallback for runtimes without reconfigure. Replace streams with
    # line-buffered wrappers so we never block the Swift reader.
    sys.stdout = io.TextIOWrapper(  # type: ignore[assignment]
        sys.stdout.buffer, encoding="utf-8", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(  # type: ignore[assignment]
        sys.stderr.buffer, encoding="utf-8", line_buffering=True
    )

# --- sys.path bootstrap ------------------------------------------------------
# PyInstaller bundles the volta package via hidden imports; this path
# manipulation only matters during development (`python daemon_entry.py`).
# At runtime under PyInstaller, the package is already importable from the
# frozen stdlib path. This block is a no-op in frozen mode.
if not getattr(sys, "frozen", False):
    from pathlib import Path
    _REPO_ROOT = Path(__file__).resolve().parents[3]
    _SRC = _REPO_ROOT / "src"
    if _SRC.exists() and str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    # Also allow sibling module imports (protocol.py, handlers.py, audit_log.py)
    _HERE = Path(__file__).resolve().parent
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))


# =============================================================================
# Module imports (after sys.path bootstrap)
# =============================================================================

from protocol import (  # noqa: E402 — sys.path bootstrap above is intentional
    RpcError,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INTERNAL_ERROR,
    make_result,
    make_error,
    make_notification,
    parse_request,
    serialize,
)
from handlers import (  # noqa: E402
    HandlerContext,
    get_handler,
    ping as handle_ping,
    health_check as handle_health_check,
    list_operations as handle_list_operations,
    shutdown as handle_shutdown,
)
from audit_log import AuditLogger, get_default_logger  # noqa: E402


# =============================================================================
# Daemon supervisor — owns the HandlerContext and heartbeat loop
# =============================================================================

class VoltaDaemon:
    """Owns the HandlerContext, heartbeat timer, and shutdown flag.

    The asyncio main loop (amain, below) constructs one of these and
    passes it to the request reader. Handlers receive the HandlerContext
    directly; the heartbeat timer reads the daemon's `maybe_heartbeat`.
    """

    HEARTBEAT_INTERVAL_S = 10.0

    def __init__(self, ctx: HandlerContext, audit: AuditLogger) -> None:
        self.ctx = ctx
        self.audit = audit
        self._last_heartbeat = time.monotonic()

    @property
    def shutdown_requested(self) -> bool:
        return self.ctx.shutdown_requested

    def request_shutdown(self) -> None:
        self.ctx.request_shutdown()

    def maybe_heartbeat(self, force: bool = False) -> bool:
        """Emit a heartbeat notification if interval elapsed.

        Returns True if a heartbeat was emitted. The Swift ProcessManager
        resets its watchdog on receipt (no RPC round-trip required).
        """
        now = time.monotonic()
        if not (force or (now - self._last_heartbeat) >= self.HEARTBEAT_INTERVAL_S):
            return False
        payload = make_notification(
            "heartbeat",
            {"epoch": time.time(), "pid": os.getpid()},
        )
        try:
            sys.stdout.write(serialize(payload) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            # Swift side gone — main loop will notice EOF and exit.
            return False
        self._last_heartbeat = now
        return True


# =============================================================================
# Request dispatch
# =============================================================================

async def dispatch(daemon: VoltaDaemon, raw_request: str) -> dict[str, Any] | None:
    """Parse + dispatch one raw request line.

    Returns:
        Response payload dict, or None if the request was a notification
        (no reply expected).

    All exceptions are caught here and converted to error payloads —
    the caller never sees an unhandled exception from a handler.
    """
    # Parse
    try:
        request_id, method, params = parse_request(raw_request)
    except RpcError as exc:
        daemon.audit.log_rpc(method="(parse)", error=exc.message)
        return exc.to_payload(None)

    # Heartbeat notification (no id) — log and drop.
    # The Swift side normally sends requests with ids, but defensive code
    # for the rare bidirectional heartbeat case.
    if request_id is None and method == "heartbeat":
        return None

    # Method lookup
    handler = get_handler(method)
    if handler is None:
        err = RpcError(METHOD_NOT_FOUND, f"Method '{method}' not found")
        daemon.audit.log_rpc(method=method, request_id=str(request_id), error=err.message)
        return err.to_payload(request_id)

    # Execute (sync handler in thread executor → non-blocking)
    start = time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: handler(params, daemon.ctx)
        )
        duration_ms = (time.monotonic() - start) * 1000.0
        daemon.audit.log_rpc(
            method=method,
            request_id=str(request_id),
            duration_ms=round(duration_ms, 2),
        )
        # Handler-returned None means "notification, no reply" — used by
        # MCP `initialized` and other notification handlers. Phase 167.
        if result is None:
            return None
        return make_result(request_id, result)
    except RpcError as exc:
        daemon.audit.log_rpc(
            method=method,
            request_id=str(request_id),
            error=exc.message,
        )
        return exc.to_payload(request_id)
    except Exception as exc:  # noqa: BLE001 — surface every error to caller
        err = RpcError(
            INTERNAL_ERROR,
            f"Unhandled exception in '{method}': {exc}",
            data={"type": type(exc).__name__},
        )
        daemon.audit.log_rpc(
            method=method,
            request_id=str(request_id),
            error=f"{type(exc).__name__}: {exc}",
        )
        return err.to_payload(request_id)


# =============================================================================
# Main loop
# =============================================================================

async def read_requests(stream: asyncio.StreamReader, daemon: VoltaDaemon) -> None:
    """Read line-delimited JSON-RPC requests from stdin until EOF."""
    while not daemon.shutdown_requested:
        try:
            line = await stream.readline()
        except (asyncio.CancelledError, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[daemon] stdin read error: {exc}\n")
            sys.stderr.flush()
            daemon.audit.log_event("stdin_read_error", error=str(exc))
            daemon.request_shutdown()
            return

        if not line:
            # EOF — Swift closed stdin. Shut down cleanly.
            sys.stderr.write("[daemon] stdin EOF, exiting\n")
            sys.stderr.flush()
            daemon.audit.log_event("stdin_eof")
            daemon.request_shutdown()
            return

        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue

        response = await dispatch(daemon, text)
        if response is not None:
            await emit(response)

        # Cheap heartbeat: opportunistically emit on every iteration.
        daemon.maybe_heartbeat()


async def emit(payload: dict[str, Any]) -> None:
    """Write one JSON-RPC payload to stdout, line-delimited."""
    try:
        sys.stdout.write(serialize(payload) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Swift side gone. Caller will notice EOF and exit.
        sys.stderr.write("[daemon] stdout broken pipe\n")
        sys.stderr.flush()


async def heartbeat_loop(daemon: VoltaDaemon) -> None:
    """Idle heartbeat emitter so the watchdog sees traffic even with no RPCs."""
    while not daemon.shutdown_requested:
        await asyncio.sleep(1.0)
        daemon.maybe_heartbeat()


async def amain() -> int:
    # Construct audit logger (stderr sink during Phase 162; Phase 168
    # wires this to a per-project audit file).
    audit = get_default_logger()

    # Construct handler context. Executor is lazy — only loaded when a
    # caller invokes a handler that needs it.
    def _executor_factory():  # type: ignore[no-untyped-def]
        from volta.ops.executor import OperationExecutor  # type: ignore[import-not-found]
        return OperationExecutor()

    ctx = HandlerContext(executor_factory=_executor_factory, audit=audit)
    daemon = VoltaDaemon(ctx=ctx, audit=audit)

    audit.log_event("daemon_start", pid=os.getpid(), python=sys.version.split()[0])

    # Install signal handlers for graceful shutdown.
    def _on_signal(signum: int, _frame: Any) -> None:
        sys.stderr.write(f"[daemon] received signal {signum}, requesting shutdown\n")
        sys.stderr.flush()
        audit.log_event("signal", signum=signum)
        daemon.request_shutdown()

    # SIGTERM is what ProcessManager sends first; SIGINT is for dev runs.
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            # Not in main thread or not supported; ignore.
            pass

    loop = asyncio.get_running_loop()

    # Hook stdin into the asyncio loop. readline() returns b"" on EOF.
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    heartbeat_task = asyncio.create_task(heartbeat_loop(daemon), name="heartbeat")
    reader_task = asyncio.create_task(read_requests(reader, daemon), name="reader")

    # Wait for either the reader to finish (EOF / shutdown) or signal-induced exit.
    done, pending = await asyncio.wait(
        {reader_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    # Drain cancellations.
    for task in pending:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    audit.log_event("daemon_exit", status="clean")
    sys.stderr.write("[daemon] clean exit\n")
    sys.stderr.flush()
    return 0


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[daemon] fatal: {exc}\n")
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
