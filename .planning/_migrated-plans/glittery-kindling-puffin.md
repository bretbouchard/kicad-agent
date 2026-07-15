# Plan: Component Search MCP Server

## Context

volta needs an MCP server so AI agents (Claude, etc.) can search for electronic components and retrieve CAD data without leaving the conversation. The existing `EasyEdaClient` in `src/volta/crawler/easyeda_api.py` already provides anonymous JLCPCB search and EasyEDA CAD data retrieval — the heavy lifting is done. This plan wraps that client in an MCP server with a clean tool interface.

**Bead:** volta-4 (open)
**Prerequisite research:** LCSC/EasyEDA API (anonymous, high-volume) + Octopart/Nexar (deferred — requires API key)

## Architecture

```
Claude/LLM → MCP protocol (stdio) → ComponentSearchServer → EasyEdaClient → JLCPCB/EasyEDA APIs
```

- **Transport:** stdio (standard for Claude Code MCP servers)
- **Framework:** `mcp` Python SDK (official Anthropic package)
- **Entry point:** `volta component-search` CLI subcommand + standalone `kicad-component-search` script
- **Reuse:** Existing `EasyEdaClient` from `crawler/easyeda_api.py` — no new HTTP code needed

## MCP Tools (4 tools)

### 1. `search_components`
Search JLCPCB by keyword. Returns ranked results with LCSC numbers, names, packages, stock, price, datasheet URLs.

```
Input:  keyword (str), limit (int, default 10), part_type ("basic"|"extended"|None)
Output: List of {lcsc, name, brand, package, category, stock, part_type, price, datasheet, attributes}
```

### 2. `get_component_details`
Full CAD data for a specific LCSC part — pins, pads, package info.

```
Input:  lcsc_id (str, e.g. "C83700")
Output: {lcsc, title, package, pins: [{number, name, x, y, rotation, type}], pads: [{number, x, y, width, height, layer, shape}]}
```

### 3. `search_and_detail`
Combined search + detail in one call. Returns top N results with full pin/pad data for each.

```
Input:  keyword (str), detail_limit (int, default 3), search_limit (int, default 10)
Output: {results: [{lcsc, name, package, stock, price, datasheet, pins, pads}], total}
```

### 4. `get_component_suggestions`
Quick suggestion list — just LCSC + name + package for autocomplete-style UX.

```
Input:  keyword (str), limit (int, default 5)
Output: List of {lcsc, name, package, stock}
```

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/volta/mcp/__init__.py` | NEW | Package init |
| `src/volta/mcp/server.py` | NEW | MCP server implementation (~150 lines) |
| `src/volta/mcp/tools.py` | NEW | Tool definitions, input schemas, response formatting (~200 lines) |
| `src/volta/cli.py` | MODIFY | Add `component-search` subcommand |
| `pyproject.toml` | MODIFY | Add `mcp` optional dependency + entry point |
| `tests/test_mcp_server.py` | NEW | Tests for all 4 MCP tools |
| `skills/prompt.md` | MODIFY | Document MCP server usage |

## Step 1: Dependencies — `pyproject.toml`

Add optional dependency group:

```toml
[project.optional-dependencies]
mcp = [
    "mcp>=1.0.0",
]
```

Add entry point:

```toml
[project.scripts]
kicad-component-search = "volta.mcp.server:main"
```

## Step 2: Tool Definitions — `src/volta/mcp/tools.py`

Four functions, each:
1. Accept typed parameters
2. Call `EasyEdaClient` methods
3. Format response as dict (JSON-serializable)

Key patterns:
- `EasyEdaClient` instantiated once at server startup, reused across calls
- File-based cache via `EasyEdaClient(cache_dir=Path("~/.cache/volta/components"))` to avoid repeated API hits
- Pin type mapping: EasyEDA int → human-readable string (`{0: "unspecified", 1: "input", 2: "output", 3: "bidirectional", 4: "power"}`)

## Step 3: MCP Server — `src/volta/mcp/server.py`

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("kicad-component-search")

@app.list_tools()
async def list_tools() -> list[Tool]:
    # Return 4 tool definitions with JSON Schema inputs

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Route to appropriate tool function

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
```

Reuse existing code:
- `EasyEdaClient.search_jlcpcb()` → `search_components` tool
- `EasyEdaClient.get_component_cad_data()` → `get_component_details` tool
- `dataclasses.asdict()` for converting frozen dataclasses to JSON

## Step 4: CLI Integration — `cli.py`

Add `component-search` subcommand that launches the MCP server:

```python
subparsers.add_parser("component-search", help="Start component search MCP server (stdio)")
```

When invoked, runs `asyncio.run(server.main())`.

## Step 5: Tests — `test_mcp_server.py`

Test strategy: Mock `EasyEdaClient` at the tool layer (no network calls in CI).

- `test_search_components` — Mock search_jlcpcb, verify output format
- `test_get_component_details` — Mock get_component_cad_data, verify pin/pad parsing
- `test_search_and_detail` — Combined flow, verify only top N get detailed
- `test_get_component_suggestions` — Lightweight output format
- `test_search_empty_results` — Graceful empty response
- `test_component_not_found` — None return from API handled cleanly

## Step 6: Documentation — `prompt.md`

Add "## Component Search MCP Server" section:
- How to configure as MCP server in Claude Desktop / Claude Code
- Example tool calls
- Supported search patterns

## What This Does NOT Include (Phase 2)

- EasyEDA → KiCad symbol/footprint conversion (use `easyeda2kicad.py` externally)
- Octopart/Nexar integration (requires API key, add later)
- 3D model downloading (EasyEDA has OBJ/STEP endpoints, but conversion is complex)
- Caching layer beyond EasyEdaClient's file cache

## Verification

1. `pip install -e ".[mcp]"` — dependencies install cleanly
2. `python -m pytest tests/test_mcp_server.py -v` — all tests pass
3. `echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | kicad-component-search` — server responds with tool list
4. `python -m pytest tests/ -v` — no regressions in existing tests
5. Manual: Configure in Claude Code MCP settings, test `search_components` with "STM32"
