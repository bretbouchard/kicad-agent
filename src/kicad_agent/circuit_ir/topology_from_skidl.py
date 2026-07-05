"""Build a CircuitTopology from a skidl.Circuit (no file I/O required).

This bridges SKIDL's in-memory circuit representation to the Sugiyama
autolayout engine. It replaces the SchematicGraph → TopologyBuilder chain
for the SKIDL→schematic emitter path, avoiding a round-trip through a
.kicad_sch file.

Pipeline:
    skidl.Circuit → CircuitTopology → SubcircuitDetector → LayoutGraph
    → SugiyamaLayout.layout() → LayoutResult(positions=...)

The CircuitTopology is constructed directly from circuit.parts and
circuit.get_nets(), classifying pin roles using the same rules as
TopologyBuilder._classify_pin_role.
"""
from __future__ import annotations

import logging
from typing import Any

from kicad_agent.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
    _classify_component_type,
    _IC_PIN_RULES,
    _POWER_PIN_PATTERNS,
    _INPUT_PIN_PATTERNS,
    _OUTPUT_PIN_PATTERNS,
    _CONTROL_PIN_PATTERNS,
)
from kicad_agent.analysis.types import NetClassification, PinRole

logger = logging.getLogger(__name__)


def build_topology_from_skidl(circuit: Any) -> CircuitTopology:
    """Build a CircuitTopology from a skidl.Circuit object.

    Args:
        circuit: A skidl.Circuit with parts and nets populated.

    Returns:
        A frozen CircuitTopology ready for SubcircuitDetector or
        LayoutGraph.from_topology().
    """
    # Build TopologyNodes from circuit.parts.
    nodes: list[TopologyNode] = []
    for part in circuit.parts:
        ref = getattr(part, "ref", "")
        if not ref:
            continue
        lib_id = _skidl_part_lib_id(part)
        comp_type = _classify_component_type(lib_id)

        power_pins: list[str] = []
        input_pins: list[str] = []
        output_pins: list[str] = []
        pin_count = 0
        for pin in getattr(part, "pins", []):
            pin_count += 1
            pin_name = getattr(pin, "name", "") or ""
            pin_num = str(getattr(pin, "num", ""))
            role = _classify_pin_role_skidl(lib_id, comp_type, pin_name)
            if role == PinRole.POWER:
                power_pins.append(pin_num)
            elif role == PinRole.INPUT:
                input_pins.append(pin_num)
            elif role == PinRole.OUTPUT:
                output_pins.append(pin_num)

        nodes.append(TopologyNode(
            ref=ref,
            lib_id=lib_id,
            component_type=comp_type,
            pin_count=pin_count,
            power_pins=tuple(power_pins),
            input_pins=tuple(input_pins),
            output_pins=tuple(output_pins),
        ))

    # Build TopologyEdges from circuit nets.
    edges: list[TopologyEdge] = []
    power_nets: list[str] = []
    for net in circuit.nets:
        net_name = getattr(net, "name", "") or ""
        if net_name in ("", "__NOCONNECT", "__NOCOLLIDE"):
            continue
        pins = list(net.pins)
        if len(pins) < 2:
            continue

        # Classify the net.
        is_power = _is_power_net(net_name)
        if is_power:
            power_nets.append(net_name)

        # Get the refs of pins on this net.
        ref_pin_pairs = []
        for pin in pins:
            ref = getattr(pin.part, "ref", "")
            pin_num = str(getattr(pin, "num", ""))
            if ref and pin_num:
                ref_pin_pairs.append((ref, pin_num))

        if len(ref_pin_pairs) < 2:
            continue

        # Build edges: connect first pin to each other pin (star topology).
        # The Sugiyama engine handles this by treating the net as a hyperedge.
        source_ref, source_pin = ref_pin_pairs[0]
        for target_ref, target_pin in ref_pin_pairs[1:]:
            signal_direction = "power" if is_power else "forward"
            edges.append(TopologyEdge(
                net_name=net_name,
                source_ref=source_ref,
                source_pin=source_pin,
                target_ref=target_ref,
                target_pin=target_pin,
                classification=NetClassification.POWER if is_power else NetClassification.SIGNAL,
                signal_direction=signal_direction,
            ))

    return CircuitTopology(
        nodes=tuple(nodes),
        edges=tuple(edges),
        input_nets=(),
        output_nets=(),
        power_nets=tuple(power_nets),
        signal_paths=(),
        stats={
            "component_count": len(nodes),
            "net_count": len(set(e.net_name for e in edges)),
            "edge_count": len(edges),
        },
    )


def _skidl_part_lib_id(part: Any) -> str:
    """Extract a KiCad lib_id from a skidl Part (shared with skidl_to_kicad)."""
    name = getattr(part, "name", "")
    lib = getattr(part, "lib", None)
    if lib is not None:
        lib_name = getattr(lib, "filename", None) or str(getattr(lib, "name", ""))
        if ":" in str(lib_name):
            return str(lib_name)
        if lib_name and name:
            return f"{lib_name}:{name}"
    return name or ""


def _classify_pin_role_skidl(lib_id: str, comp_type: str, pin_name: str) -> PinRole:
    """Classify pin role from lib_id + pin_name (no PinPosition needed)."""
    if comp_type in ("resistor", "capacitor", "inductor"):
        return PinRole.BIDIRECTIONAL

    # IC-specific rules.
    for ic_pattern, pin_map in _IC_PIN_RULES:
        if ic_pattern.lower() in lib_id.lower():
            pin_name_upper = pin_name.upper()
            if pin_name_upper in pin_map:
                return pin_map[pin_name_upper]

    # Fallback pattern matching.
    pin_name_upper = pin_name.upper()
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


def _is_power_net(net_name: str) -> bool:
    """Check if a net name indicates a power net."""
    power_patterns = ["VCC", "VDD", "V+", "V-", "VSS", "GND", "GNDA", "VEE", "VAA",
                      "+3V3", "+5V", "+12V", "-12V", "+BATT", "AVDD", "AGND"]
    upper = net_name.upper()
    return any(p in upper for p in power_patterns)


def compute_sugiyama_positions(
    circuit: Any,
    *,
    layer_spacing_mm: float = 25.4,
    node_spacing_mm: float = 12.7,
) -> dict[str, tuple[float, float]]:
    """Run the Sugiyama layout on a skidl.Circuit and return positions.

    This is the main entry point for the emitter. It builds a topology,
    detects subcircuits, runs the 5-stage Sugiyama algorithm, and
    fit-to-page. Returns {ref: (x, y)} coordinates.

    Args:
        circuit: A skidl.Circuit object.
        layer_spacing_mm: Vertical spacing between Sugiyama layers.
        node_spacing_mm: Horizontal spacing between nodes in a layer.

    Returns:
        Dict mapping ref designators to (x, y) coordinates in mm.
    """
    from kicad_agent.schematic_autolayout import SugiyamaLayout, LayoutGraph, paper_sizes
    from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector

    topology = build_topology_from_skidl(circuit)
    if not topology.nodes:
        return {}

    # Detect subcircuits.
    detector = SubcircuitDetector()
    subcircuits = detector.detect(topology)
    subcircuit_map: dict[str, str] = {}
    for sc in subcircuits:
        for ref in sc.components:
            subcircuit_map[ref] = sc.subcircuit_id
        if sc.center_component:
            subcircuit_map[sc.center_component] = sc.subcircuit_id
    # Components not in any subcircuit → single default group.
    for node in topology.nodes:
        if node.ref not in subcircuit_map:
            subcircuit_map[node.ref] = "SC-DEFAULT"

    graph = LayoutGraph.from_topology(topology, subcircuit_map)
    layout = SugiyamaLayout(
        layer_spacing_mm=layer_spacing_mm,
        node_spacing_mm=node_spacing_mm,
    )

    # Run layout per-subcircuit if multiple, else whole graph.
    positions: dict[str, tuple[float, float]] = {}
    if len(graph.subcircuit_ids) > 1:
        x_offset = 0.0
        for sc_id in graph.subcircuit_ids:
            subgraph = graph.subgraph_for(sc_id)
            if len(subgraph.nodes) == 0:
                continue
            result = layout.layout(subgraph)
            for ref, coord in result.positions.items():
                positions[ref] = (coord.x + x_offset, coord.y)
            max_x = max(c[0] for c in positions.values()) if positions else 0.0
            x_offset = max_x + node_spacing_mm * 2
    else:
        if len(graph.nodes) > 0:
            result = layout.layout(graph)
            for ref, coord in result.positions.items():
                positions[ref] = (coord.x, coord.y)

    # fit_to_page.
    page_w, page_h = 297.0, 210.0  # A4 landscape
    margin = 20.0
    fitted = layout.fit_to_page(positions, page_w, page_h, margin)
    return {ref: (c.x, c.y) for ref, c in fitted.items()}
