"""
test_audit_log.py — JSONL audit log tests.

Phase 162 — Python Daemon Bundling.

Tests cover:
    - JSONL format (one record per line, parseable)
    - Required fields (ts, epoch, event)
    - Caller-supplied fields merge correctly
    - Never raises (broken stream, closed handle)
    - Convenience methods (log_spawn, log_shutdown, etc.)
    - File-backed logger durability (open_file_logger)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from audit_log import AuditLogger, get_default_logger, open_file_logger


# =============================================================================
# AuditLogger core
# =============================================================================

class TestAuditLoggerBasic:
    def test_log_event_writes_one_line(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("test_event")
        out = stream.getvalue()
        lines = [l for l in out.split("\n") if l]
        assert len(lines) == 1

    def test_log_event_emits_valid_json(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("test_event", foo="bar", count=42)
        line = stream.getvalue().strip()
        record = json.loads(line)  # must not raise
        assert record["event"] == "test_event"
        assert record["foo"] == "bar"
        assert record["count"] == 42

    def test_required_fields_present(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("anything")
        record = json.loads(stream.getvalue().strip())
        assert "ts" in record
        assert "epoch" in record
        assert "event" in record
        assert record["event"] == "anything"

    def test_timestamp_is_iso_format(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("ev")
        record = json.loads(stream.getvalue().strip())
        # ISO-8601 with trailing Z (UTC).
        ts = record["ts"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_epoch_is_float(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("ev")
        record = json.loads(stream.getvalue().strip())
        assert isinstance(record["epoch"], float)
        assert record["epoch"] > 1_600_000_000  # sanity: after 2020


# =============================================================================
# Never raises
# =============================================================================

class TestAuditLoggerNeverRaises:
    def test_broken_stream_does_not_raise(self) -> None:
        class BrokenStream:
            def write(self, _data: str) -> int:
                raise OSError("broken")
            def flush(self) -> None:
                raise OSError("broken")
            def fileno(self) -> int:
                raise OSError("no fileno")

        logger = AuditLogger(stream=BrokenStream())  # type: ignore[arg-type]
        # This must not raise.
        logger.log_event("should_not_raise")

    def test_closed_logger_does_not_raise(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.close()
        # After close, log_event must be a no-op, not an error.
        logger.log_event("after_close")
        assert stream.getvalue() == ""

    def test_close_is_idempotent(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.close()
        logger.close()  # second close must not raise


# =============================================================================
# Convenience methods
# =============================================================================

class TestConvenienceMethods:
    def test_log_spawn(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_spawn(pid=12345, executable="/path/to/daemon")
        rec = json.loads(stream.getvalue().strip())
        assert rec["event"] == "spawn"
        assert rec["pid"] == 12345
        assert rec["executable"] == "/path/to/daemon"

    def test_log_shutdown(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_shutdown(pid=123, status=0)
        rec = json.loads(stream.getvalue().strip())
        assert rec["event"] == "shutdown"
        assert rec["status"] == 0

    def test_log_crash(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_crash(pid=123, status=139, reason="segfault")
        rec = json.loads(stream.getvalue().strip())
        assert rec["event"] == "crash"
        assert rec["status"] == 139
        assert rec["reason"] == "segfault"

    def test_log_force_kill(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_force_kill(pid=99, timeout_s=5.0)
        rec = json.loads(stream.getvalue().strip())
        assert rec["event"] == "force_kill"
        assert rec["timeout_s"] == 5.0

    def test_log_watchdog_timeout(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_watchdog_timeout(pid=7, idle_s=30.0)
        rec = json.loads(stream.getvalue().strip())
        assert rec["event"] == "watchdog_timeout"
        assert rec["idle_s"] == 30.0

    def test_log_rpc_minimal(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_rpc(method="ping")
        rec = json.loads(stream.getvalue().strip())
        assert rec["event"] == "rpc"
        assert rec["method"] == "ping"

    def test_log_rpc_full(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_rpc(
            method="execute",
            request_id="abc",
            duration_ms=12.5,
            error="bad params",
        )
        rec = json.loads(stream.getvalue().strip())
        assert rec["method"] == "execute"
        assert rec["id"] == "abc"
        assert rec["duration_ms"] == 12.5
        assert rec["error"] == "bad params"


# =============================================================================
# JSONL format invariants
# =============================================================================

class TestJsonlFormat:
    def test_multiple_events_each_on_own_line(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        for i in range(10):
            logger.log_event("ev", idx=i)
        lines = [l for l in stream.getvalue().split("\n") if l]
        assert len(lines) == 10
        for line in lines:
            json.loads(line)  # all parseable

    def test_records_have_increasing_epochs(self) -> None:
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("first")
        logger.log_event("second")
        logger.log_event("third")
        lines = [l for l in stream.getvalue().split("\n") if l]
        epochs = [json.loads(l)["epoch"] for l in lines]
        assert epochs == sorted(epochs)  # monotonic non-decreasing

    def test_compact_separator_form(self) -> None:
        """JSONL should use compact separators (no spaces) for line efficiency."""
        stream = io.StringIO()
        logger = AuditLogger(stream=stream)
        logger.log_event("e", a=1, b=2)
        line = stream.getvalue().strip()
        # Compact form: no space after , or :
        assert ", " not in line
        assert ": " not in line


# =============================================================================
# Default logger
# =============================================================================

class TestDefaultLogger:
    def test_get_default_logger_returns_singleton(self) -> None:
        l1 = get_default_logger()
        l2 = get_default_logger()
        assert l1 is l2

    def test_default_logger_writes_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Reset singleton to pick up the new stderr.
        import audit_log
        audit_log._default_logger = None
        logger = get_default_logger()
        logger.log_event("captured_event")
        captured = capsys.readouterr()
        assert "captured_event" in captured.err


# =============================================================================
# File-backed logger
# =============================================================================

class TestFileLogger:
    def test_open_file_logger_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "audit" / "daemon.jsonl"
        logger = open_file_logger(path)
        logger.log_event("file_event", foo="bar")
        logger.close()
        assert path.exists()
        line = path.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["event"] == "file_event"
        assert rec["foo"] == "bar"

    def test_open_file_logger_appends(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        # First writer.
        l1 = open_file_logger(path)
        l1.log_event("first")
        l1.close()
        # Second writer — should append, not truncate.
        l2 = open_file_logger(path)
        l2.log_event("second")
        l2.close()
        lines = [l for l in path.read_text(encoding="utf-8").split("\n") if l]
        assert len(lines) == 2
        events = [json.loads(l)["event"] for l in lines]
        assert events == ["first", "second"]

    def test_open_file_logger_creates_parent_dir(self, tmp_path: Path) -> None:
        path = tmp_path / "deeply" / "nested" / "dir" / "audit.jsonl"
        logger = open_file_logger(path)
        logger.log_event("nested")
        logger.close()
        assert path.exists()
