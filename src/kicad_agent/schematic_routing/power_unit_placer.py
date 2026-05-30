"""Place missing power units for ICs and connect them to power symbols.

Fixes ERC 'missing_power_pin' errors by inserting the hidden power unit
(e.g. unit 5 for CD4066BE/4066, unit 3 for NE5532) with appropriate
power symbol connections (+9V/-9V for op-amps, +9V/GNDA for analog switches).
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ICInfo:
    """Info about an IC that needs a power unit placed."""
    ref: str
    lib_id: str
    value: str
    footprint: str
    signal_x: float
    signal_y: float
    signal_rot: float
    instance_path: str
    sheet: str
    power_unit: int  # 5 for CD4066BE/4066, 3 for NE5532


# IC-specific power configuration
# Pin geometry sourced from KiCad 10 symbol libraries.
# Library coords have Y-up; schematic has Y-down, so conn_offset_y = -library_y.
# conn_offset: (dx, dy) from unit origin to pin CONNECTION POINT in schematic coords
# wire_dir: signed distance from connection point to power symbol (away from unit center)
IC_POWER_CONFIG = {
    # Analog_Switch:CD4066BE — unit 5 has VDD (pin 14) and VSS (pin 7)
    # Library: VDD at (0, 7.62) angle 270° len 2.54, VSS at (0, -7.62) angle 90° len 2.54
    "CD4066BE": {
        "power_unit": 5,
        "pins": [
            {"name": "VDD", "pin_number": "14", "power_sym": "power:+9V",
             "conn_offset": (0, -7.62), "wire_dir": -2.54},
            {"name": "VSS", "pin_number": "7", "power_sym": "power:GNDA",
             "conn_offset": (0, 7.62), "wire_dir": 1.27},
        ],
        "all_pin_numbers": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"],
    },
    # 4xxx:4066 (extends 4016) — unit 5 has VDD (pin 14) and VSS (pin 7)
    # Library: VDD at (0, 12.7) angle 270° len 5.08, VSS at (0, -12.7) angle 90° len 5.08
    "4066": {
        "power_unit": 5,
        "pins": [
            {"name": "VDD", "pin_number": "14", "power_sym": "power:+9V",
             "conn_offset": (0, -12.7), "wire_dir": -2.54},
            {"name": "VSS", "pin_number": "7", "power_sym": "power:GNDA",
             "conn_offset": (0, 12.7), "wire_dir": 1.27},
        ],
        "all_pin_numbers": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"],
    },
    # Amplifier_Operational:NE5532 (extends LM2904) — unit 3 has V+ (pin 8) and V- (pin 4)
    # Library: V+ at (-2.54, 7.62) angle 270° len 3.81, V- at (-2.54, -7.62) angle 90° len 3.81
    "NE5532": {
        "power_unit": 3,
        "pins": [
            {"name": "V+", "pin_number": "8", "power_sym": "power:+9V",
             "conn_offset": (-2.54, -7.62), "wire_dir": -2.54},
            {"name": "V-", "pin_number": "4", "power_sym": "power:-9V",
             "conn_offset": (-2.54, 7.62), "wire_dir": 2.54},
        ],
        "all_pin_numbers": ["1", "2", "3", "4", "5", "6", "7", "8"],
    },
}

# How far to offset the power unit from the signal unit
POWER_UNIT_OFFSET_X = 15.24  # 0.6 inches


def _gen_uuid() -> str:
    return str(uuid.uuid4())


def _find_ic_signal_unit(content: str, ref: str) -> Optional[dict]:
    """Find the existing signal unit (unit 1 or 2) for a given reference."""
    for m in re.finditer(
        r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)\s+\(unit\s+(\d+)\)',
        content,
    ):
        lib_id = m.group(1)
        start = m.start()
        depth = 0
        end = start
        for i in range(start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = content[start:end]
        ref_m = re.search(r'\(property\s+"Reference"\s+"' + re.escape(ref) + r'"', block)
        if not ref_m:
            continue

        value_m = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
        fp_m = re.search(r'\(property\s+"Footprint"\s+"([^"]+)"', block)
        inst_m = re.search(r'\(path\s+"([^"]+)"\s*\n\s+\(reference\s+"[^"]+"\)\s*\n\s+\(unit\s+\d+\)', block)

        return {
            "lib_id": lib_id,
            "x": float(m.group(2)),
            "y": float(m.group(3)),
            "rot": float(m.group(4)),
            "unit": int(m.group(5)),
            "value": value_m.group(1) if value_m else "",
            "footprint": fp_m.group(1) if fp_m else "",
            "instance_path": inst_m.group(1) if inst_m else "",
            "block": block,
        }
    return None


def _check_power_unit_exists(content: str, ref: str, power_unit: int) -> bool:
    """Check if the power unit is already placed for this reference."""
    for m in re.finditer(
        r'\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+[\d.]+\s+[\d.]+\s+[\d.-]+\)\s+\(unit\s+' + str(power_unit) + r'\)',
        content,
    ):
        start = m.start()
        depth = 0
        end = start
        for i in range(start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = content[start:end]
        if re.search(r'\(property\s+"Reference"\s+"' + re.escape(ref) + r'"', block):
            return True
    return False


def _get_power_config(lib_id: str) -> Optional[dict]:
    """Get power configuration for a lib_id."""
    for key, config in IC_POWER_CONFIG.items():
        if key in lib_id:
            return config
    return None


def _extract_value_from_lib_id(lib_id: str) -> str:
    """Extract the power net name from a lib_id like 'power:+9V' → '+9V'."""
    if ":" in lib_id:
        return lib_id.split(":", 1)[1]
    return lib_id


def _generate_power_symbol_block(
    lib_id: str, ref: str, sym_x: float, sym_y: float,
    instance_path: str, project_name: str = "analog-board",
) -> str:
    """Generate a power symbol S-expression block matching KiCad's format."""
    pwr_uuid = _gen_uuid()
    value = _extract_value_from_lib_id(lib_id)
    return f'''\t(symbol
\t\t(lib_id "{lib_id}")
\t\t(at {sym_x:.2f} {sym_y:.2f} 0)
\t\t(unit 1)
\t\t(body_style 1)
\t\t(exclude_from_sim no)
\t\t(in_bom no)
\t\t(on_board no)
\t\t(in_pos_files yes)
\t\t(dnp no)
\t\t(uuid "{pwr_uuid}")
\t\t(property "Reference" "{ref}"
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "{value}"
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Footprint" ""
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Datasheet" ""
\t\t\t(at {sym_x:.2f} {sym_y:.2f} 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Description" ""
\t\t\t(at {sym_x:.2f} {sym_y:.2f} 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(pin "1"
\t\t\t(uuid "{_gen_uuid()}")
\t\t)
\t\t(instances
\t\t\t(project "{project_name}"
\t\t\t\t(path "{instance_path}"
\t\t\t\t\t(reference "{ref}")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
'''


def _generate_wire_block(x1: float, y1: float, x2: float, y2: float) -> str:
    """Generate a wire S-expression block."""
    return f'''\t(wire
\t\t(pts
\t\t\t(xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f})
\t\t)
\t\t(stroke
\t\t\t(width 0)
\t\t\t(type default)
\t\t)
\t\t(uuid "{_gen_uuid()}")
\t)
'''


def _generate_power_unit_block(ic: ICInfo, pu_x: float, pu_y: float, config: dict, project_name: str = "analog-board") -> str:
    """Generate the power unit symbol S-expression block."""
    pin_blocks = ""
    for pn in config["all_pin_numbers"]:
        pin_blocks += f'''\t\t(pin "{pn}"
\t\t\t(uuid "{_gen_uuid()}")
\t\t)
'''

    return f'''\t(symbol
\t\t(lib_id "{ic.lib_id}")
\t\t(at {pu_x:.2f} {pu_y:.2f} 0)
\t\t(unit {config["power_unit"]})
\t\t(body_style 1)
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(in_pos_files yes)
\t\t(dnp no)
\t\t(uuid "{_gen_uuid()}")
\t\t(property "Reference" "{ic.ref}"
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "{ic.value}"
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Footprint" "{ic.footprint}"
\t\t\t(at 0 0 0)
\t\t\t(hide yes)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Datasheet" ""
\t\t\t(at 0 0 0)
\t\t\t(hide yes)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Description" ""
\t\t\t(at {pu_x:.2f} {pu_y:.2f} 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
{pin_blocks}\t\t(instances
\t\t\t(project "{project_name}"
\t\t\t\t(path "{ic.instance_path}"
\t\t\t\t\t(reference "{ic.ref}")
\t\t\t\t\t(unit {config["power_unit"]})
\t\t\t\t)
\t\t\t)
\t\t)
\t)
'''


def _find_max_pwr_number(sch_path: Path) -> int:
    """Scan all schematic files for the highest #PWR number."""
    max_num = 0
    for sch_file in sch_path.glob("*.kicad_sch"):
        content = sch_file.read_text()
        for m in re.finditer(r'#PWR(\d+)', content):
            num = int(m.group(1))
            if num > max_num:
                max_num = num
    return max_num


def _find_project_name(sch_path: Path) -> str:
    """Extract project name from the root schematic or first sub-sheet."""
    for sch_file in sorted(sch_path.glob("*.kicad_sch")):
        content = sch_file.read_text()
        m = re.search(r'\(project\s+"([^"]+)"', content)
        if m:
            return m.group(1)
    return "analog-board"


def place_power_units(sch_dir: str, refs: Optional[list[str]] = None) -> dict:
    """Place missing power units for specified ICs (or all missing ones).

    Args:
        sch_dir: Path to the directory containing .kicad_sch sub-sheet files.
        refs: Optional list of specific references to fix. If None, fixes all.

    Returns:
        Dict with 'placed' count and 'skipped' list.
    """
    sch_path = Path(sch_dir)
    placed = 0
    skipped = []
    all_ic_info: dict[str, ICInfo] = {}
    project_name = _find_project_name(sch_path)
    pwr_counter = _find_max_pwr_number(sch_path) + 1

    # Phase 1: Find all ICs needing power units across all sub-sheets
    for sch_file in sorted(sch_path.glob("*.kicad_sch")):
        sheet = sch_file.stem
        content = sch_file.read_text()

        # Find all placed symbols
        for m in re.finditer(
            r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)\s+\(unit\s+(\d+)\)',
            content,
        ):
            lib_id = m.group(1)
            config = _get_power_config(lib_id)
            if not config:
                continue

            start = m.start()
            depth = 0
            end = start
            for i in range(start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            block = content[start:end]
            ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
            if not ref_m:
                continue
            ref = ref_m.group(1)
            if ref.startswith("#"):
                continue
            unit = int(m.group(5))

            # Only consider signal units (1-4)
            if unit > 4:
                continue

            # Filter by requested refs
            if refs and ref not in refs:
                continue

            # Check if power unit already exists
            if _check_power_unit_exists(content, ref, config["power_unit"]):
                skipped.append(f"{ref} (power unit already placed)")
                continue

            value_m = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
            fp_m = re.search(r'\(property\s+"Footprint"\s+"([^"]+)"', block)
            inst_m = re.search(
                r'\(path\s+"([^"]+)"\s*\n\s+\(reference\s+"[^"]+"\)\s*\n\s+\(unit\s+\d+\)',
                block,
            )

            all_ic_info[ref] = ICInfo(
                ref=ref,
                lib_id=lib_id,
                value=value_m.group(1) if value_m else "",
                footprint=fp_m.group(1) if fp_m else "",
                signal_x=float(m.group(2)),
                signal_y=float(m.group(3)),
                signal_rot=float(m.group(4)),
                instance_path=inst_m.group(1) if inst_m else "",
                sheet=sheet,
                power_unit=config["power_unit"],
            )

    # Phase 2: For each IC, insert power unit + power symbols + wires
    # Group by sheet to minimize file writes
    sheets_modified: dict[str, list[str]] = {}

    for ref, ic in sorted(all_ic_info.items()):
        config = _get_power_config(ic.lib_id)
        if not config:
            skipped.append(f"{ref} (no power config for {ic.lib_id})")
            continue

        pu_x = round(ic.signal_x + POWER_UNIT_OFFSET_X, 2)
        pu_y = ic.signal_y

        # Generate blocks
        additions = []
        additions.append(_generate_power_unit_block(ic, pu_x, pu_y, config, project_name))

        # For each power pin, add power symbol + wire
        for pin_cfg in config["pins"]:
            cx, cy = pin_cfg["conn_offset"]
            rad = math.radians(ic.signal_rot)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            # Pin connection point in schematic coords (conn_offset already Y-flipped)
            conn_x = round(pu_x + cx * cos_a - cy * sin_a, 2)
            conn_y = round(pu_y + cx * sin_a + cy * cos_a, 2)
            # Power symbol position: wire extends away from unit center
            sym_y = round(conn_y + pin_cfg["wire_dir"], 2)
            sym_x = conn_x

            # Wire from pin connection point to power symbol
            wire = _generate_wire_block(conn_x, conn_y, sym_x, sym_y)
            additions.append(wire)

            # Power symbol with correct instance path and project name
            pwr_ref = f"#PWR{pwr_counter:03d}"
            pwr_counter += 1
            additions.append(
                _generate_power_symbol_block(
                    pin_cfg["power_sym"], pwr_ref, sym_x, sym_y,
                    instance_path=ic.instance_path,
                    project_name=project_name,
                )
            )

        block_text = "\n".join(additions)
        sheets_modified.setdefault(ic.sheet, []).append(block_text)
        placed += 1

    # Phase 3: Write to files
    for sheet, blocks in sheets_modified.items():
        sch_file = sch_path / f"{sheet}.kicad_sch"
        content = sch_file.read_text()

        # Insert before the closing ')'
        insert_text = "\n".join(blocks)
        # Find the last closing paren (end of schematic)
        last_close = content.rfind(")")
        new_content = content[:last_close] + insert_text + "\n)"

        sch_file.write_text(new_content)
        print(f"  Modified {sheet}.kicad_sch: placed {len(blocks) // 3} power units")

    return {"placed": placed, "skipped": skipped}


if __name__ == "__main__":
    import sys

    sch_dir = sys.argv[1] if len(sys.argv) > 1 else (
        "/Users/bretbouchard/apps/analog-ecosystem/hardware/network-io/channel-strip"
    )

    result = place_power_units(sch_dir)
    print(f"\nPlaced {result['placed']} power units")
    if result["skipped"]:
        print(f"Skipped: {result['skipped']}")
