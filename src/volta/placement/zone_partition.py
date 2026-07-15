"""Functional zone partitioning for zone-aware PCB placement.

Assigns component references to named functional zones based on priority refs,
prefix-based heuristics, and round-robin distribution. Also converts zone
assignments into keepout rectangles for the existing placement engine.
"""

import re


def assign_to_zone(
    ref: str,
    value: str,
    zones: list,
) -> str:
    """Assign a component reference to a functional zone.

    Priority order:
    1. Direct match in any zone's priority_refs list
    2. Value-based heuristic for ICs (power, digital, audio patterns)
    3. Prefix-based round-robin for passives

    Args:
        ref: Component reference (e.g., "R1", "U5", "J2").
        value: Component value string (e.g., "NE5532", "10k").
        zones: List of ZoneDefinition objects (from _schema_placement).

    Returns:
        Zone name string.
    """
    # 1. Priority refs -- direct match
    for zone in zones:
        if ref in zone.priority_refs:
            return zone.name

    # Extract ref prefix
    prefix_m = re.match(r'^([A-Za-z]+)', ref)
    prefix = prefix_m.group(1).upper() if prefix_m else ""

    # 2. IC (U-prefix) with value-based heuristics
    if prefix == "U":
        upper_val = value.upper()

        # Power IC patterns -> first zone with "power" in name
        _power_patterns = ["TPS63700", "TPS63020", "TPS736", "AMS1117", "TL431", "MC34063", "TC1044"]
        for pat in _power_patterns:
            if pat in upper_val:
                return _find_zone_by_name(zones, "power") or zones[0].name

        # Digital control patterns -> first zone with "input" in name
        _digital_patterns = ["CD4066", "MCP4131", "MCP4728", "PCA9534", "SN74HC595", "MCP23017"]
        for pat in _digital_patterns:
            if pat in upper_val:
                return _find_zone_by_name(zones, "input") or zones[0].name

        # Audio IC patterns -> alternate between eq/comp zones
        _audio_patterns = ["NE5532", "NE5534", "THAT4301", "THAT2180", "LM4562", "OPA2134", "TL072", "TL074"]
        for pat in _audio_patterns:
            if pat in upper_val:
                eq_zone = _find_zone_by_name(zones, "eq")
                comp_zone = _find_zone_by_name(zones, "comp")
                if eq_zone and comp_zone:
                    return [eq_zone, comp_zone][hash(ref) % 2]
                return eq_zone or comp_zone or zones[0].name

        # Generic U-prefix: round-robin across signal zones
        signal_zones = [z for z in zones if "power" not in z.name.lower()]
        if signal_zones:
            return signal_zones[hash(ref) % len(signal_zones)].name

    # 3. Test points -> power zone
    if prefix == "TP":
        return _find_zone_by_name(zones, "power") or zones[0].name

    # 4. Connectors -> connector zone
    if prefix == "J":
        return _find_zone_by_name(zones, "connector") or zones[0].name

    # 5. Standard passives: round-robin across non-power zones
    signal_zones = [z for z in zones if "power" not in z.name.lower()]
    if signal_zones:
        return signal_zones[hash(ref + value) % len(signal_zones)].name

    return zones[0].name


def build_keepouts_from_zone(
    target_zone_name: str,
    all_zones: list,
) -> list[tuple[float, float, float, float]]:
    """Convert a zone assignment into keepout rectangles for other zones.

    Returns a list of (x1, y1, x2, y2) tuples representing all OTHER
    zones as keepout regions. This bridges zone-aware placement with
    volta's keepout-based engine.

    Args:
        target_zone_name: The zone the component is assigned to.
        all_zones: All zone definitions.

    Returns:
        List of keepout rectangles.
    """
    keepouts = []
    for zone in all_zones:
        if zone.name != target_zone_name:
            x1, x2 = zone.x_range
            y1, y2 = zone.y_range
            keepouts.append((x1, y1, x2, y2))
    return keepouts


def _find_zone_by_name(zones: list, name_fragment: str):
    """Find a zone whose name contains the given fragment (case-insensitive)."""
    for zone in zones:
        if name_fragment.lower() in zone.name.lower():
            return zone.name
    return None
