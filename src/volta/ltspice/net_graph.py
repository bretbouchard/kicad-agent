"""Net connectivity derivation from LTspice wire geometry.

LTSPICE-03: Build a networkx graph from wire segments, assign net names
from FLAG positions, and match component pins to nets.

Algorithm:
1. Add wire segment endpoints as graph nodes, wire segments as edges
2. Split wire segments at component pin positions (interior points)
3. Propagate FLAG net names across connected components
4. Compute component pin absolute positions from symbol offsets + rotation
5. Match pins to wire graph nodes to assign net membership
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import networkx as nx
from spicelib.editor.asc_editor import AsyReader

if TYPE_CHECKING:
    from volta.ltspice.types import LTspiceSchematic

ASY_STUBS_DIR: Path = Path(__file__).parent / "asy_stubs"

# Valid rotation values for pin position calculation.
_VALID_ROTATIONS = frozenset(
    {"R0", "R90", "R180", "R270", "M0", "M90", "M180", "M270"}
)


def _rotate_pin(
    pin_ox: int,
    pin_oy: int,
    comp_x: int,
    comp_y: int,
    rotation: str,
) -> tuple[int, int]:
    """Compute absolute pin position from symbol offset + component position + rotation.

    Args:
        pin_ox: Pin X offset from symbol .asy file.
        pin_oy: Pin Y offset from symbol .asy file.
        comp_x: Component X position from .asc file.
        comp_y: Component Y position from .asc file.
        rotation: Rotation string (R0, R90, R180, R270, M0, M90, M180, M270).

    Returns:
        (absolute_x, absolute_y) tuple for the pin position.

    Raises:
        ValueError: If rotation is not a recognized value.
    """
    if rotation not in _VALID_ROTATIONS:
        raise ValueError(
            f"Unknown rotation '{rotation}'; "
            f"expected one of {sorted(_VALID_ROTATIONS)}"
        )

    if rotation == "R0":
        return (comp_x + pin_ox, comp_y + pin_oy)
    elif rotation == "R90":
        return (comp_x - pin_oy, comp_y + pin_ox)
    elif rotation == "R180":
        return (comp_x - pin_ox, comp_y - pin_oy)
    elif rotation == "R270":
        return (comp_x + pin_oy, comp_y - pin_ox)
    elif rotation == "M0":
        return (comp_x - pin_ox, comp_y + pin_oy)
    elif rotation == "M90":
        return (comp_x + pin_oy, comp_y + pin_ox)
    elif rotation == "M180":
        return (comp_x + pin_ox, comp_y - pin_oy)
    else:  # M270
        return (comp_x - pin_oy, comp_y - pin_ox)


def _point_on_segment(
    px: int, py: int, x1: int, y1: int, x2: int, y2: int
) -> bool:
    """Check if point (px, py) lies on the axis-aligned segment (x1,y1)-(x2,y2).

    The point must be strictly in the interior (not at the endpoints)
    for splitting purposes, but this function checks inclusion at any point.
    """
    if x1 == x2:  # vertical segment
        return px == x1 and min(y1, y2) <= py <= max(y1, y2)
    elif y1 == y2:  # horizontal segment
        return py == y1 and min(x1, x2) <= px <= max(x1, x2)
    return False


def _load_symbol_pins(
    symbol_name: str, asy_cache: dict[str, list[tuple[int, int, int]]]
) -> list[tuple[int, int, int]]:
    """Load pin offsets from a bundled .asy stub file.

    Args:
        symbol_name: Symbol name (e.g. "res", "cap", "voltage").
        asy_cache: Cache dict to avoid re-reading .asy files.

    Returns:
        List of (pin_number, offset_x, offset_y) tuples.
    """
    if symbol_name in asy_cache:
        return asy_cache[symbol_name]

    asy_path = ASY_STUBS_DIR / f"{symbol_name}.asy"
    if not asy_path.exists():
        asy_cache[symbol_name] = []
        return []

    reader = AsyReader(str(asy_path))
    pins: list[tuple[int, int, int]] = []
    for pin_text in reader.pins:
        text = pin_text.text
        pin_number = 0
        for part in text.split(";"):
            if part.startswith("PinName="):
                name_val = part.split("=", 1)[1]
                try:
                    pin_number = int(name_val)
                except ValueError:
                    pin_number = 0
                break
        pins.append((pin_number, int(pin_text.coord.X), int(pin_text.coord.Y)))

    asy_cache[symbol_name] = pins
    return pins


@dataclass
class LTspiceNetGraph:
    """Connectivity graph for an LTspice schematic built from wire geometry.

    Nodes are (x, y) coordinate tuples. Edges connect wire endpoints.
    FLAG statements assign net names to coordinate points, which propagate
    across connected components.
    """

    graph: nx.Graph = field(default_factory=nx.Graph)
    _flag_map: dict[tuple[int, int], str] = field(default_factory=dict)
    _net_index: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    _component_pins: dict[str, list[tuple[int, int, int]]] = field(
        default_factory=dict
    )

    @classmethod
    def from_schematic(
        cls,
        schematic: LTspiceSchematic,
    ) -> LTspiceNetGraph:
        """Build a net connectivity graph from an LTspiceSchematic.

        Args:
            schematic: Parsed LTspiceSchematic with components, wires, flags.

        Returns:
            LTspiceNetGraph with full connectivity and net assignments.
        """
        net_graph = cls()

        # Step 1: Compute component pin absolute positions
        asy_cache: dict[str, list[tuple[int, int, int]]] = {}
        all_pin_positions: set[tuple[int, int]] = set()

        for comp in schematic.components:
            symbol_pins = _load_symbol_pins(comp.symbol, asy_cache)
            comp_pins: list[tuple[int, int, int]] = []

            for pin_num, ox, oy in symbol_pins:
                abs_x, abs_y = _rotate_pin(
                    ox, oy, comp.position_x, comp.position_y, comp.rotation
                )
                comp_pins.append((pin_num, abs_x, abs_y))
                all_pin_positions.add((abs_x, abs_y))

            net_graph._component_pins[comp.reference] = comp_pins

        # Step 2: Build wire graph, splitting segments at pin positions
        for wire in schematic.wires:
            x1, y1 = wire.x1, wire.y1
            x2, y2 = wire.x2, wire.y2

            # Find pin positions that lie on this wire segment's interior
            split_points: list[tuple[int, int]] = []
            for (px, py) in all_pin_positions:
                if _point_on_segment(px, py, x1, y1, x2, y2):
                    # Only split at interior points, not at existing endpoints
                    if (px, py) != (x1, y1) and (px, py) != (x2, y2):
                        split_points.append((px, py))

            if split_points:
                # Sort split points along the segment
                if x1 == x2:  # vertical: sort by Y
                    split_points.sort(key=lambda p: p[1])
                else:  # horizontal: sort by X
                    split_points.sort(key=lambda p: p[0])

                # Create sub-segments
                points = [(x1, y1)] + split_points + [(x2, y2)]
                for i in range(len(points) - 1):
                    net_graph.graph.add_edge(points[i], points[i + 1])
            else:
                net_graph.graph.add_edge((x1, y1), (x2, y2))

        # Step 3: Add pin positions as graph nodes (they may not be on any wire)
        for comp_ref, pins in net_graph._component_pins.items():
            for _pin_num, abs_x, abs_y in pins:
                if not net_graph.graph.has_node((abs_x, abs_y)):
                    net_graph.graph.add_node((abs_x, abs_y))

        # Step 4: Map FLAG positions to net names
        for flag in schematic.flags:
            flag_pos = (flag.x, flag.y)
            net_graph._flag_map[flag_pos] = flag.text
            # Ensure flag position is a graph node
            if not net_graph.graph.has_node(flag_pos):
                net_graph.graph.add_node(flag_pos)

        # Step 5: Propagate net names across connected components
        # Build a mapping from any node to its net name via FLAG propagation
        _node_net_map: dict[tuple[int, int], str] = {}
        for flag_pos, net_name in net_graph._flag_map.items():
            if net_graph.graph.has_node(flag_pos):
                component = nx.node_connected_component(
                    net_graph.graph, flag_pos
                )
                for node in component:
                    if node in _node_net_map:
                        # Validation: multiple flags on same component
                        # should agree on net name
                        existing = _node_net_map[node]
                        if existing != net_name:
                            # Keep the first assignment (could raise, but
                            # LTspice would reject this too)
                            pass
                    else:
                        _node_net_map[node] = net_name

        # Step 6: Match component pins to nets
        for comp_ref, pins in net_graph._component_pins.items():
            for pin_num, abs_x, abs_y in pins:
                pin_pos = (abs_x, abs_y)
                if pin_pos in _node_net_map:
                    net_name = _node_net_map[pin_pos]
                    net_graph._net_index.setdefault(net_name, []).append(
                        (comp_ref, pin_num)
                    )

        return net_graph

    def get_net_names(self) -> set[str]:
        """Return all named nets from FLAG assignments.

        Returns:
            Set of net name strings.
        """
        return set(self._net_index.keys())

    def get_pins_on_net(self, net_name: str) -> list[tuple[str, int]]:
        """Return all (reference, pin_number) pairs connected to the named net.

        Args:
            net_name: Net name from a FLAG (e.g. "0" for GND).

        Returns:
            List of (component_reference, pin_number) tuples.
        """
        return list(self._net_index.get(net_name, []))

    def get_connected_component(
        self, point: tuple[int, int]
    ) -> set[tuple[int, int]]:
        """Return all coordinates electrically connected to the given point.

        Args:
            point: (x, y) coordinate to query.

        Returns:
            Set of (x, y) coordinates in the same connected component.
            Empty set if the point is not in the graph.
        """
        if not self.graph.has_node(point):
            return set()
        return nx.node_connected_component(self.graph, point)

    def are_connected(
        self, p1: tuple[int, int], p2: tuple[int, int]
    ) -> bool:
        """Check if two points are electrically connected.

        Args:
            p1: First (x, y) coordinate.
            p2: Second (x, y) coordinate.

        Returns:
            True if both points are in the same connected component.
        """
        if p1 == p2:
            return True
        if not self.graph.has_node(p1) or not self.graph.has_node(p2):
            return False
        return nx.has_path(self.graph, p1, p2)

    def get_net_stats(self) -> dict[str, int]:
        """Return connectivity statistics.

        Returns:
            Dict with total_nets, total_nodes, total_edges, total_pins.
        """
        total_pins = sum(len(pins) for pins in self._net_index.values())
        return {
            "total_nets": len(self._net_index),
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "total_pins": total_pins,
        }
