"""Phase 156 Wave 3: Symbol library resolver.

Resolves KiCad lib_ids (e.g. "Device:R") to their raw symbol blocks from
.kicad_sym library files. Handles:
  - Multi-unit symbols (NE5532 units A/B, RP2350B power/GPIO units)
  - extends inheritance (child inherits parent pins)
  - _0_0 → _1_1 common-pin rename (KiCad convention for shared pins)

Ported from analog-ecosystem gen_schematic.py (resolve_lib_symbol +
_resolve_extends), adapted for the circuit_ir package.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Default KiCad symbol library location.
_DEFAULT_SYM_DIR = Path(
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
)


def resolve_lib_symbol(lib_id: str, sym_dir: Path | None = None) -> str:
    """Resolve a KiCad lib_id to its raw symbol block from the .kicad_sym file.

    Args:
        lib_id: Library ID like "Device:R" or "Amplifier_Operational:NE5532".
        sym_dir: Symbol library directory (default: system KiCad path).

    Returns:
        The raw S-expression symbol block, ready for embedding in lib_symbols.

    Raises:
        ValueError: If the symbol or its library file can't be found.
    """
    sym_dir = sym_dir or _DEFAULT_SYM_DIR
    if ":" not in lib_id:
        raise ValueError(f"Invalid lib_id (expected 'Lib:Symbol'): {lib_id}")

    lib_name, symbol_name = lib_id.split(":", 1)
    lib_file = sym_dir / f"{lib_name}.kicad_sym"

    if not lib_file.exists():
        raise ValueError(f"Library file not found: {lib_file}")

    content = _load_lib(lib_file)
    raw = _get_raw_symbol(content, symbol_name)
    if raw is None:
        raise ValueError(f"Symbol '{symbol_name}' not found in {lib_file.name}")

    # Handle extends inheritance.
    extends_match = re.search(r'\(extends\s+"([^"]+)"\)', raw)
    if extends_match:
        parent_name = extends_match.group(1)
        parent_raw = _get_raw_symbol(content, parent_name)
        if parent_raw:
            raw = _resolve_extends(raw, symbol_name, parent_name, parent_raw)

    # Normalize: rename outer symbol to lib:symbol format.
    raw = re.sub(
        rf'\(symbol\s+"{re.escape(symbol_name)}"',
        f'(symbol "{lib_id}"',
        raw,
        count=1,
    )

    # Normalize _0_0 → _1_1 (common-pin convention).
    raw = re.sub(
        rf'{re.escape(symbol_name)}_0_0',
        f'{symbol_name}_1_1',
        raw,
    )

    return raw


def get_pin_names(lib_id: str, sym_dir: Path | None = None) -> dict[str, str]:
    """Extract pin number → pin name mapping from a symbol.

    Args:
        lib_id: Library ID like "Device:R".

    Returns:
        Dict mapping pin numbers to pin names (e.g. {"1": "~", "2": "~"}).
    """
    try:
        raw = resolve_lib_symbol(lib_id, sym_dir)
    except ValueError:
        return {}

    pins: dict[str, str] = {}
    # KiCad 10 pin format (multiline):
    # (pin passive line
    #   (at 0 3.81 270)
    #   (length 1.27)
    #   (name "" (effects ...))
    #   (number "1" (effects ...))
    # )
    # Extract name and number separately — they may span lines.
    # Find each (pin ... block and extract name+number from it.
    pin_block_re = re.compile(r'\(pin\s+\w+', re.DOTALL)
    for pin_match in pin_block_re.finditer(raw):
        # Extract the balanced block for this pin.
        start = pin_match.start()
        block = _extract_balanced_block(raw, start)

        name_match = re.search(r'\(name\s+"([^"]*)"', block)
        number_match = re.search(r'\(number\s+"([^"]*)"', block)

        if number_match:
            num = number_match.group(1)
            name = name_match.group(1) if name_match else num
            pins[num] = name if name else num

    return pins


@lru_cache(maxsize=32)
def _load_lib(lib_file: Path) -> str:
    """Load and cache a .kicad_sym library file."""
    return lib_file.read_text(encoding="utf-8")


def _get_raw_symbol(content: str, symbol_name: str) -> str | None:
    """Extract a raw symbol block from library content.

    Matches (symbol "NAME" at the start of a line (not sub-symbols like
    R_0_1 or R_1_1 which are indented).
    """
    # Find (symbol "NAME" — must be a top-level symbol definition.
    pattern = rf'\n\s*(\(symbol\s+"{re.escape(symbol_name)}")'
    match = re.search(pattern, content)
    if not match:
        return None

    start = match.start(1)
    return _extract_balanced_block(content, start)


def _extract_balanced_block(content: str, start: int) -> str:
    """Extract a balanced-paren block starting at 'start'."""
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
    return content[start:]


def _resolve_extends(
    child_block: str,
    child_name: str,
    parent_name: str,
    parent_block: str,
) -> str:
    """Resolve a child symbol that extends a parent.

    The child inherits all pins/units from the parent but may override
    properties. Returns the fully-resolved symbol block.
    """
    # Start from the parent block.
    resolved = parent_block

    # Rename parent references to child.
    resolved = resolved.replace(
        f'(symbol "{parent_name}"',
        f'(symbol "{child_name}"',
    )
    # Rename sub-symbols (parent_0_0, parent_1_1, etc.)
    resolved = re.sub(
        rf'{re.escape(parent_name)}_(\d+)_(\d+)',
        rf'{child_name}_\1_\2',
        resolved,
    )

    # Remove the (extends ...) from the child — the resolved block doesn't need it.
    # The parent block already has all the pins.

    return resolved
