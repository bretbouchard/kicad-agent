"""Signal flow grouping for layout-aware placement.

Converts Subcircuit[] to SignalFlowGroup[] with input/output ordering
and contiguous zone assignment. Components in signal-flow order are
placed in contiguous board zones left-to-right.

Usage::

    from volta.placement.signal_flow import SignalFlowGrouper

    grouper = SignalFlowGrouper()
    groups = grouper.group(subcircuits, intents=intents)
    for group in groups:
        for zone in group.ordered_zones:
            print(f"Zone {zone.zone_id}: {zone.zone_type} "
                  f"({len(zone.component_refs)} components)")
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from volta.analysis.intent_schemas import SubcircuitIntent
    from volta.analysis.subcircuit_detector import Subcircuit, SubcircuitType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPE_PRIORITY: dict[str, int] = {
    "PREAMP": 10,
    "COMPRESSOR": 10,
    "EQ": 10,
    "FILTER": 10,
    "VCA": 10,
    "ENVELOPE": 10,
    "LFO": 10,
    "MIXER": 10,
    "OSCILLATOR": 10,
    "DIGITAL_CONTROL": 10,
    "ANALOG_SWITCH": 10,
    "PROTECTION": 10,
    "OUTPUT_STAGE": 20,
    "POWER_SUPPLY": 30,
    "UNKNOWN": 40,
}
"""Priority ordering for subcircuit types. Lower = placed earlier (left)."""

# Map SubcircuitType to zone_type string
_TYPE_TO_ZONE: dict[str, str] = {
    "PREAMP": "processing",
    "COMPRESSOR": "processing",
    "EQ": "processing",
    "FILTER": "processing",
    "VCA": "processing",
    "ENVELOPE": "processing",
    "LFO": "processing",
    "MIXER": "processing",
    "OSCILLATOR": "processing",
    "DIGITAL_CONTROL": "processing",
    "ANALOG_SWITCH": "processing",
    "PROTECTION": "processing",
    "OUTPUT_STAGE": "output",
    "POWER_SUPPLY": "power",
    "UNKNOWN": "ungrouped",
}
"""Map SubcircuitType enum values to zone_type string."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalFlowZone:
    """A contiguous zone for a group of components on the board.

    Attributes:
        zone_id: Unique identifier (e.g., "SC-001").
        component_refs: Component references in this zone.
        nets: Nets within this zone.
        zone_type: Functional classification of the zone.
        priority: Ordering priority (lower = placed earlier/left).
    """

    zone_id: str
    component_refs: tuple[str, ...]
    nets: tuple[str, ...]
    zone_type: str  # "input" | "processing" | "output" | "power" | "ungrouped"
    priority: int


@dataclass(frozen=True)
class SignalFlowGroup:
    """A group of zones forming a signal flow chain.

    Attributes:
        group_id: Unique group identifier.
        ordered_zones: Zones in signal-flow order (left-to-right).
        signal_entry_nets: Input nets entering the group from outside.
        signal_exit_nets: Output nets leaving the group to outside.
    """

    group_id: str
    ordered_zones: tuple[SignalFlowZone, ...]
    signal_entry_nets: tuple[str, ...]
    signal_exit_nets: tuple[str, ...]


# ---------------------------------------------------------------------------
# SignalFlowGrouper
# ---------------------------------------------------------------------------


class SignalFlowGrouper:
    """Groups subcircuits into signal-flow ordered zones for layout-aware placement.

    Algorithm:
    1. Build adjacency graph from shared boundary_nets
    2. Find connected components via BFS -- each component is a SignalFlowGroup
    3. Within each group, order zones by signal flow (entry -> exit)
    4. Fall back to type priority ordering when signal flow is ambiguous
    """

    def group(
        self,
        subcircuits: list[Subcircuit],
        intents: list[SubcircuitIntent] | None = None,
    ) -> list[SignalFlowGroup]:
        """Group subcircuits into signal-flow ordered zones.

        Args:
            subcircuits: Detected subcircuits from SubcircuitDetector.
            intents: Optional inferred intents with input/output net info.

        Returns:
            List of SignalFlowGroup, sorted by first zone priority.
        """
        if not subcircuits:
            return []

        # Build intent lookup: subcircuit_id -> SubcircuitIntent
        intent_map: dict[str, SubcircuitIntent] = {}
        if intents:
            for intent in intents:
                for ref in intent.component_refs:
                    # Match intent to subcircuit by component overlap
                    for sc in subcircuits:
                        if ref in sc.components:
                            intent_map[sc.subcircuit_id] = intent
                            break

        # Step 1: Build adjacency from shared boundary_nets
        adjacency = self._build_adjacency(subcircuits)

        # Step 2: Find connected components via BFS
        components = self._find_connected_components(subcircuits, adjacency)

        # Step 3: Build groups with ordered zones
        groups: list[SignalFlowGroup] = []
        for comp_idx, comp_sc_indices in enumerate(components):
            group_scs = [subcircuits[i] for i in comp_sc_indices]
            group = self._build_group(
                f"GRP-{comp_idx + 1:03d}",
                group_scs,
                intent_map,
            )
            groups.append(group)

        # Sort groups by first zone priority
        groups.sort(key=lambda g: g.ordered_zones[0].priority if g.ordered_zones else 99)

        return groups

    def _build_adjacency(
        self, subcircuits: list[Subcircuit]
    ) -> dict[int, set[int]]:
        """Build adjacency: subcircuits sharing boundary_nets are adjacent.

        Returns:
            Dict mapping index -> set of adjacent indices.
        """
        # net -> list of subcircuit indices that share it as boundary
        net_to_indices: dict[str, list[int]] = {}
        for idx, sc in enumerate(subcircuits):
            for net in sc.boundary_nets:
                net_to_indices.setdefault(net, []).append(idx)

        adjacency: dict[int, set[int]] = {i: set() for i in range(len(subcircuits))}
        for _net, indices in net_to_indices.items():
            for i in indices:
                for j in indices:
                    if i != j:
                        adjacency[i].add(j)
                        adjacency[j].add(i)

        return adjacency

    def _find_connected_components(
        self,
        subcircuits: list[Subcircuit],
        adjacency: dict[int, set[int]],
    ) -> list[list[int]]:
        """Find connected components via BFS on adjacency graph.

        Returns:
            List of components, each a list of subcircuit indices.
        """
        visited: set[int] = set()
        components: list[list[int]] = []

        for start in range(len(subcircuits)):
            if start in visited:
                continue
            component: list[int] = []
            queue: deque[int] = deque([start])
            visited.add(start)
            while queue:
                node = queue.popleft()
                component.append(node)
                for neighbor in adjacency.get(node, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(component)

        return components

    def _build_group(
        self,
        group_id: str,
        subcircuits: list[Subcircuit],
        intent_map: dict[str, SubcircuitIntent],
    ) -> SignalFlowGroup:
        """Build a SignalFlowGroup from a connected component of subcircuits.

        Orders zones by signal flow when possible, falls back to type priority.
        """
        # Build zones from subcircuits
        zones: list[SignalFlowZone] = []
        for sc in subcircuits:
            sc_type_value = sc.subcircuit_type.value
            zone_type = _TYPE_TO_ZONE.get(sc_type_value, "ungrouped")
            priority = _TYPE_PRIORITY.get(sc_type_value, 40)
            zones.append(SignalFlowZone(
                zone_id=sc.subcircuit_id,
                component_refs=tuple(sorted(sc.components)),
                nets=sc.nets,
                zone_type=zone_type,
                priority=priority,
            ))

        # Try signal flow ordering
        ordered = self._order_by_signal_flow(zones, subcircuits, intent_map)

        # Identify entry and exit nets
        entry_nets, exit_nets = self._find_entry_exit_nets(
            ordered, subcircuits, intent_map,
        )

        return SignalFlowGroup(
            group_id=group_id,
            ordered_zones=tuple(ordered),
            signal_entry_nets=tuple(sorted(entry_nets)),
            signal_exit_nets=tuple(sorted(exit_nets)),
        )

    def _order_by_signal_flow(
        self,
        zones: list[SignalFlowZone],
        subcircuits: list[Subcircuit],
        intent_map: dict[str, SubcircuitIntent],
    ) -> list[SignalFlowZone]:
        """Order zones by signal flow: entry -> ... -> exit.

        Entry zones have input_nets that are NOT boundary_nets of any other
        subcircuit in the group. Follow boundary_net chain for ordering.
        Fall back to type priority if ambiguous.
        """
        if len(zones) <= 1:
            return zones

        # Build zone_id -> zone lookup
        zone_map = {z.zone_id: z for z in zones}

        # Build sc_id -> intent lookup for I/O net info
        sc_ids = {sc.subcircuit_id for sc in subcircuits}

        # Collect all boundary nets within this group
        group_boundary_nets: set[str] = set()
        for sc in subcircuits:
            group_boundary_nets.update(sc.boundary_nets)

        # Find entry zones: those with input_nets not in any other subcircuit's boundary_nets
        entry_zones: list[str] = []
        for sc in subcircuits:
            intent = intent_map.get(sc.subcircuit_id)
            if intent and intent.input_nets:
                # Check if any input_net is NOT a boundary net of another sc in group
                non_boundary_inputs = [
                    n for n in intent.input_nets
                    if n not in group_boundary_nets
                ]
                if non_boundary_inputs:
                    entry_zones.append(sc.subcircuit_id)

        # If no clear entry zones found, fall back to type priority
        if not entry_zones:
            return sorted(zones, key=lambda z: z.priority)

        # BFS from entry zones following boundary_net adjacency
        # Build adjacency: zone_id -> [zone_id] based on shared boundary_nets
        sc_id_to_idx = {sc.subcircuit_id: i for i, sc in enumerate(subcircuits)}
        zone_adjacency: dict[str, list[str]] = {z.zone_id: [] for z in zones}

        # Reuse the boundary net adjacency
        for i, sc_a in enumerate(subcircuits):
            for j, sc_b in enumerate(subcircuits):
                if i >= j:
                    continue
                shared = set(sc_a.boundary_nets) & set(sc_b.boundary_nets)
                if shared:
                    zone_adjacency[sc_a.subcircuit_id].append(sc_b.subcircuit_id)
                    zone_adjacency[sc_b.subcircuit_id].append(sc_a.subcircuit_id)

        # BFS from first entry zone to determine ordering
        ordered_ids: list[str] = []
        visited: set[str] = set()
        queue: deque[str] = deque(entry_zones[:1])  # Start from first entry
        visited.add(entry_zones[0])

        while queue:
            current = queue.popleft()
            ordered_ids.append(current)
            for neighbor in zone_adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        # Add any unvisited zones (disconnected within group -- shouldn't happen
        # but be safe)
        for z in zones:
            if z.zone_id not in visited:
                ordered_ids.append(z.zone_id)

        return [zone_map[zid] for zid in ordered_ids]

    def _find_entry_exit_nets(
        self,
        ordered_zones: list[SignalFlowZone],
        subcircuits: list[Subcircuit],
        intent_map: dict[str, SubcircuitIntent],
    ) -> tuple[list[str], list[str]]:
        """Identify signal entry and exit nets for a group.

        Entry nets: input_nets of the first zone that are not boundary_nets.
        Exit nets: output_nets of the last zone that are not boundary_nets.
        """
        if not ordered_zones:
            return [], []

        sc_map = {sc.subcircuit_id: sc for sc in subcircuits}

        # Entry nets from first zone
        entry_nets: list[str] = []
        first_sc = sc_map.get(ordered_zones[0].zone_id)
        first_intent = intent_map.get(ordered_zones[0].zone_id) if first_sc else None
        if first_intent and first_intent.input_nets:
            first_boundary = set(first_sc.boundary_nets) if first_sc else set()
            entry_nets = [n for n in first_intent.input_nets if n not in first_boundary]

        # Exit nets from last zone
        exit_nets: list[str] = []
        last_sc = sc_map.get(ordered_zones[-1].zone_id)
        last_intent = intent_map.get(ordered_zones[-1].zone_id) if last_sc else None
        if last_intent and last_intent.output_nets:
            last_boundary = set(last_sc.boundary_nets) if last_sc else set()
            exit_nets = [n for n in last_intent.output_nets if n not in last_boundary]

        return entry_nets, exit_nets
