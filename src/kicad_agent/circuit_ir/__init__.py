"""Circuit IR — bidirectional KiCad ↔ SKIDL bridge.

Provides:
- convert_to_skidl: read .kicad_sch → generate Python build_*.py
- convert_from_skidl: execute SKIDL code → generate KiCad schematic

Architecture mirrors the ltspice/ package: neutral intermediate
representation (circuit_ir) that bridges KiCad and downstream tools.
"""

import os as _os

# CRITICAL: KICAD_SYMBOL_DIR must be set BEFORE importing skidl.
# skidl reads it at module import time (module-level side effect).
# Without this, skidl emits "KICAD8_SYMBOL_DIR is missing" warnings.
_DEFAULT_SYM_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
if not _os.environ.get("KICAD_SYMBOL_DIR"):
    _os.environ["KICAD_SYMBOL_DIR"] = _DEFAULT_SYM_DIR
for _v in ("KICAD5", "KICAD6", "KICAD7", "KICAD8", "KICAD9"):
    _env_key = f"{_v}_SYMBOL_DIR"
    if not _os.environ.get(_env_key):
        _os.environ[_env_key] = _DEFAULT_SYM_DIR

from .converter import KiCadToSkidlConverter
from .emitter import SkidlEmitter
from .parts_mapper import PartsMapper

__all__ = [
    "KiCadToSkidlConverter",
    "SkidlEmitter",
    "PartsMapper",
    "convert_to_skidl",
]
