"""Query handler implementations -- read-only PCB queries (no Transaction, no serialization).

Handlers receive (op, PcbIR, file_path) and return a result dict.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from volta.ir.pcb_ir import PcbIR

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
    from volta.ops.connectivity_query import handle_connectivity_query
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
    from volta.parser.pcb_native_parser import (
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
    from volta.manufacturing.board_spec import load_board_spec

    spec = load_board_spec(file_path)

    return {
        "title": title,
        "date": date,
        "rev": rev,
        "company": company,
        "comments": comments,
        "board_spec": spec.model_dump() if spec else None,
    }


@register_query("drc_vendor")
def _handle_drc_vendor(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Run vendor-specific DRC checks (DRC-01, DRC-04).

    Uses the internal geometric evaluator against ManufacturerProfile limits.
    Optionally also runs KiCad's built-in DRC (run_kicad_drc flag).

    CRITICAL: re-parse the PCB via NativeParser.parse_pcb(file_path) to get a
    NativeBoard. ``execute_query`` builds PcbIR via the kiutils path where
    _native_board is None (same dual-path issue as Phase 205's
    read_board_metadata handler). The evaluator needs the NativeBoard geometry.
    """
    from dataclasses import asdict

    from volta.dfm.profiles import load_profile
    from volta.manufacturing.vendor_drc import run_vendor_drc
    from volta.parser.pcb_native_parser import NativeParser

    profile = load_profile(op.vendor)  # raises ValueError if unknown
    board = NativeParser.parse_pcb(file_path)
    result = run_vendor_drc(board, profile)

    kicad_drc_result = None
    if op.run_kicad_drc:
        try:
            from volta.validation.erc_drc import run_drc
            drc = run_drc(file_path)
            kicad_drc_result = {
                "passed": drc.passed,
                "violations": [asdict(v) for v in drc.violations],
            }
        except Exception as exc:
            # kicad-cli may be absent in test/dev — degrade gracefully.
            kicad_drc_result = {"error": str(exc)}

    out = asdict(result)
    out["kicad_drc"] = kicad_drc_result
    # `passed` reflects VENDOR DRC only. kicad_drc is separate — user can check both.
    # If kicad_drc failed with errors, that does NOT affect vendor passed status.
    return out


@register_query("list_vendor_drc_profiles")
def _handle_list_vendor_drc_profiles(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """List available vendor DRC profiles with capabilities (DRC-08).

    The handler ignores ir and file_path — execute_query always builds a PcbIR
    before dispatching, so target_file is required by the schema even though
    unused (CONTEXT.md line 149 accepted trade-off).
    """
    from dataclasses import asdict

    from volta.manufacturing.drc_profiles import list_drc_profiles

    profiles = [asdict(p) for p in list_drc_profiles()]
    return {"profiles": profiles, "count": len(profiles)}

