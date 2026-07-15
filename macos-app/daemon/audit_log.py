"""
audit_log.py — Append-only JSONL audit log for the bundled daemon.

Phase 162 — Python Daemon Bundling.

Extends the existing `src/volta/routing/audit.py` pattern: every
event is written as one JSON object per line and fsync'd before the
caller continues. This gives us crash-durable audit trails for daemon
lifecycle events (spawn, crash, watchdog kill, RPC errors).

Phase 168 will hook every RPC through `log_event("rpc", ...)`; Phase 162
uses it for daemon lifecycle only.

Log format (one JSON object per line, UTF-8, \\n separator):

    {"ts": "2026-07-07T22:00:00.123Z", "event": "spawn", "pid": 12345, ...}
    {"ts": "2026-07-07T22:00:05.001Z", "event": "rpc", "method": "ping", ...}

JSONL is chosen over CSV/JSON-array because:
    - Append-only friendly (no array close bracket needed)
    - Line-oriented → grep/awk friendly, one record per line
    - Streamable (reader doesn't need to load entire file)
    - Crash-safe (partial last line is the only loss on power failure)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


# =============================================================================
# AuditLogger
# =============================================================================

class AuditLogger:
    """Append-only JSONL audit log with fsync durability.

    Each `log_event` call:
        1. Builds the record (timestamp + caller fields).
        2. Serializes to JSON on one line.
        3. Writes to the underlying file handle.
        4. Flushes Python's buffer.
        5. Calls os.fsync() on the file descriptor.

    fsync is the only way to force the kernel to push buffered writes to
    disk; without it, a power loss can lose the last several seconds of
    log lines even after a "successful" write().

    The logger never raises — a broken audit log must not bring down the
    daemon. All I/O errors are written to stderr and swallowed.
    """

    def __init__(self, stream: TextIO | None = None, owns_stream: bool = False) -> None:
        """Construct a logger writing to `stream`.

        Args:
            stream: Writable text stream. Defaults to sys.stderr (so logs
                surface during development). Production callers should pass
                a file handle opened in append mode.
            owns_stream: When True, close() will close the underlying stream.
                Set True only when the logger created the stream (e.g.
                open_file_logger). Caller-supplied streams (StringIO, stderr)
                are not closed — the caller owns their lifecycle.
        """
        self._stream: TextIO = stream if stream is not None else sys.stderr
        self._closed = False
        self._owns_stream = owns_stream

    # -- core API -------------------------------------------------------------
    def log_event(self, event: str, **fields: Any) -> None:
        """Append one audit record. Never raises."""
        if self._closed:
            return
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "epoch": time.time(),
            "event": event,
        }
        # Caller-supplied fields override defaults (except `ts`/`epoch`).
        record.update(fields)
        try:
            line = json.dumps(record, default=str, separators=(",", ":"))
            self._stream.write(line + "\n")
            self._stream.flush()
            _fsync(self._stream)
        except (BrokenPipeError, OSError, ValueError) as exc:
            # Last-resort: try stderr, but never propagate.
            try:
                sys.stderr.write(f"[audit_log] write failed: {exc}\n")
                sys.stderr.flush()
            except Exception:
                pass

    # -- convenience event types ----------------------------------------------
    def log_spawn(self, pid: int, executable: str) -> None:
        self.log_event("spawn", pid=pid, executable=executable)

    def log_shutdown(self, pid: int, status: int | None = None) -> None:
        self.log_event("shutdown", pid=pid, status=status)

    def log_crash(self, pid: int, status: int, reason: str = "unknown") -> None:
        self.log_event("crash", pid=pid, status=status, reason=reason)

    def log_force_kill(self, pid: int, timeout_s: float) -> None:
        self.log_event("force_kill", pid=pid, timeout_s=timeout_s)

    def log_watchdog_timeout(self, pid: int, idle_s: float) -> None:
        self.log_event("watchdog_timeout", pid=pid, idle_s=idle_s)

    def log_rpc(
        self,
        method: str,
        request_id: Any | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        fields: dict[str, Any] = {"method": method}
        if request_id is not None:
            fields["id"] = request_id
        if error is not None:
            fields["error"] = error
        if duration_ms is not None:
            fields["duration_ms"] = duration_ms
        self.log_event("rpc", **fields)

    # -- lifecycle ------------------------------------------------------------
    def close(self) -> None:
        """Close the underlying stream. Idempotent.

        Only closes the stream when this logger owns it (e.g. created by
        open_file_logger). Caller-supplied streams are flushed but left open.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._stream.flush()
            if self._owns_stream:
                self._stream.close()
        except Exception:
            pass


# =============================================================================
# Helpers
# =============================================================================

def _now_iso() -> str:
    """Current UTC timestamp in ISO-8601 with milliseconds."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _fsync(stream: TextIO) -> None:
    """Best-effort fsync on a text stream's underlying file descriptor.

    Swallows EBADF (file not open for writing) and EINVAL (underlying
    object doesn't support fsync, e.g. a StringIO during tests).
    """
    try:
        fd = stream.fileno()
        os.fsync(fd)
    except (OSError, ValueError, AttributeError):
        # StringIO, closed fd, pipe that doesn't support fsync — all fine.
        # The flush() call before this is the important part for in-process
        # readers; fsync only matters for cross-process durability.
        pass


# =============================================================================
# Default logger
# =============================================================================

# Default singleton writing to stderr. Callers can construct their own
# AuditLogger pointing at a real file when they want durability across
# process crashes. Phase 168 wires this to a per-project audit file.
_default_logger: AuditLogger | None = None


def get_default_logger() -> AuditLogger:
    """Return the process-wide default logger (stderr sink)."""
    global _default_logger
    if _default_logger is None:
        _default_logger = AuditLogger()
    return _default_logger


def open_file_logger(path: str | Path) -> AuditLogger:
    """Open (or create) an append-mode UTF-8 file and wrap it in an AuditLogger.

    The returned logger owns the file handle — close() will close it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered
    return AuditLogger(stream=stream, owns_stream=True)
