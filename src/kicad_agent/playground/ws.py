"""WebSocket handler for real-time operation execution feedback.

Protocol:
  Client -> Server: {"action": "execute", "operation": {...}}
  Server -> Client: {"type": "connected"}
  Server -> Client: {"type": "progress", "message": "..."}
  Server -> Client: {"type": "complete", "result": {...}}
  Server -> Client: {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from kicad_agent.handler import handle_operation, validate_operation

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def handle_ws(websocket: WebSocket) -> None:
    """Handle WebSocket connections for real-time operation feedback."""
    await websocket.accept()
    await websocket.send_json({"type": "connected", "message": "kicad-agent playground ready"})

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "execute":
                await _handle_execute(websocket, data)
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


async def _handle_execute(websocket: WebSocket, data: dict) -> None:
    """Handle an execute action via WebSocket."""
    operation = data.get("operation", {})
    op_json = json.dumps(operation)

    op, err = validate_operation(op_json)
    if err:
        await websocket.send_json({
            "type": "error",
            "message": err.error,
            "suggestion": err.suggestion,
        })
        return

    await websocket.send_json({
        "type": "progress",
        "message": f"Executing {operation.get('op_type', 'unknown')}...",
    })

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, handle_operation, op_json)
        result_data = asdict(result) if result else None
        await websocket.send_json({"type": "complete", "result": result_data})
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": f"Execution failed: {exc}"})
