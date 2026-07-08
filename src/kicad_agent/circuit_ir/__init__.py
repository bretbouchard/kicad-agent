"""Phase 156: SKIDL Circuit IR — bidirectional KiCad↔SKIDL bridge.

SKIDL becomes the canonical intermediate representation for all downstream
circuit operations (floor planning, SPICE, training data). This package
provides the KiCad→SKIDL read-back path (the one direction that did not
exist) by composing SchematicIR + extract_nets.

Pitfall #6 guard: KICAD_SYMBOL_DIR MUST be set before importing skidl,
otherwise skidl silently resolves no symbols and parts get no pins.

Public API:
    - CircuitIR, PartDescriptor, NetDescriptor, PinRef — immutable types
    - build_circuit — KiCad→SKIDL read-back (returns live skidl.Circuit)
    - KiCadToSkidlConverter — generates build_*.py text (Wave 2)
    - PartsMapper — maps KiCad lib_ids to SKIDL strategies
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- Pitfall #6: KICAD_SYMBOL_DIR must be set BEFORE importing skidl ---

_KICAD_SYMBOL_PATHS = [
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
    Path("/usr/share/kicad/symbols"),
    Path("/usr/local/share/kicad/symbols"),
    Path.home() / ".local" / "share" / "kicad" / "symbols",
]


def _find_symbol_dir() -> str | None:
    """Find the KiCad symbol library directory on this system."""
    env_val = os.environ.get("KICAD_SYMBOL_DIR")
    if env_val and Path(env_val).exists():
        return env_val
    for p in _KICAD_SYMBOL_PATHS:
        if p.exists() and any(p.glob("*.kicad_sym")):
            return str(p)
    return None


def _ensure_skidl_env(symbol_dir: str | None = None) -> str:
    """Set KICAD_SYMBOL_DIR before importing skidl (pitfall #6).

    skidl resolves symbols against the KiCad library at import time.
    If KICAD_SYMBOL_DIR is unset, parts silently get no pins.
    """
    sym_dir = symbol_dir or _find_symbol_dir()
    if not sym_dir:
        raise RuntimeError(
            "KICAD_SYMBOL_DIR not set and KiCad symbols not found at "
            "standard paths. Set KICAD_SYMBOL_DIR or pass symbol_dir="
        )
    os.environ["KICAD_SYMBOL_DIR"] = sym_dir
    for ver in (5, 6, 7, 8, 9, 10):
        os.environ[f"KICAD{ver}_SYMBOL_DIR"] = sym_dir
    return sym_dir


# Set the environment before any skidl import.
_SYMBOL_DIR = _ensure_skidl_env()

# Now safe to import skidl.
import skidl  # noqa: E402

# kicad-agent-pzz fix (revised): redirect skidl's backup_lib file to a stable
# cache dir instead of disabling it. Original fix (no-op backup_parts) broke
# skidl's in-memory symbol cache — every Part() lookup re-parsed the full
# Device.kicad_sym library (~8-12s per build_preamp_circuit call vs <1s).
#
# skidl.Circuit.backup_parts() writes a {script_name}_sklib.py file on every
# Circuit context exit. Under pytest, get_script_name() returns the test's
# tmp_path prefix → tmp00sg8hh9_sklib.py files pollute cwd. Solution: point
# backup_lib_file_name at a stable, per-user cache dir so:
#   (a) cwd stays clean (no tmp*_sklib.py pollution)
#   (b) skidl's caching stays active (fast Part() lookups)
#   (c) the cache file persists across sessions for warm-start speedup
#
# Cache dir resolution uses stdlib only (no platformdirs dep):
#   macOS:   ~/Library/Caches/kicad-agent/skidl
#   Linux:   ${XDG_CACHE_HOME:-~/.cache}/kicad-agent/skidl
if sys.platform == "darwin":
    _CACHE_BASE = Path.home() / "Library" / "Caches"
else:
    _CACHE_BASE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
_CACHE_DIR = _CACHE_BASE / "kicad-agent" / "skidl"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_FILE = _CACHE_DIR / "backup_sklib.py"

skidl.config.backup_lib_name = "kicad_agent_cache"  # type: ignore[attr-defined]
skidl.config.backup_lib_file_name = str(_CACHE_FILE)  # type: ignore[attr-defined]
skidl.config.query_backup_lib = True  # type: ignore[attr-defined]

from kicad_agent.circuit_ir.types import (  # noqa: E402
    CircuitIR,
    NetDescriptor,
    PartDescriptor,
    PinRef,
)
from kicad_agent.circuit_ir.skidl_circuit import build_circuit  # noqa: E402
from kicad_agent.circuit_ir.converter import KiCadToSkidlConverter  # noqa: E402
from kicad_agent.circuit_ir.emitter import SkidlEmitter  # noqa: E402
from kicad_agent.circuit_ir.parts_mapper import PartsMapper  # noqa: E402
from kicad_agent.circuit_ir.symbol_resolver import resolve_lib_symbol, get_pin_names  # noqa: E402
from kicad_agent.circuit_ir.skidl_emitter import emit_build_py  # noqa: E402
from kicad_agent.circuit_ir.hierarchy_flattener import flatten_to_circuit_ir  # noqa: E402
from kicad_agent.circuit_ir.skidl_to_kicad import circuit_to_kicad_sch  # noqa: E402

__all__ = [
    "CircuitIR",
    "PartDescriptor",
    "NetDescriptor",
    "PinRef",
    "build_circuit",
    "emit_build_py",
    "resolve_lib_symbol",
    "get_pin_names",
    "flatten_to_circuit_ir",
    "circuit_to_kicad_sch",
    "KiCadToSkidlConverter",
    "SkidlEmitter",
    "PartsMapper",
    "_ensure_skidl_env",
]
