"""Circuit topology graph with signal flow direction inference.

Builds a directed networkx graph from SchematicGraph or SchematicIR where:
- Nodes are components (TopologyNode)
- Edges are signal-carrying nets (TopologyEdge) with flow direction
- Signal flow is inferred from IC pin types and passive behavior

DOMAIN-01: Foundation for all domain intelligence.

Usage:
    from volta.analysis.topology_graph import TopologyBuilder
    from volta.schematic_routing.schematic_graph import SchematicGraph

    graph = SchematicGraph.from_file("compressor.kicad_sch")
    builder = TopologyBuilder()
    topology = builder.from_schematic_graph(graph)
    for edge in topology.edges:
        print(f"{edge.source_ref}.{edge.source_pin} --[{edge.net_name}]--> {edge.target_ref}.{edge.target_pin}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from volta.analysis.types import NetClassification, PinRole
from volta.schematic_routing.schematic_graph import SchematicGraph

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

# Re-export TopologyBuilder from extracted module for backward compatibility
from volta.analysis.topology_builder import TopologyBuilder  # noqa: E402
