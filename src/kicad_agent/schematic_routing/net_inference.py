"""Infer net connectivity from partial wiring with confidence scoring.

Issue #14: Wraps extract_nets() with confidence scoring and power pin
inference to feed the wire router on partially-wired schematics.

Confidence levels:
  - "high": net has an explicit label name (not auto-generated)
  - "medium": multi-pin net with wires but auto-named
  - "low": single pin, no wires, inferred from pin map

Usage:
    from kicad_agent.schematic_routing.net_inference import infer_nets

    result = infer_nets("board.kicad_sch", pin_map="backplane")
    # result["nets"][0] = {"name": "VCC_3V3", "confidence": "high", ...}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kicad_agent.ops.net_label_placer import _load_pin_map
from kicad_agent.schematic_routing.net_extractor import extract_nets

logger = logging.getLogger(__name__)

# Power pin names used across common IC profiles
_POWER_PIN_NAMES = frozenset({
    "VDD", "VCC", "VEE", "GND", "VSS", "AGND", "DGND",
    "TVDD", "AVDD", "DVDD", "DVDDH", "AVDRV",
})

# Auto-generated net name prefix from extract_nets
_AUTO_NET_PREFIX = "Net_"


def infer_nets(
    sch_path: Path | str,
    pin_map: str = "auto",
    confidence_threshold: str = "medium",
    ir: SchematicIR | None = None,
) -> dict[str, Any]:
    """Infer net connectivity from partial wiring.

    1. Run extract_nets() to get existing net topology
    2. Score each net by confidence level
    3. For unconnected power pins, check pin_map profiles for suggested net
    4. Return structured output compatible with batch_wiring

    Args:
        sch_path: Path to the .kicad_sch file.
        pin_map: Built-in profile name or path to JSON mapping file.
        confidence_threshold: Minimum confidence to include ("low", "medium", "high").
        ir: Optional pre-built SchematicIR to avoid re-parsing (Council CRITICAL #1).

    Returns:
        Dict with "nets", "unconnected_pins", and "stats" keys.
    """
    sch_path = Path(sch_path)

    # Step 1: Get existing connectivity
    extraction = extract_nets(sch_path, include_positions=True)
    raw_nets: dict[str, list[dict[str, Any]]] = extraction["nets"]

    # Step 2: Score each net
    threshold_order = {"low": 0, "medium": 1, "high": 2}
    min_threshold = threshold_order.get(confidence_threshold, 1)

    nets: list[dict[str, Any]] = []
    high_count = 0
    medium_count = 0
    low_count = 0

    for net_name, pins in raw_nets.items():
        confidence, source = _score_net(net_name, pins)
        conf_level = threshold_order.get(confidence, 0)

        if conf_level < min_threshold:
            continue

        if confidence == "high":
            high_count += 1
        elif confidence == "medium":
            medium_count += 1
        else:
            low_count += 1

        nets.append({
            "name": net_name,
            "pins": pins,
            "confidence": confidence,
            "source": source,
        })

    # Step 3: Identify unconnected pins and suggest nets from profiles
    mapping = _safe_load_pin_map(pin_map, sch_path)
    connected_refs = _build_connected_ref_set(raw_nets)
    unconnected = _find_unconnected_pins(sch_path, connected_refs, mapping, ir=ir)

    return {
        "nets": nets,
        "unconnected_pins": unconnected,
        "stats": {
            "total_nets": len(nets),
            "high_confidence": high_count,
            "medium_confidence": medium_count,
            "low_confidence": low_count,
            "unconnected_pins": len(unconnected),
        },
    }


def _score_net(
    net_name: str,
    pins: list[dict[str, Any]],
) -> tuple[str, str]:
    """Score a net's confidence level.

    Returns:
        (confidence, source) tuple.
        confidence: "high", "medium", or "low"
        source: "label", "wire_trace", or "single_pin"
    """
    is_auto_named = (
        net_name.startswith(_AUTO_NET_PREFIX)
        and net_name[4:].isdigit()
    )

    if not is_auto_named:
        return "high", "label"

    if len(pins) >= 2:
        return "medium", "wire_trace"

    return "low", "single_pin"


def _safe_load_pin_map(
    pin_map: str,
    sch_path: Path,
) -> dict[str, dict[str, str | None]]:
    """Load pin map, returning empty dict on failure."""
    try:
        return _load_pin_map(pin_map, sch_path)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        logger.debug("Could not load pin map '%s': %s", pin_map, exc)
        return {}


def _build_connected_ref_set(
    raw_nets: dict[str, list[dict[str, Any]]],
) -> set[tuple[str, str]]:
    """Build set of (ref, pin_number) tuples that are already connected."""
    connected: set[tuple[str, str]] = set()
    for pins in raw_nets.values():
        for pin in pins:
            connected.add((pin["ref"], pin["pin_number"]))
    return connected


def _find_unconnected_pins(
    sch_path: Path,
    connected: set[tuple[str, str]],
    mapping: dict[str, dict[str, str | None]],
    ir: SchematicIR | None = None,
) -> list[dict[str, Any]]:
    """Find pins not in any net and suggest net names from profiles."""
    from kicad_agent.ir.schematic_ir import SchematicIR

    if ir is None:
        from kicad_agent.parser import parse_schematic
        result = parse_schematic(sch_path)
        ir = SchematicIR(_parse_result=result)

    all_pins = ir.get_pin_positions()

    # Build ref -> lib_id lookup
    sch = ir.schematic
    ref_to_libid: dict[str, str] = {}
    for sym in sch.schematicSymbols:
        ref_prop = None
        for prop in sym.properties:
            if prop.key == "Reference":
                ref_prop = prop.value
                break
        if ref_prop:
            ref_to_libid[ref_prop] = sym.libId

    unconnected: list[dict[str, Any]] = []
    for pin in all_pins:
        ref = pin["reference"]
        pin_number = pin.get("pin_number", "")
        key = (ref, pin_number)

        if key in connected:
            continue

        # Look up suggested net from pin map
        suggested_net = _suggest_net(ref, pin, ref_to_libid, mapping)

        unconnected.append({
            "ref": ref,
            "pin": pin["pin_name"],
            "pin_number": pin_number,
            "electrical_type": pin.get("electrical_type", "passive"),
            "suggested_net": suggested_net,
            "position": [pin["x"], pin["y"]],
        })

    return unconnected


def _suggest_net(
    ref: str,
    pin: dict[str, Any],
    ref_to_libid: dict[str, str],
    mapping: dict[str, dict[str, str | None]],
) -> str | None:
    """Suggest a net name for an unconnected pin from the profile mapping."""
    lib_id = ref_to_libid.get(ref, "")
    entry_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id

    component_mapping = mapping.get(entry_name)
    if not component_mapping:
        return None

    pin_name = pin["pin_name"]
    net_name = component_mapping.get(pin_name)
    # Return the suggested net (None means no suggestion or explicitly no-connect)
    if net_name is None and pin_name not in component_mapping:
        return None
    return net_name
