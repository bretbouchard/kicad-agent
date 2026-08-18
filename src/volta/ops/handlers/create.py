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
    from volta.ops.create_file import create_schematic
    return create_schematic(op, file_path)


@register_create("create_pcb")
def _handle_create_pcb(op: Any, file_path: Path) -> dict[str, Any]:
    from volta.ops.create_file import create_pcb
    return create_pcb(op, file_path)


@register_create("create_project")
def _handle_create_project(op: Any, file_path: Path) -> dict[str, Any]:
    from volta.ops.create_file import create_project
    return create_project(op, file_path)


@register_create("create_symbol")
def _handle_create_symbol(op: Any, file_path: Path) -> dict[str, Any]:
    from volta.ops.create_file import create_symbol
    return create_symbol(op, file_path)


@register_create("create_footprint")
def _handle_create_footprint(op: Any, file_path: Path) -> dict[str, Any]:
    from volta.ops.create_file import create_footprint
    return create_footprint(op, file_path)


def _pins_from_cad_data(data: dict) -> list:
    """Map EasyEda CAD pin data to PinSpec list (pure, volta-4).

    Pin positions from the part's real pin map, scaled to schematic mm;
    names preserved so netlist intent survives import.
    """
    from volta.ops.schema import PinSpec, PositionSpec

    pins = []
    for p in data.get("pins", []):
        pins.append(PinSpec(
            number=str(p["number"]),
            name=str(p.get("name") or f"~{p['number']}"),
            electrical_type="passive",
            position=PositionSpec(
                x=round(float(p.get("x", 0.0)) * 2.54 / 1.0, 3),
                y=round(float(p.get("y", 0.0)) * 2.54 / 1.0, 3),
            ),
        ))
    return pins


@register_create("import_symbol")
def _handle_import_symbol(op: Any, file_path: Path) -> dict[str, Any]:
    """volta-4: import a symbol into the project library."""
    from volta.ops.schema import Operation

    if op.symbol_sexp is not None:
        # Raw path: append the supplied symbol S-expression to the library.
        symbol_name = op.symbol_name
        if symbol_name is None:
            import re

            m = re.search(r"\(symbol\s+\"([^\"]+)\"", op.symbol_sexp)
            if not m:
                return {"status": "error",
                    "error": "symbol_sexp has no symbol name header"}
            symbol_name = m.group(1)
        content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        if f'(symbol "{symbol_name}"' in content:
            return {"status": "error", "error": f"symbol {symbol_name!r} already exists in {file_path.name}"}
        # Append before the final closing paren of the library root.
        sexp = op.symbol_sexp.strip()
        if content.strip():
            last = content.rfind(")")
            content = content[:last] + "\n" + sexp + "\n" + content[last:]
        else:
            content = sexp + "\n"
        file_path.write_text(content, encoding="utf-8")
        return {
            "status": "ok",
            "symbol_name": symbol_name,
            "source": "raw",
            "library": str(file_path),
            "bytes": len(content),
        }

    # Provider path: LCSC part data -> real-pinned symbol via create_symbol.
    from volta.crawler.easyeda_source import EasyEdaSource

    source = EasyEdaSource()
    data = source.get_cad_data(op.part_number)
    if data is None:
        return {
            "status": "error",
            "error": f"no CAD data for part {op.part_number!r} (offline or unknown part)",
        }
    title = data.get("title") or op.part_number
    symbol_name = op.symbol_name or title.replace(" ", "_")
    create_op = Operation.model_validate({
        "root": {
            "op_type": "create_symbol",
            "target_file": file_path.name,
            "symbol_name": symbol_name,
            "reference_prefix": op.reference_prefix,
            "value": op.value or title,
            "pins": [
                {
                    "number": p.number,
                    "name": p.name,
                    "electrical_type": p.electrical_type,
                    "position": {"x": p.position.x, "y": p.position.y},
                }
                for p in _pins_from_cad_data(data)
            ],
        }
    })
    from volta.ops.create_file import create_symbol as _create_symbol

    result = _create_symbol(create_op.root, file_path)
    result.setdefault("status", "ok")
    result["source"] = "lcsc"
    result["part_number"] = op.part_number
    result["pin_count"] = len(data.get("pins", []))
    return result


@register_create("convert_from_skidl")
def _handle_convert_from_skidl(op: Any, file_path: Path) -> dict[str, Any]:
    """Phase 156 C-03/REG-2: Build a .kicad_sch from a SKIDL program.

    Registered as a CREATE op because it creates a new file (bypasses
    the existence check in the executor). Writes raw S-expr.
    """
    from volta.circuit_ir.skidl_to_kicad import skidl_to_kicad_sch

    source = Path(op.source)
    result_path = skidl_to_kicad_sch(source, file_path)

    return {
        "op_type": "convert_from_skidl",
        "source": str(source),
        "output": str(result_path),
        "source_type": getattr(op, "source_type", "skidl"),
    }
