"""Phase 204 volta-4 fix: KiCad symbol + footprint writer from EasyEDA CAD data.

Closes the gap in the existing component-search MCP server. The server had
search_components + get_component_details but no symbol/footprint DOWNLOAD
into the project library. Users had to manually create symbols.

This module converts EasyEdaComponentData (pins + pads) into minimal but
functional KiCad .kicad_sym + .kicad_mod files. The output has correct
electrical structure (pins with proper names/types, pads with proper
numbers/positions) but no graphical decoration — users add graphics later
via KiCad GUI or other tools.

Output format:
- Symbol: KiCad 7+ .kicad_sym file with one symbol per LCSC part
- Footprint: KiCad .kicad_mod file with pads positioned per EasyEDA coords
"""
from __future__ import annotations

import logging
from pathlib import Path

from volta.crawler.easyeda_api import (
    EasyEdaComponentData,
    EasyEdaFootprintPad,
    EasyEdaPin,
)

logger = logging.getLogger(__name__)


def write_symbol_to_library(
    data: EasyEdaComponentData,
    library_path: Path,
    library_name: str = "volta_imports",
) -> Path:
    """Append a symbol (from EasyEDA pin data) to a KiCad .kicad_sym library.

    Creates the library file if it doesn't exist; appends the symbol if it does.
    Pins are placed in a vertical column for legibility.

    Args:
        data: EasyEdaComponentData with .pins populated.
        library_path: Directory where the .kicad_sym file lives.
        library_name: Library file basename (no extension).

    Returns:
        Absolute path to the written .kicad_sym file.
    """
    library_path.mkdir(parents=True, exist_ok=True)
    sym_file = library_path / f"{library_name}.kicad_sym"

    # Symbol name: use LCSC part number (unique) — falls back to a sanitized name.
    sym_name = data.lcsc or "unknown_part"

    # Generate pin lines. EasyEDA pins are typically numbered 1..N with names.
    pin_lines: list[str] = []
    pin_spacing_mm = 2.54
    start_y = (len(data.pins) - 1) * pin_spacing_mm / 2
    for i, pin in enumerate(data.pins):
        y = start_y - i * pin_spacing_mm
        # Pin (electrical) — placed at x=-5mm with stub extending to x=0
        # Format: (pin <type> line (at -5.08 Y 0) (length 5.08) (name <name>) (number <num>))
        pin_type = _map_pin_type(pin)
        pin_name = _escapeStringSafe(pin.pin_name or f"P{i+1}")
        pin_num = _escapeStringSafe(pin.pin_number or str(i + 1))
        pin_lines.append(
            f"        (pin {pin_type} line"
            f" (at -5.08 {y:.2f} 0)"
            f" (length 5.08)"
            f" (name {pin_name})"
            f" (number {pin_num}))"
        )

    symbol_block = f"""(symbol "{sym_name}"
      (pin_names (offset 1.016))
      (in_bom yes)
      (on_board yes)
      (property "Reference" "U" (at 0 1.27 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{sym_name}" (at 0 -1.27 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "{sym_name}_0_1"
        (rectangle (start -2.54 {start_y + 1.27:.2f}) (end 2.54 {-(start_y + 1.27):.2f}) (stroke (width 0.254)) (fill (type background)))
{chr(10).join(pin_lines) if pin_lines else '        ; (no pins parsed from EasyEDA data)'}
      )
    )
"""

    if sym_file.exists():
        # Append before the closing paren.
        existing = sym_file.read_text()
        # KiCad .kicad_sym files end with a closing paren. Insert before it.
        if existing.rstrip().endswith(")"):
            new_content = existing.rstrip()[:-1] + symbol_block + ")\n"
        else:
            new_content = existing + symbol_block
    else:
        # New library — start with the standard header.
        header = f"""(kicad_symbol_lib
  (version 20231120)
  (generator "volta_mcp")
  (generator_version "0.1")
"""
        new_content = header + symbol_block + ")\n"

    sym_file.write_text(new_content)
    logger.info("Symbol %s written to %s", sym_name, sym_file)
    return sym_file


def write_footprint_to_library(
    data: EasyEdaComponentData,
    library_path: Path,
    library_name: str = "volta_imports",
) -> Path:
    """Write a KiCad .kicad_mod footprint from EasyEDA pad data.

    Args:
        data: EasyEdaComponentData with .pads populated.
        library_path: Directory where the footprint lives (.pretty dir).
        library_name: Footprint library subdirectory name.

    Returns:
        Absolute path to the written .kicad_mod file.
    """
    pretty_dir = library_path / f"{library_name}.pretty"
    pretty_dir.mkdir(parents=True, exist_ok=True)
    fp_name = data.lcsc or "unknown_part"
    fp_file = pretty_dir / f"{fp_name}.kicad_mod"

    # Generate pad lines. EasyEDA pads have (x, y, number) in mm.
    pad_lines: list[str] = []
    for i, pad in enumerate(data.pads):
        x, y = pad.pos_x, pad.pos_y
        pad_num = _escapeStringSafe(pad.pad_number or str(i + 1))
        # Standard SMD pad: 1.6 x 0.8mm at the EasyEDA coordinate.
        pad_lines.append(
            f"    (pad {pad_num} smd roundrect"
            f" (at {x:.3f} {y:.3f})"
            f" (size 1.6 0.8)"
            f" (layers \"F.Cu\" \"F.Paste\" \"F.Mask\")"
            f" (roundrect_rratio 0.25))"
        )

    footprint_block = f"""(footprint "{library_name}:{fp_name}"
    (layer "F.Cu")
    (attr smd)
    (property "Reference" "REF**" (at 0 -2.0 0) (effects (font (size 1.0 1.0))))
    (property "Value" "{fp_name}" (at 0 2.0 0) (effects (font (size 1.0 1.0))))
{chr(10).join(pad_lines) if pad_lines else '    ; (no pads parsed from EasyEDA data)'}
)
"""

    fp_file.write_text(footprint_block)
    logger.info("Footprint %s written to %s", fp_name, fp_file)
    return fp_file


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PIN_TYPE_MAP = {
    # EasyEDA pin_type integer (per EasyEdaPin docstring) → KiCad electrical type.
    # 0=unspecified, 1=input, 2=output, 3=bidirectional, 4=power.
    0: "unspecified",
    1: "input",
    2: "output",
    3: "bidirectional",
    4: "power_in",
}


def _map_pin_type(pin: EasyEdaPin) -> str:
    """Map EasyEDA pin_type int to KiCad electrical type. Defaults to 'passive'."""
    return _PIN_TYPE_MAP.get(pin.pin_type, "passive")


def _escapeStringSafe(s: str) -> str:
    """Escape a string for KiCad S-expression — wraps in quotes if needed."""
    if not s:
        return '""'
    # Quote if it contains spaces, special chars, or starts with a digit.
    if any(c in s for c in ' ()\t"\\') or s[0].isdigit():
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return s


def _escapeStringSafe_aliases(*args, **kwargs):  # pragma: no cover - kept for clarity
    """Legacy alias — use _escapeStringSafe."""
    return _escapeStringSafe(*args, **kwargs)


def _escape_string(s: str) -> str:
    """Escape for symbol name in property context."""
    return _escapeStringSafe(s)
