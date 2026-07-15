"""
test_dispatch.py — End-to-end dispatch tests against the daemon's main loop.

Phase 162 — Python Daemon Bundling.

These tests verify that the daemon_entry module's request dispatch
behaves correctly for the four built-in RPCs and for error cases.
They don't spawn the actual process — they call `dispatch()` directly
with a constructed `VoltaDaemon` instance.

Coverage:
    - ping → {"pong": true, ...}
    - list_operations → ops list
    - health_check → ok=true
    - shutdown → shutting_down=true + ctx flag set
    - parse error → -32700
    - method not found → -32601
    - audit log records RPC events
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest

# These tests use @pytest.mark.asyncio, which requires the pytest-asyncio
# plugin. The plugin is only installed in the project's required Python 3.11+
# env (pyproject.toml requires-python). Skip the entire module on older
# Pythons — without this, pytest fails at collection time with a confusing
# "'asyncio' not found in markers" error.
pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="pytest-asyncio plugin requires Python 3.11+ (pyproject.toml requires-python)",
)

from audit_log import AuditLogger
from handlers import HandlerContext
from protocol import (
    PARSE_ERROR,
    METHOD_NOT_FOUND,
)

# daemon_entry is the top-level module — importing it triggers the
# sys.path bootstrap, so we can import it cleanly here.
import daemon_entry  # type: ignore[import-not-found]


# =============================================================================
# Fixtures
# =============================================================================

class _CapturingAudit(AuditLogger):
    """Audit logger that captures every event for assertions."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        # Bypass parent __init__ — we don't want a stream.
        self._closed = False

    def log_event(self, event: str, **fields: Any) -> None:  # type: ignore[override]
        record = {"event": event, **fields}
        self.events.append(record)

    def log_rpc(self, method: str, **fields: Any) -> None:  # type: ignore[override]
        self.events.append({"event": "rpc", "method": method, **fields})


@pytest.fixture
def daemon() -> daemon_entry.VoltaDaemon:
    audit = _CapturingAudit()
    ctx = HandlerContext(executor_factory=lambda: None, audit=audit)
    return daemon_entry.VoltaDaemon(ctx=ctx, audit=audit)


# =============================================================================
# Built-in handlers (happy path)
# =============================================================================

class TestPingDispatch:
    @pytest.mark.asyncio
    async def test_ping_returns_pong(self, daemon: daemon_entry.VoltaDaemon) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "ping", "params": {}})
        response = await daemon_entry.dispatch(daemon, raw)
        assert response is not None
        assert response["id"] == "1"
        assert response["result"]["pong"] is True

    @pytest.mark.asyncio
    async def test_ping_logs_rpc_event(self, daemon: daemon_entry.VoltaDaemon) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "ping"})
        await daemon_entry.dispatch(daemon, raw)
        audit = daemon.audit
        assert isinstance(audit, _CapturingAudit)
        rpc_events = [e for e in audit.events if e.get("event") == "rpc"]
        assert any(e["method"] == "ping" for e in rpc_events)


class TestListOperationsDispatch:
    @pytest.mark.asyncio
    async def test_returns_ops_list(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        raw = json.dumps({
            "jsonrpc": "2.0", "id": "2", "method": "list_operations", "params": {},
        })
        response = await daemon_entry.dispatch(daemon, raw)
        assert response is not None
        assert "operations" in response["result"]
        assert "count" in response["result"]


class TestHealthCheckDispatch:
    @pytest.mark.asyncio
    async def test_returns_ok(self, daemon: daemon_entry.VoltaDaemon) -> None:
        raw = json.dumps({
            "jsonrpc": "2.0", "id": "3", "method": "health_check", "params": {},
        })
        response = await daemon_entry.dispatch(daemon, raw)
        assert response is not None
        assert response["result"]["ok"] is True

    @pytest.mark.asyncio
    async def test_health_alias_works(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        raw = json.dumps({
            "jsonrpc": "2.0", "id": "3b", "method": "health", "params": {},
        })
        response = await daemon_entry.dispatch(daemon, raw)
        assert response is not None
        assert response["result"]["ok"] is True


class TestShutdownDispatch:
    @pytest.mark.asyncio
    async def test_sets_shutdown_flag(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        assert daemon.shutdown_requested is False
        raw = json.dumps({"jsonrpc": "2.0", "id": "4", "method": "shutdown"})
        response = await daemon_entry.dispatch(daemon, raw)
        assert response is not None
        assert response["result"]["shutting_down"] is True
        assert daemon.shutdown_requested is True


# =============================================================================
# Error cases
# =============================================================================

class TestParseError:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_parse_error(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        response = await daemon_entry.dispatch(daemon, "not valid json")
        assert response is not None
        assert response["error"]["code"] == PARSE_ERROR
        assert response["id"] is None  # parse error → no id known


class TestMethodNotFound:
    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        raw = json.dumps({
            "jsonrpc": "2.0", "id": "5", "method": "made_up_method", "params": {},
        })
        response = await daemon_entry.dispatch(daemon, raw)
        assert response is not None
        assert response["error"]["code"] == METHOD_NOT_FOUND
        assert "made_up_method" in response["error"]["message"]


class TestHeartbeatPassthrough:
    @pytest.mark.asyncio
    async def test_heartbeat_notification_returns_none(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "method": "heartbeat", "params": {}})
        response = await daemon_entry.dispatch(daemon, raw)
        # Notifications get no response.
        assert response is None


# =============================================================================
# VoltaDaemon supervisor
# =============================================================================

class TestDaemonSupervisor:
    def test_maybe_heartbeat_emits_notification_first_call(
        self, daemon: daemon_entry.VoltaDaemon, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Force=True triggers immediate emit regardless of interval.
        emitted = daemon.maybe_heartbeat(force=True)
        assert emitted is True
        captured = capsys.readouterr()
        line = captured.out.strip()
        assert line  # something was written
        notif = json.loads(line)
        assert notif["method"] == "heartbeat"
        assert "epoch" in notif["params"]
        assert "pid" in notif["params"]

    def test_maybe_heartbeat_skips_within_interval(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        # First call emits (force), second immediately after should not.
        daemon.maybe_heartbeat(force=True)
        emitted = daemon.maybe_heartbeat()
        assert emitted is False

    def test_request_shutdown_sets_flag(
        self, daemon: daemon_entry.VoltaDaemon
    ) -> None:
        assert daemon.shutdown_requested is False
        daemon.request_shutdown()
        assert daemon.shutdown_requested is True
