"""Net short fixer -- targeted repair of specific shorted net pairs.

Combines netlist-based pin tracing (#67) with positional bridge detection
to safely remove the wire(s) causing a short between two named nets.

Safety constraints (from issue #68):
- NEVER auto-fix critical shorts (power-to-power, power-to-ground)
- NEVER auto-fix medium shorts (ground-to-ground variants)
- NEVER auto-fix power-to-signal shorts (too risky)
- Only auto-fix signal-to-signal shorts

Strategies:
- "remove_wire": find and remove bridging wire(s) via BFS (default)
- "disconnect_a": remove all wires touching net_a labels
- "disconnect_b": remove all wires touching net_b labels

Usage:
    from volta.ops.net_short_fixer import fix_net_short

    result = fix_net_short(ir, file_path, net_a="SDA", net_b="SCL")
    print(f"Fixed: {result['fixed']}")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------


def _is_safe_to_auto_fix(net_a: str, net_b: str) -> tuple[bool, str]:
    """Check if a short is safe for automatic repair.

    Only signal-to-signal shorts are auto-fixed. All power-related
    and ground-related shorts are refused and require manual review.

    Args:
        net_a: First net name.
        net_b: Second net name.

    Returns:
        Tuple of (is_safe, reason).
    """
    from volta.ops.net_short_detector import (
        _classify_severity,
        _is_power_net,
    )

    severity = _classify_severity(net_a, net_b)

    if severity == "critical":
        return False, (
            f"critical: {net_a} <-> {net_b} "
            "(power-to-power or power-to-ground)"
        )

    if severity == "medium":
        return False, (
            f"medium: {net_a} <-> {net_b} "
            "(ground-to-ground, may be intentional)"
        )

    # severity == "high": check if power-to-signal
    if _is_power_net(net_a) or _is_power_net(net_b):
        return False, (
            f"power-to-signal: {net_a} <-> {net_b} "
            "(requires manual review)"
        )

    # Both are signal nets
    return True, "signal-to-signal"


# ---------------------------------------------------------------------------
# Wire finding helpers
# ---------------------------------------------------------------------------


def _find_wires_touching_net(
    ir: Any,
    target_net: str,
) -> list[int]:
    """Find wire indices that have at least one endpoint near a label of target_net.

    Args:
        ir: SchematicIR for the target schematic.
        target_net: Net name to find wires for.

    Returns:
        List of wire indices touching labels of target_net.
    """
    label_positions = ir.get_label_positions()
    wire_endpoints = ir.get_wire_endpoints()

    # Collect label positions for target_net
    label_pos_set: set[tuple[float, float]] = set()
    for lp in label_positions:
        if lp["name"] == target_net:
            label_pos_set.add((round(lp["x"], 2), round(lp["y"], 2)))

    if not label_pos_set:
        return []

    # Find wires with at least one endpoint matching a label position
    touching_wires: list[int] = []
    for we in wire_endpoints:
        start_key = (round(we["start_x"], 2), round(we["start_y"], 2))
        end_key = (round(we["end_x"], 2), round(we["end_y"], 2))
        if start_key in label_pos_set or end_key in label_pos_set:
            touching_wires.append(we["wire_index"])

    return touching_wires


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_net_short(
    ir: Any,
    file_path: Path,
    *,
    net_a: str,
    net_b: str,
    dry_run: bool = False,
    remove_strategy: str = "remove_wire",
) -> dict[str, Any]:
    """Fix a specific shorted net pair by removing bridging wire(s).

    Safety constraints:
    - Refuses critical shorts (power-to-power, power-to-ground)
    - Refuses medium shorts (ground-to-ground variants)
    - Refuses power-to-signal shorts
    - Only fixes signal-to-signal shorts

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        net_a: First shorted net name.
        net_b: Second shorted net name.
        dry_run: If True, report what would be fixed without modifying.
        remove_strategy: "remove_wire", "disconnect_a", or "disconnect_b".

    Returns:
        Dict with fixed, action, wire details, and shared pins.
    """
    from volta.ops.net_short_detector import (
        _classify_severity,
        _export_and_parse_netlist,
        _find_shared_pins,
    )

    # 1. Classify and check safety
    is_safe, reason = _is_safe_to_auto_fix(net_a, net_b)
    severity = _classify_severity(net_a, net_b)

    if not is_safe:
        return {
            "fixed": False,
            "action": "refused",
            "reason": reason,
            "severity": severity,
            "net_a": net_a,
            "net_b": net_b,
            "dry_run": dry_run,
        }

    # 2. Get shared pins from netlist
    net_pins = _export_and_parse_netlist(file_path)
    shared_pins = _find_shared_pins(net_a, net_b, net_pins)

    # 3. Find wires to remove based on strategy
    sch = ir.schematic
    wires_removed: list[dict[str, Any]] = []
    wire_indices_to_remove: list[int] = []

    if remove_strategy == "remove_wire":
        from volta.ops.repair_nets import _verify_clean_break
        from volta.ops.repair_wires import find_bridge_wires

        bridges = find_bridge_wires(ir, net_a, net_b)

        if not bridges:
            return {
                "fixed": False,
                "action": "no_bridge_found",
                "reason": "No bridging wire found between labels",
                "severity": severity,
                "net_a": net_a,
                "net_b": net_b,
                "shared_pins": shared_pins,
                "dry_run": dry_run,
            }

        # Build label seed sets for clean-break verification
        label_positions = ir.get_label_positions()
        net_a_seeds: set[tuple[float, float]] = set()
        net_b_seeds: set[tuple[float, float]] = set()
        wire_endpoints = ir.get_wire_endpoints()

        for lp in label_positions:
            pos = (round(lp["x"], 2), round(lp["y"], 2))
            if lp["name"] == net_a:
                net_a_seeds.add(pos)
            elif lp["name"] == net_b:
                net_b_seeds.add(pos)

        for bridge in bridges[:5]:
            is_clean = _verify_clean_break(
                wire_endpoints, bridge["wire_index"],
                net_a_seeds, net_b_seeds,
            )
            if not is_clean:
                continue

            wires_removed.append({
                "start": bridge["start"],
                "end": bridge["end"],
                "wire_index": bridge["wire_index"],
            })
            wire_indices_to_remove.append(bridge["wire_index"])
            break

    elif remove_strategy in ("disconnect_a", "disconnect_b"):
        target_net = net_a if remove_strategy == "disconnect_a" else net_b

        touching = _find_wires_touching_net(ir, target_net)

        if not touching:
            return {
                "fixed": False,
                "action": "no_wires_found",
                "reason": f"No wires touching {target_net} labels",
                "severity": severity,
                "net_a": net_a,
                "net_b": net_b,
                "shared_pins": shared_pins,
                "dry_run": dry_run,
            }

        wire_endpoints = ir.get_wire_endpoints()
        wire_map = {we["wire_index"]: we for we in wire_endpoints}

        for wi in touching:
            we = wire_map.get(wi)
            if we:
                wires_removed.append({
                    "start": [we["start_x"], we["start_y"]],
                    "end": [we["end_x"], we["end_y"]],
                    "wire_index": wi,
                })
            wire_indices_to_remove.append(wi)

    # 4. No actionable wires found
    if not wire_indices_to_remove:
        return {
            "fixed": False,
            "action": "no_action",
            "severity": severity,
            "net_a": net_a,
            "net_b": net_b,
            "shared_pins": shared_pins,
            "dry_run": dry_run,
        }

    # 5. Dry run: report without modifying
    if dry_run:
        return {
            "fixed": False,
            "action": "dry_run",
            "severity": severity,
            "net_a": net_a,
            "net_b": net_b,
            "shared_pins": shared_pins,
            "wires": wires_removed,
            "wire_count": len(wires_removed),
            "dry_run": True,
        }

    # 6. Remove wires in reverse index order to preserve indices
    for idx in sorted(set(wire_indices_to_remove), reverse=True):
        if idx < len(sch.graphicalItems):
            sch.graphicalItems.pop(idx)
            ir._record_mutation("fix_net_short", {
                "net_a": net_a,
                "net_b": net_b,
                "strategy": remove_strategy,
                "wire_index": idx,
            })

    return {
        "fixed": True,
        "action": remove_strategy,
        "severity": severity,
        "net_a": net_a,
        "net_b": net_b,
        "shared_pins": shared_pins,
        "wires": wires_removed,
        "wire_count": len(wires_removed),
    }
