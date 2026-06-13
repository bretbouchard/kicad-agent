"""MCP server exposing all kicad-agent operations as individually named tools.

Dynamic tool generation from Pydantic Operation discriminated union.
Follows the same pattern as the existing component-search server.

Usage:
    # Start as MCP server (stdio transport)
    kicad-agent-edit

    # Configure project directory
    KICAD_PROJECT_DIR=/path/to/project kicad-agent-edit
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_args

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from kicad_agent.context import render_project_context
from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.registry import get_readonly_operations, get_destructive_operations
from kicad_agent.ops.schema import Operation
from kicad_agent.ops.undo_stack import UndoStack
from kicad_agent.validation.erc_drc import run_erc, run_drc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server lifecycle state
# ---------------------------------------------------------------------------

_started_at = time.time()
_shutdown_event = threading.Event()
_in_flight_count = 0
_in_flight_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Response size limit
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 50 * 1024  # 50KB


# ---------------------------------------------------------------------------
# ToolAnnotations by category
# ---------------------------------------------------------------------------

# Auto-derive read-only and destructive operation sets from registry metadata.
# This ensures MCP annotations stay in sync with the operation registry
# without manual maintenance.
_READ_ONLY_OPS: frozenset[str] = frozenset(
    meta.op_type for meta in get_readonly_operations()
)

_DESTRUCTIVE_OPS: frozenset[str] = frozenset(
    meta.op_type for meta in get_destructive_operations()
)

_IDEMPOTENT_OPS = frozenset({
    "create_schematic", "create_pcb", "create_project", "create_symbol",
    "create_footprint", "embed_symbol", "add_lib_entry", "snap_to_grid",
    "convert_kicad6_to_10",
})


def _annotations_for(op_type: str) -> types.ToolAnnotations | None:
    """Assign ToolAnnotations based on operation category."""
    if op_type in _READ_ONLY_OPS:
        return types.ToolAnnotations(readOnlyHint=True)
    if op_type in _DESTRUCTIVE_OPS:
        return types.ToolAnnotations(destructiveHint=True)
    if op_type in _IDEMPOTENT_OPS:
        return types.ToolAnnotations(idempotentHint=True)
    return None


# ---------------------------------------------------------------------------
# Dynamic tool generation from Operation discriminated union
# ---------------------------------------------------------------------------

def _inline_refs(schema: dict[str, Any]) -> None:
    """Inline $ref references using $defs so the schema is self-contained.

    After inlining, removes $defs since all references are resolved.

    Args:
        schema: JSON Schema dict (modified in-place).
    """
    defs = schema.pop("$defs", None)
    if not defs:
        return

    def _resolve(node: Any) -> Any:
        """Recursively replace $ref with the resolved definition."""
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                # Handle "#/$defs/KeyName" format
                if ref_path.startswith("#/$defs/"):
                    key = ref_path[len("#/$defs/"):]
                    if key in defs:
                        resolved = dict(defs[key])  # shallow copy
                        # Carry over any sibling keys (e.g. description overrides)
                        for k, v in node.items():
                            if k != "$ref":
                                resolved[k] = v
                        return _resolve(resolved)
                return node
            return {k: _resolve(v) for k, v in node.items()}
        elif isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    resolved_schema = _resolve(schema)
    schema.update(resolved_schema)
    # Remove $defs key if it re-appeared (shouldn't, but safety)
    schema.pop("$defs", None)


def _generate_operation_tools() -> list[types.Tool]:
    """Generate one MCP tool per Operation union variant."""
    ann = Operation.model_fields["root"].annotation
    variants = get_args(ann)
    tools: list[types.Tool] = []

    for variant_cls in variants:
        op_type = variant_cls.model_fields["op_type"].default
        schema = variant_cls.model_json_schema()
        # Preserve $defs and $ref — MCP clients need these for schema
        # validation. Inline any $ref so the schema is self-contained.
        _inline_refs(schema)

        description = schema.pop("description", f"Execute {op_type} operation.")
        annotations = _annotations_for(op_type)

        tools.append(types.Tool(
            name=op_type,
            description=description,
            inputSchema=schema,
            annotations=annotations,
        ))

    return tools


# Meta-tool definitions (static)
_META_TOOLS = [
    types.Tool(
        name="health_check",
        description=(
            "Returns server health status including uptime, operation count, "
            "and executor readiness. Use for liveness probing."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="get_operation_schema",
        description=(
            "Get the full JSON Schema for all kicad-agent operations. "
            "Use this to discover available operations and their parameters."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="get_project_context",
        description=(
            "Get a summary of the current KiCad project: files, component counts, "
            "net counts, and board statistics. Useful for understanding the project "
            "before making edits."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "enrich": {
                    "type": "boolean",
                    "description": "Parse files to count components and nets (default true)",
                    "default": True,
                },
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="erc_check",
        description=(
            "Run Electrical Rules Check (ERC) on a KiCad schematic using kicad-cli. "
            "Returns structured results: pass/fail status, violation count, and "
            "violation details with positions. Equivalent to kicad-cli sch erc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "schematic_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_sch file (e.g. 'motor-driver.kicad_sch')",
                    "minLength": 1,
                },
            },
            "required": ["schematic_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="drc_check",
        description=(
            "Run Design Rules Check (DRC) on a KiCad PCB using kicad-cli. "
            "Returns structured results: pass/fail status, violation count, "
            "unconnected items, and violation details with positions. "
            "Equivalent to kicad-cli pcb drc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file (e.g. 'motor-driver.kicad_pcb')",
                    "minLength": 1,
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="undo",
        description=(
            "Undo the most recent file mutation. Restores the file to its state "
            "before the last operation. Session-scoped -- undo history is lost on "
            "server restart. Create operations (create_schematic, create_pcb, etc.) "
            "are not undoable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_file": {
                    "type": "string",
                    "description": (
                        "Relative path to the file to undo (e.g. 'motor-driver.kicad_sch'). "
                        "Optional -- when omitted, undoes the most recently modified file."
                    ),
                },
            },
        },
        annotations=types.ToolAnnotations(destructiveHint=True),
    ),
    types.Tool(
        name="redo",
        description=(
            "Redo the most recently undone operation. Restores the file to its state "
            "after the undone operation. Session-scoped -- redo history is lost on "
            "server restart."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_file": {
                    "type": "string",
                    "description": (
                        "Relative path to the file to redo (e.g. 'motor-driver.kicad_sch'). "
                        "Optional -- when omitted, redoes the most recently undone file."
                    ),
                },
            },
        },
        annotations=types.ToolAnnotations(destructiveHint=True),
    ),
    types.Tool(
        name="list_workflows",
        description=(
            "List all available workflow templates. Workflows are pre-defined multi-step "
            "operation sequences for common KiCad tasks like fixing ERC errors, wiring "
            "schematics, or setting up PCBs. Each workflow lists the required operation "
            "steps in order."
        ),
        inputSchema={"type": "object", "properties": {}},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="get_workflow",
        description=(
            "Get the detailed steps of a specific workflow template. Returns the "
            "operation sequence, file types, and step descriptions. Use list_workflows "
            "first to discover available workflow names."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Workflow name (e.g. 'fix_erc_errors', 'wire_schematic')",
                    "minLength": 1,
                },
            },
            "required": ["name"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    # --- Export/Render convenience tools ---
    types.Tool(
        name="render_pcb",
        description=(
            "Render a 3D view of a KiCad PCB as a PNG/JPEG image. Supports rotation, "
            "zoom, board side selection, and background color. Useful for visual "
            "inspection of PCB layouts without opening KiCad. Equivalent to "
            "kicad-cli pcb render."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_file": {
                    "type": "string",
                    "description": "Output image path (default: {stem}-render.png)",
                },
                "width": {
                    "type": "integer",
                    "description": "Render width in pixels (default: 1600)",
                    "default": 1600,
                },
                "height": {
                    "type": "integer",
                    "description": "Render height in pixels (default: 1200)",
                    "default": 1200,
                },
                "side": {
                    "type": "string",
                    "description": "Board side: 'front' or 'back'",
                    "enum": ["front", "back"],
                },
                "rotate": {
                    "type": "string",
                    "description": "Rotation string e.g. '-45,0,45' for isometric view",
                },
                "zoom": {
                    "type": "number",
                    "description": "Zoom factor (default: 1.0)",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_schematic_svg",
        description=(
            "Export a KiCad schematic as SVG. Supports theme and page selection "
            "for multi-sheet schematics. Equivalent to kicad-cli sch export svg."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "schematic_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_sch file",
                    "minLength": 1,
                },
                "output_file": {
                    "type": "string",
                    "description": "Output SVG path (default: {stem}.svg)",
                },
                "theme": {
                    "type": "string",
                    "description": "Color theme name",
                },
                "page": {
                    "type": "string",
                    "description": "Page identifier for multi-sheet schematics",
                },
            },
            "required": ["schematic_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_pcb_svg",
        description=(
            "Export a KiCad PCB as SVG. Supports theme, layer, and page selection. "
            "Equivalent to kicad-cli pcb export svg."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_file": {
                    "type": "string",
                    "description": "Output SVG path (default: {stem}.svg)",
                },
                "theme": {
                    "type": "string",
                    "description": "Color theme name",
                },
                "layers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Layer names to export (default: all layers)",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_pcb_pdf",
        description=(
            "Export a KiCad PCB as PDF. Supports theme selection. Equivalent to "
            "kicad-cli pcb export pdf."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_file": {
                    "type": "string",
                    "description": "Output PDF path (default: {stem}.pdf)",
                },
                "theme": {
                    "type": "string",
                    "description": "Color theme name",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_schematic_bom",
        description=(
            "Export a Bill of Materials from a KiCad schematic as CSV. Supports "
            "field selection, grouping, and DNP exclusion. Returns component counts "
            "and the CSV file path. Equivalent to kicad-cli sch export bom."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "schematic_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_sch file",
                    "minLength": 1,
                },
                "output_file": {
                    "type": "string",
                    "description": "Output CSV path (default: {stem}-BOM.csv)",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of fields to export",
                },
                "exclude_dnp": {
                    "type": "boolean",
                    "description": "Exclude Do Not Populate components (default: false)",
                    "default": False,
                },
            },
            "required": ["schematic_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_pcb_step",
        description=(
            "Export a KiCad PCB as a STEP 3D model. Supports origin selection "
            "and DNP exclusion. Useful for mechanical integration. Equivalent to "
            "kicad-cli pcb export step."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_file": {
                    "type": "string",
                    "description": "Output STEP path (default: {stem}.step)",
                },
                "no_dnp": {
                    "type": "boolean",
                    "description": "Exclude DNP components (default: true)",
                    "default": True,
                },
                "origin": {
                    "type": "string",
                    "description": "Origin mode: 'grid' or 'drill'",
                    "enum": ["grid", "drill"],
                    "default": "grid",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_pcb_gerbers",
        description=(
            "Export Gerber files from a KiCad PCB for manufacturing. Supports "
            "layer selection, drill origin, and soldermask subtraction. Returns "
            "the output directory and list of generated files. Equivalent to "
            "kicad-cli pcb export gerbers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory (default: gerber/)",
                },
                "layers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Layer names to export (default: all layers)",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_pcb_drill",
        description=(
            "Export drill files from a KiCad PCB. Supports format selection "
            "(Excellon or Gerber) and drill map generation. Equivalent to "
            "kicad-cli pcb export drill."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory (default: gerber/)",
                },
                "format": {
                    "type": "string",
                    "description": "Drill format: 'excellon' or 'gerber'",
                    "enum": ["excellon", "gerber"],
                    "default": "excellon",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="export_pcb_position",
        description=(
            "Export component position files from a KiCad PCB for pick-and-place "
            "machines. Supports format, units, and side selection. Equivalent to "
            "kicad-cli pcb export pos."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory (default: PCB parent dir)",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'ascii', 'csv', or 'gerber'",
                    "enum": ["ascii", "csv", "gerber"],
                    "default": "ascii",
                },
                "units": {
                    "type": "string",
                    "description": "Output units: 'mm' or 'in'",
                    "enum": ["mm", "in"],
                    "default": "mm",
                },
                "side": {
                    "type": "string",
                    "description": "Which side to export: 'front', 'back', or 'both'",
                    "enum": ["front", "back", "both"],
                    "default": "both",
                },
            },
            "required": ["pcb_file"],
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
    types.Tool(
        name="run_workflow",
        description=(
            "Run a predefined workflow on a PCB file. The 'route_and_fill' workflow "
            "analyzes routing gaps and fills them iteratively. Other workflow names run "
            "their registered template steps via batch execution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workflow_name": {
                    "type": "string",
                    "description": "Workflow name: 'route_and_fill' or a registered template name",
                    "minLength": 1,
                },
                "pcb_file": {
                    "type": "string",
                    "description": "Relative path to .kicad_pcb file",
                    "minLength": 1,
                },
                "use_ai": {
                    "type": "boolean",
                    "description": "Use AI for gap filling (default: true)",
                    "default": True,
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Max gap-fill iterations 1-3 (default: 3)",
                    "minimum": 1,
                    "maximum": 3,
                },
                "target_route_pct": {
                    "type": "number",
                    "description": "Target route percentage 0-100 (default: 95)",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
            "required": ["workflow_name", "pcb_file"],
        },
    ),
]


# Cache tool list at module level
_OPERATION_TOOLS = _generate_operation_tools()
_ALL_TOOLS = _OPERATION_TOOLS + _META_TOOLS
_OP_NAMES = {t.name for t in _OPERATION_TOOLS}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _cap_response(text: str) -> str:
    """Truncate response if it exceeds 50KB."""
    if len(text.encode("utf-8")) <= _MAX_RESPONSE_BYTES:
        return text
    truncation_notice = (
        f'\n\n--- RESPONSE TRUNCATED (original {len(text)} chars) ---\n'
        "Use query_connectivity or get_project_context for focused queries."
    )
    budget = _MAX_RESPONSE_BYTES - len(truncation_notice.encode("utf-8"))
    return text[:budget] + truncation_notice


def _error_result(error_type: str, message: str, suggestion: str = "") -> types.CallToolResult:
    """Build a structured error result."""
    body = {"error_type": error_type, "message": message}
    if suggestion:
        body["suggestion"] = suggestion
    return types.CallToolResult(
        isError=True,
        content=[types.TextContent(type="text", text=json.dumps(body, indent=2))],
    )


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def server_lifespan(server: Server):  # type: ignore[type-arg]
    """Create OperationExecutor and resolve base directory."""
    base_dir_str = os.environ.get("KICAD_PROJECT_DIR", "")
    base_dir = Path(base_dir_str) if base_dir_str else Path.cwd()
    base_dir = base_dir.resolve()

    if not base_dir.is_dir():
        logger.warning("KICAD_PROJECT_DIR does not exist: %s", base_dir)

    # M-02: Parse KICAD_UNDO_MAX_SIZE with error handling
    try:
        max_undo = max(1, int(os.environ.get("KICAD_UNDO_MAX_SIZE", "50")))
    except (ValueError, TypeError):
        max_undo = 50

    # Issue #7: Use PersistentUndoStack when project dir is known,
    # so undo survives process restarts.
    try:
        from kicad_agent.ops.persistent_undo import PersistentUndoStack
        undo_stack = PersistentUndoStack(project_dir=base_dir, max_size=max_undo)
    except Exception as exc:
        logger.info("Falling back to in-memory undo stack: %s", exc)
        undo_stack = UndoStack(max_size=max_undo)
    executor = OperationExecutor(base_dir=base_dir, undo_stack=undo_stack)
    yield {"executor": executor, "base_dir": base_dir}


app = Server("kicad-agent-edit", version="0.1.0", lifespan=server_lifespan)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return all available MCP tools (operation tools + 18 meta-tools)."""
    return _ALL_TOOLS


# Names of export/render convenience tools
_EXPORT_TOOL_NAMES = frozenset({
    "render_pcb",
    "export_schematic_svg",
    "export_pcb_svg",
    "export_pcb_pdf",
    "export_schematic_bom",
    "export_pcb_step",
    "export_pcb_gerbers",
    "export_pcb_drill",
    "export_pcb_position",
})


async def _dispatch_export_tool(
    name: str,
    arguments: dict[str, Any],
    base_dir: Path,
) -> types.CallToolResult | None:
    """Dispatch export/render convenience tools.

    Returns None if the tool name is not an export tool (caller should continue
    dispatching to other handlers). Returns a CallToolResult for recognized tools.
    """
    if name not in _EXPORT_TOOL_NAMES:
        return None

    try:
        if name == "render_pcb":
            result = await asyncio.to_thread(
                _export_render_pcb, arguments, base_dir,
            )
            return _render_result_to_mcp(result)

        if name == "export_schematic_svg":
            result = await asyncio.to_thread(
                _export_schematic_svg_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

        if name == "export_pcb_svg":
            result = await asyncio.to_thread(
                _export_pcb_svg_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

        if name == "export_pcb_pdf":
            result = await asyncio.to_thread(
                _export_pcb_pdf_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

        if name == "export_schematic_bom":
            result = await asyncio.to_thread(
                _export_schematic_bom_handler, arguments, base_dir,
            )
            return _bom_result_to_mcp(result)

        if name == "export_pcb_step":
            result = await asyncio.to_thread(
                _export_pcb_step_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

        if name == "export_pcb_gerbers":
            result = await asyncio.to_thread(
                _export_pcb_gerbers_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

        if name == "export_pcb_drill":
            result = await asyncio.to_thread(
                _export_pcb_drill_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

        if name == "export_pcb_position":
            result = await asyncio.to_thread(
                _export_pcb_position_handler, arguments, base_dir,
            )
            return _export_result_to_mcp(result)

    except FileNotFoundError as e:
        return _error_result("file_not_found", str(e), "Verify the file path is correct.")
    except ValueError as e:
        return _error_result("validation_error", str(e))
    except Exception as e:
        return _error_result("export_error", str(e))

    return None


# ---------------------------------------------------------------------------
# Export tool handler implementations (sync, called via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _export_render_pcb(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle render_pcb MCP tool call."""
    from kicad_agent.export.render import render_pcb
    pcb_path = base_dir / arguments["pcb_file"]
    output_path = base_dir / arguments["output_file"] if "output_file" in arguments else None
    return render_pcb(
        pcb_path,
        output_path=output_path,
        width=arguments.get("width", 1600),
        height=arguments.get("height", 1200),
        background_color=arguments.get("background_color"),
        side=arguments.get("side"),
        rotate=arguments.get("rotate"),
        zoom=arguments.get("zoom"),
    )


def _export_schematic_svg_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_schematic_svg MCP tool call."""
    from kicad_agent.export.render import export_schematic_svg
    sch_path = base_dir / arguments["schematic_file"]
    output_path = base_dir / arguments["output_file"] if "output_file" in arguments else None
    return export_schematic_svg(
        sch_path,
        output_path=output_path,
        theme=arguments.get("theme"),
        page=arguments.get("page"),
    )


def _export_pcb_svg_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_pcb_svg MCP tool call."""
    from kicad_agent.export.render import export_pcb_svg
    pcb_path = base_dir / arguments["pcb_file"]
    output_path = base_dir / arguments["output_file"] if "output_file" in arguments else None
    return export_pcb_svg(
        pcb_path,
        output_path=output_path,
        theme=arguments.get("theme"),
        layers=arguments.get("layers"),
        page=arguments.get("page"),
    )


def _export_pcb_pdf_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_pcb_pdf MCP tool call."""
    from kicad_agent.export.render import export_pcb_pdf
    pcb_path = base_dir / arguments["pcb_file"]
    output_path = base_dir / arguments["output_file"] if "output_file" in arguments else None
    return export_pcb_pdf(
        pcb_path,
        output_path=output_path,
        theme=arguments.get("theme"),
    )


def _export_schematic_bom_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_schematic_bom MCP tool call."""
    from kicad_agent.export.bom import export_bom
    sch_path = base_dir / arguments["schematic_file"]
    output_path = base_dir / arguments["output_file"] if "output_file" in arguments else None
    return export_bom(
        sch_path,
        output_path=output_path,
        fields=arguments.get("fields"),
        exclude_dnp=arguments.get("exclude_dnp", False),
    )


def _export_pcb_step_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_pcb_step MCP tool call."""
    from kicad_agent.export.general import export_step
    pcb_path = base_dir / arguments["pcb_file"]
    output_path = base_dir / arguments["output_file"] if "output_file" in arguments else None
    return export_step(
        pcb_path,
        output_path=output_path,
        no_dnp=arguments.get("no_dnp", True),
        origin=arguments.get("origin", "grid"),
    )


def _export_pcb_gerbers_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_pcb_gerbers MCP tool call."""
    from kicad_agent.export.gerber import export_gerber
    pcb_path = base_dir / arguments["pcb_file"]
    output_dir = base_dir / arguments["output_dir"] if "output_dir" in arguments else None
    return export_gerber(
        pcb_path,
        output_dir=output_dir,
        layers=arguments.get("layers"),
    )


def _export_pcb_drill_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_pcb_drill MCP tool call."""
    from kicad_agent.export.gerber import export_drill
    pcb_path = base_dir / arguments["pcb_file"]
    output_dir = base_dir / arguments["output_dir"] if "output_dir" in arguments else None
    return export_drill(
        pcb_path,
        output_dir=output_dir,
        format=arguments.get("format", "excellon"),
    )


def _export_pcb_position_handler(arguments: dict[str, Any], base_dir: Path) -> object:
    """Handle export_pcb_position MCP tool call."""
    from kicad_agent.export.general import export_position
    pcb_path = base_dir / arguments["pcb_file"]
    output_dir = base_dir / arguments["output_dir"] if "output_dir" in arguments else None
    return export_position(
        pcb_path,
        output_dir=output_dir,
        format=arguments.get("format", "ascii"),
        units=arguments.get("units", "mm"),
        side=arguments.get("side", "both"),
    )


# ---------------------------------------------------------------------------
# Result-to-MCP converters
# ---------------------------------------------------------------------------


def _render_result_to_mcp(result: Any) -> types.CallToolResult:
    """Convert a RenderResult to an MCP CallToolResult."""
    data = {
        "success": result.success,
        "output_path": str(result.output_path),
        "width_px": result.width_px,
        "height_px": result.height_px,
        "command": result.command,
    }
    if result.stderr:
        data["stderr"] = result.stderr
    text = _cap_response(json.dumps(data, indent=2))
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def _export_result_to_mcp(result: Any) -> types.CallToolResult:
    """Convert an ExportResult to an MCP CallToolResult."""
    data = {
        "success": result.success,
        "output_dir": str(result.output_dir),
        "files": [str(f) for f in result.files],
        "file_count": len(result.files),
        "command": result.command,
    }
    if result.stderr:
        data["stderr"] = result.stderr
    text = _cap_response(json.dumps(data, indent=2))
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def _bom_result_to_mcp(result: Any) -> types.CallToolResult:
    """Convert a BomResult to an MCP CallToolResult."""
    data = {
        "success": result.success,
        "output_path": str(result.output_path),
        "component_count": result.component_count,
        "unique_components": result.unique_components,
        "command": result.command,
    }
    if result.stderr:
        data["stderr"] = result.stderr
    text = _cap_response(json.dumps(data, indent=2))
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    executor: OperationExecutor,
    base_dir: Path,
) -> types.CallToolResult:
    """Route tool calls to executor or meta-tool handlers.

    Separated from the MCP handler for testability — tests can call this
    directly without needing a live MCP request context.
    """
    global _in_flight_count

    # --- Meta-tools ---
    if name == "health_check":
        uptime = time.time() - _started_at
        with _in_flight_lock:
            current_count = _in_flight_count
        health = {
            "status": "shutting_down" if _shutdown_event.is_set() else "healthy",
            "uptime_seconds": round(uptime, 1),
            "executor_ready": executor is not None,
            "project_dir": str(base_dir),
            "in_flight_operations": current_count,
            "total_tools_available": len(_ALL_TOOLS),
        }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(health, indent=2))],
        )

    # Reject all other operations during shutdown
    if _shutdown_event.is_set():
        return _error_result("shutting_down", "Server is shutting down, not accepting new operations")

    if name == "get_operation_schema":
        schema = Operation.model_json_schema()
        text = _cap_response(json.dumps(schema, indent=2))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
        )

    if name == "get_project_context":
        try:
            enrich = arguments.get("enrich", True)
            context = await asyncio.to_thread(
                render_project_context, base_dir, enrich,
            )
            text = _cap_response(context)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result("context_error", str(e))

    # --- Validation tools ---
    if name == "erc_check":
        try:
            sch_file = arguments["schematic_file"]
            sch_path = base_dir / sch_file
            result = await asyncio.to_thread(run_erc, sch_path)
            text = _cap_response(json.dumps({
                "passed": result.passed,
                "file": str(result.file_path),
                "violation_count": len(result.violations),
                "errors": len(result.errors),
                "warnings": len(result.warnings),
                "violations": [
                    {"severity": v.severity.value, "type": v.type,
                     "description": v.description, "sheet": v.sheet_path}
                    for v in result.violations[:50]
                ],
                "kicad_version": result.kicad_version,
                "error_message": result.error_message,
            }, indent=2, default=str))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result(
                "erc_error", str(e), "Verify the schematic file path is correct."
            )

    if name == "drc_check":
        try:
            pcb_file = arguments["pcb_file"]
            pcb_path = base_dir / pcb_file
            result = await asyncio.to_thread(run_drc, pcb_path)
            text = _cap_response(json.dumps({
                "passed": result.passed,
                "file": str(result.file_path),
                "violation_count": len(result.violations),
                "unconnected_count": len(result.unconnected_items),
                "violations": [
                    {"severity": v.severity.value, "type": v.type,
                     "description": v.description}
                    for v in result.violations[:50]
                ],
                "unconnected_items": [
                    {"description": v.description, "type": v.type}
                    for v in result.unconnected_items[:20]
                ],
                "kicad_version": result.kicad_version,
                "error_message": result.error_message,
            }, indent=2, default=str))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result(
                "drc_error", str(e), "Verify the PCB file path is correct."
            )

    # --- Undo/Redo tools ---
    if name == "undo":
        try:
            target_file = arguments.get("target_file")
            result = await asyncio.to_thread(executor.undo, target_file)
            if result.get("success"):
                text = _cap_response(json.dumps(result, indent=2, default=str))
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                )
            return _error_result("undo_error", result.get("error", "No operations to undo"))
        except Exception as e:
            return _error_result("undo_error", str(e), "No operations to undo.")

    if name == "redo":
        try:
            target_file = arguments.get("target_file")
            result = await asyncio.to_thread(executor.redo, target_file)
            if result.get("success"):
                text = _cap_response(json.dumps(result, indent=2, default=str))
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                )
            return _error_result("redo_error", result.get("error", "No operations to redo"))
        except Exception as e:
            return _error_result("redo_error", str(e), "No operations to redo.")

    # --- Workflow meta-tools ---
    if name == "list_workflows":
        try:
            from kicad_agent.ops.workflows import list_workflows as _list_wfs
            workflows = _list_wfs()
            text = _cap_response(json.dumps(workflows, indent=2))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result("workflow_error", str(e))

    if name == "get_workflow":
        try:
            wf_name = arguments.get("name", "")
            from kicad_agent.ops.workflows import get_workflow as _get_wf
            wf = _get_wf(wf_name)
            if wf is None:
                return _error_result(
                    "workflow_not_found",
                    f"Unknown workflow: {wf_name!r}",
                    "Use list_workflows to discover available workflow names.",
                )
            wf_dict = {
                "name": wf.name,
                "description": wf.description,
                "file_types": wf.file_types,
                "steps": [
                    {
                        "op_type": s.op_type,
                        "description": s.description,
                        "required": s.required,
                    }
                    for s in wf.steps
                ],
            }
            text = _cap_response(json.dumps(wf_dict, indent=2))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result("workflow_error", str(e))

    if name == "run_workflow":
        try:
            wf_name = arguments.get("workflow_name", "")
            pcb_path = arguments.get("pcb_file", "")
            if not pcb_path:
                return _error_result("workflow_error", "pcb_file is required")

            from kicad_agent.ops.workflow_runner import WorkflowRunner

            overrides: dict[str, Any] = {}
            if "use_ai" in arguments:
                overrides["use_ai"] = arguments["use_ai"]
            if "max_iterations" in arguments:
                overrides["max_iterations"] = arguments["max_iterations"]
            if "target_route_pct" in arguments:
                overrides["target_route_pct"] = arguments["target_route_pct"]

            runner = WorkflowRunner()
            result = await asyncio.to_thread(runner.run, wf_name, pcb_path, **overrides)
            text = _cap_response(json.dumps(result.to_json(), indent=2, default=str))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return _error_result("workflow_error", str(e))

    # --- Export/Render convenience tools ---
    _export_tool_result = await _dispatch_export_tool(name, arguments, base_dir)
    if _export_tool_result is not None:
        return _export_tool_result

    # --- Operation tools ---
    if name not in _OP_NAMES:
        return _error_result(
            "unknown_tool",
            f"Unknown tool: {name}",
            f"Available tools: {', '.join(sorted(_OP_NAMES)[:10])}...",
        )

    with _in_flight_lock:
        _in_flight_count += 1
    try:
        # Inject op_type and resolve target_file against base_dir
        payload = {**arguments, "op_type": name}
        if "target_file" in payload:
            payload["target_file"] = str(Path(payload["target_file"]))
        if "target_files" in payload and isinstance(payload["target_files"], list):
            payload["target_files"] = [
                {**tf, "path": str(Path(tf["path"]))} if isinstance(tf, dict) and "path" in tf else tf
                for tf in payload["target_files"]
            ]

        # Validate via Pydantic
        op = Operation.model_validate({"root": payload})

        # Execute in thread to avoid blocking event loop
        result = await asyncio.to_thread(executor.execute, op)

        text = _cap_response(json.dumps(result, indent=2, default=str))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
        )

    except Exception as e:
        correlation_id = str(uuid.uuid4())[:8]
        logger.exception("Tool %s failed [ref=%s]", name, correlation_id)

        error_type = type(e).__name__
        message = str(e)
        suggestion = ""

        if "validation error" in message.lower():
            error_type = "validation_error"
            suggestion = "Check parameter types and required fields against the operation schema."
        elif isinstance(e, FileNotFoundError):
            suggestion = "Verify the target file path is correct and the file exists."
        elif isinstance(e, PermissionError):
            suggestion = "Check file permissions on the target KiCad file."

        return _error_result(
            error_type,
            f"{message} [ref: {correlation_id}]",
            suggestion,
        )
    finally:
        with _in_flight_lock:
            _in_flight_count -= 1


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """MCP handler — extracts lifespan context and delegates to dispatch_tool."""
    lifespan_ctx = app.request_context.lifespan_context  # type: ignore[attr-defined]
    executor: OperationExecutor = lifespan_ctx["executor"]
    base_dir: Path = lifespan_ctx["base_dir"]
    return await dispatch_tool(name, arguments, executor, base_dir)


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
    """CLI entry point for kicad-agent-edit."""
    from kicad_agent.logging_config import configure_logging
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
        # Windows fallback -- signal.signal works but is less clean
        import signal as sig_mod
        sig_mod.signal(sig_mod.SIGTERM, lambda s, f: _request_shutdown())
        sig_mod.signal(sig_mod.SIGINT, lambda s, f: _request_shutdown())

    try:
        loop.run_until_complete(_run_server())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
