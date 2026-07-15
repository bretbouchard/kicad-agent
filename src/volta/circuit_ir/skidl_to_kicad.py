"""Phase 156 Wave 6: SKIDL → KiCad schematic generation.

Generates a .kicad_sch from a skidl.Circuit. Uses raw S-expression emission
(pitfall #7 — NOT kiutils serialization which drops fields).

Pipeline:
  1. Run circuit.generate_netlist() to get the .net file.
  2. Parse the netlist for components + nets.
  3. Emit a minimal .kicad_sch with placed symbols (no wires by default).
  4. Embed resolved lib_symbols from the KiCad symbol library.

KiCad 10 schematic structure (verified against Arduino_Mega fixture):
  (kicad_sch ...
    (lib_symbols ...)           <- library definitions
    (wire ...)                  <- wires (top-level)
    (label ...)                 <- labels (top-level)
    (symbol (lib_id "...") ...) <- symbol instances (TOP-LEVEL, depth 1)
    (symbol_instances           <- per-sheet instance metadata
      (path "/" (page "1"))
    )
  )

CRITICAL: (symbol ...) blocks are TOP-LEVEL children of (kicad_sch),
NOT inside (symbol_instances). symbol_instances contains (path ...) entries.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from volta.circuit_ir.symbol_resolver import resolve_lib_symbol, get_pin_names

logger = logging.getLogger(__name__)

# KiCad grid constant (schematic coordinates are screen-style, Y down).
_KICAD_GRID_MM = 2.54

# Minimal KiCad schematic template.
# Note: NO (general (thickness ...)) — that's a PCB-only element.
# Note: NO (generator_version ...) — kicad-cli rejects unknown values.
_SCH_TEMPLATE = """(kicad_sch (version 20241129) (generator "kicad-agent")
  (paper "A4")
  (lib_symbols
{lib_symbols}
  )
{wires}
{labels}
{symbols}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def _detect_units(lib_id: str) -> dict[int, list[str]]:
    """Detect multi-unit structure from a symbol library definition.

    Returns:
        Dict mapping unit_number → list of pin numbers in that unit.
        For single-unit symbols, returns {1: [all_pins]}.
    """
    try:
        raw = resolve_lib_symbol(lib_id)
    except (ValueError, FileNotFoundError):
        return {}

    # Find sub-symbols like "NAME_1_1", "NAME_2_1", etc.
    # The pattern is <lib_basename>_<unit>_<convert>.
    base_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
    unit_pattern = re.compile(rf'\(symbol\s+"{re.escape(base_name)}_(\d+)_(\d+)"')
    matches = unit_pattern.findall(raw)
    if not matches:
        return {}

    units: dict[int, list[str]] = {}
    for unit_num_str, _convert in matches:
        unit_num = int(unit_num_str)
        # Extract the pins for this unit.
        unit_full = f"{base_name}_{unit_num_str}_{_convert}"
        m = re.search(rf'\(symbol\s+"{re.escape(unit_full)}"', raw)
        if m:
            start = m.start()
            depth = 0
            block = ""
            for i in range(start, len(raw)):
                if raw[i] == "(":
                    depth += 1
                elif raw[i] == ")":
                    depth -= 1
                    if depth == 0:
                        block = raw[start:i + 1]
                        break
            pin_nums = re.findall(r'\(number\s+"([^"]*)"', block)
            units[unit_num] = pin_nums

    return units


def _extract_pin_offsets_for_unit(lib_id: str, unit_num: int) -> dict[str, tuple[float, float]]:
    """Extract pin offsets for a specific unit of a multi-unit symbol.

    KiCad symbol libraries split graphical body and pins across sub-blocks:
      - ``(symbol "NE555P" ...)`` — top-level, may contain ALL pins
      - ``(symbol "NE555P_0_1" ...)`` — body graphics (unit 0 = all units)
      - ``(symbol "NE555P_1_1" ...)`` — unit 1 graphics + sometimes pins

    The original code only looked at ``_1_1``, which for symbols like NE555P
    contains only the 2 power pins (GND, VCC). The other 6 signal pins live
    in the TOP-LEVEL block. This produced wires that connected to only 2 of
    8 pins — the rest showed as ``pin_not_connected`` in ERC.

    Fix: ALWAYS extract from the top-level block (which has every pin),
    then filter by unit if the symbol is multi-unit. For single-unit
    symbols (most resistors, caps, ICs) the top-level has all pins.
    """
    try:
        raw = resolve_lib_symbol(lib_id)
    except (ValueError, FileNotFoundError):
        return {}

    base_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id

    # Always start from the top-level symbol block — it contains ALL pins.
    m = re.search(rf'\(symbol\s+"{re.escape(lib_id)}"', raw)
    if m:
        return _extract_pin_offsets_from_block(raw, m.start())

    # Fallback: try base name without library prefix.
    m = re.search(rf'\(symbol\s+"{re.escape(base_name)}"', raw)
    if m:
        return _extract_pin_offsets_from_block(raw, m.start())
    return {}


def _extract_pin_offsets_from_block(raw: str, start: int) -> dict[str, tuple[float, float]]:
    """Extract pin BODY-ANCHOR offsets from a lib symbol block.

    KiCad pins have two relevant points:
      - Body anchor: ``(at X Y angle)`` — where wires ELECTRICALLY connect
      - Graphical tip: body_anchor + length in the pin's direction

    ERC checks wire connectivity at the BODY ANCHOR, not the graphical tip.
    Wires in a working schematic terminate at the body anchor position
    (verified against the RaspberryPi-uHAT fixture: J1.7's wire connects at
    body (60.96, 66.04), NOT at the tip (64.77, 66.04)).

    Returns ``{pin_number: (body_anchor_x, body_anchor_y)}`` — these are
    relative to the symbol's origin. The caller adds the component's
    absolute position to get wire connection coordinates.
    """
    block = _extract_balanced_block(raw, start)
    offsets: dict[str, tuple[float, float]] = {}
    for pin_match in re.finditer(r'\(pin\s+\w+\s+\w+', block):
        pstart = pin_match.start()
        pblock = _extract_balanced_block(block, pstart)
        at_match = re.search(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)', pblock)
        num_match = re.search(r'\(number\s+"([^"]*)"', pblock)
        if at_match and num_match:
            offsets[num_match.group(1)] = (float(at_match.group(1)), float(at_match.group(2)))
    return offsets


def _extract_pin_offsets(lib_id: str) -> dict[str, tuple[float, float]]:
    """Extract pin offsets for unit 1 of a symbol (backward compat wrapper)."""
    return _extract_pin_offsets_for_unit(lib_id, 1)


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


def _snap_to_grid(value: float) -> float:
    """Snap a coordinate to the KiCad grid (2.54mm)."""
    return round(round(value / _KICAD_GRID_MM) * _KICAD_GRID_MM, 2)


def _part_lib_id(part: object) -> str:
    """Extract a KiCad lib_id ("Lib:Symbol") from a skidl Part.

    SKIDL 2.x pitfall: ``part.lib`` is a SchLib object whose string representation
    dumps the entire library contents — NOT the library name. The library name
    lives at ``part.lib.filename``. Combined with ``part.name`` (the symbol name),
    the lib_id is ``"{lib.filename}:{name}"``.
    """
    name = getattr(part, "name", "")
    lib = getattr(part, "lib", None)
    if lib is not None:
        # SKIDL SchLib: use .filename for the library name.
        lib_name = getattr(lib, "filename", None) or str(getattr(lib, "name", ""))
        if ":" in str(lib_name):
            # Some SKIDL versions return "Lib:Symbol" from filename.
            return str(lib_name)
        if lib_name and name:
            return f"{lib_name}:{name}"
    return name or ""


def circuit_to_kicad_sch(
    circuit: object,
    out_path: Path | str,
    *,
    place: bool = True,
    emit_wires: bool = True,
    use_sugiyama: bool = True,
) -> Path:
    """Generate a .kicad_sch from a skidl.Circuit.

    Args:
        circuit: A skidl.Circuit object.
        out_path: Output file path.
        place: If True, place components (default).
        emit_wires: If True, emit (wire ...) blocks from circuit.nets (default).
            This produces an electrically complete schematic that passes ERC.
        use_sugiyama: If True, use Sugiyama topology-aware layout instead of
            a dumb grid (default). Produces signal-flow-hierarchical placement.

    Returns:
        Path to the written file.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect unique lib_ids for the lib_symbols section.
    lib_ids: set[str] = set()
    for part in circuit.parts:
        lib_id = _part_lib_id(part)
        if lib_id and ":" in lib_id:
            lib_ids.add(lib_id)

    # Resolve and embed symbol definitions + cache pin offsets per lib_id.
    lib_symbol_blocks: list[str] = []
    pin_offsets_cache: dict[str, dict[str, tuple[float, float]]] = {}
    for lib_id in sorted(lib_ids):
        try:
            raw = resolve_lib_symbol(lib_id)
            lib_symbol_blocks.append(f"    {raw}")
            pin_offsets_cache[lib_id] = _extract_pin_offsets(lib_id)
        except (ValueError, FileNotFoundError) as e:
            logger.warning("Could not resolve %s: %s", lib_id, e)

    # Place components using Sugiyama topology-aware layout (or grid fallback).
    sch_uuid = _uuid_from_str("schematic_root")

    # Track placement positions and pin absolute positions for wire emission.
    part_positions: dict[str, tuple[float, float]] = {}
    # pin_abs[ref][pin_num] = (abs_x, abs_y)
    pin_abs: dict[str, dict[str, tuple[float, float]]] = {}

    if place and use_sugiyama:
        # Sugiyama topology-aware placement: components grouped by signal
        # flow into layers (sources at top, sinks at bottom).
        try:
            from volta.circuit_ir.topology_from_skidl import compute_sugiyama_positions
            sugiyama_positions = compute_sugiyama_positions(circuit)
        except Exception as e:
            logger.warning("Sugiyama layout failed (%s), falling back to grid", e)
            sugiyama_positions = {}
    else:
        sugiyama_positions = {}

    col, row = 0, 0
    col_spacing = 25.4  # 10 grid units
    row_spacing = 25.4
    max_cols = 6

    def _snap(value: float) -> float:
        """Snap to KiCad 2.54mm grid. Prevents endpoint_off_grid warnings."""
        return round(round(value / _KICAD_GRID_MM) * _KICAD_GRID_MM, 2)

    symbol_blocks: list[str] = []
    for i, part in enumerate(circuit.parts):
        ref = getattr(part, "ref", f"U{i}")
        if place:
            if ref in sugiyama_positions:
                x, y = sugiyama_positions[ref]
            else:
                # Grid fallback for parts not in the Sugiyama result.
                x = (col % max_cols) * col_spacing + 50
                y = (row * row_spacing) + 150  # Below Sugiyama layout
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
        else:
            x, y = 50.0 + i * col_spacing, 50.0

        # Grid-snap component positions so all derived pin positions land on-grid.
        x, y = _snap(x), _snap(y)

        value = getattr(part, "value", "") or ""
        value_safe = value.replace("\\", "\\\\").replace('"', '\\"')
        lib_id = _part_lib_id(part)
        sym_uuid = _uuid_from_ref(ref, i)

        part_positions[ref] = (x, y)

        # Compute absolute pin positions for this part.
        # CRITICAL: KiCad schematic Y is INVERTED (screen-style, Y-down).
        # The lib_symbol pin (at Y) has positive Y = UP on screen, but in
        # absolute schematic coordinates positive Y = DOWN. So pin absolute
        # Y = part_Y - pin_rel_Y (subtract, not add). X is unaffected.
        # See MEMORY.md: "abs_Y = comp_Y - pin_rel_Y"
        #
        # For multi-unit symbols (e.g. LM358 with units A/B/C), we emit a
        # single symbol block with unit=1 but include ALL pins from ALL units.
        # This avoids the "missing_power_pin" ERC error (unit C unplaced) while
        # keeping the pin_abs mapping consistent for wire emission.
        offsets = pin_offsets_cache.get(lib_id, {})
        pin_abs[ref] = {}
        for pin_num, (dx, dy) in offsets.items():
            # KiCad lib symbol pin offsets use Y-up convention (math):
            # pin 1 of a vertical resistor is at Y=+3.81 (above center).
            # Schematic coordinates are Y-down (screen). So SUBTRACT the lib Y
            # to get the screen Y. X is unaffected (same direction).
            #
            # DO NOT grid-snap pin positions — they must EXACTLY match the
            # lib symbol's pin anchor for ERC connectivity. Grid-snapping
            # 146.05 to 147.32 breaks the electrical connection.
            ax = x + dx
            ay = y - dy
            pin_abs[ref][pin_num] = (ax, ay)

        # Get pin list for this symbol (for pin UUIDs).
        pin_map = get_pin_names(lib_id) if ":" in lib_id else {}

        # Build pin UUID entries.
        pin_lines: list[str] = []
        for pin_num in pin_map:
            pin_uuid = _uuid_from_str(f"{ref}_pin_{pin_num}")
            pin_lines.append(f'      (pin "{pin_num}" (uuid {pin_uuid}))')

        # Build instances block (required by KiCad 10 for symbol placement).
        instances_block = (
            f"      (instances\n"
            f'        (project "skidl_generated"\n'
            f'          (path "/{sch_uuid}"\n'
            f'            (reference "{ref}") (unit 1)\n'
            f"          )\n"
            f"        )\n"
            f"      )"
        )

        block = f'''  (symbol (lib_id "{lib_id}") (at {x:.2f} {y:.2f} 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid {sym_uuid})
    (property "Reference" "{ref}" (at {x + 2:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27))))
    (property "Value" "{value_safe}" (at {x + 2:.2f} {y + 2:.2f} 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) hide))
{chr(10).join(pin_lines)}
{instances_block}
  )'''
        symbol_blocks.append(block)

    # Emit wires from circuit.nets (F1 fix).
    wire_blocks: list[str] = []
    label_blocks: list[str] = []
    if emit_wires:
        wire_blocks, label_blocks = _emit_nets(circuit, pin_abs)

    sch_content = _SCH_TEMPLATE.format(
        lib_symbols="\n".join(lib_symbol_blocks),
        wires="\n".join(wire_blocks),
        labels="\n".join(label_blocks),
        symbols="\n".join(symbol_blocks),
    )

    out_path.write_text(sch_content, encoding="utf-8")
    logger.info("Generated schematic: %s (%d parts, %d wires, %d labels)",
                out_path.name, len(circuit.parts), len(wire_blocks), len(label_blocks))
    return out_path


def _emit_nets(
    circuit: object,
    pin_abs: dict[str, dict[str, tuple[float, float]]],
) -> tuple[list[str], list[str]]:
    """Emit (wire ...) and (label ...) blocks from SKIDL circuit.nets.

    Phase 108 Task 2 strategy: emit a LABEL at every pin on every net, plus
    direct WIRES only between pins that are close together (≤25.4mm). This
    follows the Phase 38 finding that labels are the primary connection
    mechanism in KiCad 10 — labels at the same position create electrical
    connectivity without physical wires, eliminating the L-route crossing
    bugs that produced ``multiple_net_names`` ERC warnings.

    Returns (wire_blocks, label_blocks).
    """
    wire_blocks: list[str] = []
    label_blocks: list[str] = []
    WIRE_THRESHOLD_MM = 25.4  # only wire nearby pins

    for net in circuit.nets:
        net_name = getattr(net, "name", "") or ""
        # Skip stub/noconnect nets.
        if net_name in ("", "__NOCONNECT", "__NOCOLLIDE"):
            continue

        pins = list(net.pins)
        if not pins:
            continue

        # Collect positions for all pins on this net.
        positions: list[tuple[float, float]] = []
        for pin in pins:
            ref = pin.part.ref
            pin_num = str(pin.num)
            if ref in pin_abs and pin_num in pin_abs[ref]:
                positions.append(pin_abs[ref][pin_num])

        if not positions:
            continue

        # Emit a label at EVERY pin position. Labels with the same name at
        # different positions create electrical connectivity in KiCad —
        # this is the Phase 38 "labels are primary" pattern.
        for px, py in positions:
            label_blocks.append(
                f'  (label "{net_name}" (at {px:.2f} {py:.2f} 0))'
            )

        # Additionally, wire nearby pins (≤25.4mm apart) for visual clarity.
        # These wires reinforce the label connection but aren't required
        # for ERC connectivity.
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dx = positions[j][0] - positions[i][0]
                dy = positions[j][1] - positions[i][1]
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= WIRE_THRESHOLD_MM:
                    wire_blocks.append(_emit_wire(positions[i], positions[j]))

        # Emit a label at the first pin position for this net.
        if net_name and pins:
            first_pin = pins[0]
            ref = first_pin.part.ref
            pin_num = str(first_pin.num)
            if ref in pin_abs and pin_num in pin_abs[ref]:
                px, py = pin_abs[ref][pin_num]
                label_blocks.append(
                    f'  (label "{net_name}" (at {px:.2f} {py:.2f} 0))'
                )

    return wire_blocks, label_blocks


def _emit_wire(p1: tuple[float, float], p2: tuple[float, float]) -> str:
    """Emit a KiCad wire block between two pin positions.

    Uses L-shaped routing (horizontal then vertical). Pin endpoints are used
    at their EXACT positions (NOT grid-snapped) so wires connect to pins.
    Only intermediate routing corners could be snapped, but in practice the
    pin positions are what matter for ERC connectivity.

    KiCad wire format: (wire (pts (xy x1 y1) (xy x2 y2)))
    """
    x1, y1 = round(p1[0], 2), round(p1[1], 2)
    x2, y2 = round(p2[0], 2), round(p2[1], 2)

    if x1 == x2 or y1 == y2:
        # Straight line — single wire segment.
        return f'  (wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}))\n  )'
    else:
        # L-shaped route: horizontal to (x2, y1), then vertical to (x2, y2).
        return (
            f'  (wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y1:.2f}))\n  )\n'
            f'  (wire (pts (xy {x2:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}))\n  )'
        )


def _uuid_from_ref(ref: str, index: int) -> str:
    """Generate a deterministic UUID from a reference designator."""
    return _uuid_from_str(f"{ref}_{index}")


def _uuid_from_str(s: str) -> str:
    """Generate a deterministic UUID from a string."""
    import hashlib
    h = hashlib.md5(s.encode()).hexdigest()
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
