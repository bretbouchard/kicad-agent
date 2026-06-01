"""Circuit topology graph with signal flow direction inference.

Builds a directed networkx graph from SchematicGraph or SchematicIR where:
- Nodes are components (TopologyNode)
- Edges are signal-carrying nets (TopologyEdge) with flow direction
- Signal flow is inferred from IC pin types and passive behavior

DOMAIN-01: Foundation for all domain intelligence.

Usage:
    from kicad_agent.analysis.topology_graph import TopologyBuilder
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph

    graph = SchematicGraph.from_file("compressor.kicad_sch")
    builder = TopologyBuilder()
    topology = builder.from_schematic_graph(graph)
    for edge in topology.edges:
        print(f"{edge.source_ref}.{edge.source_pin} --[{edge.net_name}]--> {edge.target_ref}.{edge.target_pin}")
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from kicad_agent.analysis.types import NetClassification, PinRole
from kicad_agent.schematic_routing.schematic_graph import (
    SchematicGraph,
    PinPosition,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frozen result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopologyNode:
    """A component in the circuit topology."""

    ref: str
    lib_id: str
    component_type: str  # "ic", "resistor", "capacitor", "inductor", "diode", "transistor", "connector", "misc"
    pin_count: int
    power_pins: tuple[str, ...]
    input_pins: tuple[str, ...]
    output_pins: tuple[str, ...]


@dataclass(frozen=True)
class TopologyEdge:
    """A directed signal connection between two components."""

    net_name: str
    source_ref: str
    source_pin: str
    target_ref: str
    target_pin: str
    classification: NetClassification
    signal_direction: str  # "forward", "feedback", "bidirectional", "power", "unknown"


@dataclass(frozen=True)
class NetStats:
    """Statistics for a single net in the topology."""

    net_name: str
    fanout: int                      # Number of receiving components
    is_stub: bool                    # Dead-end branch (leads to test point, LED, etc.)
    is_multi_drop: bool              # 1 source, 2+ receivers on different ICs
    longest_path_from_input: int     # Hops from nearest input net
    component_count: int             # Total components on this net
    classification: NetClassification
    importance: str                  # From NetImportance enum value
    signal_integrity: str            # From SignalIntegrity enum value


@dataclass(frozen=True)
class CircuitTopology:
    """Complete circuit topology with signal flow."""

    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]
    input_nets: tuple[str, ...]
    output_nets: tuple[str, ...]
    power_nets: tuple[str, ...]
    signal_paths: tuple[tuple[str, ...], ...]  # Each path is ordered refs
    stats: dict  # component_count, net_count, signal_path_count, etc.


# ---------------------------------------------------------------------------
# Component type mapping from lib_id prefix
# ---------------------------------------------------------------------------

# Ordered list -- longer/more-specific prefixes MUST come before shorter ones.
# E.g. "Device:LED" before "Device:L" so "Device:LED" doesn't match inductor.
_LIBID_TYPE_MAP: list[tuple[str, str]] = [
    ("Device:R", "resistor"),
    ("Device:Crystal", "misc"),
    ("Device:C", "capacitor"),
    ("Device:LED", "diode"),
    ("Device:L", "inductor"),
    ("Device:D", "diode"),
    ("Device:Q", "transistor"),
    ("Device:J", "connector"),
    ("Connector:", "connector"),
]


def _classify_component_type(lib_id: str) -> str:
    """Map lib_id to component type."""
    for prefix, ctype in _LIBID_TYPE_MAP:
        if lib_id.startswith(prefix) or lib_id == prefix.rstrip(":"):
            return ctype
    # If it has a colon and isn't Device/Connector, assume IC
    if ":" in lib_id and not lib_id.startswith("Device"):
        return "ic"
    # Known IC part numbers without prefix
    ic_patterns = [
        "NE5532", "TL072", "LM358", "LM324", "CD4066", "CD4060",
        "THAT4301", "THAT2181", "RP2040", "ATmega", "STM32",
        "LM7805", "LM317", "LM7812", "7912", "555", "5532",
        "OP07", "OP27", "AD712", "OPA2134",
    ]
    for pattern in ic_patterns:
        if pattern.lower() in lib_id.lower():
            return "ic"
    return "misc"


# ---------------------------------------------------------------------------
# IC pin role classification rules
# ---------------------------------------------------------------------------

# Each rule: (lib_id_pattern, {pin_name: PinRole})
_IC_PIN_RULES: list[tuple[str, dict[str, PinRole]]] = [
    # Op-amps
    ("NE5532", {
        "IN+": PinRole.INPUT, "IN-": PinRole.INPUT,
        "OUT": PinRole.OUTPUT,
        "V+": PinRole.POWER, "V-": PinRole.POWER,
    }),
    ("TL072", {
        "IN+": PinRole.INPUT, "IN-": PinRole.INPUT,
        "OUT": PinRole.OUTPUT,
        "V+": PinRole.POWER, "V-": PinRole.POWER,
    }),
    ("LM358", {
        "IN+": PinRole.INPUT, "IN-": PinRole.INPUT,
        "OUT": PinRole.OUTPUT,
        "V+": PinRole.POWER, "GND": PinRole.POWER,
    }),
    ("LM324", {
        "IN+": PinRole.INPUT, "IN-": PinRole.INPUT,
        "OUT": PinRole.OUTPUT,
        "V+": PinRole.POWER, "GND": PinRole.POWER,
    }),
    # VCAs
    ("THAT4301", {
        "INPUT": PinRole.INPUT, "OUTPUT": PinRole.OUTPUT,
        "EC+": PinRole.INPUT, "EC-": PinRole.INPUT,
        "V+": PinRole.POWER, "V-": PinRole.POWER,
        "CASE": PinRole.POWER,
    }),
    ("THAT2181", {
        "INPUT": PinRole.INPUT, "OUTPUT": PinRole.OUTPUT,
        "EC": PinRole.INPUT,
        "V+": PinRole.POWER, "V-": PinRole.POWER,
    }),
    # Analog switches
    ("CD4066", {
        "VDD": PinRole.POWER, "VSS": PinRole.POWER,
    }),
    # Oscillators/dividers
    ("CD4060", {
        "Q3": PinRole.OUTPUT, "Q4": PinRole.OUTPUT, "Q5": PinRole.OUTPUT,
        "Q6": PinRole.OUTPUT, "Q7": PinRole.OUTPUT, "Q8": PinRole.OUTPUT,
        "Q9": PinRole.OUTPUT, "Q10": PinRole.OUTPUT, "Q11": PinRole.OUTPUT,
        "Q12": PinRole.OUTPUT, "Q13": PinRole.OUTPUT,
        "RESET": PinRole.CONTROL,
        "VDD": PinRole.POWER, "VSS": PinRole.POWER,
    }),
    # Voltage regulators
    ("LM7805", {"IN": PinRole.INPUT, "OUT": PinRole.OUTPUT, "GND": PinRole.POWER}),
    ("LM7812", {"IN": PinRole.INPUT, "OUT": PinRole.OUTPUT, "GND": PinRole.POWER}),
    ("LM317", {"IN": PinRole.INPUT, "OUT": PinRole.OUTPUT, "ADJ": PinRole.CONTROL}),
    ("7912", {"IN": PinRole.INPUT, "OUT": PinRole.OUTPUT, "GND": PinRole.POWER}),
]

# Fallback patterns for unknown ICs or unmapped pins
_POWER_PIN_PATTERNS = ["VCC", "VDD", "V+", "V-", "VSS", "GND", "GNDA", "VEE", "VAA"]
_INPUT_PIN_PATTERNS = ["IN", "INPUT", "IN+", "IN-", "A", "B", "D"]
_OUTPUT_PIN_PATTERNS = ["OUT", "OUTPUT", "Q", "Y"]
_CONTROL_PIN_PATTERNS = ["EN", "CS", "RST", "RESET", "WR", "RD", "SEL", "CLK", "C", "CTRL", "SET"]

# Safety limit for signal path tracing
_MAX_PATHS = 100

# Position tolerance for net resolution (mm)
_POSITION_TOLERANCE = 1.27


# ---------------------------------------------------------------------------
# TopologyBuilder
# ---------------------------------------------------------------------------


class TopologyBuilder:
    """Builds a circuit topology graph from SchematicGraph or SchematicIR.

    Signal flow is inferred from IC pin types:
    - IC output pins drive nets (edge direction: IC -> downstream)
    - IC input pins receive from nets (edge direction: upstream -> IC)
    - Passive components (R, C, L) are bidirectional
    - Power pins are sources (excluded from signal flow)
    """

    def from_schematic_graph(self, graph: SchematicGraph) -> CircuitTopology:
        """Build topology from a SchematicGraph.

        Algorithm:
        1. Group pins by ref -> build TopologyNode for each component
        2. Classify pin roles (input/output/power/bidirectional)
        3. Build net membership: for each pin, find its net via position matching
        4. For each net with 2+ component pins: create directed edges
        5. Detect feedback: net connects output-stage back to input-stage
        6. Trace signal paths from input_nets to output_nets via BFS
        """
        if len(graph.pins) == 0:
            return CircuitTopology(
                nodes=(),
                edges=(),
                input_nets=(),
                output_nets=(),
                power_nets=(),
                signal_paths=(),
                stats={"component_count": 0, "net_count": 0, "signal_path_count": 0, "feedback_count": 0, "net_stats": {}},
            )

        # 1. Build nodes with pin role classification
        nodes = self._build_nodes(graph)
        nodes_by_ref = {n.ref: n for n in nodes}

        # 1.5 Resolve pin nets (needed by edge building and path tracing)
        pin_nets = self._resolve_pin_nets(graph)

        # 2. Build edges with net resolution and direction
        edges = self._build_edges(graph, nodes_by_ref, pin_nets)

        # 3. Classify nets
        net_names = {e.net_name for e in edges}

        # 4. Identify input/output/power nets
        input_nets = self._identify_input_nets(graph, edges)
        output_nets = self._identify_output_nets(graph, edges)
        power_nets = tuple(
            name for name in net_names
            if any(e.classification == NetClassification.POWER for e in edges if e.net_name == name)
        )

        # 5. Detect feedback and reclassify edges
        feedback_nets = self._detect_feedback(edges, nodes_by_ref)
        updated_edges = []
        for edge in edges:
            if edge.net_name in feedback_nets and edge.classification != NetClassification.POWER:
                updated_edges.append(TopologyEdge(
                    net_name=edge.net_name,
                    source_ref=edge.source_ref,
                    source_pin=edge.source_pin,
                    target_ref=edge.target_ref,
                    target_pin=edge.target_pin,
                    classification=NetClassification.FEEDBACK,
                    signal_direction="feedback",
                ))
            else:
                updated_edges.append(edge)
        edges = updated_edges

        # 6. Trace signal paths
        signal_paths = self._trace_signal_paths(edges, list(input_nets), list(output_nets), pin_nets)

        # 7. Compute stats
        from dataclasses import asdict

        net_stats = self._compute_net_stats(edges, list(input_nets), nodes_by_ref)
        stats = {
            "component_count": len(nodes),
            "net_count": len(net_names),
            "signal_path_count": len(signal_paths),
            "feedback_count": len(feedback_nets),
            "net_stats": {name: asdict(stat) for name, stat in net_stats.items()},
        }

        if len(nodes) > 500:
            logger.warning("Large schematic topology: %d components", len(nodes))

        return CircuitTopology(
            nodes=tuple(nodes),
            edges=tuple(edges),
            input_nets=tuple(input_nets),
            output_nets=tuple(output_nets),
            power_nets=tuple(power_nets),
            signal_paths=tuple(tuple(p) for p in signal_paths),
            stats=stats,
        )

    # -------------------------------------------------------------------
    # Net stats computation
    # -------------------------------------------------------------------

    def _compute_net_stats(
        self,
        edges: list[TopologyEdge],
        input_nets: list[str],
        nodes: dict[str, TopologyNode],
    ) -> dict[str, NetStats]:
        """Compute per-net statistics.

        Algorithm:
        1. Group edges by net_name
        2. For each net:
           a. fanout = count of unique target refs
           b. is_stub = net connects to exactly one component that is a dead-end
           c. is_multi_drop = fanout >= 2 and receivers are on different ICs
           d. longest_path_from_input = BFS depth from input nets
           e. component_count = unique refs on this net
        """
        from dataclasses import asdict
        from kicad_agent.analysis.net_classifier import NetClassifier, SignalIntegrity

        classifier = NetClassifier()

        # Group edges by net name
        net_edges: dict[str, list[TopologyEdge]] = {}
        for edge in edges:
            net_edges.setdefault(edge.net_name, []).append(edge)

        # Build adjacency for BFS depth from input nets
        forward: dict[str, list[tuple[str, str]]] = {}
        for edge in edges:
            if edge.classification == NetClassification.POWER:
                continue
            forward.setdefault(edge.source_ref, []).append((edge.target_ref, edge.net_name))

        # BFS from input-net-connected components to compute depth
        depth: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque()
        input_refs: set[str] = set()
        for edge in edges:
            if edge.net_name in input_nets:
                input_refs.add(edge.source_ref)
                input_refs.add(edge.target_ref)
        for ref in input_refs:
            if ref not in depth:
                depth[ref] = 0
                queue.append((ref, 0))
        while queue:
            ref, d = queue.popleft()
            for target, _net in forward.get(ref, []):
                if target not in depth:
                    depth[target] = d + 1
                    queue.append((target, d + 1))

        result: dict[str, NetStats] = {}
        for net_name, net_edge_list in net_edges.items():
            # Unique refs on this net
            all_refs: set[str] = set()
            source_refs: set[str] = set()
            target_refs: set[str] = set()
            classification = NetClassification.UNKNOWN
            for edge in net_edge_list:
                all_refs.add(edge.source_ref)
                all_refs.add(edge.target_ref)
                if edge.signal_direction not in ("bidirectional",):
                    source_refs.add(edge.source_ref)
                    target_refs.add(edge.target_ref)
                else:
                    target_refs.add(edge.source_ref)
                    target_refs.add(edge.target_ref)
                classification = edge.classification

            # Fanout: unique target components (receivers)
            receivers = target_refs - source_refs
            fanout = len(receivers) if receivers else len(target_refs)

            # Component count
            component_count = len(all_refs)

            # is_multi_drop: fanout >= 2 and receivers on different ICs
            receiver_ic_count = sum(
                1 for ref in receivers
                if nodes.get(ref, None) and nodes[ref].component_type == "ic"
            )
            is_multi_drop = fanout >= 2 and receiver_ic_count >= 2

            # is_stub: net leads to exactly one dead-end component
            # Dead-end: diode (LED), connector, or component not in forward adjacency
            dead_end_types = {"diode", "connector", "misc"}
            dead_end_refs = {
                ref for ref in all_refs
                if nodes.get(ref) and (
                    nodes[ref].component_type in dead_end_types
                    or ref not in forward
                )
            }
            # Stub: at least one dead-end component, and all dead-ends have no outgoing edges
            is_stub = len(dead_end_refs) >= 1 and len(dead_end_refs) < len(all_refs)

            # Longest path from input: max BFS depth of any component on this net
            if depth:
                net_depths = [depth.get(ref, 0) for ref in all_refs if ref in depth]
                longest_path = max(net_depths) if net_depths else 0
            else:
                longest_path = 0

            # Signal integrity and importance
            importance = classifier.rank_importance(classification)
            signal_integrity = classifier.classify_signal_integrity(net_name)

            result[net_name] = NetStats(
                net_name=net_name,
                fanout=fanout,
                is_stub=is_stub,
                is_multi_drop=is_multi_drop,
                longest_path_from_input=longest_path,
                component_count=component_count,
                classification=classification,
                importance=importance.value,
                signal_integrity=signal_integrity.value,
            )

        return result

    # -------------------------------------------------------------------
    # Pin grouping and role classification
    # -------------------------------------------------------------------

    def _group_pins_by_ref(self, pins: list[PinPosition]) -> dict[str, list[PinPosition]]:
        """Group pins by component reference."""
        groups: dict[str, list[PinPosition]] = {}
        for pin in pins:
            groups.setdefault(pin.ref, []).append(pin)
        return groups

    def _classify_pin_role(self, ref: str, pin: PinPosition, lib_id: str) -> PinRole:
        """Classify a pin's role based on component type and pin name/number."""
        # 1. Check if component is passive -> BIDIRECTIONAL
        comp_type = _classify_component_type(lib_id)
        if comp_type in ("resistor", "capacitor", "inductor"):
            return PinRole.BIDIRECTIONAL

        # 2. Look up IC-specific pin rules (exact lib_id match first, then partial)
        for ic_pattern, pin_map in _IC_PIN_RULES:
            if ic_pattern.lower() in lib_id.lower():
                pin_name_upper = pin.pin_name.upper()
                if pin_name_upper in pin_map:
                    return pin_map[pin_name_upper]

        # 3. Fallback: pattern matching on pin name
        pin_name_upper = pin.pin_name.upper()
        for pattern in _POWER_PIN_PATTERNS:
            if pattern in pin_name_upper:
                return PinRole.POWER
        for pattern in _OUTPUT_PIN_PATTERNS:
            if pin_name_upper.startswith(pattern) or pin_name_upper == pattern:
                return PinRole.OUTPUT
        for pattern in _INPUT_PIN_PATTERNS:
            if pin_name_upper.startswith(pattern) or pin_name_upper == pattern:
                return PinRole.INPUT
        for pattern in _CONTROL_PIN_PATTERNS:
            if pattern in pin_name_upper:
                return PinRole.CONTROL

        return PinRole.UNKNOWN

    # -------------------------------------------------------------------
    # Node building
    # -------------------------------------------------------------------

    def _build_nodes(self, graph: SchematicGraph) -> list[TopologyNode]:
        """Build TopologyNode for each component."""
        pin_groups = self._group_pins_by_ref(graph.pins)
        nodes = []
        for ref, pins in pin_groups.items():
            lib_id = graph.ref_to_libid.get(ref, "")
            comp_type = _classify_component_type(lib_id)

            power_pins = []
            input_pins = []
            output_pins = []
            for pin in pins:
                role = self._classify_pin_role(ref, pin, lib_id)
                if role == PinRole.POWER:
                    power_pins.append(pin.pin_number)
                elif role == PinRole.INPUT:
                    input_pins.append(pin.pin_number)
                elif role == PinRole.OUTPUT:
                    output_pins.append(pin.pin_number)

            nodes.append(TopologyNode(
                ref=ref,
                lib_id=lib_id,
                component_type=comp_type,
                pin_count=len(pins),
                power_pins=tuple(power_pins),
                input_pins=tuple(input_pins),
                output_pins=tuple(output_pins),
            ))
        return nodes

    # -------------------------------------------------------------------
    # Edge building with net resolution
    # -------------------------------------------------------------------

    def _resolve_pin_nets(self, graph: SchematicGraph) -> dict[tuple[str, str], str]:
        """Resolve each pin to its net name using Union-Find grouping.

        Uses Union-Find to group all positions (pin positions, wire endpoints,
        label positions) into electrically connected clusters. Each cluster
        gets a net name from the first label found in it, or an anonymous name.

        Returns a dict mapping (ref, pin_number) -> net_name.
        """
        # Union-Find data structure
        parent: dict[tuple[float, float], tuple[float, float]] = {}

        def find(x: tuple[float, float]) -> tuple[float, float]:
            root = x
            while parent.get(root, root) != root:
                root = parent[root]
            # Path compression: point all nodes directly to root
            while parent.get(x, x) != root:
                next_x = parent[x]
                parent[x] = root
                x = next_x
            return root

        def union(a: tuple[float, float], b: tuple[float, float]) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Round positions for consistent keys
        def rp(pos: tuple[float, ...]) -> tuple[float, float]:
            return (round(pos[0], 2), round(pos[1], 2))

        # Initialize parent for all positions
        for pin in graph.pins:
            pos = rp(pin.position)
            parent.setdefault(pos, pos)
        for wire in graph.wires:
            s, e = rp(wire.start), rp(wire.end)
            parent.setdefault(s, s)
            parent.setdefault(e, e)
        for label in graph.labels:
            pos = rp(label.position)
            parent.setdefault(pos, pos)

        # Union wire endpoints
        for wire in graph.wires:
            s, e = rp(wire.start), rp(wire.end)
            union(s, e)

        # Union pins at wire endpoints (pin position == wire endpoint)
        for pin in graph.pins:
            pos = rp(pin.position)
            # Check all nearby positions (within tolerance)
            for other_pos in list(parent.keys()):
                if other_pos == pos:
                    continue
                dist = ((pos[0] - other_pos[0]) ** 2 + (pos[1] - other_pos[1]) ** 2) ** 0.5
                if dist <= _POSITION_TOLERANCE:
                    union(pos, other_pos)

        # Union labels at pin positions or wire endpoints (proximity)
        for label in graph.labels:
            lpos = rp(label.position)
            for other_pos in list(parent.keys()):
                dist = ((lpos[0] - other_pos[0]) ** 2 + (lpos[1] - other_pos[1]) ** 2) ** 0.5
                if dist <= _POSITION_TOLERANCE:
                    union(lpos, other_pos)

        # Build clusters: root -> set of positions
        clusters: dict[tuple[float, float], set[tuple[float, float]]] = {}
        for pos in parent:
            root = find(pos)
            clusters.setdefault(root, set()).add(pos)

        # For each cluster, find the net name (from labels) or assign anonymous name
        cluster_nets: dict[tuple[float, float], str] = {}
        anon_counter = 0
        for root, positions in clusters.items():
            # Find any label in this cluster
            net_name = None
            for label in graph.labels:
                lpos = rp(label.position)
                if lpos in positions:
                    net_name = label.name
                    break

            if net_name is None:
                # Check proximity to any label in cluster
                for label in graph.labels:
                    lpos = rp(label.position)
                    for pos in positions:
                        dist = ((pos[0] - lpos[0]) ** 2 + (pos[1] - lpos[1]) ** 2) ** 0.5
                        if dist <= _POSITION_TOLERANCE:
                            net_name = label.name
                            break
                    if net_name:
                        break

            if net_name is None:
                anon_counter += 1
                net_name = f"Net_{anon_counter}"

            cluster_nets[root] = net_name

        # Map each pin to its cluster's net name
        pin_nets: dict[tuple[str, str], str] = {}
        for pin in graph.pins:
            pos = rp(pin.position)
            if pos in parent:
                root = find(pos)
                net_name = cluster_nets.get(root)
                if net_name:
                    pin_nets[(pin.ref, pin.pin_number)] = net_name

        return pin_nets

    def _build_edges(self, graph: SchematicGraph, nodes: dict[str, TopologyNode], pin_nets: dict[tuple[str, str], str]) -> list[TopologyEdge]:
        """Build directed TopologyEdge for each signal-carrying net."""
        from kicad_agent.analysis.net_classifier import NetClassifier

        # Group pins by net
        net_pins: dict[str, list[tuple[str, str, PinRole]]] = {}
        for pin in graph.pins:
            pin_key = (pin.ref, pin.pin_number)
            net_name = pin_nets.get(pin_key)
            if not net_name:
                continue
            node = nodes.get(pin.ref)
            if not node:
                continue
            role = self._classify_pin_role(pin.ref, pin, node.lib_id)
            net_pins.setdefault(net_name, []).append((pin.ref, pin.pin_number, role))

        classifier = NetClassifier()
        edges = []

        for net_name, members in net_pins.items():
            if len(members) < 2:
                continue

            # Build pin_roles for classifier topology context
            pin_roles = {(ref, pnum): role for ref, pnum, role in members}
            classification = classifier.classify(net_name, pin_roles)

            # Find drivers (OUTPUT pins) and receivers (INPUT, BIDIRECTIONAL)
            drivers = [(ref, pnum) for ref, pnum, role in members if role == PinRole.OUTPUT]
            receivers = [(ref, pnum) for ref, pnum, role in members if role in (PinRole.INPUT, PinRole.BIDIRECTIONAL, PinRole.UNKNOWN)]
            bidirectional = [(ref, pnum) for ref, pnum, role in members if role == PinRole.BIDIRECTIONAL]

            if drivers:
                # Directed edges from each driver to each receiver
                for d_ref, d_pin in drivers:
                    for r_ref, r_pin in receivers:
                        if d_ref == r_ref:
                            continue
                        direction = "forward"
                        if classification == NetClassification.POWER:
                            direction = "power"
                        edges.append(TopologyEdge(
                            net_name=net_name,
                            source_ref=d_ref,
                            source_pin=d_pin,
                            target_ref=r_ref,
                            target_pin=r_pin,
                            classification=classification,
                            signal_direction=direction,
                        ))
            elif len(members) >= 2:
                # No driver -- bidirectional/unknown connections (two edges per pair)
                # Include all non-power members
                non_power = [(ref, pnum) for ref, pnum, role in members if role != PinRole.POWER]
                for i in range(len(non_power)):
                    for j in range(i + 1, len(non_power)):
                        r1, p1 = non_power[i]
                        r2, p2 = non_power[j]
                        direction = "bidirectional"
                        if classification == NetClassification.POWER:
                            direction = "power"
                        edges.append(TopologyEdge(
                            net_name=net_name,
                            source_ref=r1,
                            source_pin=p1,
                            target_ref=r2,
                            target_pin=p2,
                            classification=classification,
                            signal_direction=direction,
                        ))
                        edges.append(TopologyEdge(
                            net_name=net_name,
                            source_ref=r2,
                            source_pin=p2,
                            target_ref=r1,
                            target_pin=p1,
                            classification=classification,
                            signal_direction=direction,
                        ))

        return edges

    # -------------------------------------------------------------------
    # Net identification
    # -------------------------------------------------------------------

    def _identify_input_nets(self, graph: SchematicGraph, edges: list[TopologyEdge]) -> list[str]:
        """Identify input nets -- nets entering from connectors or external labels."""
        input_nets = set()

        # Look for connector components
        connector_refs = set()
        for ref, lib_id in graph.ref_to_libid.items():
            if _classify_component_type(lib_id) == "connector":
                connector_refs.add(ref)

        # Find labels that look like inputs
        input_label_patterns = ["IN", "INPUT", "SIG_IN", "AUDIO_IN"]
        for label in graph.labels:
            upper = label.name.upper()
            for pattern in input_label_patterns:
                if upper.startswith(pattern) or upper == pattern:
                    input_nets.add(label.name)

        # Nets connected to connectors are potential inputs
        for edge in edges:
            if edge.source_ref in connector_refs:
                input_nets.add(edge.net_name)

        return sorted(input_nets)

    def _identify_output_nets(self, graph: SchematicGraph, edges: list[TopologyEdge]) -> list[str]:
        """Identify output nets -- nets leaving to connectors or external labels."""
        output_nets = set()

        # Look for connector components
        connector_refs = set()
        for ref, lib_id in graph.ref_to_libid.items():
            if _classify_component_type(lib_id) == "connector":
                connector_refs.add(ref)

        # Find labels that look like outputs
        output_label_patterns = ["OUT", "OUTPUT", "SIG_OUT", "AUDIO_OUT"]
        for label in graph.labels:
            upper = label.name.upper()
            for pattern in output_label_patterns:
                if upper.startswith(pattern) or upper == pattern:
                    output_nets.add(label.name)

        # Nets connected to connectors are potential outputs
        for edge in edges:
            if edge.target_ref in connector_refs:
                output_nets.add(edge.net_name)

        return sorted(output_nets)

    # -------------------------------------------------------------------
    # Feedback detection
    # -------------------------------------------------------------------

    def _detect_feedback(self, edges: list[TopologyEdge], nodes: dict[str, TopologyNode]) -> set[str]:
        """Detect feedback nets by checking if signal flows from output stage back to input stage.

        Algorithm:
        1. Build forward adjacency from directed edges
        2. Compute BFS depth of each node from any entry point
        3. For each signal edge, if source depth > target depth -> feedback
        4. Local feedback (same IC): output -> own inverting input via resistor
        """
        feedback_nets: set[str] = set()

        # Build adjacency: ref -> list of (target_ref, net_name)
        forward: dict[str, list[tuple[str, str]]] = {}
        for edge in edges:
            if edge.classification == NetClassification.POWER:
                continue
            forward.setdefault(edge.source_ref, []).append((edge.target_ref, edge.net_name))

        # Compute BFS depth from all nodes with output pins (start from ICs)
        depth: dict[str, int] = {}
        # Find entry points: nodes with input pins that have no incoming signal edges
        all_sources = {e.source_ref for e in edges if e.classification != NetClassification.POWER}
        all_targets = {e.target_ref for e in edges if e.classification != NetClassification.POWER}
        entry_points = all_sources - all_targets
        if not entry_points:
            # All nodes participate in cycles -- use output drivers as entry points
            entry_points = {n.ref for n in nodes.values() if n.output_pins and n.component_type == "ic"}
        if not entry_points:
            entry_points = set(nodes.keys())

        # BFS from entry points
        queue: deque[tuple[str, int]] = deque()
        for ref in entry_points:
            if ref not in depth:
                depth[ref] = 0
                queue.append((ref, 0))

        while queue:
            ref, d = queue.popleft()
            for target, _net in forward.get(ref, []):
                if target not in depth:
                    depth[target] = d + 1
                    queue.append((target, d + 1))

        # Check each signal edge for backward flow
        for edge in edges:
            if edge.classification == NetClassification.POWER:
                continue
            src_depth = depth.get(edge.source_ref, -1)
            tgt_depth = depth.get(edge.target_ref, -1)

            # If we haven't assigned depth, skip
            if src_depth < 0 or tgt_depth < 0:
                continue

            # Backward edge: source is deeper than target
            if src_depth > tgt_depth:
                feedback_nets.add(edge.net_name)

        # Also detect local feedback: output -> same IC inverting input
        for edge in edges:
            if edge.classification == NetClassification.POWER:
                continue
            if edge.source_ref == edge.target_ref:
                # Same component -- local feedback
                feedback_nets.add(edge.net_name)

        return feedback_nets

    # -------------------------------------------------------------------
    # Signal path tracing
    # -------------------------------------------------------------------

    def _trace_signal_paths(
        self,
        edges: list[TopologyEdge],
        input_nets: list[str],
        output_nets: list[str],
        pin_nets: dict[tuple[str, str], str] | None = None,
    ) -> list[list[str]]:
        """BFS trace from input nets to output nets through directed edges.

        Algorithm:
        1. Start from all components connected to input nets
        2. Follow directed edges, skipping POWER-classified edges
        3. Record each path that reaches a component connected to an output net
        4. Skip dead-end branches
        5. Apply max_paths limit for safety
        """
        # Build adjacency: ref -> [(target_ref, net_name)]
        forward: dict[str, list[tuple[str, str]]] = {}
        for edge in edges:
            if edge.classification == NetClassification.POWER:
                continue
            forward.setdefault(edge.source_ref, []).append((edge.target_ref, edge.net_name))

        # Find refs connected to input nets (either as edge source/target or via pin_nets)
        input_refs: set[str] = set()
        for edge in edges:
            if edge.net_name in input_nets:
                input_refs.add(edge.source_ref)
                input_refs.add(edge.target_ref)
        # Also check pin_nets for single-pin input nets (no edges created)
        if pin_nets:
            for (ref, _pnum), net in pin_nets.items():
                if net in input_nets:
                    input_refs.add(ref)

        # Find refs connected to output nets
        output_refs: set[str] = set()
        for edge in edges:
            if edge.net_name in output_nets:
                output_refs.add(edge.source_ref)
                output_refs.add(edge.target_ref)
        if pin_nets:
            for (ref, _pnum), net in pin_nets.items():
                if net in output_nets:
                    output_refs.add(ref)

        if not input_refs or not output_refs:
            return []

        # BFS from input refs to output refs
        paths: list[list[str]] = []
        # Queue entries: (current_ref, path_so_far)
        queue: deque[tuple[str, list[str]]] = deque()
        for ref in sorted(input_refs):
            queue.append((ref, [ref]))

        visited_states: set[tuple[str, int]] = set()  # (ref, path_len) to limit exploration

        while queue and len(paths) < _MAX_PATHS:
            ref, path = queue.popleft()

            # Avoid cycles
            if ref in path[:-1]:
                continue

            # State limiting
            state = (ref, len(path))
            if state in visited_states:
                continue
            visited_states.add(state)

            # Found output
            if ref in output_refs and len(path) >= 1:
                # Only record if we traversed at least one edge or this is an input AND output component
                if len(path) > 1 or (ref in input_refs and ref in output_refs):
                    paths.append(path)
                if len(path) > 1:
                    continue

            # Expand
            for target, _net in forward.get(ref, []):
                if target not in path:
                    queue.append((target, path + [target]))

        return paths
