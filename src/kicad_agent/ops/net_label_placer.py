"""Pin-to-net mapping operation for automated net label placement.

Issue #8: Places net labels on IC pins based on a known pin-to-net mapping.
Critical safety: labels are ONLY placed at positions that already have wire
endpoints, preventing label_dangling violations.

Built-in mapping profiles provide common pin assignments for popular ICs:
- Power pins (VDD/VCC → power nets)
- Bus pins (I2C, SPI, TDM → bus nets)
- Signal pins (context-dependent, mapped to None → no_connect)

Usage:
    from kicad_agent.ops.net_label_placer import place_net_labels

    result = place_net_labels(ir, file_path, pin_map="backplane")
    print(f"Placed {result['labels_placed']} labels, {result['no_connects_placed']} NCs")
"""

import json
import logging
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.schematic_routing.net_extractor import NetPositionIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in pin mapping profiles
# ---------------------------------------------------------------------------

_BUILTIN_PROFILES: dict[str, dict[str, dict[str, str | None]]] = {
    "backplane": {
        # AK4619VN audio codec (32 pins)
        "AK4619VN": {
            "TVDD": "VCC_3V3", "AVDD": "VCC_3V3", "AVDRV": "VCC_12V",
            "DVDD": "VCC_3V3", "DVDDH": "VCC_3V3",
            "VSS1": "GND", "VSS2": "GND", "VSS3": "GND", "VSS4": "GND",
            "SCL": "I2C1_SCL",
            "SDA": "I2C1_SDA",
            "MCLK": "MCLK", "SCLK": "TDM_BCLK", "BCLK": "TDM_BCLK", "LRCK": "TDM_LRCK",
            "SDTO1": None, "SDTO2": None, "SDTI1": None, "SDTI2": None,
            "AIN1": None, "AIN2": None, "AIN3": None, "AIN4": None,
            "AOUT1": None, "AOUT2": None, "AOUT3": None, "AOUT4": None,
        },
        # MT8816 crosspoint switch (40 pins)
        "MT8816": {
            "VDD": "VCC_5V", "VSS": "GND", "VEE": "VCC_-12V",
        },
        # W5500 Ethernet (16 pins)
        "W5500": {
            "VDD": "VCC_3V3", "GND": "GND",
        },
        # MCP4728 quad DAC (10 pins)
        "MCP4728": {
            "VDD": "VCC_3V3", "VSS": "GND",
            "SCL": "I2C1_SCL", "SDA": "I2C1_SDA",
        },
        # P82B96DP I2C buffer (8 pins)
        "P82B96DP": {
            "VCC": "VCC_3V3", "GND": "GND",
        },
    },
}


def _load_pin_map(pin_map: str, file_path: Path) -> dict[str, dict[str, str | None]]:
    """Load a pin mapping from a built-in profile or JSON file.

    Args:
        pin_map: Built-in profile name (e.g. "backplane") or path to JSON file.
        file_path: Base file path for resolving relative JSON paths.

    Returns:
        Dict mapping component entry_name -> {pin_name -> net_name_or_None}.
    """
    if pin_map in _BUILTIN_PROFILES:
        return _BUILTIN_PROFILES[pin_map]

    # Try as JSON file path
    json_path = Path(pin_map)
    if not json_path.is_absolute():
        json_path = file_path.parent / pin_map

    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)

    # Try "auto" mode — use all built-in profiles
    if pin_map == "auto":
        merged: dict[str, dict[str, str | None]] = {}
        for profile in _BUILTIN_PROFILES.values():
            merged.update(profile)
        return merged

    raise ValueError(
        f"Unknown pin_map profile '{pin_map}' and no JSON file found at '{json_path}'"
    )


def place_net_labels(
    ir: SchematicIR,
    file_path: Path,
    pin_map: str = "auto",
    references: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Place net labels on IC pins based on a pin-to-net mapping.

    Issue #8: Labels are ONLY placed at positions that already have wire
    endpoints. Pins mapped to None receive no_connect flags (only if no
    wire exists at that position).

    Safety gates:
    1. Wire connectivity check: only place labels where wires exist
    2. Existing label check: don't place duplicate labels
    3. Dry-run mode: preview changes before applying
    4. ERC verification suggestion: run ERC after to compare

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the schematic file.
        pin_map: Built-in profile name or path to JSON mapping file.
        references: Specific component references to process. None = all.
        dry_run: If True, report without modifying.

    Returns:
        Dict with labels_placed, no_connects_placed, skipped counts, and details.
    """
    mapping = _load_pin_map(pin_map, file_path)
    if not mapping:
        return {
            "labels_placed": 0, "no_connects_placed": 0,
            "skipped_no_wire": 0, "skipped_existing_label": 0,
            "skipped_no_mapping": 0, "details": [],
        }

    # Build connectivity sets
    pin_positions = ir.get_pin_positions()
    wire_endpoints = ir.get_wire_endpoints()
    label_positions_list = ir.get_label_positions()
    sch = ir.schematic

    # Set of positions that have wire endpoints (rounded to 0.01mm)
    wire_positions: set[tuple[float, float]] = set()
    for we in wire_endpoints:
        wire_positions.add((round(we["start_x"], 2), round(we["start_y"], 2)))
        wire_positions.add((round(we["end_x"], 2), round(we["end_y"], 2)))

    # Set of positions that already have labels
    existing_label_positions: set[tuple[float, float]] = set()
    for lp in label_positions_list:
        existing_label_positions.add((round(lp["x"], 2), round(lp["y"], 2)))

    # Existing no_connect positions
    existing_nc: set[tuple[float, float]] = set()
    for nc in sch.noConnects:
        existing_nc.add((round(nc.position.X, 2), round(nc.position.Y, 2)))

    # Build reference → component info lookup
    ref_filter = set(references) if references else None
    pin_by_ref: dict[str, list[dict[str, Any]]] = {}
    for p in pin_positions:
        ref = p["reference"]
        if ref_filter and ref not in ref_filter:
            continue
        pin_by_ref.setdefault(ref, []).append(p)

    # Also build reference → lib_id lookup
    ref_to_libid: dict[str, str] = {}
    for sym in sch.schematicSymbols:
        ref_prop = None
        for prop in sym.properties:
            if prop.key == "Reference":
                ref_prop = prop.value
                break
        if ref_prop:
            ref_to_libid[ref_prop] = sym.libId

    labels_placed = 0
    nc_placed = 0
    skipped_no_wire = 0
    skipped_existing_label = 0
    skipped_no_mapping = 0
    details: list[dict[str, Any]] = []

    for ref, pins in pin_by_ref.items():
        lib_id = ref_to_libid.get(ref, "")
        # Extract entry name from lib_id (e.g. "Audio_Codec:AK4619VN" -> "AK4619VN")
        entry_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id

        component_mapping = mapping.get(entry_name)
        if not component_mapping:
            skipped_no_mapping += len(pins)
            continue

        for pin in pins:
            pin_name = pin["pin_name"]
            net_name = component_mapping.get(pin_name)
            if net_name is None and pin_name not in component_mapping:
                continue  # Pin not in mapping — skip entirely

            pos_key = (round(pin["x"], 2), round(pin["y"], 2))

            if net_name is None:
                # Pin mapped to None → place no_connect (only if no wire)
                if pos_key in existing_nc:
                    continue
                if pos_key in wire_positions:
                    continue  # Has wire, don't place NC
                if dry_run:
                    details.append({
                        "reference": ref, "pin_name": pin_name,
                        "action": "would_place_no_connect", "position": [pin["x"], pin["y"]],
                    })
                else:
                    ir.add_no_connect(x=pin["x"], y=pin["y"])
                    existing_nc.add(pos_key)
                    nc_placed += 1
                    details.append({
                        "reference": ref, "pin_name": pin_name,
                        "action": "placed_no_connect", "position": [pin["x"], pin["y"]],
                    })
                continue

            # Pin mapped to a net name → place label (only if wire exists)
            if pos_key in existing_label_positions:
                skipped_existing_label += 1
                continue

            if pos_key not in wire_positions:
                # Safety: don't place labels at bare pin positions
                skipped_no_wire += 1
                logger.debug(
                    "Skipping label '%s' at %s pin %s: no wire at (%.2f, %.2f)",
                    net_name, ref, pin_name, pin["x"], pin["y"],
                )
                continue

            if dry_run:
                details.append({
                    "reference": ref, "pin_name": pin_name,
                    "action": "would_place_label", "net_name": net_name,
                    "position": [pin["x"], pin["y"]],
                })
            else:
                ir.add_label(name=net_name, x=pin["x"], y=pin["y"], label_type="label")
                existing_label_positions.add(pos_key)
                labels_placed += 1
                details.append({
                    "reference": ref, "pin_name": pin_name,
                    "action": "placed_label", "net_name": net_name,
                    "position": [pin["x"], pin["y"]],
                })

    return {
        "labels_placed": labels_placed,
        "no_connects_placed": nc_placed,
        "skipped_no_wire": skipped_no_wire,
        "skipped_existing_label": skipped_existing_label,
        "skipped_no_mapping": skipped_no_mapping,
        "details": details,
    }
