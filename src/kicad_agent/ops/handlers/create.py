"""Create handler implementations -- file creation (no IR, no Transaction).

Handlers receive (op, file_path) and return a result dict.
"""

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CREATE_HANDLERS: dict[str, Callable] = {}


def register_create(op_type: str) -> Callable:
    """Decorator to register a file-creation operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CREATE_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_create("create_schematic")
def _handle_create_schematic(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_schematic
    return create_schematic(op, file_path)


@register_create("create_pcb")
def _handle_create_pcb(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_pcb
    return create_pcb(op, file_path)


@register_create("create_project")
def _handle_create_project(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_project
    return create_project(op, file_path)


@register_create("create_symbol")
def _handle_create_symbol(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_symbol
    return create_symbol(op, file_path)


@register_create("create_footprint")
def _handle_create_footprint(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.create_file import create_footprint
    return create_footprint(op, file_path)
