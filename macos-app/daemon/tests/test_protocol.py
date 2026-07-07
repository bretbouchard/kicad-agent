"""
test_protocol.py — JSON-RPC 2.0 envelope handling tests.

Phase 162 — Python Daemon Bundling.

These tests exercise the pure protocol layer (`protocol.py`):
    - Envelope constructors
    - RpcError serialization
    - parse_request success + error cases
    - Heartbeat detection
    - Serialization round-trip

No I/O, no asyncio — pure function tests.
"""

from __future__ import annotations

import json

import pytest

from protocol import (
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    RpcError,
    make_result,
    make_error,
    make_notification,
    parse_request,
    is_heartbeat,
    serialize,
)


# =============================================================================
# Envelope constructors
# =============================================================================

class TestMakeResult:
    def test_basic_result_envelope(self) -> None:
        env = make_result("abc", {"pong": True})
        assert env == {
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {"pong": True},
        }

    def test_result_with_none_id(self) -> None:
        env = make_result(None, None)
        assert env["id"] is None
        assert env["result"] is None

    def test_result_preserves_complex_payload(self) -> None:
        payload = {"ops": ["add_wire", "add_via"], "count": 2}
        env = make_result(42, payload)
        assert env["result"] == payload
        assert env["id"] == 42


class TestMakeError:
    def test_basic_error_envelope(self) -> None:
        env = make_error("id1", METHOD_NOT_FOUND, "no such method")
        assert env == {
            "jsonrpc": "2.0",
            "id": "id1",
            "error": {"code": -32601, "message": "no such method"},
        }

    def test_error_with_none_id(self) -> None:
        env = make_error(None, PARSE_ERROR, "bad json")
        assert env["id"] is None
        assert env["error"]["code"] == PARSE_ERROR

    def test_error_with_data_field(self) -> None:
        env = make_error(
            "id2",
            INVALID_PARAMS,
            "missing field",
            data={"field": "op"},
        )
        assert env["error"]["data"] == {"field": "op"}


class TestMakeNotification:
    def test_notification_has_no_id(self) -> None:
        notif = make_notification("heartbeat", {"epoch": 1.0})
        assert "id" not in notif
        assert notif["method"] == "heartbeat"
        assert notif["params"] == {"epoch": 1.0}

    def test_notification_without_params(self) -> None:
        notif = make_notification("shutdown")
        assert "params" not in notif
        assert notif["method"] == "shutdown"


# =============================================================================
# RpcError
# =============================================================================

class TestRpcError:
    def test_to_payload_basic(self) -> None:
        err = RpcError(METHOD_NOT_FOUND, "not found")
        assert err.to_payload("req1") == {
            "jsonrpc": "2.0",
            "id": "req1",
            "error": {"code": -32601, "message": "not found"},
        }

    def test_to_payload_with_data(self) -> None:
        err = RpcError(INVALID_PARAMS, "bad", data={"got": "string"})
        payload = err.to_payload("req2")
        assert payload["error"]["data"] == {"got": "string"}

    def test_to_payload_with_none_id(self) -> None:
        err = RpcError(PARSE_ERROR, "broken")
        payload = err.to_payload(None)
        assert payload["id"] is None

    def test_is_exception_subclass(self) -> None:
        err = RpcError(INTERNAL_ERROR, "boom")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            raise RpcError(METHOD_NOT_FOUND, "missing")
        assert exc_info.value.code == METHOD_NOT_FOUND
        assert "missing" in str(exc_info.value)


# =============================================================================
# parse_request
# =============================================================================

class TestParseRequest:
    def test_valid_request_with_params(self) -> None:
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": "abc",
            "method": "ping",
            "params": {"foo": "bar"},
        })
        rid, method, params = parse_request(raw)
        assert rid == "abc"
        assert method == "ping"
        assert params == {"foo": "bar"}

    def test_valid_request_without_params(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        rid, method, params = parse_request(raw)
        assert rid == 1
        assert method == "ping"
        assert params == {}  # default

    def test_notification_no_id(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "method": "heartbeat"})
        rid, method, params = parse_request(raw)
        assert rid is None
        assert method == "heartbeat"

    def test_params_none_becomes_empty_dict(self) -> None:
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": "x",
            "method": "ping",
            "params": None,
        })
        _, _, params = parse_request(raw)
        assert params == {}

    def test_malformed_json_raises_parse_error(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            parse_request("not json at all")
        assert exc_info.value.code == PARSE_ERROR

    def test_non_object_raises_invalid_request(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            parse_request("[1, 2, 3]")
        assert exc_info.value.code == INVALID_REQUEST

    def test_missing_method_raises_invalid_request(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": "1"})
        with pytest.raises(RpcError) as exc_info:
            parse_request(raw)
        assert exc_info.value.code == INVALID_REQUEST

    def test_non_string_method_raises_invalid_request(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": "1", "method": 42})
        with pytest.raises(RpcError) as exc_info:
            parse_request(raw)
        assert exc_info.value.code == INVALID_REQUEST

    def test_empty_string_raises_parse_error(self) -> None:
        with pytest.raises(RpcError) as exc_info:
            parse_request("")
        assert exc_info.value.code == PARSE_ERROR


# =============================================================================
# is_heartbeat
# =============================================================================

class TestIsHeartbeat:
    def test_heartbeat_notification(self) -> None:
        req = {"jsonrpc": "2.0", "method": "heartbeat", "params": {}}
        assert is_heartbeat(req) is True

    def test_request_with_id_is_not_heartbeat(self) -> None:
        req = {"jsonrpc": "2.0", "id": "1", "method": "heartbeat"}
        assert is_heartbeat(req) is False

    def test_notification_different_method_is_not_heartbeat(self) -> None:
        req = {"jsonrpc": "2.0", "method": "shutdown"}
        assert is_heartbeat(req) is False

    def test_empty_dict_is_not_heartbeat(self) -> None:
        assert is_heartbeat({}) is False


# =============================================================================
# serialize
# =============================================================================

class TestSerialize:
    def test_round_trip_basic(self) -> None:
        env = make_result("1", {"pong": True})
        s = serialize(env)
        parsed = json.loads(s)
        assert parsed == env

    def test_no_trailing_newline(self) -> None:
        s = serialize(make_result("1", {}))
        assert not s.endswith("\n")

    def test_uses_compact_separators(self) -> None:
        s = serialize({"a": 1, "b": 2})
        assert " " not in s  # compact form, no spaces after , or :

    def test_serializes_non_json_native_types_via_str(self) -> None:
        from pathlib import Path
        env = {"path": Path("/tmp/foo")}
        s = serialize(env)
        parsed = json.loads(s)
        assert parsed["path"] == "/tmp/foo"

    def test_serializes_error_envelope(self) -> None:
        env = make_error("1", PARSE_ERROR, "bad", data={"line": 10})
        s = serialize(env)
        parsed = json.loads(s)
        assert parsed["error"]["code"] == PARSE_ERROR
        assert parsed["error"]["data"] == {"line": 10}
