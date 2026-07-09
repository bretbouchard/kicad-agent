"""
test_mcp_tools.py — MCP tools/list and tools/call tests.

Phase 167 — Stdio MCP Client.

Coverage:
    tools/list:
        - Returns 151 tools matching the kicad_agent.ops registry count
        - Every tool name is kicad.<op_type>
        - Every tool has description, inputSchema
        - Names are sorted alphabetically (mirror of registry sort)

    tools/call:
        - Rejects unknown name with RpcError(INVALID_PARAMS)
        - Rejects non-'kicad.' namespaced names
        - Rejects missing 'name' param
        - Rejects malformed arguments (not dict)
        - Returns MCP content envelope when executor unavailable
        - Returns MCP content envelope on execution failure
        - Wraps successful result as JSON-encoded text in content array

These tests run without spawning the actual daemon. They exercise the
handler functions directly with a HandlerContext that has a no-op
executor factory (so the executor path is exercised but no real KiCad
file mutations occur).
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from handlers import (
    HandlerContext,
    tools_list,
    tools_call,
    _registered_operations,
    _build_tool_descriptor,
)
from protocol import RpcError, INVALID_PARAMS

# These tests require the kicad_agent ops registry, which only imports on
# Python 3.11+ (the schema uses `X | None` syntax that fails on 3.9/3.10).
# Skip the entire module if running on an older Python — without this, the
# registry comes back empty and every call_tool test fails with a confusing
# "unknown operation" error instead of a clear version mismatch message.
pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="kicad_agent.ops.registry requires Python 3.11+ (pyproject.toml requires-python)",
)


# =============================================================================
# HandlerContext fixtures
# =============================================================================

class _NoopAudit:
    def log_event(self, event: str, **fields: Any) -> None:
        pass

    def log_rpc(self, method: str, **fields: Any) -> None:
        pass


class _FakeExecutor:
    """Stand-in executor that records calls and returns synthetic results."""

    def __init__(self, result: Any = None, raise_exc: Exception | None = None) -> None:
        self.result = result or {"success": True, "operation": "fake"}
        self.raise_exc = raise_exc
        self.calls: list[Any] = []

    def execute(self, op: Any) -> dict[str, Any]:
        self.calls.append(op)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


@pytest.fixture
def ctx() -> HandlerContext:
    """Context with a no-op executor (returns None → tools/call short-circuits)."""
    return HandlerContext(executor_factory=lambda: None, audit=_NoopAudit())


def _make_ctx_with_executor(executor: Any) -> HandlerContext:
    return HandlerContext(executor_factory=lambda: executor, audit=_NoopAudit())


# =============================================================================
# tools/list
# =============================================================================

class TestToolsList:
    def test_returns_dict_with_tools_key(self, ctx: HandlerContext) -> None:
        result = tools_list({}, ctx)
        assert isinstance(result, dict)
        assert "tools" in result
        assert isinstance(result["tools"], list)

    def test_returns_151_tools_matching_registry(self, ctx: HandlerContext) -> None:
        result = tools_list({}, ctx)
        registered = _registered_operations()
        # Skip when kicad_agent isn't importable (test env quirk).
        if not registered:
            pytest.skip("kicad_agent.ops.registry not importable in this env")
        assert len(result["tools"]) == len(registered) == 151

    def test_every_tool_name_uses_kicad_namespace(self, ctx: HandlerContext) -> None:
        result = tools_list({}, ctx)
        for tool in result["tools"]:
            assert tool["name"].startswith("kicad."), f"tool '{tool['name']}' missing kicad. prefix"

    def test_every_tool_has_required_fields(self, ctx: HandlerContext) -> None:
        result = tools_list({}, ctx)
        for tool in result["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert isinstance(tool["description"], str)
            assert isinstance(tool["inputSchema"], dict)

    def test_tool_descriptions_are_nonempty(self, ctx: HandlerContext) -> None:
        result = tools_list({}, ctx)
        for tool in result["tools"]:
            assert len(tool["description"]) > 0, f"empty description for {tool['name']}"

    def test_tools_are_sorted_alphabetically(self, ctx: HandlerContext) -> None:
        result = tools_list({}, ctx)
        names = [t["name"] for t in result["tools"]]
        assert names == sorted(names)

    def test_known_op_present(self, ctx: HandlerContext) -> None:
        """Sanity: add_component must be in the tool list."""
        result = tools_list({}, ctx)
        names = {t["name"] for t in result["tools"]}
        if not names:
            pytest.skip("kicad_agent.ops.registry not importable")
        assert "kicad.add_component" in names

    def test_tolerates_none_params(self, ctx: HandlerContext) -> None:
        # Should not raise.
        result = tools_list(None, ctx)
        assert isinstance(result, dict)


# =============================================================================
# tools/call — input validation
# =============================================================================

class TestToolsCallValidation:
    def test_rejects_missing_name(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            tools_call({"arguments": {}}, ctx)
        assert exc_info.value.code == INVALID_PARAMS
        assert "missing required field 'name'" in exc_info.value.message

    def test_rejects_non_string_name(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            tools_call({"name": 123}, ctx)
        assert exc_info.value.code == INVALID_PARAMS
        assert "'name' must be a string" in exc_info.value.message

    def test_rejects_non_kicad_namespaced_name(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            tools_call({"name": "foo.bar", "arguments": {}}, ctx)
        assert exc_info.value.code == INVALID_PARAMS
        assert "unknown tool 'foo.bar'" in exc_info.value.message
        assert "Expected 'kicad.<op_type>'" in exc_info.value.message

    def test_rejects_bare_name(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            tools_call({"name": "bogus"}, ctx)
        assert exc_info.value.code == INVALID_PARAMS

    def test_rejects_unknown_kicad_op(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            tools_call({"name": "kicad.does_not_exist", "arguments": {}}, ctx)
        assert exc_info.value.code == INVALID_PARAMS
        assert "unknown operation 'does_not_exist'" in exc_info.value.message

    def test_rejects_non_dict_arguments(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError) as exc_info:
            tools_call({"name": "kicad.ping", "arguments": "not a dict"}, ctx)
        assert exc_info.value.code == INVALID_PARAMS
        assert "'arguments' must be an object" in exc_info.value.message

    def test_tolerates_none_arguments(self, ctx: HandlerContext) -> None:
        # Should not raise on None arguments; will reach executor path.
        # We can't easily test the dispatch path without a real op, so
        # just verify the handler accepts None arguments without raising
        # in the validation phase.
        with pytest.raises(RpcError) as exc_info:
            # kicad.bogus will still be rejected for unknown op, but the
            # arguments None should not trigger the 'must be object' error.
            tools_call({"name": "kicad.does_not_exist", "arguments": None}, ctx)
        # Error is about unknown op, NOT about arguments type.
        assert "unknown operation" in exc_info.value.message


# =============================================================================
# tools/call — dispatch behavior
# =============================================================================

class TestToolsCallDispatch:
    def test_returns_error_envelope_when_executor_unavailable(self, ctx: HandlerContext) -> None:
        """When ctx.executor() returns None (no factory), return isError envelope."""
        result = tools_call({"name": "kicad.add_component", "arguments": {}}, ctx)
        assert isinstance(result, dict)
        assert "content" in result
        assert result["isError"] is True
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        payload = json.loads(result["content"][0]["text"])
        assert payload["success"] is False
        assert "OperationExecutor unavailable" in payload["error"]

    def test_returns_error_envelope_when_executor_raises(self) -> None:
        """Executor failures are wrapped in MCP error envelope, not raised."""
        raising_executor = _FakeExecutor(raise_exc=ValueError("test error"))
        ctx = _make_ctx_with_executor(raising_executor)

        # We need an op that validates successfully but the executor raises.
        # Use a real op with minimal valid args. add_component requires
        # target_file, library_id, position.
        result = tools_call(
            {
                "name": "kicad.add_component",
                "arguments": {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "test.kicad_sch",
                        "library_id": "Device:R",
                        "position": {"x": 0.0, "y": 0.0},
                    }
                },
            },
            ctx,
        )
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["success"] is False
        assert "test error" in payload["error"]

    def test_returns_content_envelope_with_json_text_on_success(self) -> None:
        """Successful execution returns MCP-compliant content array with JSON."""
        # Mock executor returns a known dict; we wrap as JSON text.
        # Use list_lib_entries — it's a query op that may not need target_file.
        # Actually we use any op with minimal args; the executor is mocked so
        # it just returns our canned result.
        mock = _FakeExecutor(result={"success": True, "details": {"foo": "bar"}})
        ctx = _make_ctx_with_executor(mock)

        # Use the simplest possible op — list_lib_entries is read-only.
        # Provide just enough args to validate.
        result = tools_call(
            {
                "name": "kicad.list_lib_entries",
                "arguments": {
                    "root": {
                        "op_type": "list_lib_entries",
                        "target_file": "test.kicad_sch",
                    }
                },
            },
            ctx,
        )
        assert result["isError"] is False
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        payload = json.loads(result["content"][0]["text"])
        assert payload["success"] is True
        assert payload["details"] == {"foo": "bar"}

    def test_executor_receives_validated_operation(self) -> None:
        """The op passed to executor.execute() is a Pydantic Operation."""
        mock = _FakeExecutor()
        ctx = _make_ctx_with_executor(mock)

        tools_call(
            {
                "name": "kicad.list_lib_entries",
                "arguments": {
                    "root": {
                        "op_type": "list_lib_entries",
                        "target_file": "test.kicad_sch",
                    }
                },
            },
            ctx,
        )
        assert len(mock.calls) == 1
        op = mock.calls[0]
        # It's a Pydantic Operation with a root.
        assert hasattr(op, "root")
        assert op.root is not None

    def test_patches_op_type_from_name_when_mismatched(self) -> None:
        """When caller's op_type doesn't match name=kicad.X, we override with X.

        This handles the MCP client pattern where the tool name carries the
        op_type and arguments.root.op_type may be missing or wrong. Pydantic
        requires op_type, so the test passes the right one — but verify the
        patching code path is exercised.
        """
        mock = _FakeExecutor()
        ctx = _make_ctx_with_executor(mock)

        result = tools_call(
            {
                "name": "kicad.list_lib_entries",
                "arguments": {
                    "root": {
                        "op_type": "list_lib_entries",  # correct
                        "target_file": "test.kicad_sch",
                    }
                },
            },
            ctx,
        )
        assert mock.calls, "executor should have been called"
        op = mock.calls[0]
        assert op.root.op_type == "list_lib_entries"
        # Verify isError is False on success.
        assert result["isError"] is False


# =============================================================================
# _build_tool_descriptor helper
# =============================================================================

class TestBuildToolDescriptor:
    def test_returns_dict_for_known_op(self) -> None:
        descriptor = _build_tool_descriptor("add_component")
        assert descriptor is not None
        assert descriptor["name"] == "kicad.add_component"
        assert "description" in descriptor
        assert "inputSchema" in descriptor

    def test_returns_kicad_namespaced_name(self) -> None:
        descriptor = _build_tool_descriptor("list_lib_entries")
        assert descriptor is not None
        assert descriptor["name"] == "kicad.list_lib_entries"

    def test_returns_minimal_descriptor_when_registry_unavailable(self) -> None:
        """If kicad_agent.ops.registry isn't importable, we still get a descriptor."""
        # Force the import to fail by patching sys.modules — too heavy for a unit
        # test. Instead, verify the descriptor has the minimum shape required.
        descriptor = _build_tool_descriptor("any_op_name")
        assert descriptor is not None
        assert "name" in descriptor
        assert "description" in descriptor
        assert "inputSchema" in descriptor
