"""Suggest canonical net names based on labels, component refs, and power conventions.

Algorithm:
  1. Call extract_nets to get net topology (pins per net)
  2. Parse SchematicGraph to get labels and ref_to_libid mapping
  3. Build label lookup by matching label names to net names from extract_nets
  4. For each net, apply priority-ordered name resolution:
     - Priority 1: Global label (confidence 1.0)
     - Priority 2: Hierarchical label (confidence 0.9)
     - Priority 3: Power convention (confidence 0.85)
     - Priority 4: Component ref + pin name (confidence 0.7)
     - Priority 5: Fallback ref + pin number (confidence 0.5)
  5. Return suggestions list and stats

Usage:
    from volta.schematic_routing.net_namer import suggest_net_names

    result = suggest_net_names(sch_path="board.kicad_sch")
    # result = {"suggestions": [...], "stats": {...}}
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from volta.schematic_routing.net_extractor import extract_nets
from volta.schematic_routing.schematic_graph import SchematicGraph


# ---------------------------------------------------------------------------
# Power pattern recognition
# ---------------------------------------------------------------------------

# Exact power pin names (case-insensitive match)
_POWER_PATTERNS: frozenset[str] = frozenset({
    "VCC", "VDD", "VEE", "VSS",
    "GND", "AGND", "DGND", "GND_ANALOG",
    "VIN", "VOUT",
})

# Regex for voltage patterns like +3V3, +5V, -12V, +3.3V, +1V8, +2V5
# Matches: [+-]DIGITS[Vv]DIGITS or [+-]DIGITS.DIGITS[Vv]
_VOLTAGE_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?[Vv]\d*$|^[+-]?\d+\.?\d*[Vv]$")


def _is_power_pin(pin_name: str) -> bool:
    """Check if a pin name matches a power convention pattern."""
    upper = pin_name.upper()
    if upper in _POWER_PATTERNS:
        return True
    if _VOLTAGE_PATTERN.match(pin_name):
        return True
    return False


def _get_power_name(pin_name: str) -> str:
    """Return the canonical power name for a pin.

    For known patterns like GND, VCC etc., returns uppercase.
    For voltage patterns like +3V3, returns with uppercase V suffix.
    """
    upper = pin_name.upper()
    if upper in _POWER_PATTERNS:
        return upper
    if _VOLTAGE_PATTERN.match(pin_name):
        # Normalize: keep sign/digits, uppercase the V
        return pin_name[:-1] + pin_name[-1].upper() if pin_name[-1].lower() == "v" else pin_name
    return pin_name.upper()


# ---------------------------------------------------------------------------
# Passive component detection
# ---------------------------------------------------------------------------

_PASSIVE_PREFIXES: frozenset[str] = frozenset({
    "Device:R", "Device:C", "Device:L",
})


def _is_passive(lib_id: str) -> bool:
    """Check if a component is a passive (R, C, L) based on lib_id."""
    for prefix in _PASSIVE_PREFIXES:
        if prefix in lib_id:
            return True
    return False


def _is_numeric_pin_name(pin_name: str) -> bool:
    """Check if a pin name is just a number (e.g., "1", "2")."""
    try:
        int(pin_name)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Core naming logic
# ---------------------------------------------------------------------------


def suggest_net_names(
    sch_path: Path | str,
    netlist_path: Optional[str] = None,
    naming_convention: str = "ref_pin",
) -> dict[str, Any]:
    """Suggest canonical net names based on labels and topology.

    Args:
        sch_path: Path to the .kicad_sch file.
        netlist_path: Optional path to .net file for net name resolution.
        naming_convention: "ref_pin" for "U1_SDA" or "ref_pin_number" for "U1_Pin5".

    Returns:
        Dict with "suggestions" list and "stats" dict.
    """
    # Step 1: Extract net topology
    net_data = extract_nets(
        sch_path=sch_path,
        include_positions=True,
        netlist_path=netlist_path,
    )
    nets = net_data["nets"]

    # Step 2: Parse labels and ref_to_libid from SchematicGraph
    graph = SchematicGraph.from_file(sch_path)

    # Step 3: Build label lookups
    global_labels: dict[str, Any] = {}  # net_name -> Label
    hierarchical_labels: dict[str, Any] = {}  # net_name -> Label
    for label in graph.labels:
        if label.label_type == "global":
            global_labels[label.name] = label
        elif label.label_type == "hierarchical":
            hierarchical_labels[label.name] = label

    # Step 4: Process each net
    suggestions: list[dict[str, Any]] = []
    named_nets = 0

    for net_name, pins in nets.items():
        # Strip position data for pin entries in suggestion
        pin_entries = [
            {"ref": p["ref"], "pin_number": p["pin_number"], "pin_name": p["pin_name"]}
            for p in pins
        ]

        # Check if this is a named net (not auto-generated)
        is_auto_named = net_name.startswith("Net_") and net_name[4:].isdigit()

        # --- Priority 1: Global label (confidence 1.0) ---
        if net_name in global_labels:
            named_nets += 1
            suggestions.append({
                "current_name": net_name,
                "suggested_name": net_name,
                "confidence": 1.0,
                "basis": "global_label",
                "pins": pin_entries,
            })
            continue

        # --- Priority 2: Hierarchical label (confidence 0.9) ---
        if net_name in hierarchical_labels:
            named_nets += 1
            suggestions.append({
                "current_name": net_name,
                "suggested_name": net_name,
                "confidence": 0.9,
                "basis": "hierarchical_label",
                "pins": pin_entries,
            })
            continue

        # For remaining priorities, we look at pin properties
        # Sort pins: prefer non-passive IC pins, then by ref number

        # --- Priority 3: Power convention (confidence 0.85) ---
        power_name = _find_power_pin(pins, graph.ref_to_libid)
        if power_name is not None:
            suggestions.append({
                "current_name": net_name,
                "suggested_name": power_name,
                "confidence": 0.85,
                "basis": "power_convention",
                "pins": pin_entries,
            })
            if not is_auto_named:
                named_nets += 1
            continue

        # --- Priority 4: Component pin name (confidence 0.7) ---
        ic_pin = _find_best_ic_pin(pins, graph.ref_to_libid)
        if ic_pin is not None:
            ref = ic_pin["ref"]
            pin_name = ic_pin["pin_name"]
            if naming_convention == "ref_pin":
                suggested = f"{ref}_{pin_name}"
            else:
                suggested = f"{ref}_Pin{ic_pin['pin_number']}"
            suggestions.append({
                "current_name": net_name,
                "suggested_name": suggested,
                "confidence": 0.7,
                "basis": "component_ref",
                "pins": pin_entries,
            })
            if not is_auto_named:
                named_nets += 1
            continue

        # --- Priority 5: Fallback (confidence 0.5) ---
        fallback = _make_fallback_name(pins, graph.ref_to_libid, naming_convention)
        suggestions.append({
            "current_name": net_name,
            "suggested_name": fallback,
            "confidence": 0.5,
            "basis": "fallback",
            "pins": pin_entries,
        })
        if not is_auto_named:
            named_nets += 1

    return {
        "suggestions": suggestions,
        "stats": {
            "total_nets": len(nets),
            "named_nets": named_nets,
            "suggested_nets": len(suggestions),
        },
    }


def _find_power_pin(
    pins: list[dict[str, Any]],
    ref_to_libid: dict[str, str],
) -> Optional[str]:
    """Find a power pin among the net's pins. Returns the power name or None."""
    for pin in pins:
        pin_name = pin["pin_name"]
        if _is_power_pin(pin_name):
            return _get_power_name(pin_name)
    return None


def _find_best_ic_pin(
    pins: list[dict[str, Any]],
    ref_to_libid: dict[str, str],
) -> Optional[dict[str, Any]]:
    """Find the best IC pin for naming (non-passive, meaningful pin name).

    Prefers the pin from the first non-passive component with the longest
    non-numeric pin name.
    """
    candidates: list[tuple[int, dict[str, Any]]] = []

    for pin in pins:
        ref = pin["ref"]
        lib_id = ref_to_libid.get(ref, "")

        # Skip passive components
        if _is_passive(lib_id):
            continue

        pin_name = pin["pin_name"]

        # Skip purely numeric pin names (not meaningful for naming)
        if _is_numeric_pin_name(pin_name):
            # Still consider ICs with numeric pins at lower priority
            candidates.append((100 + _extract_ref_number(ref), pin))
            continue

        # Prefer pins with longer, more descriptive names
        candidates.append((_extract_ref_number(ref), pin))

    if not candidates:
        return None

    # Sort by ref number (lower first), then by pin name length (longer first)
    candidates.sort(key=lambda x: (x[0], -len(x[1]["pin_name"])))
    return candidates[0][1]


def _make_fallback_name(
    pins: list[dict[str, Any]],
    ref_to_libid: dict[str, str],
    naming_convention: str,
) -> str:
    """Generate a fallback name from the first available pin's ref and pin number/name."""
    if not pins:
        return "Net_Unknown"

    # Use the first pin (sorted by ref number)
    sorted_pins = sorted(pins, key=lambda p: (_extract_ref_number(p["ref"]), p["pin_number"]))
    pin = sorted_pins[0]
    ref = pin["ref"]

    if naming_convention == "ref_pin_number":
        return f"{ref}_Pin{pin['pin_number']}"
    else:
        return f"{ref}_{pin['pin_number']}"


def _extract_ref_number(ref: str) -> int:
    """Extract the numeric part from a reference designator (e.g., 'U1' -> 1)."""
    import re as _re
    match = _re.search(r"(\d+)$", ref)
    if match:
        return int(match.group(1))
    return 0
