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


@register_query("read_board_metadata")
def _handle_read_board_metadata(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Read title_block fields + board_spec sidecar (META-01).

    CRITICAL: execute_query builds PcbIR via the kiutils path (RESEARCH RQ1),
    so ``ir.board`` is a kiutils Board and ``ir.board.title_block`` does NOT
    exist. Parse title_block from ``ir.raw_content`` using the native parser
    helper functions directly.
    """
    import sexpdata
    from kicad_agent.parser.pcb_native_parser import (
        _find_string_child,
        _find_symbol,
        _sym,
    )

    tree = sexpdata.loads(ir.raw_content)
    tb_block = _find_symbol(tree, "title_block")

    title = ""
    date = ""
    rev = ""
    company = ""
    comments: list[str] = []
    if tb_block is not None:
        title = _find_string_child(tb_block, "title")
        date = _find_string_child(tb_block, "date")
        rev = _find_string_child(tb_block, "rev")
        company = _find_string_child(tb_block, "company")
        comments_map: dict[int, str] = {}
        for item in tb_block:
            if isinstance(item, list) and len(item) >= 3 and _sym(item[0]) == "comment":
                try:
                    num = int(item[1])
                    text = item[2] if isinstance(item[2], str) else str(item[2])
                    comments_map[num] = text
                except (ValueError, TypeError):
                    continue
        if comments_map:
            max_n = max(comments_map)
            comments = [comments_map.get(i, "") for i in range(1, max_n + 1)]

    # Load board_spec sidecar if present (META-04)
    from kicad_agent.manufacturing.board_spec import load_board_spec

    spec = load_board_spec(file_path)

    return {
        "title": title,
        "date": date,
        "rev": rev,
        "company": company,
        "comments": comments,
        "board_spec": spec.model_dump() if spec else None,
    }

