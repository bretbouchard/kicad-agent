"""
protocol.py — JSON-RPC 2.0 protocol envelopes for the bundled daemon.

Phase 162 — Python Daemon Bundling.

Extracted from daemon_entry.py so the protocol layer is independently
testable (`tests/test_protocol.py`). This module is pure: no I/O, no
asyncio, no signal handlers. The daemon entry point composes these
helpers; the tests exercise them directly.

JSON-RPC 2.0 spec: https://www.jsonrpc.org/specification

Wire format (line-delimited over stdio):
    Request:        {"jsonrpc":"2.0","id":"<uuid>","method":"ping","params":{}}
    Response:       {"jsonrpc":"2.0","id":"<uuid>","result":{...}}
    Error:          {"jsonrpc":"2.0","id":"<uuid>","error":{"code":-32601,...}}
    Notification:   {"jsonrpc":"2.0","method":"heartbeat","params":{...}}
                    (no id — fire-and-forget daemon → app messages)

Error codes follow the JSON-RPC 2.0 reserved table:
    -32700  PARSE_ERROR
    -32600  INVALID_REQUEST
    -32601  METHOD_NOT_FOUND
    -32602  INVALID_PARAMS
    -32603  INTERNAL_ERROR
"""

from __future__ import annotations

import json
from typing import Any, Optional


# =============================================================================
# JSON-RPC error codes (spec-defined)
# =============================================================================

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# =============================================================================
# RpcError exception
# =============================================================================

class RpcError(Exception):
    """JSON-RPC 2.0 error. Carries a spec-defined `code` plus message."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_payload(self, request_id: Any | None = None) -> dict[str, Any]:
        """Render this error as a JSON-RPC 2.0 error payload."""
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": self.code, "message": self.message},
        }
        if self.data is not None:
            payload["error"]["data"] = self.data
        return payload


# =============================================================================
# Envelope constructors
# =============================================================================

def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a success response envelope."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(
    request_id: Any | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    """Build an error response envelope."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def make_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a daemon → app notification (no id, no reply expected)."""
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    return payload


# =============================================================================
# Request parsing & validation
# =============================================================================

def parse_request(raw: str) -> tuple[Any, Optional[str], Optional[dict[str, Any]]]:
    """Parse one line of JSON-RPC input.

    Returns:
        Tuple of (request_id, method, params). request_id may be None for
        notifications; method is None on parse error.

    Raises:
        RpcError(PARSE_ERROR) — malformed JSON.
        RpcError(INVALID_REQUEST) — valid JSON, wrong shape (missing method).
    """
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RpcError(PARSE_ERROR, f"Invalid JSON: {exc}") from exc

    if not isinstance(request, dict):
        raise RpcError(INVALID_REQUEST, "Request must be a JSON object")

    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    if not isinstance(method, str):
        raise RpcError(INVALID_REQUEST, "Missing or invalid 'method'")

    if params is None:
        params = {}

    return request_id, method, params


def is_heartbeat(request: dict[str, Any]) -> bool:
    """True if the parsed request is a heartbeat notification.

    Heartbeats are daemon → app, but the Swift watchdog can also send them
    back as a sanity ping during development.
    """
    return (
        "id" not in request
        and request.get("method") == "heartbeat"
    )


# =============================================================================
# Serialization helper
# =============================================================================

def serialize(payload: dict[str, Any]) -> str:
    """Serialize a payload to a line-delimited JSON string (no trailing newline).

    `default=str` ensures non-JSON-serializable values (Path, datetime, etc.)
    are stringified rather than crashing the daemon.
    """
    return json.dumps(payload, default=str, separators=(",", ":"))
