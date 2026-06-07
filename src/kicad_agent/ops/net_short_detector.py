"""Net short detector -- netlist-based shorted net detection with severity classification.

Exports netlist via kicad-cli, parses pin memberships per net, cross-references
with ERC violations to identify shorted net pairs, and classifies severity.

Usage:
    from kicad_agent.ops.net_short_detector import detect_net_shorts

    result = detect_net_shorts(Path("schematic.kicad_sch"))
    for short in result["shorts"]:
        print(f"{short['severity']}: {short['net_a']} <-> {short['net_b']}")
        print(f"  Shared pins: {short['shared_pins']}")
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Netlist parsing
# ---------------------------------------------------------------------------

def _export_and_parse_netlist(sch_path: Path) -> dict[str, set[tuple[str, str]]]:
    """Export netlist via kicad-cli and parse net-to-pin membership.

    KiCad S-expression netlist format:
        (net (code N) (name "X") (node (ref "R") (pin "1") ...))

    Args:
        sch_path: Path to a .kicad_sch file.

    Returns:
        Dict mapping net name to set of (ref, pin) tuples.
    """
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "export", "netlist", str(sch_path), "-o", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("kicad-cli netlist export failed: %s", result.stderr)
            return {}

        content = tmp_path.read_text()
    except FileNotFoundError:
        logger.warning("kicad-cli not found")
        return {}
    except subprocess.TimeoutExpired:
        logger.warning("kicad-cli netlist export timed out")
        return {}
    finally:
        tmp_path.unlink(missing_ok=True)

    return _parse_kicad_netlist(content)


def _parse_kicad_netlist(content: str) -> dict[str, set[tuple[str, str]]]:
    """Parse KiCad S-expression netlist into net-to-pin mapping.

    Args:
        content: Raw S-expression netlist content.

    Returns:
        Dict mapping net name to set of (ref, pin) tuples.
    """
    nets: dict[str, set[tuple[str, str]]] = {}

    # Split on (net boundaries — each net block starts with (net
    net_blocks = re.split(r'\n\t\t\(net\b', content)

    for block in net_blocks[1:]:  # skip content before first (net
        name_match = re.search(r'\(name\s+"([^"]+)"', block)
        if not name_match:
            continue
        name = name_match.group(1)

        # Extract (ref "X") (pin "Y") from (node ...) blocks
        nodes = re.findall(
            r'\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)',
            block,
        )
        nets[name] = set(tuple(n) for n in nodes)

    return nets


# ---------------------------------------------------------------------------
# ERC cross-referencing
# ---------------------------------------------------------------------------

def _extract_erc_shorts(sch_path: Path) -> list[dict[str, Any]]:
    """Run ERC and extract multiple_net_names violations.

    Returns list of dicts with net_a, net_b, sheet, positions.
    """
    from kicad_agent.ops.erc_parser import parse_erc

    violations = parse_erc(sch_path)
    shorts: list[dict[str, Any]] = []

    for v in violations:
        if v.type != "multiple_net_names":
            continue

        # Extract net names from description: "Both NET_A and NET_B are attached..."
        desc_match = re.match(
            r'Both (\S+) and (\S+) are attached to the same items',
            v.description,
        )
        if not desc_match:
            continue

        net_a = desc_match.group(1)
        net_b = desc_match.group(2)

        shorts.append({
            "net_a": net_a,
            "net_b": net_b,
            "sheet": v.sheet,
            "positions": v.positions,
            "description": v.description,
        })

    return shorts


def _find_shared_pins(
    net_a: str,
    net_b: str,
    net_pins: dict[str, set[tuple[str, str]]],
) -> list[str]:
    """Find pins shared between two nets.

    Args:
        net_a: First net name.
        net_b: Second net name.
        net_pins: Dict mapping net name to set of (ref, pin) tuples.

    Returns:
        Sorted list of "ref.pin" strings shared by both nets.
    """
    pins_a = net_pins.get(net_a, set())
    pins_b = net_pins.get(net_b, set())
    shared = pins_a & pins_b
    return sorted(f"{ref}.{pin}" for ref, pin in shared)


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

# Ground net patterns — variants that are acceptable to merge
_GROUND_PATTERNS: list[re.Pattern] = [
    re.compile(r'^(GND|AGND|DGND|PGND|SGND|CHASSIS|GNDA)$', re.IGNORECASE),
]

# Power net patterns — anything that looks like a voltage rail
_POWER_PATTERNS: list[re.Pattern] = [
    re.compile(r'^(VCC|VDD|VSS|VEE)$', re.IGNORECASE),
    re.compile(r'^\+?\d+V\d*$'),           # +3V3, +5V, +9V, +12V
    re.compile(r'^-\d+V\d*$'),            # -15V, -12V
    re.compile(r'^(PWR|VIN|VOUT)$', re.IGNORECASE),
    re.compile(r'^VREG'),                   # voltage regulator related
]


def _is_ground_net(net_name: str) -> bool:
    """Check if a net name is a ground variant."""
    return any(p.match(net_name) for p in _GROUND_PATTERNS)


def _is_power_net(net_name: str) -> bool:
    """Check if a net name is a power rail (including grounds)."""
    return _is_ground_net(net_name) or any(p.match(net_name) for p in _POWER_PATTERNS)


def _classify_severity(net_a: str, net_b: str) -> str:
    """Classify short severity based on net types.

    Args:
        net_a: First net name.
        net_b: Second net name.

    Returns:
        "critical", "high", or "medium".
    """
    a_is_power = _is_power_net(net_a)
    b_is_power = _is_power_net(net_b)

    if a_is_power and b_is_power:
        # Both are power nets — but are they the same type?
        a_is_ground = _is_ground_net(net_a)
        b_is_ground = _is_ground_net(net_b)

        if a_is_ground and b_is_ground:
            # Ground-to-ground variant (e.g. GND↔AGND) — may be intentional
            return "medium"
        elif a_is_ground or b_is_ground:
            # Power-to-ground — destroys hardware
            return "critical"
        else:
            # Two different power rails shorted (e.g. +3V3↔+5V) — hardware damage
            return "critical"

    if a_is_power or b_is_power:
        # One power, one signal — power contaminates signal path
        return "high"

    # Both signal nets — wrong readings, crosstalk
    return "high"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_net_shorts(
    sch_path: Path,
    *,
    include: list[str] | None = None,
    severity: str = "all",
) -> dict[str, Any]:
    """Detect shorted nets with pin-level tracing and severity classification.

    Combines ERC violation data (multiple_net_names) with netlist pin
    membership to identify exactly which pins are shared between shorted
    nets, then classifies each short by severity.

    Args:
        sch_path: Path to a .kicad_sch file.
        include: Only check these specific net names. None = all.
        severity: Filter results by severity ("all", "critical", "high", "medium").

    Returns:
        Dict with shorts list, totals, and severity breakdown.
    """
    # 1. Parse netlist for pin memberships
    net_pins = _export_and_parse_netlist(sch_path)

    # 2. Get ERC short violations
    erc_shorts = _extract_erc_shorts(sch_path)

    # 3. Enrich each short with pin data and severity
    shorts: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for short in erc_shorts:
        net_a = short["net_a"]
        net_b = short["net_b"]

        # Normalize pair for deduplication (alphabetical order)
        pair = tuple(sorted([net_a, net_b]))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        # Filter by include list
        if include is not None:
            if net_a not in include and net_b not in include:
                continue

        sev = _classify_severity(net_a, net_b)

        # Filter by severity
        if severity != "all" and sev != severity:
            continue

        shared_pins = _find_shared_pins(net_a, net_b, net_pins)

        shorts.append({
            "net_a": net_a,
            "net_b": net_b,
            "shared_pins": shared_pins,
            "pin_count": len(shared_pins),
            "sheet": short["sheet"],
            "positions": short["positions"],
            "severity": sev,
        })

    # Sort by severity (critical first, then high, then medium)
    severity_order = {"critical": 0, "high": 1, "medium": 2}
    shorts.sort(key=lambda s: severity_order.get(s["severity"], 99))

    return {
        "shorts": shorts,
        "total": len(shorts),
        "critical": sum(1 for s in shorts if s["severity"] == "critical"),
        "high": sum(1 for s in shorts if s["severity"] == "high"),
        "medium": sum(1 for s in shorts if s["severity"] == "medium"),
        "net_count": len(net_pins),
    }
