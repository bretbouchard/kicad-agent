"""Cross-file handler implementations -- operations spanning multiple files.

Handlers receive (op, ir_map, base_dir) and return a result dict.
"""

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CROSSFILE_HANDLERS: dict[str, Callable] = {}


def register_crossfile(op_type: str) -> Callable:
    """Decorator to register a cross-file operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CROSSFILE_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_crossfile("propagate_symbol_change")
def _handle_propagate_symbol_change(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    from kicad_agent.crossfile.propagation import (
        propagate_footprint_ref,
        propagate_symbol_ref,
    )
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.ir.schematic_ir import SchematicIR

    results = []
    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            result = propagate_symbol_ref(ir, op.old_lib_id, op.new_lib_id)
            results.append({"file": str(file_path.name), "type": "schematic", "updated": result.updated_count})
        elif isinstance(ir, PcbIR):
            result = propagate_footprint_ref(ir, op.old_lib_id, op.new_lib_id)
            results.append({"file": str(file_path.name), "type": "pcb", "updated": result.updated_count})
    return {"files_modified": results, "total_updated": sum(r["updated"] for r in results)}
