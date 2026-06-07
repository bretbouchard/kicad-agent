"""Ground topology analyzer -- analyze ground net separation in mixed-signal designs.

Analyzes ground nets in a schematic to determine if ground-to-ground shorts
are intentional (single ground plane) or design errors (separate grounds
shorted early). Classifies ground domains and recommends merge/split/star_point.

Usage:
    from kicad_agent.ops.ground_topology import analyze_ground_topology

    result = analyze_ground_topology(Path("mixed_signal.kicad_sch"))
    for conn in result["connections"]:
        print(f"{conn['net_a']} <-> {conn['net_b']}: {conn['recommendation']}")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain classification heuristics
# ---------------------------------------------------------------------------

# References matching these prefixes/patterns are considered digital ICs
_DIGITAL_REF_PATTERNS: list[re.Pattern] = [
    re.compile(r"^U\d*.*MCU", re.IGNORECASE),
    re.compile(r"^U\d*.*(FPGA|CPLD|PAL|GAL)", re.IGNORECASE),
    re.compile(r"^U\d*.*(74[A-Z]{0,2}\d|40\d{2}|CD4\d{2})", re.IGNORECASE),
    re.compile(r"^U\d*.*(LOGIC|BUFFER|DRIVER|GATE)", re.IGNORECASE),
    re.compile(r"^U\d*.*(STM32|ESP32|RP2040|SAMD|nRF|ATTiny|ATmega)", re.IGNORECASE),
    re.compile(r"^U\d*.*(XC[0-9]|ispMACH|MAX|EPM)", re.IGNORECASE),
]

# References matching these are considered analog/ADC ICs
_ANALOG_REF_PATTERNS: list[re.Pattern] = [
    re.compile(r"^U\d*.*(ADC|DAC|CODEC|OP[-_ ]?AMP|AMP|INA|THS|LM358|NE5532|TL07)", re.IGNORECASE),
    re.compile(r"^U\d*.*(VREF|REF\d*|BANDGAP)", re.IGNORECASE),
    re.compile(r"^U\d*.*(AUDIO|SOUND|MIC|PREAMP)", re.IGNORECASE),
]

# Passive component prefixes — if ALL pins on a ground net connect to these,
# the net is passive_only
_PASSIVE_PREFIXES = {"R", "C", "L", "D", "F", "FB", "TP", "J", "P"}


def _classify_ground_domain(
    net_name: str,
    pins: set[tuple[str, str]],
) -> str:
    """Classify a ground net's electrical domain based on connected components.

    Args:
        net_name: Ground net name (for logging).
        pins: Set of (ref, pin) tuples connected to this net.

    Returns:
        "digital", "analog", or "passive_only".
    """
    if not pins:
        return "passive_only"

    refs = {ref for ref, _pin in pins}
    has_digital = False
    has_analog = False

    for ref in refs:
        prefix = re.split(r"\d", ref, 1)[0].upper() if re.search(r"\d", ref) else ref.upper()

        # If all refs are passives, short-circuit
        if prefix in _PASSIVE_PREFIXES:
            continue

        # Check against IC patterns
        ref_str = ref.upper()
        if any(p.match(ref_str) for p in _DIGITAL_REF_PATTERNS):
            has_digital = True
        if any(p.match(ref_str) for p in _ANALOG_REF_PATTERNS):
            has_analog = True

        # Fallback: any U* not matched by specific patterns → analog (conservative)
        if prefix == "U" and not has_digital and not has_analog:
            has_analog = True

    if has_digital and has_analog:
        return "analog"  # mixed domain → conservative, don't recommend merging
    if has_digital:
        return "digital"
    if has_analog:
        return "analog"
    return "passive_only"


def _recommend(
    domain_a: str,
    domain_b: str,
    net_a: str,
    net_b: str,
) -> dict[str, str]:
    """Recommend merge/split/star_point for a ground-to-ground connection.

    Rules:
    - Both passive_only → "merge" (single ground plane is fine)
    - One digital, one analog → "split" (keep separate)
    - One passive, one active → "star_point" (connect at supply)
    - Both same domain → "merge" (redundant naming)

    Args:
        domain_a: Domain of first ground net.
        domain_b: Domain of second ground net.
        net_a: First ground net name.
        net_b: Second ground net name.

    Returns:
        Dict with "recommendation" and "reason".
    """
    if domain_a == domain_b:
        return {
            "recommendation": "merge",
            "reason": (
                f"{net_a} and {net_b} serve the same {domain_a} domain. "
                "Consider merging into a single net."
            ),
        }

    if domain_a == "passive_only" and domain_b == "passive_only":
        return {
            "recommendation": "merge",
            "reason": (
                f"Both {net_a} and {net_b} connect only to passive components. "
                "Safe to merge into a single ground net."
            ),
        }

    if (domain_a == "digital" and domain_b == "analog") or (
        domain_a == "analog" and domain_b == "digital"
    ):
        return {
            "recommendation": "split",
            "reason": (
                f"{net_a} serves {domain_a} circuits, {net_b} serves {domain_b} circuits. "
                "Separate ground domains reduce noise coupling."
            ),
        }

    # One passive, one active (digital or analog)
    active = net_a if domain_a != "passive_only" else net_b
    passive = net_a if domain_a == "passive_only" else net_b
    active_domain = domain_a if domain_a != "passive_only" else domain_b

    return {
        "recommendation": "star_point",
        "reason": (
            f"{active} ({active_domain}) should connect to {passive} (passive) "
            "at a single star point, typically at the power supply."
        ),
    }


# ---------------------------------------------------------------------------
# Ground net discovery
# ---------------------------------------------------------------------------

def _find_ground_nets(
    net_pins: dict[str, set[tuple[str, str]]],
    explicit_list: list[str] | None = None,
) -> dict[str, set[tuple[str, str]]]:
    """Filter netlist to ground nets only.

    Args:
        net_pins: Full netlist dict from _export_and_parse_netlist.
        explicit_list: If provided, only return these nets. Otherwise auto-detect.

    Returns:
        Dict mapping ground net name to set of (ref, pin) tuples.
    """
    from kicad_agent.ops.net_short_detector import _is_ground_net

    if explicit_list:
        return {
            name: pins
            for name, pins in net_pins.items()
            if name in explicit_list
        }

    return {
        name: pins
        for name, pins in net_pins.items()
        if _is_ground_net(name)
    }


def _find_ground_connections(
    ground_net_names: set[str],
    erc_shorts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find ERC-reported shorts between ground nets.

    Args:
        ground_net_names: Set of ground net names to check.
        erc_shorts: List of short dicts from _extract_erc_shorts.

    Returns:
        List of connection dicts with net_a, net_b, sheet, positions.
    """
    connections: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()

    for short in erc_shorts:
        net_a, net_b = short["net_a"], short["net_b"]
        pair = frozenset({net_a, net_b})

        if not ground_net_names.issuperset(pair) or pair in seen_pairs:
            continue

        seen_pairs.add(pair)
        connections.append({
            "net_a": net_a,
            "net_b": net_b,
            "sheet": short["sheet"],
            "positions": short["positions"],
            "description": short["description"],
        })

    return connections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_ground_topology(
    sch_path: Path,
    *,
    ground_nets: list[str] | None = None,
) -> dict[str, Any]:
    """Analyze ground net topology for mixed-signal designs.

    Exports netlist via kicad-cli, identifies ground nets, classifies their
    domains (digital/analog/passive), and recommends merge/split/star_point
    for each ground-to-ground connection.

    Args:
        sch_path: Path to a .kicad_sch file.
        ground_nets: Specific ground nets to analyze. None = auto-detect all.

    Returns:
        Dict with ground_nets catalog, connections, and recommendations.
    """
    from kicad_agent.ops.net_short_detector import (
        _export_and_parse_netlist,
        _extract_erc_shorts,
    )

    # 1. Parse netlist and find ground nets
    net_pins = _export_and_parse_netlist(sch_path)
    ground = _find_ground_nets(net_pins, explicit_list=ground_nets)

    if not ground:
        return {
            "ground_nets": {},
            "connections": [],
            "recommendation": "none",
            "reason": "No ground nets found in schematic",
            "ground_net_count": 0,
        }

    # 2. Get ERC shorts
    erc_shorts = _extract_erc_shorts(sch_path)

    # 3. Find ground-to-ground connections
    ground_names = set(ground.keys())
    connections = _find_ground_connections(ground_names, erc_shorts)

    # 4. Classify domains for each ground net
    ground_info: dict[str, dict[str, Any]] = {}
    for name, pins in ground.items():
        domain = _classify_ground_domain(name, pins)
        refs = sorted({ref for ref, _ in pins})
        ground_info[name] = {
            "pin_count": len(pins),
            "pins": sorted(f"{ref}.{pin}" for ref, pin in pins),
            "refs": refs,
            "domain": domain,
        }

    # 5. Generate recommendations for each connection
    enriched_connections: list[dict[str, Any]] = []
    overall_recommendation = "merge"  # default if no connections
    overall_reason = "No ground-to-ground shorts detected. Ground nets are isolated."

    for conn in connections:
        net_a, net_b = conn["net_a"], conn["net_b"]
        info_a = ground_info.get(net_a, {})
        info_b = ground_info.get(net_b, {})
        domain_a = info_a.get("domain", "passive_only")
        domain_b = info_b.get("domain", "passive_only")

        rec = _recommend(domain_a, domain_b, net_a, net_b)
        conn["recommendation"] = rec["recommendation"]
        conn["reason"] = rec["reason"]
        conn["domain_a"] = domain_a
        conn["domain_b"] = domain_b
        conn["pin_count_a"] = info_a.get("pin_count", 0)
        conn["pin_count_b"] = info_b.get("pin_count", 0)
        enriched_connections.append(conn)

    # 6. Overall recommendation based on connections
    if enriched_connections:
        recs = {c["recommendation"] for c in enriched_connections}
        if "split" in recs:
            overall_recommendation = "split"
            split_conns = [c for c in enriched_connections if c["recommendation"] == "split"]
            overall_reason = split_conns[0]["reason"]
        elif "star_point" in recs:
            overall_recommendation = "star_point"
            star_conns = [c for c in enriched_connections if c["recommendation"] == "star_point"]
            overall_reason = star_conns[0]["reason"]
        else:
            overall_recommendation = "merge"
            overall_reason = (
                "All ground-to-ground connections are between same-domain or "
                "passive-only nets. Safe to merge."
            )

    return {
        "ground_nets": ground_info,
        "connections": enriched_connections,
        "recommendation": overall_recommendation,
        "reason": overall_reason,
        "ground_net_count": len(ground_info),
        "connection_count": len(enriched_connections),
    }
