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

# kicad-agent-7xj fix: memoize skidl.utilities.get_abs_filename.
# Profiling showed Part() took ~500ms each because skidl.schlib.SchLib.__init__
# calls get_abs_filename(descend=-1) on EVERY Part() construction, BEFORE
# checking the SchLib._cache. The descend=-1 triggers an unlimited recursive
# filesystem walk (~100k+ scandir/lstat calls per Part()). Since library file
# paths don't change during a process lifetime, memoize the function.
import skidl.utilities  # noqa: E402
import functools  # noqa: E402

_ORIG_GET_ABS_FILENAME = skidl.utilities.get_abs_filename
_ABS_FILENAME_MEMO: dict[tuple, str | None] = {}

@functools.wraps(_ORIG_GET_ABS_FILENAME)
def _memoized_get_abs_filename(filename, paths=None, ext=None, allow_failure=False, descend=0):
    # Hashable cache key — paths may be a list, ext may be a list, both hashable
    # as tuples. descend + allow_failure are scalars.
    key = (filename, tuple(paths) if paths else None, tuple(ext) if ext else None, allow_failure, descend)
    if key in _ABS_FILENAME_MEMO:
        return _ABS_FILENAME_MEMO[key]
    result = _ORIG_GET_ABS_FILENAME(filename, paths, ext, allow_failure, descend)
    _ABS_FILENAME_MEMO[key] = result
    return result

# Patch both the module attribute and SchLib's lookup path (skidl imports
# get_abs_filename into its namespace at module load — must replace there too).
skidl.utilities.get_abs_filename = _memoized_get_abs_filename
# SchLib imports it via `from .utilities import find_and_open_file, ...` — but
# actually calls get_abs_filename via `from .utilities import get_abs_filename`
# at line ~109 of schlib.py. That bound name lives in schlib's namespace.
import skidl.schlib  # noqa: E402
skidl.schlib.get_abs_filename = _memoized_get_abs_filename

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
