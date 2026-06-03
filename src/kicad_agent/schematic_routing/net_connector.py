"""Net connector -- connect pins into a net with wire/label generation.

Generates net labels at pin wire endpoints offset outward from IC body
(configurable via label_offset, default 2.54mm) for guaranteed KiCad
connectivity, and optionally generates wires for nearby same-axis pins
with collision zone avoidance.

Three strategies:
  - wire_first: Generate wires for connected pins, labels for unreached.
  - label_only: No wires, just labels at every pin.
  - hybrid: Short/clean wires where possible, labels everywhere.

Key insight: net labels at every pin position provide guaranteed connectivity.
Wires are cosmetic for programmatic schematics. The connect_pins operation
generates labels offset outward from IC body (body_position -> position +
label_offset along pin direction), and optionally generates wires for
short/clean routes.

Security (threat model):
  T-38-03-03: Wires generated at exact pin positions only -- no arbitrary
              coordinate injection
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from kicad_agent.schematic_routing.pin_resolver import PinResolver


class NetConnector:
    """Connect pins into a net with wire and label generation.

    Usage::

        from kicad_agent.schematic_routing.net_connector import NetConnector

        connector = NetConnector("schematic.kicad_sch")
        result = connector.connect_pins(
            net_name="VCC",
            pins=[{"ref": "R55", "pin": "1"}, {"ref": "R56", "pin": "2"}],
            strategy="hybrid",
        )
    """

    # KiCad standard grid spacing (50 mils)
    GRID_MM = 2.54

    def __init__(self, filepath: str | Path) -> None:
        """Initialize NetConnector with a schematic file path.

        Args:
            filepath: Path to the .kicad_sch file.
        """
        self._filepath = Path(filepath)
        self._resolver = PinResolver(self._filepath)

    def _snap_coord(self, value: float) -> float:
        """Snap a coordinate to the nearest grid point."""
        nearest = int(value / self.GRID_MM + 0.5)
        return round(nearest * self.GRID_MM, 2)

    def connect_pins(
        self,
        net_name: str,
        pins: list[dict[str, str]],
        strategy: str = "hybrid",
        collision_zones: list[dict[str, Any]] | None = None,
        max_wire_length: float = 40.0,
        label_offset: float = 2.54,
    ) -> dict[str, Any]:
        """Connect pins into a net with wire/label generation.

        Algorithm:
        1. Resolve all pin positions using PinResolver.
        2. Generate labels at pin positions offset outward from IC body.
        3. Generate wires (unless strategy is label_only):
           - Same-axis pins get direct wires.
           - Other pins get L-shaped wires (horizontal then vertical).
           - Skip wires through collision zones.
           - Skip wires longer than max_wire_length.
        4. Return counts and wire/label data.

        Args:
            net_name: Net name for generated labels.
            pins: List of {"ref": str, "pin": str} dicts.
            strategy: "wire_first", "label_only", or "hybrid".
            collision_zones: Optional list of collision zone dicts with
                direction, coordinate, tolerance keys.
            max_wire_length: Skip wires longer than this (mm).
            label_offset: Distance (mm) to offset labels outward from pin
                wire endpoint along pin direction. Default 2.54mm (1 grid unit).
                Set to 0.0 to place labels exactly at wire endpoints.

        Returns:
            Dict with net_name, wires_generated, labels_generated,
            collisions_avoided, wires list, labels list, notes list.
        """
        if collision_zones is None:
            collision_zones = []

        # Step 1: Resolve pin positions
        resolved_pins = self._resolve_pins(pins)
        if not resolved_pins:
            return {
                "net_name": net_name,
                "wires_generated": 0,
                "labels_generated": 0,
                "collisions_avoided": 0,
                "wires": [],
                "labels": [],
                "notes": ["No pins resolved"],
            }

        # Step 2: Generate labels offset outward from pin wire endpoints.
        # Direction: from body_position toward position (pin points outward
        # from IC body), then extend further by label_offset.
        labels: list[dict] = []
        for pin_info in resolved_pins:
            bx, by = pin_info["body_position"]
            wx, wy = pin_info["position"]

            if label_offset > 0 and not (
                math.isclose(bx, wx, abs_tol=0.01)
                and math.isclose(by, wy, abs_tol=0.01)
            ):
                # Direction vector from body to wire endpoint (outward from IC)
                dx = wx - bx
                dy = wy - by
                length = math.sqrt(dx * dx + dy * dy)
                if length > 0.01:
                    # Normalize and extend from wire endpoint
                    nx = dx / length
                    ny = dy / length
                    lx = round(wx + nx * label_offset, 2)
                    ly = round(wy + ny * label_offset, 2)
                else:
                    lx, ly = wx, wy
            else:
                lx, ly = wx, wy

            label_sexpr = (
                f'  (label "{net_name}" (at {lx:g} {ly:g} 0) '
                f'(effects (font (size 0.75 0.75))))\n'
            )
            labels.append({
                "position": (lx, ly),
                "sexpr": label_sexpr,
                "ref": pin_info["ref"],
                "pin": pin_info["pin"],
            })

        # Step 3: Generate wires (if not label_only)
        wires: list[dict] = []
        collisions_avoided = 0

        if strategy != "label_only" and len(resolved_pins) >= 2:
            wires, collisions_avoided = self._generate_wires(
                resolved_pins=resolved_pins,
                collision_zones=collision_zones,
                max_wire_length=max_wire_length,
                strategy=strategy,
            )

        notes: list[str] = []
        if collisions_avoided > 0:
            notes.append(
                f"Skipped {collisions_avoided} wire(s) due to collision zones"
            )
        if strategy == "label_only":
            notes.append("Label-only strategy: no wires generated")

        return {
            "net_name": net_name,
            "wires_generated": len(wires),
            "labels_generated": len(labels),
            "collisions_avoided": collisions_avoided,
            "wires": wires,
            "labels": labels,
            "notes": notes,
        }

    def _resolve_pins(self, pins: list[dict[str, str]]) -> list[dict]:
        """Resolve pin positions for all requested pins.

        Args:
            pins: List of {"ref": str, "pin": str} dicts.

        Returns:
            List of dicts with ref, pin, position, body_position, pin_name.
            Pins that cannot be resolved are skipped.
        """
        resolved: list[dict] = []

        for pin_spec in pins:
            ref = pin_spec["ref"]
            pin_id = pin_spec["pin"]

            comp = self._resolver.resolve(ref)
            if comp is None:
                continue

            comp_pins = comp.get("pins", {})
            pin_info = comp_pins.get(pin_id)

            # If pin not found by number, try looking by name
            if pin_info is None:
                for pnum, pdata in comp_pins.items():
                    if pdata.get("pin_name") == pin_id:
                        pin_info = pdata
                        break

            if pin_info is None:
                continue

            resolved.append({
                "ref": ref,
                "pin": pin_id,
                "position": pin_info["position"],
                "body_position": pin_info["body_position"],
                "pin_name": pin_info.get("pin_name", ""),
            })

        return resolved

    def _generate_wires(
        self,
        resolved_pins: list[dict],
        collision_zones: list[dict[str, Any]],
        max_wire_length: float,
        strategy: str,
    ) -> tuple[list[dict], int]:
        """Generate wires between resolved pins.

        Args:
            resolved_pins: List of resolved pin dicts.
            collision_zones: Collision zones to avoid.
            max_wire_length: Maximum wire length in mm.
            strategy: Routing strategy.

        Returns:
            Tuple of (wires list, collisions_avoided count).
        """
        wires: list[dict] = []
        collisions_avoided = 0
        connected_by_wire: set[int] = set()

        # For wire_first: try to connect all pins with a spanning set of wires.
        # For hybrid: try to connect nearby pins with short wires.
        # In both cases, generate L-shaped or direct wires between pin pairs.

        # Iterate over all pairs of pins
        for i in range(len(resolved_pins)):
            for j in range(i + 1, len(resolved_pins)):
                pin_a = resolved_pins[i]
                pin_b = resolved_pins[j]

                # Use wire endpoint positions (where wires actually connect)
                ax, ay = pin_a["position"]
                bx, by = pin_b["position"]

                # Calculate wire distance
                dx = abs(bx - ax)
                dy = abs(by - ay)
                distance = math.sqrt(dx * dx + dy * dy)

                # Skip if too far
                if distance > max_wire_length:
                    continue

                # Determine wire path
                same_x = math.isclose(ax, bx, abs_tol=0.1)
                same_y = math.isclose(ay, by, abs_tol=0.1)

                if same_x or same_y:
                    # Direct wire (horizontal or vertical)
                    wire_segments = [(ax, ay, bx, by)]
                else:
                    # L-shaped wire: horizontal then vertical
                    # Snap midpoint to grid to avoid off-grid vertices
                    mid_x = self._snap_coord(bx)
                    mid_y = self._snap_coord(ay)
                    wire_segments = [
                        (ax, ay, mid_x, mid_y),
                        (mid_x, mid_y, bx, by),
                    ]

                # Check each segment for collision zones
                any_collision = False
                for seg in wire_segments:
                    sx, sy, ex, ey = seg
                    if self._wire_through_collision_zone(
                        sx, sy, ex, ey, collision_zones
                    ):
                        any_collision = True
                        collisions_avoided += 1
                        break

                if any_collision:
                    continue

                # Generate wire S-expressions
                for seg in wire_segments:
                    sx, sy, ex, ey = seg
                    wire_sexpr = (
                        f'  (wire (pts (xy {sx:g} {sy:g}) (xy {ex:g} {ey:g})))\n'
                    )
                    wires.append({
                        "start": (sx, sy),
                        "end": (ex, ey),
                        "sexpr": wire_sexpr,
                    })

                connected_by_wire.add(i)
                connected_by_wire.add(j)

                # For wire_first with 2 pins, one wire is enough
                if strategy == "wire_first" and len(resolved_pins) == 2:
                    break

            if strategy == "wire_first" and len(resolved_pins) == 2 and wires:
                break

        return wires, collisions_avoided

    def _wire_through_collision_zone(
        self,
        sx: float,
        sy: float,
        ex: float,
        ey: float,
        zones: list[dict[str, Any]],
    ) -> bool:
        """Check if a wire segment passes through any collision zone.

        Args:
            sx, sy: Start point of wire segment.
            ex, ey: End point of wire segment.
            zones: List of collision zone dicts.

        Returns:
            True if wire passes through a collision zone.
        """
        for zone in zones:
            direction = zone.get("direction", "")
            coordinate = zone.get("coordinate", 0)
            tolerance = zone.get("tolerance", 2.54)

            if direction == "vertical":
                # Vertical zone: avoid x-coordinates near 'coordinate'
                # Check if the wire's x-range overlaps the zone
                x_min = min(sx, ex)
                x_max = max(sx, ex)
                if x_min - tolerance <= coordinate <= x_max + tolerance:
                    # Also check if y-range overlaps
                    return True

            elif direction == "horizontal":
                # Horizontal zone: avoid y-coordinates near 'coordinate'
                y_min = min(sy, ey)
                y_max = max(sy, ey)
                if y_min - tolerance <= coordinate <= y_max + tolerance:
                    return True

        return False
