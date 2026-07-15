"""Pin position resolver for schematic routing.

Resolves absolute pin coordinates for every component in a .kicad_sch file,
handling multi-unit ICs, named pins, and rotation transforms.

Reuses the pin geometry parsing logic from schematic_graph.py:
  - _parse_lib_pins: extracts pin offsets from lib_symbols section
  - _parse_symbol_pins: computes absolute positions via rotation transform

The PinResolver differs from SchematicGraph in its output format:
  - SchematicGraph.pins is a flat list of PinPosition dataclasses
  - PinResolver returns structured dicts keyed by ref, suitable for
    routing operations and the resolve_pin_positions executor handler.

Security (threat model):
  T-38-01-03: Rejects files >10MB and >10000 pins to prevent DoS
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

from volta.schematic_routing.schematic_graph import (
    _find_lib_symbols_range,
    _parse_lib_pins,
)

# DoS mitigation limits (T-38-01-03)
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_MAX_PIN_COUNT = 10000


class PinResolver:
    """Resolve absolute pin positions for schematic components.

    Parses a .kicad_sch file and computes absolute (x, y) coordinates for
    every pin of every component, including multi-unit ICs, named-pin ICs,
    and rotation transforms.

    Usage::

        from volta.schematic_routing.pin_resolver import PinResolver

        resolver = PinResolver("schematic.kicad_sch")
        all_pins = resolver.resolve_all()
        r55_pins = resolver.resolve("R55")
    """

    def __init__(self, filepath: str | Path) -> None:
        """Parse a .kicad_sch file and prepare pin resolution data.

        Args:
            filepath: Path to the .kicad_sch file.

        Raises:
            ValueError: If file exceeds 10MB (T-38-01-03 DoS mitigation).
            ValueError: If pin count exceeds 10000 (T-38-01-03).
            FileNotFoundError: If the file does not exist.
        """
        filepath = Path(filepath)

        # T-38-01-03: File size limit
        file_size = filepath.stat().st_size
        if file_size > _MAX_FILE_SIZE:
            raise ValueError(
                f"File too large: {file_size} bytes exceeds {_MAX_FILE_SIZE} byte limit"
            )

        content = filepath.read_text(encoding="utf-8")

        lib_start, lib_end = _find_lib_symbols_range(content)
        if lib_start == lib_end:
            self._components: dict[str, dict] = {}
            return

        lib_section = content[lib_start:lib_end]
        body = content[lib_end:]

        # Parse lib symbols for pin geometry
        lib_symbols = _parse_lib_pins(lib_section)

        # T-38-01-03: Pin count limit
        total_pins = sum(len(pins) for pins in lib_symbols.values())
        if total_pins > _MAX_PIN_COUNT:
            raise ValueError(
                f"Pin count {total_pins} exceeds {_MAX_PIN_COUNT} limit"
            )

        # Parse symbol instances and compute pin positions
        self._components = self._parse_components(body, lib_symbols)

    def resolve(self, ref: str) -> Optional[dict]:
        """Resolve pin positions for a single component reference.

        Args:
            ref: Component reference designator (e.g. ``"R55"``, ``"U21"``).

        Returns:
            Dict with keys: ref, lib_id, pins (dict keyed by pin number).
            Each pin entry has: position, body_position, pin_name.
            Returns None if the ref is not found.
        """
        return self._components.get(ref)

    def resolve_all(self) -> dict[str, dict]:
        """Resolve pin positions for all components.

        Returns:
            Dict keyed by component reference, each value containing
            ref, lib_id, and pins dict.
        """
        return dict(self._components)

    def _build_unit_index(
        self,
        lib_symbols: dict[str, list[tuple]],
    ) -> dict[tuple[str, int], list[tuple]]:
        """Build a (lib_id, unit) -> pins lookup from parsed lib_symbols.

        KiCad sub-symbols use naming convention: ``"SymbolName_U_B"``
        where U is the unit number and B is the body style (always 1 for
        standard symbols).  For single-unit symbols, the key may be the
        bare lib_id or ``"SymbolName_1_1"``.

        Returns:
            {(lib_id_or_short_name, unit_number): [pin_tuple, ...]}
        """
        index: dict[tuple[str, int], list[tuple]] = {}
        for sub_name, pins in lib_symbols.items():
            # Extract unit number from sub-symbol name like "CD4066BE_1_1"
            # or "R_1_1" or just "R" for single-unit symbols
            parts = sub_name.rsplit("_", 2)
            if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
                # Sub-symbol with unit info: "ParentName_Unit_BodyStyle"
                base = parts[0]
                unit = int(parts[-2])
            elif len(parts) == 2 and parts[-1].isdigit():
                # Two-part name like "R_1" -- ambiguous but treat as unit 1
                base = parts[0]
                unit = 1
            else:
                # No unit suffix -- single-unit symbol, map to unit 1
                base = sub_name
                unit = 1

            # Handle colon-qualified names: "Device:R_1_1" -> base "Device:R"
            # The parent lib_id may be "Device:R", sub_name may be "Device:R_1_1"
            # or just "R_1_1".  Store both the full base and the short base.
            if ":" in base:
                short_base = base.split(":")[-1]
            else:
                short_base = base

            index[(base, unit)] = pins
            if short_base != base:
                index[(short_base, unit)] = pins

            # Also store as unit 0 (all units) for single-unit symbols
            # so they match regardless of the unit number in the instance
            if unit == 1 and len(pins) <= 20:
                # Heuristic: if there's only one sub-symbol entry for this
                # base name, map it to all units as a fallback
                index.setdefault((base, 0), pins)
                if short_base != base:
                    index.setdefault((short_base, 0), pins)

        return index

    def _resolve_lib_pins(
        self,
        lib_id: str,
        unit: int,
        lib_symbols: dict[str, list[tuple]],
        unit_index: dict[tuple[str, int], list[tuple]],
    ) -> list[tuple] | None:
        """Resolve pins for a (lib_id, unit) combination.

        Tries multiple lookup strategies:
          1. Exact (lib_id, unit) match in unit_index
          2. Short-name (lib_id, unit) match in unit_index
          3. Fallback: (lib_id, 0) -> use unit-0 catch-all
          4. Legacy: iterate lib_symbols for matching sub-symbol names

        Returns:
            List of pin tuples, or None if not found.
        """
        # Strategy 1: Exact match with full lib_id
        key = (lib_id, unit)
        if key in unit_index:
            return unit_index[key]

        # Strategy 2: Short name match
        short_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        key = (short_name, unit)
        if key in unit_index:
            return unit_index[key]

        # Strategy 3: Unit-0 catch-all (single-unit symbols)
        key = (lib_id, 0)
        if key in unit_index:
            return unit_index[key]
        key = (short_name, 0)
        if key in unit_index:
            return unit_index[key]

        # Strategy 4: Legacy fallback -- match sub-symbol names directly
        # This handles cases where the sub-symbol name matches the lib_id
        lib_pins = lib_symbols.get(lib_id)
        if lib_pins:
            return lib_pins

        for k in lib_symbols:
            if k.split(":")[-1] == short_name or k == short_name:
                return lib_symbols[k]

        return None

    def _parse_components(
        self,
        body: str,
        lib_symbols: dict[str, list[tuple]],
    ) -> dict[str, dict]:
        """Parse placed symbol instances and compute absolute pin positions.

        Returns:
            {ref: {"ref": ref, "lib_id": str, "pins": {pin_number: {...}}}}
        """
        components: dict[str, dict] = {}
        unit_index = self._build_unit_index(lib_symbols)

        for sym_match in re.finditer(
            r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)',
            body,
        ):
            lib_id = sym_match.group(1)
            sx = float(sym_match.group(2))
            sy = float(sym_match.group(3))
            sa = float(sym_match.group(4))

            # Find end of this symbol instance block
            sym_start = sym_match.start()
            depth = 0
            sym_end = sym_start
            for i in range(sym_start, len(body)):
                if body[i] == "(":
                    depth += 1
                elif body[i] == ")":
                    depth -= 1
                    if depth == 0:
                        sym_end = i + 1
                        break

            sym_block = body[sym_start:sym_end]

            # Extract reference designator
            ref_match = re.search(
                r'\(property\s+"Reference"\s+"([^"]+)"', sym_block
            )
            if not ref_match:
                continue
            ref = ref_match.group(1)

            # Skip power symbols (#PWR, #FLG)
            if ref.startswith("#"):
                continue

            # Extract unit number for multi-unit components
            unit_match = re.search(r'\(unit\s+(\d+)\)', sym_block)
            unit = int(unit_match.group(1)) if unit_match else 1

            # Find matching lib symbol pins for this (lib_id, unit)
            lib_pins = self._resolve_lib_pins(
                lib_id, unit, lib_symbols, unit_index
            )
            if not lib_pins:
                continue

            # Calculate absolute pin positions
            rad = math.radians(sa)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)

            pin_data = {}
            for pin_type, px, py, pa, pl, pin_name, pin_number in lib_pins:
                # Rotate pin offset by symbol angle
                rot_px = px * cos_a - py * sin_a
                rot_py = px * sin_a + py * cos_a

                # Absolute body position
                body_x = round(sx + rot_px, 2)
                body_y = round(sy + rot_py, 2)

                # Wire connection point: extend from body by pin_length
                # in the combined pin direction + symbol rotation
                total_angle = pa + sa
                end_rad = math.radians(total_angle)
                wire_x = round(body_x + pl * math.cos(end_rad), 2)
                wire_y = round(body_y + pl * math.sin(end_rad), 2)

                pin_data[pin_number] = {
                    "position": (wire_x, wire_y),
                    "body_position": (body_x, body_y),
                    "pin_name": pin_name,
                    "unit": unit,
                }

            # Merge pins into component entry
            # (multi-unit components get pins merged from multiple instances)
            if ref in components:
                components[ref]["pins"].update(pin_data)
            else:
                components[ref] = {
                    "ref": ref,
                    "lib_id": lib_id,
                    "pins": pin_data,
                }

        return components
