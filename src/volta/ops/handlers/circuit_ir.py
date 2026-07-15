"""Handlers for circuit_ir operations (SKIDL converter)."""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CIRCUIT_IR_HANDLERS: dict[str, Callable] = {}


def register_circuit_ir(op_type: str) -> Callable:
    """Decorator to register a circuit_ir operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CIRCUIT_IR_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_circuit_ir("convert_to_skidl")
def _handle_convert_to_skidl(op: Any, file_path: Path) -> dict[str, Any]:
    """Convert a KiCad schematic to SKIDL Python code."""
    from volta.circuit_ir import KiCadToSkidlConverter
    
    converter = KiCadToSkidlConverter()
    
    level = getattr(op, "level", "L1")
    output_file = getattr(op, "output_file", None)
    
    code = converter.convert(file_path, output_file, level=level)
    
    return {
        "op_type": "convert_to_skidl",
        "file": str(file_path),
        "level": level,
        "output_lines": code.count("\n"),
        "output_file": output_file,
        "components": len(converter.components) if hasattr(converter, 'components') else 0,
        "power_nets": sorted(converter.power_nets) if hasattr(converter, 'power_nets') else [],
        "code_length": len(code),
    }
