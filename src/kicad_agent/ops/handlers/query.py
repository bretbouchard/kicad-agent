"""Query handler implementations -- read-only PCB queries (no Transaction, no serialization).

Handlers receive (op, PcbIR, file_path) and return a result dict.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)

_QUERY_HANDLERS: dict[str, Callable] = {}


def register_query(op_type: str) -> Callable:
    """Decorator to register a read-only query operation handler."""
    def decorator(fn: Callable) -> Callable:
        _QUERY_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_query("query_connectivity")
def _handle_query_connectivity(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.connectivity_query import handle_connectivity_query
    return handle_connectivity_query(op, ir, file_path)
