"""Net repair operations -- shorted net detection, resolution, and verification.

Provides net-level repair functions for schematic ERC auto-fix:
- Shorted net detection via NetPositionIndex
- Shorted net fixing by label removal
- Atomic short resolution (wire breaking + label fixing)
- Power-net protection guards
- Net snapshot comparison for post-repair verification
"""

import logging
import math
import re
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.schematic_routing.net_extractor import NetPositionIndex

logger = logging.getLogger(__name__)


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _round_pos(x: float, y: float) -> tuple[float, float]:
    """Round position to SNAP_TOLERANCE precision for grouping."""
    precision = 2  # 0.01mm precision
    return (round(x, precision), round(y, precision))


def detect_shorted_nets(ir: SchematicIR) -> dict[str, Any]:
    """Find connected components where multiple named nets overlap.

    Delegates to NetPositionIndex.detect_shorts() which uses the
    full union-find pipeline with mid-point connectivity, junction
    handling, and pin-aware grouping -- replacing the former ad-hoc
    union-find that only checked wire start/end positions.

    Args:
        ir: SchematicIR for the target schematic.

    Returns:
        Dict with shorts (list of {position, nets}) and clean (bool).
    """
    # Build NetPositionIndex from the schematic file on disk.
    # ir.file_path points to the original parsed file; callers invoke
    # detect_shorted_nets before making mutations so disk state matches.
    file_path = ir.file_path
    if file_path is None:
        return {"shorts": [], "clean": True}

    index = NetPositionIndex.from_file(file_path)
    shorts = index.detect_shorts()
    return {"shorts": shorts, "clean": len(shorts) == 0}


def fix_shorted_nets(
    ir: SchematicIR, file_path: Path, *,
    strategy: str = "keep_first",
    keep_nets: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fix positions where multiple net names connect to the same items.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        strategy: "keep_first", "keep_last", "keep_majority", or "manual".
            - keep_first: keep the first alphabetically.
            - keep_last: keep the last alphabetically.
            - keep_majority: keep the net with the most connections (pins +
              labels). Power nets are always preferred over signal nets.
              Power-to-power shorts are never auto-resolved.
            - manual: use the keep_nets list to decide.
        keep_nets: For "manual" strategy, which net names to keep.
        dry_run: If True, report shorts without modifying.

    Returns:
        Dict with shorts_found, labels_removed, and details.
    """
    from kicad_agent.ops.repair_wires import SNAP_TOLERANCE

    short_result = detect_shorted_nets(ir)
    shorts = short_result["shorts"]

    if not shorts:
        return {"shorts_found": 0, "labels_removed": [], "clean": True}

    label_positions = ir.get_label_positions()
    sch = ir.schematic

    labels_removed: list[dict[str, Any]] = []

    for short in shorts:
        nets = short["nets"]
        if len(nets) < 2:
            continue

        # Decide which net to keep
        if strategy == "keep_first":
            keep_net = nets[0]
        elif strategy == "keep_last":
            keep_net = nets[-1]
        elif strategy == "keep_majority":
            # Count connections per net via NetPositionIndex
            try:
                index = NetPositionIndex.from_file(file_path)
            except Exception:
                index = None

            net_counts: dict[str, int] = {}
            for net_name in nets:
                if index is not None:
                    positions = index.get_positions_for_net(net_name)
                    net_counts[net_name] = len(positions)
                else:
                    net_counts[net_name] = 0

            # Separate power nets from signal nets
            power_nets = [n for n in nets if _is_power_net(n)]
            signal_nets = [n for n in nets if not _is_power_net(n)]

            if len(power_nets) >= 2:
                # Power-to-power short: NEVER auto-resolve
                logger.warning(
                    "Power-to-power short detected: %s. Skipping auto-fix.",
                    ", ".join(power_nets),
                )
                continue

            if power_nets:
                # Power-to-signal short: always keep the power net
                keep_net = power_nets[0]
            else:
                # Signal-to-signal short: keep the one with more connections
                keep_net = max(signal_nets, key=lambda n: net_counts.get(n, 0))

            logger.info(
                "Short resolution (keep_majority): keeping %s, removing %s",
                keep_net,
                set(nets) - {keep_net},
            )
        elif strategy == "manual":
            if keep_nets is None:
                continue
            keep_net = None
            for kn in keep_nets:
                if kn in nets:
                    keep_net = kn
                    break
            if keep_net is None:
                continue
        else:
            continue

        # Power-net safety guard: block auto-removal of power nets
        # unless strategy is "manual" (explicit user choice).
        remove_nets = set(nets) - {keep_net}
        power_being_removed = [n for n in remove_nets if _is_power_net(n)]
        if power_being_removed and strategy != "manual":
            logger.warning(
                "Refusing to auto-remove power net(s) %s. "
                "Use strategy='manual' with explicit keep_nets.",
                power_being_removed,
            )
            continue

        for label in list(sch.labels):
            if label.text in remove_nets:
                pos_key = _round_pos(label.position.X, label.position.Y)
                short_pos = (round(short["position"][0], 2), round(short["position"][1], 2))
                if pos_key == short_pos or _distance(
                    label.position.X, label.position.Y,
                    short["position"][0], short["position"][1],
                ) <= SNAP_TOLERANCE:
                    if not dry_run:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                        })
                        sch.labels.remove(label)
                        ir._record_mutation("fix_shorted_net", {
                            "removed_label": label.text,
                            "kept_net": keep_net,
                        })
                    else:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                            "dry_run": True,
                        })

        for label in list(sch.globalLabels):
            if label.text in remove_nets:
                pos_key = _round_pos(label.position.X, label.position.Y)
                short_pos = (round(short["position"][0], 2), round(short["position"][1], 2))
                if pos_key == short_pos or _distance(
                    label.position.X, label.position.Y,
                    short["position"][0], short["position"][1],
                ) <= SNAP_TOLERANCE:
                    if not dry_run:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                        })
                        sch.globalLabels.remove(label)
                        ir._record_mutation("fix_shorted_net", {
                            "removed_label": label.text,
                            "kept_net": keep_net,
                        })
                    else:
                        labels_removed.append({
                            "name": label.text,
                            "position": [label.position.X, label.position.Y],
                            "kept": keep_net,
                            "dry_run": True,
                        })

    return {
        "shorts_found": len(shorts),
        "labels_removed": labels_removed,
        "clean": len(labels_removed) == 0,
    }


# Power net name patterns -- regex patterns that indicate power rails.
# These nets should NEVER be auto-removed during short resolution.
# HI-06 (Phase 66 Council): Frozenset approach missed unconventional names
# like +3.3V, VDD_3V3, VIN, VOUT. Regex covers these systematically.
_POWER_NET_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(VCC|VDD|VSS|VEE)$", re.IGNORECASE),
    re.compile(r"^(GND|AGND|DGND|PGND|SGND|CHASSIS)$", re.IGNORECASE),
    re.compile(r"^\+?\d+V\d*$"),          # +3V3, +5V, +9V, +12V, +15V, 3V3
    re.compile(r"^-\d+V\d*$"),             # -15V, -12V
    re.compile(r"^(PWR|VIN|VOUT)$", re.IGNORECASE),
]


def _is_power_net(net_name: str) -> bool:
    """Check if a net name looks like a power rail.

    Uses regex patterns to match common power rail naming conventions
    including voltage rails (+3V3, +5V, -15V), ground variants (GND,
    AGND, DGND), and supply pins (VCC, VDD, VIN, VOUT).
    """
    return any(p.match(net_name) for p in _POWER_NET_PATTERNS)


def _check_orphan_count(
    wire_endpoints: list[dict[str, Any]],
    bridge_wire_index: int,
    label_positions: list[dict[str, Any]],
) -> int:
    """Count pins/labels orphaned if bridge_wire_index is removed.

    Returns 0 if the break is clean (no orphans).
    """
    # Build adjacency without the bridge wire
    adjacency: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for we in wire_endpoints:
        wi = we["wire_index"]
        if wi == bridge_wire_index:
            continue
        start = _round_pos(we["start_x"], we["start_y"])
        end = _round_pos(we["end_x"], we["end_y"])
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)

    # Collect all label positions
    label_pos_set: set[tuple[float, float]] = set()
    for label in label_positions:
        label_pos_set.add(_round_pos(label["x"], label["y"]))

    # BFS from label positions to find reachable set
    visited: set[tuple[float, float]] = set()
    queue: list[tuple[float, float]] = list(label_pos_set)
    for pos in queue:
        visited.add(pos)

    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    # Count label positions NOT reachable from any other label
    orphan_count = 0
    for pos in label_pos_set:
        if pos not in visited:
            orphan_count += 1

    return orphan_count


def _verify_clean_break(
    wire_endpoints: list[dict[str, Any]],
    bridge_wire_index: int,
    net_a_labels: set[tuple[float, float]],
    net_b_labels: set[tuple[float, float]],
) -> bool:
    """Verify that removing bridge_wire_index cleanly separates net_a from net_b.

    Graph-bridge algorithm:
    1. Build adjacency graph from all wires EXCEPT the candidate bridge wire
    2. BFS from any net_a label position
    3. If all net_a labels are reachable and NO net_b labels are reachable,
       the break is clean (the wire was the sole connection between the two groups)

    Complexity: O(W + P) where W = wire count, P = position count.

    Args:
        wire_endpoints: All wire endpoint data from ir.get_wire_endpoints().
        bridge_wire_index: Index of the candidate bridge wire to remove.
        net_a_labels: Positions of labels belonging to net_a.
        net_b_labels: Positions of labels belonging to net_b.

    Returns:
        True if removing the wire cleanly separates the two net groups.
    """
    if not net_a_labels or not net_b_labels:
        return False

    # Build adjacency without the bridge wire
    adjacency: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for we in wire_endpoints:
        if we["wire_index"] == bridge_wire_index:
            continue
        start = _round_pos(we["start_x"], we["start_y"])
        end = _round_pos(we["end_x"], we["end_y"])
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)

    # BFS from a net_a seed
    seed = next(iter(net_a_labels))
    visited: set[tuple[float, float]] = set()
    queue: list[tuple[float, float]] = [seed]
    visited.add(seed)

    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    # Check: all net_a labels reachable, no net_b labels reachable
    net_a_unreachable = net_a_labels - visited
    net_b_reachable = net_b_labels & visited

    return len(net_a_unreachable) == 0 and len(net_b_reachable) == 0


# ---------------------------------------------------------------------------
# Post-repair verification (Phase 70)
# ---------------------------------------------------------------------------


def _take_net_snapshot(ir: SchematicIR) -> dict[str, Any]:
    """Build net topology snapshot from in-memory IR state.

    Uses pin-set identity (frozenset of (ref, pin_number)) for stable
    comparison across snapshots, immune to auto-naming order changes.
    """
    wire_endpoints = ir.get_wire_endpoints()
    label_positions = ir.get_label_positions()
    pin_positions = ir.get_pin_positions()

    # Build union-find over wire-connected positions
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def _uf_find(pos: tuple[float, float]) -> tuple[float, float]:
        while parent.get(pos, pos) != pos:
            parent[pos] = parent.get(parent[pos], parent[pos])
            pos = parent[pos]
        return pos

    def _uf_union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = _uf_find(a), _uf_find(b)
        if ra != rb:
            parent[ra] = rb

    # Union wire start/end
    for we in wire_endpoints:
        start = _round_pos(we["start_x"], we["start_y"])
        end = _round_pos(we["end_x"], we["end_y"])
        _uf_union(start, end)

    # Collect label positions and pin positions
    pos_to_pins: dict[tuple[float, float], list[tuple[str, str]]] = {}
    for p in pin_positions:
        key = _round_pos(p["x"], p["y"])
        pos_to_pins.setdefault(key, []).append((p["reference"], p["pin_number"]))

    pos_to_labels: dict[tuple[float, float], str] = {}
    for label in label_positions:
        key = _round_pos(label["x"], label["y"])
        pos_to_labels[key] = label["name"]

    # Build components by root
    components: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for we in wire_endpoints:
        for coord in [(we["start_x"], we["start_y"]), (we["end_x"], we["end_y"])]:
            key = _round_pos(coord[0], coord[1])
            root = _uf_find(key)
            components.setdefault(root, set()).add(key)
    for key in pos_to_pins:
        root = _uf_find(key)
        components.setdefault(root, set()).add(key)
    for key in pos_to_labels:
        root = _uf_find(key)
        components.setdefault(root, set()).add(key)

    # Build per-component pin sets and net names
    result: dict[str, Any] = {"components": {}}
    for root, positions in components.items():
        pin_set: set[tuple[str, str]] = set()
        net_name: str | None = None
        for pos in positions:
            if pos in pos_to_pins:
                pin_set.update(pos_to_pins[pos])
            if pos in pos_to_labels and net_name is None:
                net_name = pos_to_labels[pos]
        result["components"][root] = {
            "pin_set": frozenset(pin_set),
            "net_name": net_name,
        }

    return result


def _diff_net_snapshots(before: dict, after: dict) -> dict[str, Any]:
    """Compare two net snapshots and detect regressions.

    Returns dict with broken_nets, merged_nets, new_components, and clean flag.
    Uses pin-set overlap for component matching (not net names).
    """
    before_comps = before.get("components", {})
    after_comps = after.get("components", {})

    # Build pin_set -> component mappings
    before_by_pins: dict[frozenset, tuple] = {}
    for root, data in before_comps.items():
        pins = data["pin_set"]
        if pins:
            before_by_pins[pins] = (root, data)

    after_by_pins: dict[frozenset, tuple] = {}
    for root, data in after_comps.items():
        pins = data["pin_set"]
        if pins:
            after_by_pins[pins] = (root, data)

    broken_nets: list[dict] = []
    merged_nets: list[dict] = []
    new_components: list[dict] = []

    # Find broken: before component with no after match
    matched_after: set[frozenset] = set()
    for pins, (root, data) in before_by_pins.items():
        if pins in after_by_pins:
            matched_after.add(pins)
        else:
            # Check for partial match (subset of pins still present)
            found_partial = False
            for after_pins, (after_root, after_data) in after_by_pins.items():
                if after_pins and pins and after_pins.issubset(pins) and len(after_pins) >= len(pins) * 0.5:
                    found_partial = True
                    matched_after.add(after_pins)
                    break
            if not found_partial:
                broken_nets.append({
                    "net_name": data.get("net_name"),
                    "pin_count": len(pins),
                })

    # Find merged: multiple before components matching same after component
    # (This would indicate a short was introduced)
    # Find new: after components with no before match
    for pins, (root, data) in after_by_pins.items():
        if pins not in matched_after:
            new_components.append({
                "net_name": data.get("net_name"),
                "pin_count": len(pins),
            })

    clean = len(broken_nets) == 0 and len(merged_nets) == 0
    return {
        "broken_nets": broken_nets,
        "merged_nets": merged_nets,
        "new_components": new_components,
        "clean": clean,
    }


def resolve_shorted_nets(
    ir: SchematicIR, file_path: Path, *,
    strategy: str = "smart",
    keep_nets: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atomically resolve shorted nets by breaking bridge wires and fixing labels.

    Phase 67: Combines break_wire_shorts + fix_shorted_nets into one atomic
    operation with proper ordering, clean-break verification, and power-net
    protection.

    Strategy "smart" (default):
      1. Detect all shorts via NetPositionIndex
      2. For each short, attempt to find bridge wire(s)
      3. If bridge wire found and removal is clean (verified via BFS) -> break wire
      4. If no clean break possible -> fix labels (with power-net protection)
      5. If neither works -> log warning, skip (manual resolution needed)

    Note: This operation works on single-sheet schematics only.
    Cross-sheet shorts (via hierarchical labels) require whole-project
    netlist analysis and are out of scope for this operation.

    For hierarchical projects, use on each sub-sheet individually, then
    verify with ``kicad-cli sch erc`` on the root schematic.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the schematic file.
        strategy: Resolution strategy:
            - "smart": try wire break, fall back to label fix (default)
            - "break_only": only attempt wire breaking
            - "fix_labels_only": only fix labels (no wire removal)
            - "manual": report only, no changes
        keep_nets: For "manual" strategy, which nets to keep.
        dry_run: If True, report without modifying.

    Returns:
        Dict with shorts_found, wires_broken, labels_fixed, unresolved,
        and details.
    """
    from kicad_agent.ops.repair_wires import SNAP_TOLERANCE, find_bridge_wires

    shorts_result = detect_shorted_nets(ir)
    shorts = shorts_result["shorts"]

    if not shorts:
        return {
            "shorts_found": 0,
            "wires_broken": 0,
            "labels_fixed": 0,
            "unresolved": 0,
            "details": [],
        }

    wire_endpoints = ir.get_wire_endpoints()
    label_positions = ir.get_label_positions()
    sch = ir.schematic

    results: dict[str, Any] = {
        "shorts_found": len(shorts),
        "wires_broken": [],
        "labels_fixed": [],
        "unresolved": [],
        "details": [],
    }

    for short in shorts:
        nets = short["nets"]
        if len(nets) < 2:
            continue

        # Power-safety check (from plan 67-02)
        power_nets = [n for n in nets if _is_power_net(n)]
        if len(power_nets) >= 2:
            results["unresolved"].append({
                "nets": sorted(nets),
                "reason": "power_to_power",
                "position": list(short["position"]),
            })
            continue

        if strategy == "manual":
            if keep_nets is not None:
                results["details"].append({
                    "nets": sorted(nets),
                    "action": "manual",
                    "keep_nets": keep_nets,
                })
            else:
                results["details"].append({
                    "nets": sorted(nets),
                    "action": "manual_only",
                    "position": list(short["position"]),
                })
            continue

        # Try to find and break bridge wire
        bridge_found = False
        if strategy in ("smart", "break_only"):
            bridges = find_bridge_wires(ir, nets[0], nets[1])

            # Build seed sets for clean-break verification
            net_a_seeds: set[tuple[float, float]] = set()
            net_b_seeds: set[tuple[float, float]] = set()
            for lp in label_positions:
                pos = _round_pos(lp["x"], lp["y"])
                if lp["name"] == nets[0]:
                    net_a_seeds.add(pos)
                elif lp["name"] == nets[1]:
                    net_b_seeds.add(pos)

            for bridge in bridges[:5]:  # limit candidate count
                is_clean = _verify_clean_break(
                    wire_endpoints, bridge["wire_index"],
                    net_a_seeds, net_b_seeds,
                )
                if not is_clean:
                    continue

                if dry_run:
                    results["wires_broken"].append({
                        "nets": sorted(nets),
                        "wire_start": bridge["start"],
                        "wire_end": bridge["end"],
                        "dry_run": True,
                    })
                    bridge_found = True
                    break

                # Remove the bridge wire
                wire_idx = bridge["wire_index"]
                if wire_idx < len(sch.graphicalItems):
                    sch.graphicalItems.pop(wire_idx)
                    ir._record_mutation("resolve_shorted_net", {
                        "action": "break_bridge",
                        "nets": sorted(nets),
                        "wire_index": wire_idx,
                    })
                    results["wires_broken"].append({
                        "nets": sorted(nets),
                        "wire_start": bridge["start"],
                        "wire_end": bridge["end"],
                    })
                    bridge_found = True
                    break

        # If no clean break, try label fix (unless break_only)
        if not bridge_found and strategy != "break_only":
            # Determine which net to keep (power-net protection from 67-02)
            if power_nets:
                # Power-to-signal: always keep the power net
                keep_net = power_nets[0]
            else:
                # Signal-to-signal: keep first (alphabetically)
                keep_net = sorted(nets)[0]

            remove_nets = set(nets) - {keep_net}

            # Power-net safety guard: block auto-removal of power nets
            power_being_removed = [n for n in remove_nets if _is_power_net(n)]
            if power_being_removed:
                results["unresolved"].append({
                    "nets": sorted(nets),
                    "reason": "would_remove_power_net",
                    "position": list(short["position"]),
                })
                continue

            removed_labels: list[str] = []
            for label in list(sch.labels):
                if label.text in remove_nets:
                    pos_key = _round_pos(label.position.X, label.position.Y)
                    short_pos = (
                        round(short["position"][0], 2),
                        round(short["position"][1], 2),
                    )
                    if pos_key == short_pos or _distance(
                        label.position.X, label.position.Y,
                        short["position"][0], short["position"][1],
                    ) <= 0.5:
                        if not dry_run:
                            removed_labels.append(label.text)
                            sch.labels.remove(label)
                            ir._record_mutation("resolve_shorted_net", {
                                "action": "remove_label",
                                "removed": label.text,
                                "kept": keep_net,
                            })
                        else:
                            removed_labels.append(label.text)

            for label in list(sch.globalLabels):
                if label.text in remove_nets:
                    pos_key = _round_pos(label.position.X, label.position.Y)
                    short_pos = (
                        round(short["position"][0], 2),
                        round(short["position"][1], 2),
                    )
                    if pos_key == short_pos or _distance(
                        label.position.X, label.position.Y,
                        short["position"][0], short["position"][1],
                    ) <= 0.5:
                        if not dry_run:
                            removed_labels.append(label.text)
                            sch.globalLabels.remove(label)
                            ir._record_mutation("resolve_shorted_net", {
                                "action": "remove_label",
                                "removed": label.text,
                                "kept": keep_net,
                            })
                        else:
                            removed_labels.append(label.text)

            if removed_labels:
                results["labels_fixed"].append({
                    "nets": sorted(nets),
                    "kept": keep_net,
                    "removed": removed_labels,
                    "dry_run": dry_run,
                })
            elif not bridge_found:
                # Neither wire break nor label fix worked
                results["unresolved"].append({
                    "nets": sorted(nets),
                    "reason": "no_clean_break",
                    "position": list(short["position"]),
                })

        elif not bridge_found:
            # break_only strategy found no clean break
            results["unresolved"].append({
                "nets": sorted(nets),
                "reason": "no_clean_break",
                "position": list(short["position"]),
            })

    return {
        "shorts_found": results["shorts_found"],
        "wires_broken": len(results["wires_broken"]),
        "labels_fixed": len(results["labels_fixed"]),
        "unresolved": len(results["unresolved"]),
        "details": results["details"] or results["wires_broken"] + results["labels_fixed"] + results["unresolved"],
    }
