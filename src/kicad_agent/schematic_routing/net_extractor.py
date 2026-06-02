"""Extract complete net topology from a .kicad_sch file.

Builds on SchematicGraph wire tracing to group connected pins into named nets.
Cross-references with netlist pin_index when available (optional netlist_path).

Algorithm:
  1. Parse schematic via SchematicGraph.from_file(filepath)
  2. If netlist_path provided, call parse_netlist(netlist_path) to get pin_index
  3. Build position-to-pin mapping for all pins
  4. Use union-find to group wire-connected positions into connected components
  5. For each component, resolve net name via labels, then pin_index, then auto-name
  6. Collect all pins belonging to each named net
  7. Return {nets: {net_name: [{ref, pin_number, pin_name, position}, ...]}, stats: {...}}

Usage:
    from kicad_agent.schematic_routing.net_extractor import extract_nets

    result = extract_nets(sch_path="board.kicad_sch")
    # result = {"nets": {"SDA": [{"ref": "U1", ...}], ...}, "stats": {...}}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from kicad_agent.schematic_routing.schematic_graph import (
    Label,
    PinPosition,
    SchematicGraph,
)
from kicad_agent.schematic_routing.schematic_graph import (
    _round_pos,
)


# ---------------------------------------------------------------------------
# Union-find (disjoint set) for wire-connected component grouping
# ---------------------------------------------------------------------------


class _UnionFind:
    """Disjoint set data structure for grouping positions into connected components."""

    def __init__(self) -> None:
        self._parent: dict[tuple[float, float], tuple[float, float]] = {}
        self._rank: dict[tuple[float, float], int] = {}

    def make_set(self, pos: tuple[float, float]) -> None:
        """Create a singleton set for position."""
        if pos not in self._parent:
            self._parent[pos] = pos
            self._rank[pos] = 0

    def find(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Find the root representative of the set containing pos."""
        # Path compression
        if self._parent[pos] != pos:
            self._parent[pos] = self.find(self._parent[pos])
        return self._parent[pos]

    def union(self, a: tuple[float, float], b: tuple[float, float]) -> None:
        """Merge the sets containing positions a and b."""
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        # Union by rank
        if self._rank[root_a] < self._rank[root_b]:
            root_a, root_b = root_b, root_a
        self._parent[root_b] = root_a
        if self._rank[root_a] == self._rank[root_b]:
            self._rank[root_a] += 1


def _point_on_segment(
    point: tuple[float, float],
    seg_start: tuple[float, float],
    seg_end: tuple[float, float],
    tolerance: float = 0.01,
) -> bool:
    """Check if a point lies on a line segment between seg_start and seg_end.

    Uses a tolerance for floating-point imprecision.
    """
    dx = seg_end[0] - seg_start[0]
    dy = seg_end[1] - seg_start[1]

    # Degenerate segment (zero-length wire)
    if abs(dx) < tolerance and abs(dy) < tolerance:
        return (
            abs(point[0] - seg_start[0]) < tolerance
            and abs(point[1] - seg_start[1]) < tolerance
        )

    # Horizontal segment
    if abs(dy) < tolerance:
        if abs(point[1] - seg_start[1]) > tolerance:
            return False
        min_x = min(seg_start[0], seg_end[0]) - tolerance
        max_x = max(seg_start[0], seg_end[0]) + tolerance
        return min_x <= point[0] <= max_x

    # Vertical segment
    if abs(dx) < tolerance:
        if abs(point[0] - seg_start[0]) > tolerance:
            return False
        min_y = min(seg_start[1], seg_end[1]) - tolerance
        max_y = max(seg_start[1], seg_end[1]) + tolerance
        return min_y <= point[1] <= max_y

    # Diagonal segment: use dominant axis for parameter t, then verify
    # perpendicular distance. Using the larger-magnitude axis gives a more
    # stable parameterization and avoids the bias from averaging t_x/t_y
    # when one axis is nearly-zero (nearly axis-aligned diagonal).
    if abs(dx) >= abs(dy):
        t = (point[0] - seg_start[0]) / dx
    else:
        t = (point[1] - seg_start[1]) / dy

    if t < -tolerance or t > 1.0 + tolerance:
        return False

    # Verify collinearity: distance from point to the infinite line
    # through seg_start..seg_end must be within tolerance.
    seg_len_sq = dx * dx + dy * dy
    cross = abs((point[0] - seg_start[0]) * dy - (point[1] - seg_start[1]) * dx)
    perp_dist = cross / (seg_len_sq ** 0.5)
    return perp_dist <= tolerance


# ---------------------------------------------------------------------------
# Shared union-find construction (used by extract_nets and NetPositionIndex)
# ---------------------------------------------------------------------------

def _build_union_find_components(
    graph: SchematicGraph,
) -> tuple[
    _UnionFind,
    set[tuple[float, float]],
    dict[tuple[float, float], list[PinPosition]],
    dict[tuple[float, float], Label],
]:
    """Build union-find components from a SchematicGraph.

    Constructs the union-find over ALL positions (wire endpoints, pins,
    labels, junctions) and unions positions that lie on shared wire
    segments (mid-point connectivity).

    Complexity: O(P*W) for the midpoint scan, where P is the total number
    of positions and W is the number of wire segments. KiCad schematics
    are typically per-sheet with P < 1000 and W < 500, so this is
    acceptable for current use. For future large-sheet support, consider
    a spatial index (grid bucket or R-tree).

    Returns:
        Tuple of (union_find, all_positions, pin_pos_map, label_pos_map).
    """
    uf = _UnionFind()
    all_positions: set[tuple[float, float]] = set()

    # Add wire endpoints
    for wire in graph.wires:
        start = _round_pos(wire.start)
        end = _round_pos(wire.end)
        all_positions.add(start)
        all_positions.add(end)
        uf.make_set(start)
        uf.make_set(end)
        uf.union(start, end)

    # Add pin positions (multiple pins can share the same position)
    pin_pos_map: dict[tuple[float, float], list[PinPosition]] = {}
    for pin in graph.pins:
        key = _round_pos(pin.position)
        pin_pos_map.setdefault(key, []).append(pin)
        all_positions.add(key)
        uf.make_set(key)

    # Add label positions
    label_pos_map: dict[tuple[float, float], Label] = {}
    for label in graph.labels:
        key = _round_pos(label.position)
        label_pos_map[key] = label
        all_positions.add(key)
        uf.make_set(key)

    # Add junction positions
    for junc in graph.junctions:
        junc_key = _round_pos(junc)
        all_positions.add(junc_key)
        uf.make_set(junc_key)

    # Union positions that lie ON a wire segment (mid-point connectivity).
    # In KiCad, a pin at the midpoint of a wire segment is connected to that net.
    for pos in all_positions:
        for wire in graph.wires:
            if _point_on_segment(pos, _round_pos(wire.start), _round_pos(wire.end)):
                uf.union(pos, _round_pos(wire.start))
                uf.union(pos, _round_pos(wire.end))

    return uf, all_positions, pin_pos_map, label_pos_map


def _resolve_net_names(
    components: dict[tuple[float, float], set[tuple[float, float]]],
    label_pos_map: dict[tuple[float, float], Label],
    pin_pos_map: dict[tuple[float, float], list[PinPosition]],
    pin_index: dict[tuple[str, str], str] | None,
) -> tuple[dict[tuple[float, float], str], int]:
    """Resolve net names for connected components.

    Priority: label name > pin_index name > auto-name.

    Returns:
        Tuple of (root_to_net mapping, auto_counter final value).
    """
    root_to_net: dict[tuple[float, float], str] = {}
    auto_counter = 0

    for root, positions in components.items():
        net_name: str | None = None

        # Priority 1: label name
        for pos in positions:
            if pos in label_pos_map:
                net_name = label_pos_map[pos].name
                break

        # Priority 2: pin_index
        if net_name is None and pin_index:
            for pos in positions:
                if pos in pin_pos_map:
                    for pin in pin_pos_map[pos]:
                        key = (pin.ref, pin.pin_number)
                        if key in pin_index:
                            net_name = pin_index[key]
                            break
                if net_name:
                    break

        # Priority 3: auto-name
        if net_name is None:
            auto_counter += 1
            net_name = f"Net_{auto_counter}"

        root_to_net[root] = net_name

    return root_to_net, auto_counter


# ---------------------------------------------------------------------------
# Core extraction logic
# ---------------------------------------------------------------------------


def extract_nets(
    sch_path: Path | str,
    include_positions: bool = True,
    netlist_path: Optional[str] = None,
) -> dict[str, Any]:
    """Extract complete net topology from a schematic file.

    Args:
        sch_path: Path to the .kicad_sch file.
        include_positions: Include pin positions in output (default True).
        netlist_path: Optional path to .net file for net name resolution.

    Returns:
        Dict with "nets" and "stats" keys:
        - nets: {net_name: [{"ref", "pin_number", "pin_name", "position"}, ...]}
        - stats: {"total_nets", "total_pins", "named_nets", "unnamed_nets"}
    """
    graph = SchematicGraph.from_file(sch_path)

    # Build pin_index from netlist if provided
    pin_index: dict[tuple[str, str], str] = {}
    if netlist_path:
        from kicad_agent.schematic_routing.netlist_parser import parse_netlist
        _, pin_index = parse_netlist(netlist_path)

    # Build union-find components via shared pipeline
    uf, all_positions, pin_pos_map, label_pos_map = _build_union_find_components(graph)

    # Build connected components (root -> set of positions)
    components: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for pos in all_positions:
        root = uf.find(pos)
        components.setdefault(root, set()).add(pos)

    # Resolve net names
    root_to_net, _ = _resolve_net_names(
        components, label_pos_map, pin_pos_map, pin_index,
    )

    # Build per-net pin groups
    net_groups: dict[str, list[PinPosition]] = {}
    for root, positions in components.items():
        net_name = root_to_net[root]
        component_pins: list[PinPosition] = []
        for pos in positions:
            if pos in pin_pos_map:
                component_pins.extend(pin_pos_map[pos])
        net_groups.setdefault(net_name, []).extend(component_pins)

    # Build result structure
    nets: dict[str, list[dict[str, Any]]] = {}
    total_pins = 0
    named_nets = 0
    unnamed_nets = 0

    for net_name, pins in net_groups.items():
        # Deduplicate pins by (ref, pin_number) in case of duplicates
        seen: set[tuple[str, str]] = set()
        unique_pins: list[PinPosition] = []
        for pin in pins:
            key = (pin.ref, pin.pin_number)
            if key not in seen:
                seen.add(key)
                unique_pins.append(pin)

        pin_entries: list[dict[str, Any]] = []
        for pin in unique_pins:
            entry: dict[str, Any] = {
                "ref": pin.ref,
                "pin_number": pin.pin_number,
                "pin_name": pin.pin_name,
            }
            if include_positions:
                entry["position"] = list(pin.position)
            pin_entries.append(entry)

        nets[net_name] = pin_entries
        total_pins += len(unique_pins)

        if net_name.startswith("Net_") and net_name[4:].isdigit():
            unnamed_nets += 1
        else:
            named_nets += 1

    return {
        "nets": nets,
        "stats": {
            "total_nets": len(nets),
            "total_pins": total_pins,
            "named_nets": named_nets,
            "unnamed_nets": unnamed_nets,
        },
    }


# ---------------------------------------------------------------------------
# NetPositionIndex — maps any schematic position to its net name
# ---------------------------------------------------------------------------


class NetPositionIndex:
    """Maps any schematic position to its net name and connected component.

    Built from SchematicGraph + union-find over ALL positions (wire endpoints,
    pins, labels, junctions). Provides stable component-root identity for
    comparison even when net names are auto-generated.

    Used by repair operations (Phases 66-70) for connectivity-aware decisions.
    """

    def __init__(
        self,
        graph: SchematicGraph,
        pin_index: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._pos_to_root: dict[tuple[float, float], tuple[float, float]] = {}
        self._root_to_net: dict[tuple[float, float], str] = {}
        self._root_to_positions: dict[tuple[float, float], set[tuple[float, float]]] = {}
        self._net_to_positions: dict[str, set[tuple[float, float]]] = {}

        self._build(graph, pin_index)

    def _build(self, graph: SchematicGraph, pin_index: dict | None) -> None:
        # Use shared union-find pipeline (same as extract_nets)
        uf, all_positions, pin_pos_map, label_pos_map = _build_union_find_components(graph)

        # Build connected components
        components: dict[tuple[float, float], set[tuple[float, float]]] = {}
        for pos in all_positions:
            root = uf.find(pos)
            components.setdefault(root, set()).add(pos)

        # Resolve net names via shared resolver
        root_to_net, _ = _resolve_net_names(
            components, label_pos_map, pin_pos_map, pin_index,
        )

        # Store mappings
        for root, net_name in root_to_net.items():
            positions = components[root]
            self._root_to_net[root] = net_name
            self._root_to_positions[root] = positions
            self._net_to_positions.setdefault(net_name, set()).update(positions)
            for pos in positions:
                self._pos_to_root[pos] = root

    def get_net_at(self, pos: tuple[float, float]) -> str | None:
        """Return the net name at *pos*, or None if not connected."""
        root = self._pos_to_root.get(_round_pos(pos))
        if root is None:
            return None
        return self._root_to_net.get(root)

    def get_component_root(self, pos: tuple[float, float]) -> tuple[float, float] | None:
        """Return the union-find root for stable component identity."""
        return self._pos_to_root.get(_round_pos(pos))

    def get_positions_for_net(self, net_name: str) -> set[tuple[float, float]]:
        """Return all positions belonging to *net_name*."""
        return self._net_to_positions.get(net_name, set())

    @staticmethod
    def is_auto_named(net_name: str) -> bool:
        """Check if *net_name* is an auto-generated name (Net_N)."""
        return net_name.startswith("Net_") and net_name[4:].isdigit()

    @classmethod
    def from_file(
        cls,
        sch_path: Path | str,
        netlist_path: str | None = None,
    ) -> NetPositionIndex:
        """Build a NetPositionIndex from a schematic file."""
        graph = SchematicGraph.from_file(sch_path)

        pin_index: dict[tuple[str, str], str] = {}
        if netlist_path:
            from kicad_agent.schematic_routing.netlist_parser import parse_netlist
            _, pin_index = parse_netlist(netlist_path)

        return cls(graph, pin_index)
