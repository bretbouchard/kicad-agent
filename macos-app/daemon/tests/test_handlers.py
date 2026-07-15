"""
test_handlers.py — RPC handler tests.

Phase 162 — Python Daemon Bundling.

These tests exercise `handlers.py` directly — no I/O, no asyncio, no
daemon process. Each handler is invoked with synthetic params and a
mock HandlerContext so we can assert behavior cleanly.

Coverage:
    ping               — happy path, params ignored
    list_operations    — returns ops list, count matches
    health_check       — healthy response, error tolerant
    shutdown           — sets shutdown flag, returns ack
    get_handler        — method lookup
    require_dict       — param coercion
    require_field      — required field extraction
"""

from __future__ import annotations

from typing import Any

import pytest

from handlers import (
    HandlerContext,
    HANDLERS,
    ping,
    list_operations,
    health_check,
    shutdown,
    get_handler,
    registered_methods,
    require_dict,
    require_field,
)
from protocol import RpcError, INVALID_PARAMS


# =============================================================================
# HandlerContext fixtures
# =============================================================================

class _FakeAudit:
    """No-op audit logger for tests."""

    def log_event(self, event: str, **fields: Any) -> None:
        pass

    def log_rpc(self, method: str, **fields: Any) -> None:
        pass


@pytest.fixture
def ctx() -> HandlerContext:
    return HandlerContext(executor_factory=lambda: None, audit=_FakeAudit())


# =============================================================================
# ping
# =============================================================================

class TestPing:
    def test_returns_pong_true(self, ctx: HandlerContext) -> None:
        result = ping({}, ctx)
        assert result["pong"] is True

    def test_returns_epoch_float(self, ctx: HandlerContext) -> None:
        result = ping({}, ctx)
        assert isinstance(result["epoch"], float)
        assert result["epoch"] > 0

    def test_ignores_params(self, ctx: HandlerContext) -> None:
        r1 = ping({}, ctx)
        r2 = ping({"foo": "bar"}, ctx)
        assert r1["pong"] == r2["pong"] is True

    def test_tolerates_none_params(self, ctx: HandlerContext) -> None:
        result = ping(None, ctx)
        assert result["pong"] is True


# =============================================================================
# list_operations
# =============================================================================

class TestListOperations:
    def test_returns_count_field(self, ctx: HandlerContext) -> None:
        result = list_operations({}, ctx)
        assert "count" in result
        assert isinstance(result["count"], int)
        assert result["count"] >= 0

    def test_returns_operations_list(self, ctx: HandlerContext) -> None:
        result = list_operations({}, ctx)
        assert "operations" in result
        assert isinstance(result["operations"], list)

    def test_count_matches_operations_length(self, ctx: HandlerContext) -> None:
        result = list_operations({}, ctx)
        assert result["count"] == len(result["operations"])

    def test_known_operation_present(self, ctx: HandlerContext) -> None:
        """If the bundled library is importable, we should see at least
        some canonical KiCad operations."""
        result = list_operations({}, ctx)
        if result["count"] == 0:
            pytest.skip("volta.ops.registry not importable in this env")
        # add_wire is one of the most fundamental ops — should always be there.
        assert "add_wire" in result["operations"]


# =============================================================================
# health_check
# =============================================================================

class TestHealthCheck:
    def test_returns_ok_true(self, ctx: HandlerContext) -> None:
        result = health_check({}, ctx)
        assert result["ok"] is True

    def test_includes_ops_registered_count(self, ctx: HandlerContext) -> None:
        result = health_check({}, ctx)
        assert "ops_registered" in result
        assert isinstance(result["ops_registered"], int)

    def test_includes_executor_loaded_flag(self, ctx: HandlerContext) -> None:
        result = health_check({}, ctx)
        assert "executor_loaded" in result
        assert isinstance(result["executor_loaded"], bool)

    def test_executor_loaded_false_before_first_use(self, ctx: HandlerContext) -> None:
        result = health_check({}, ctx)
        assert result["executor_loaded"] is False

    def test_executor_loaded_true_after_construction(self) -> None:
        # Construct a ctx whose factory has already been called.
        ctx = HandlerContext(executor_factory=lambda: object(), audit=_FakeAudit())
        ctx.executor()  # force lazy load
        result = health_check({}, ctx)
        assert result["executor_loaded"] is True

    def test_returns_operations_sample(self, ctx: HandlerContext) -> None:
        result = health_check({}, ctx)
        assert "operations" in result
        # Sample is capped at 10.
        assert len(result["operations"]) <= 10


# =============================================================================
# shutdown
# =============================================================================

class TestShutdown:
    def test_sets_shutdown_flag(self, ctx: HandlerContext) -> None:
        assert ctx.shutdown_requested is False
        shutdown({}, ctx)
        assert ctx.shutdown_requested is True

    def test_returns_ack(self, ctx: HandlerContext) -> None:
        result = shutdown({}, ctx)
        assert result == {"shutting_down": True}

    def test_idempotent(self, ctx: HandlerContext) -> None:
        shutdown({}, ctx)
        shutdown({}, ctx)
        assert ctx.shutdown_requested is True


# =============================================================================
# get_handler + registered_methods
# =============================================================================

class TestHandlerRegistry:
    def test_returns_handler_for_known_method(self) -> None:
        h = get_handler("ping")
        assert h is ping

    def test_returns_none_for_unknown_method(self) -> None:
        assert get_handler("totally_made_up") is None

    def test_registered_methods_includes_builtins(self) -> None:
        methods = registered_methods()
        assert "ping" in methods
        assert "list_operations" in methods
        assert "health_check" in methods
        assert "shutdown" in methods

    def test_health_alias_registered(self) -> None:
        """Both 'health' and 'health_check' should resolve."""
        assert get_handler("health") is health_check
        assert get_handler("health_check") is health_check

    def test_handlers_dict_is_consistent_with_get_handler(self) -> None:
        for method, handler in HANDLERS.items():
            assert get_handler(method) is handler


# =============================================================================
# Param validation helpers
# =============================================================================

class TestRequireDict:
    def test_none_returns_empty_dict(self) -> None:
        assert require_dict(None, "ping") == {}

    def test_dict_returns_same_dict(self) -> None:
        d = {"a": 1}
        assert require_dict(d, "ping") is d

    def test_non_dict_raises_invalid_params(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            require_dict([1, 2, 3], "ping")
        assert exc_info.value.code == INVALID_PARAMS
        assert "ping" in exc_info.value.message

    def test_string_raises_invalid_params(self) -> None:
        with pytest.raises(RpcError):
            require_dict("not a dict", "ping")

    def test_int_raises_invalid_params(self) -> None:
        with pytest.raises(RpcError):
            require_dict(42, "ping")


class TestRequireField:
    def test_present_field_returns_value(self) -> None:
        params = {"op": "add_wire", "x": 1}
        assert require_field(params, "op", "execute") == "add_wire"

    def test_missing_field_raises_invalid_params(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            require_field({}, "op", "execute")
        assert exc_info.value.code == INVALID_PARAMS
        assert "op" in exc_info.value.message
        assert "execute" in exc_info.value.message

    def test_none_value_is_present(self) -> None:
        """A field explicitly set to None is still 'present'."""
        params = {"op": None}
        assert require_field(params, "op", "execute") is None

    def test_method_name_in_error_message(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            require_field({}, "missing_field", "my_method")
        assert "my_method" in exc_info.value.message
