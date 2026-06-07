"""Collision detection and pin overlap detection for schematic routing.

Identifies:
  - Vertical collision zones: columns where multiple pins from different
    components share the same x-coordinate. Any vertical wire through these
    columns would short all pins together.
  - Horizontal collision zones: rows where multiple pins from different
    components share the same y-coordinate.
  - Pin overlaps: pins from different nets at the exact same position,
    a layout bug where labels/wires create unintended shorts.

Uses PinResolver for pin position data and optionally parses netlist files
for net membership to classify overlap severity.

Security (threat model):
  T-38-02-03: PinResolver already enforces file size and pin count limits
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from kicad_agent.schematic_routing.pin_resolver import PinResolver


class CollisionDetector:
    """Detect collision zones and pin overlaps in a schematic.

    Usage::

        from kicad_agent.schematic_routing.collision_detector import CollisionDetector

        detector = CollisionDetector("schematic.kicad_sch")
        zones = detector.detect_routing_collisions()
        overlaps = detector.detect_pin_overlaps()
    """

    def __init__(
        self,
        filepath: str | Path,
        netlist_path: str | Path | None = None,
    ) -> None:
        """Initialize collision detector with a schematic file.

        Args:
            filepath: Path to the .kicad_sch file.
            netlist_path: Optional path to a netlist file for net membership.
                If not provided, all overlaps default to severity="warning".

        Raises:
            ValueError: If file exceeds PinResolver limits (T-38-02-03).
            FileNotFoundError: If the file does not exist.
        """
        filepath = Path(filepath)
        self._resolver = PinResolver(filepath)
        self._net_index: dict[tuple[str, str], str] = {}

        if netlist_path is not None:
            netlist_path = Path(netlist_path)
            if netlist_path.exists():
                self._net_index = self._parse_netlist(netlist_path)

    def _parse_netlist(self, netlist_path: Path) -> dict[tuple[str, str], str]:
        """Parse a KiCad netlist file for pin-to-net mapping.

        Returns:
            Dict mapping (ref, pin_number) to net_name.
        """
        content = netlist_path.read_text(encoding="utf-8")
        pin_index: dict[tuple[str, str], str] = {}

        # Parse net blocks: (net (code N) (name "NET_NAME") ... (node (ref "R") (pin "1")) ...)
        # R-BUG-005 fix: match both KiCad 8 (code 1) and KiCad 10 (code "1") formats
        for net_match in re.finditer(
            r'\(\s*net\s+\(code\s+"?\d+"?\)\s+\(name\s+"([^"]+)"\)',
            content,
        ):
            net_name = net_match.group(1)
            # Find all node entries within this net block
            net_start = net_match.start()
            # Find the end of this net block
            depth = 0
            net_end = net_start
            for i in range(net_start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        net_end = i + 1
                        break

            net_block = content[net_start:net_end]

            for node_match in re.finditer(
                r'\(\s*node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)',
                net_block,
            ):
                ref = node_match.group(1)
                pin = node_match.group(2)
                pin_index[(ref, pin)] = net_name

        return pin_index

    def detect_routing_collisions(self, tolerance: float = 2.54) -> list[dict]:
        """Detect vertical columns and horizontal rows where pins would collide.

        Groups pins by x-coordinate (within tolerance) for vertical zones and
        by y-coordinate for horizontal zones. Only reports zones with pins from
        two or more different component references.

        Args:
            tolerance: Max distance (mm) to group pins into the same collision
                column or row. Default 2.54mm (standard KiCad grid).

        Returns:
            List of collision zone dicts, each containing:
              - direction: "vertical" or "horizontal"
              - coordinate: The grouped coordinate value
              - range: (min, max) of the other-axis span
              - pins: List of pin dicts with ref, pin, position
              - description: Human-readable description
        """
        all_components = self._resolver.resolve_all()

        # Collect all pin positions as flat list
        all_pins: list[dict] = []
        for ref, comp_data in all_components.items():
            for pin_num, pin_info in comp_data.get("pins", {}).items():
                pos = pin_info["position"]
                all_pins.append({
                    "ref": ref,
                    "pin": pin_num,
                    "position": pos,
                })

        zones: list[dict] = []

        # Detect vertical collision zones (pins sharing x-coordinate)
        vertical_zones = self._find_collision_zones(
            all_pins, axis="x", tolerance=tolerance,
        )
        zones.extend(vertical_zones)

        # Detect horizontal collision zones (pins sharing y-coordinate)
        horizontal_zones = self._find_collision_zones(
            all_pins, axis="y", tolerance=tolerance,
        )
        zones.extend(horizontal_zones)

        return zones

    def _find_collision_zones(
        self,
        pins: list[dict],
        axis: str,
        tolerance: float,
    ) -> list[dict]:
        """Find collision zones along a single axis.

        Args:
            pins: List of pin dicts with ref, pin, position.
            axis: "x" for vertical zones, "y" for horizontal zones.
            tolerance: Grouping tolerance in mm.

        Returns:
            List of collision zone dicts.
        """
        other_axis = "y" if axis == "x" else "x"
        axis_idx = 0 if axis == "x" else 1
        other_idx = 1 - axis_idx

        # Group by quantized coordinate
        groups: dict[float, list[dict]] = defaultdict(list)
        for pin in pins:
            coord = pin["position"][axis_idx]
            quantized = round(coord / tolerance) * tolerance
            groups[quantized].append(pin)

        zones: list[dict] = []
        for quantized_coord, group_pins in sorted(groups.items()):
            # Report zones with >= 2 pins (a wire through this zone would short them)
            if len(group_pins) < 2:
                continue
            unique_refs = {p["ref"] for p in group_pins}

            # Calculate the actual coordinate (average of pin positions)
            actual_coord = sum(p["position"][axis_idx] for p in group_pins) / len(group_pins)

            # Calculate range of the other axis
            other_values = [p["position"][other_idx] for p in group_pins]
            range_min = min(other_values)
            range_max = max(other_values)

            direction = "vertical" if axis == "x" else "horizontal"

            zone = {
                "direction": direction,
                "coordinate": round(actual_coord, 2),
                "range": (round(range_min, 2), round(range_max, 2)),
                "pins": [
                    {
                        "ref": p["ref"],
                        "pin": p["pin"],
                        "position": (round(p["position"][0], 2), round(p["position"][1], 2)),
                    }
                    for p in sorted(group_pins, key=lambda p: (p["ref"], p["pin"]))
                ],
                "description": (
                    f"{direction.capitalize()} collision zone at {axis}={round(actual_coord, 2)} "
                    f"with {len(group_pins)} pins from {len(unique_refs)} components"
                ),
            }
            zones.append(zone)

        return zones

    def detect_pin_overlaps(self, tolerance: float = 0.01) -> list[dict]:
        """Detect pins from different nets at the exact same position.

        Groups pins by position (within tolerance). For each position with
        multiple pins, checks net membership to classify severity:
          - "error": Pins from different nets (unintended short)
          - "warning": Pins on same net or net unknown (may be intentional)

        Args:
            tolerance: Position tolerance (mm) for overlap detection. Default 0.01mm.

        Returns:
            List of overlap dicts, each containing:
              - position: (x, y) tuple
              - pins: List of pin dicts with ref, pin, net
              - severity: "error" or "warning"
              - note: Human-readable explanation
        """
        all_components = self._resolver.resolve_all()

        # Collect all pin positions as flat list
        all_pins: list[dict] = []
        for ref, comp_data in all_components.items():
            for pin_num, pin_info in comp_data.get("pins", {}).items():
                pos = pin_info["position"]
                net = self._net_index.get((ref, pin_num))
                all_pins.append({
                    "ref": ref,
                    "pin": pin_num,
                    "position": pos,
                    "net": net,
                })

        # Group by quantized position
        groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for pin in all_pins:
            x, y = pin["position"]
            qx = round(x / tolerance)
            qy = round(y / tolerance)
            groups[(qx, qy)].append(pin)

        overlaps: list[dict] = []
        for (qx, qy), group_pins in sorted(groups.items()):
            if len(group_pins) < 2:
                continue

            # Calculate average position
            avg_x = sum(p["position"][0] for p in group_pins) / len(group_pins)
            avg_y = sum(p["position"][1] for p in group_pins) / len(group_pins)

            # Determine severity based on net membership
            nets = {p["net"] for p in group_pins if p["net"] is not None}
            unique_refs = {p["ref"] for p in group_pins}

            # If multiple different nets are present, it's an error
            has_multiple_nets = len(nets) > 1
            # If no netlist provided, all nets are None -> warning
            all_nets_unknown = all(p["net"] is None for p in group_pins)

            if has_multiple_nets:
                severity = "error"
                note = (
                    f"Pins from different nets share position "
                    f"({round(avg_x, 2)}, {round(avg_y, 2)}) -- unintended short"
                )
            elif all_nets_unknown and len(unique_refs) > 1:
                # Multiple pins from different refs, nets unknown
                severity = "warning"
                note = (
                    f"Pins from {len(unique_refs)} components share position "
                    f"({round(avg_x, 2)}, {round(avg_y, 2)}) -- net membership unknown"
                )
            else:
                severity = "warning"
                net_name = next(iter(nets), None)
                note = (
                    f"Pins on same net '{net_name}' share position "
                    f"({round(avg_x, 2)}, {round(avg_y, 2)})"
                )

            overlap = {
                "position": (round(avg_x, 2), round(avg_y, 2)),
                "pins": [
                    {
                        "ref": p["ref"],
                        "pin": p["pin"],
                        "net": p["net"],
                    }
                    for p in sorted(group_pins, key=lambda p: (p["ref"], p["pin"]))
                ],
                "severity": severity,
                "note": note,
            }
            overlaps.append(overlap)

        return overlaps
