"""Phase 156 Wave 6: SKIDL → KiCad schematic generation.

Generates a .kicad_sch from a skidl.Circuit. Uses raw S-expression emission
(pitfall #7 — NOT kiutils serialization which drops fields).

Pipeline:
  1. Run circuit.generate_netlist() to get the .net file.
  2. Parse the netlist for components + nets.
  3. Emit a minimal .kicad_sch with placed symbols (no wires by default).
  4. Embed resolved lib_symbols from the KiCad symbol library.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from kicad_agent.circuit_ir.symbol_resolver import resolve_lib_symbol

logger = logging.getLogger(__name__)

# Minimal KiCad schematic template.
_SCH_TEMPLATE = """(kicad_sch
  (version 20241129)
  (generator "kicad-agent")
  (generator_version "10.0")
  (general (thickness 1.6))
  (paper "A4")
  (lib_symbols
{lib_symbols}
  )
  (symbol_instances
{symbol_instances}
  )
{sheets}
{sheet_instances}
  (embedded_fonts no)
)
"""


def circuit_to_kicad_sch(
    circuit: object,
    out_path: Path | str,
    *,
    place: bool = True,
) -> Path:
    """Generate a .kicad_sch from a skidl.Circuit.

    Args:
        circuit: A skidl.Circuit object.
        out_path: Output file path.
        place: If True, place components on a grid (default).

    Returns:
        Path to the written file.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect unique lib_ids for the lib_symbols section.
    lib_ids: set[str] = set()
    for part in circuit.parts:
        if hasattr(part, "lib") and hasattr(part, "name"):
            lib_id = f"{part.lib}:{part.name}"
            lib_ids.add(lib_id)

    # Resolve and embed symbol definitions.
    lib_symbol_blocks: list[str] = []
    for lib_id in sorted(lib_ids):
        try:
            raw = resolve_lib_symbol(lib_id)
            lib_symbol_blocks.append(f"    {raw}")
        except (ValueError, FileNotFoundError) as e:
            logger.warning("Could not resolve %s: %s", lib_id, e)

    # Place components on a grid.
    col, row = 0, 0
    spacing = 20.0  # mm
    max_cols = 8

    symbol_instances: list[str] = []
    for i, part in enumerate(circuit.parts):
        if place:
            x = (col % max_cols) * spacing + 50
            y = (row * spacing) + 50
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        else:
            x, y = 50.0 + i * spacing, 50.0

        ref = getattr(part, "ref", f"U{i}")
        value = getattr(part, "value", "")
        lib_id = f"{part.lib}:{part.name}" if hasattr(part, "lib") else ""

        instance = f'''    (symbol
      (lib_id "{lib_id}")
      (at {x:.2f} {y:.2f} 0)
      (unit 1)
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (dnp no)
      (fields_autoplaced yes)
      (uuid "{_uuid_from_ref(ref, i)}")
      (property "Reference" "{ref}" (at {x + 2:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{value}" (at {x + 2:.2f} {y + 2:.2f} 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at {x:.2f} {y + 5:.2f} 0) (effects (font (size 1.27 1.27)) hide))
    )'''
        symbol_instances.append(instance)

    sch_content = _SCH_TEMPLATE.format(
        lib_symbols="\n".join(lib_symbol_blocks),
        symbol_instances="\n".join(symbol_instances),
        sheets="",
        sheet_instances='  (sheet_instances\n    (path "/" (page "1"))\n  )',
    )

    out_path.write_text(sch_content, encoding="utf-8")
    logger.info("Generated schematic: %s (%d parts)", out_path.name, len(circuit.parts))
    return out_path


def _uuid_from_ref(ref: str, index: int) -> str:
    """Generate a deterministic UUID from a reference designator."""
    import hashlib
    h = hashlib.md5(f"{ref}_{index}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def skidl_to_kicad_sch(
    skidl_script_path: Path | str,
    out_path: Path | str,
) -> Path:
    """Execute a SKIDL build_*.py script and generate a .kicad_sch.

    Args:
        skidl_script_path: Path to the build_*.py SKIDL script.
        out_path: Output .kicad_sch path.

    Returns:
        Path to the written schematic.
    """
    import subprocess
    import sys
    import tempfile

    skidl_script_path = Path(skidl_script_path)
    out_path = Path(out_path)

    # Execute the SKIDL script to build the circuit.
    # The script should define build_board() → Circuit.
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        # Write a wrapper that imports and calls build_board.
        f.write(f"""
import sys
sys.path.insert(0, "{skidl_script_path.parent}")
exec(open("{skidl_script_path}").read())
circuit = build_board()
import pickle
pickle.dump(circuit, open("{skidl_script_path}.pkl", "wb"))
""")
        wrapper_path = Path(f.name)

    try:
        result = subprocess.run(
            [sys.executable, str(wrapper_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SKIDL script execution failed: {result.stderr[:500]}"
            )

        import pickle
        circuit = pickle.load(open(f"{skidl_script_path}.pkl", "rb"))

        return circuit_to_kicad_sch(circuit, out_path)
    finally:
        wrapper_path.unlink(missing_ok=True)
        Path(f"{skidl_script_path}.pkl").unlink(missing_ok=True)
