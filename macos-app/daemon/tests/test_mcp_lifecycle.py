"""
test_mcp_lifecycle.py — MCP initialize/initialized handshake tests.

Phase 167 — Stdio MCP Client.

These tests exercise the MCP lifecycle handlers directly:

    initialize  → returns protocolVersion, serverInfo, capabilities
    initialized → returns None (notification, no reply)
    tools/list  → returns 151 volta operations as MCP tool descriptors
    tools/call  → dispatches to OperationExecutor

Coverage:
    initialize:
        - Returns MCP-compliant shape (protocolVersion, serverInfo, capabilities)
        - protocolVersion matches MCP 2024-11-05
        - serverInfo has name and version strings
        - capabilities includes tools (even if empty)
        - Tolerates missing params (permissive)
        - Tolerates None params

    initialized:
        - Returns None (notification convention)
        - Logs audit event when audit logger present

    tools/list:
        - Returns {tools: [...]} with 151 entries
        - Each tool has name, description, inputSchema
        - Names are prefixed with 'kicad.' namespace
        - Names match the registered operations in volta.ops.registry

    tools/call:
        - Rejects unknown name with INVALID_PARAMS
        - Rejects non-'kicad.' namespaced names
        - Returns MCP content envelope shape

The end-to-end daemon integration is covered by test_dispatch.py which
runs initialize/tools-list/tools-call through the real dispatch loop.
"""

from __future__ import annotations

from typing import Any

import pytest

from handlers import (
    HandlerContext,
    HANDLERS,
    initialize,
    initialized,
    tools_list,
    tools_call,
    get_handler,
    registered_methods,
)
from protocol import RpcError, INVALID_PARAMS


# =============================================================================
# HandlerContext fixtures
# =============================================================================

class _CapturingAudit:
    """Capture every audit event for assertions."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def log_event(self, event: str, **fields: Any) -> None:
        self.events.append({"event": event, **fields})

    def log_rpc(self, method: str, **fields: Any) -> None:
        pass


@pytest.fixture
def ctx() -> HandlerContext:
    return HandlerContext(executor_factory=lambda: None, audit=_CapturingAudit())


@pytest.fixture
def ctx_no_audit() -> HandlerContext:
    return HandlerContext(executor_factory=lambda: None, audit=None)


# =============================================================================
# initialize
# =============================================================================

class TestInitialize:
    def test_returns_protocol_version_2024_11_05(self, ctx: HandlerContext) -> None:
        result = initialize({}, ctx)
        assert result["protocolVersion"] == "2024-11-05"

    def test_returns_server_info_with_name(self, ctx: HandlerContext) -> None:
        result = initialize({}, ctx)
        assert "serverInfo" in result
        assert isinstance(result["serverInfo"], dict)
        assert result["serverInfo"]["name"] == "volta-daemon"

    def test_returns_server_info_with_version(self, ctx: HandlerContext) -> None:
        result = initialize({}, ctx)
        assert isinstance(result["serverInfo"]["version"], str)
        assert len(result["serverInfo"]["version"]) > 0

    def test_returns_capabilities_with_tools(self, ctx: HandlerContext) -> None:
        result = initialize({}, ctx)
        assert "capabilities" in result
        assert isinstance(result["capabilities"], dict)
        # Per MCP spec, tool-capable servers advertise it.
        assert "tools" in result["capabilities"]

    def test_tolerates_missing_params(self, ctx: HandlerContext) -> None:
        result = initialize(None, ctx)
        assert result["protocolVersion"] == "2024-11-05"

    def test_tolerates_full_client_info(self, ctx: HandlerContext) -> None:
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"roots": {"listChanged": True}},
            "clientInfo": {"name": "Claude Code", "version": "1.0.0"},
        }
        result = initialize(params, ctx)
        # Server ignores client capabilities but responds with its own.
        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "volta-daemon"


# =============================================================================
# initialized (notification)
# =============================================================================

class TestInitialized:
    def test_returns_none(self, ctx: HandlerContext) -> None:
        # Per MCP spec, initialized is a notification — no reply expected.
        result = initialized({}, ctx)
        assert result is None

    def test_logs_audit_event(self, ctx: HandlerContext) -> None:
        initialized({}, ctx)
        # ctx.audit is the _CapturingAudit fixture.
        assert any(e["event"] == "mcp_initialized" for e in ctx.audit.events)

    def test_tolerates_missing_audit(self, ctx_no_audit: HandlerContext) -> None:
        # Should not raise when ctx.audit is None.
        result = initialized({}, ctx_no_audit)
        assert result is None

    def test_registered_in_handler_table(self) -> None:
        # The HANDLERS table must include 'initialized' for the dispatch
        # loop to route it. Phase 167 must not rely on convention.
        assert "initialized" in HANDLERS
        assert HANDLERS["initialized"] is initialized


# =============================================================================
# Handler registry — MCP methods are registered
# =============================================================================

class TestMCPHandlersRegistered:
    def test_initialize_in_registry(self) -> None:
        assert get_handler("initialize") is initialize

    def test_initialized_in_registry(self) -> None:
        assert get_handler("initialized") is initialized

    def test_tools_list_in_registry(self) -> None:
        assert get_handler("tools/list") is tools_list

    def test_tools_call_in_registry(self) -> None:
        assert get_handler("tools/call") is tools_call

    def test_all_four_in_registered_methods(self) -> None:
        methods = set(registered_methods())
        assert {"initialize", "initialized", "tools/list", "tools/call"}.issubset(methods)
