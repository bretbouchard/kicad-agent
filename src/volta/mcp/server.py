"""MCP server for component search via JLCPCB/EasyEDA.

Provides 4 tools for AI agents to search components and retrieve CAD data:
- search_components: Keyword search with paginated results
- get_component_details: Full pin/pad data for a specific LCSC part
- search_and_detail: Combined search + detail in one call
- get_component_suggestions: Lightweight autocomplete suggestions

Usage:
    # Start as MCP server (stdio transport)
    kicad-component-search

    # Or via CLI
    volta component-search
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from volta.crawler.easyeda_api import EasyEdaClient
from volta.mcp.tools import (
    ValidationError,
    get_component_details,
    get_component_suggestions,
    search_and_detail,
    search_components,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server lifecycle state
# ---------------------------------------------------------------------------

_started_at = time.time()
_shutdown_event = threading.Event()
_in_flight_count = 0
_in_flight_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Tool schema definitions
# ---------------------------------------------------------------------------

_TOOL_DEFINITIONS = [
    types.Tool(
        name="health_check",
        description=(
            "Returns server health status including uptime and tool availability. "
            "Use for liveness probing."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="search_components",
        description=(
            "Search JLCPCB electronic components by keyword. "
            "Returns LCSC numbers, names, packages, stock, price, and datasheet URLs. "
            "Use 'part_type' to filter: 'basic' for stocked basics, 'extended' for extended parts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search query (e.g., 'STM32', 'NE555', '100nF 0402')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (1-50, default 10)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "part_type": {
                    "type": "string",
                    "description": "Filter by part type: 'basic' or 'extended'",
                    "enum": ["basic", "extended"],
                },
            },
            "required": ["keyword"],
        },
    ),
    types.Tool(
        name="get_component_details",
        description=(
            "Get full CAD data for a specific LCSC component. "
            "Returns schematic pins (with KiCad-compatible types), "
            "footprint pads, and package information."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lcsc_id": {
                    "type": "string",
                    "description": "LCSC part number (e.g., 'C83700')",
                    "pattern": "^C\\d+$",
                },
            },
            "required": ["lcsc_id"],
        },
    ),
    types.Tool(
        name="search_and_detail",
        description=(
            "Search components and fetch full CAD data for top results in one call. "
            "More efficient than separate search + detail calls."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search query",
                },
                "detail_limit": {
                    "type": "integer",
                    "description": "Number of top results to fetch CAD data for (1-10, default 3)",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10,
                },
                "search_limit": {
                    "type": "integer",
                    "description": "Total search results to return (1-50, default 10)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["keyword"],
        },
    ),
    types.Tool(
        name="get_component_suggestions",
        description=(
            "Quick component suggestions — returns only LCSC, name, package, and stock. "
            "Useful for autocomplete or quick lookups."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum suggestions (1-50, default 5)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["keyword"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_last_call_time: float = 0.0
_rate_limit_lock = threading.Lock()
_MIN_CALL_INTERVAL = 0.3


async def _rate_limited_thread_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous function in a thread with rate limiting."""
    global _last_call_time
    now = time.monotonic()
    with _rate_limit_lock:
        elapsed = now - _last_call_time
    if elapsed < _MIN_CALL_INTERVAL:
        await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)
    result = await asyncio.to_thread(fn, *args, **kwargs)
    with _rate_limit_lock:
        _last_call_time = time.monotonic()
    return result


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def server_lifespan(server: Server):  # type: ignore[type-arg]
    """Create EasyEdaClient once, share across all tool calls."""
    cache_dir = Path("~/.cache/volta/components").expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = EasyEdaClient(cache_dir=cache_dir)
    yield {"client": client}


app = Server("kicad-component-search", version="0.1.0", lifespan=server_lifespan)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return available MCP tools."""
    return _TOOL_DEFINITIONS


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Route tool calls to the appropriate handler.

    All EasyEdaClient calls are wrapped in asyncio.to_thread() to avoid
    blocking the async event loop. Rate limiting enforces a minimum interval
    between API calls.
    """
    # Client is injected via lifespan
    lifespan_ctx = app.request_context.lifespan_context  # type: ignore[attr-defined]
    client: EasyEdaClient = lifespan_ctx["client"]

    try:
        if name == "health_check":
            uptime = time.time() - _started_at
            with _in_flight_lock:
                current_count = _in_flight_count
            health = {
                "status": "shutting_down" if _shutdown_event.is_set() else "healthy",
                "uptime_seconds": round(uptime, 1),
                "in_flight_operations": current_count,
                "total_tools_available": len(_TOOL_DEFINITIONS),
            }
            return [types.TextContent(type="text", text=json.dumps(health, indent=2))]

        # Reject new operations during shutdown
        if _shutdown_event.is_set():
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "shutting_down", "message": "Server is shutting down"}),
            )]

        if name == "search_components":
            result = await _rate_limited_thread_call(
                search_components,
                client,
                keyword=arguments["keyword"],
                limit=arguments.get("limit", 10),
                part_type=arguments.get("part_type"),
            )

        elif name == "get_component_details":
            result = await _rate_limited_thread_call(
                get_component_details,
                client,
                lcsc_id=arguments["lcsc_id"],
            )

        elif name == "search_and_detail":
            result = await _rate_limited_thread_call(
                search_and_detail,
                client,
                keyword=arguments["keyword"],
                detail_limit=arguments.get("detail_limit", 3),
                search_limit=arguments.get("search_limit", 10),
            )

        elif name == "get_component_suggestions":
            result = await _rate_limited_thread_call(
                get_component_suggestions,
                client,
                keyword=arguments["keyword"],
                limit=arguments.get("limit", 5),
            )

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    except ValidationError as e:
        return [types.TextContent(type="text", text=f"Validation error: {e}")]
    except ValueError as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        correlation_id = str(uuid.uuid4())[:8]
        logger.exception("Tool %s failed [ref=%s]", name, correlation_id)
        return [types.TextContent(
            type="text",
            text=f"Internal error (ref: {correlation_id}). See server logs for details.",
        )]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_server() -> None:
    """Run the MCP server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    """CLI entry point for kicad-component-search."""
    from volta.logging_config import configure_logging
    configure_logging()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _request_shutdown():
        _shutdown_event.set()
        logger.info("Shutdown signal received, draining in-flight ops...")

    try:
        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
    except NotImplementedError:
        import signal as sig_mod
        sig_mod.signal(sig_mod.SIGTERM, lambda s, f: _request_shutdown())
        sig_mod.signal(sig_mod.SIGINT, lambda s, f: _request_shutdown())

    try:
        loop.run_until_complete(_run_server())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
