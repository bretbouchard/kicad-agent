"""Feature extraction for subcircuit classification.

Extracts a fixed-length feature vector from each detected subcircuit.
The feature schema is designed for ML pipeline compatibility:
- JSON-serializable via dataclasses.asdict()
- Compatible with sklearn DictVectorizer
- Compatible with pytorch tensor conversion

DOMAIN-03: ML-ready feature extraction for circuit classification.

Usage:
    from volta.analysis.feature_extraction import extract_features

    features = extract_features(
        component_refs=["U1", "R1", "C1"],
        nodes={"U1": node_u1, "R1": node_r1, "C1": node_c1},
        edges=[...],
        nets=["SIG_IN", "FB", "VCC"],
        boundary_nets=["SIG_IN"],
        center_component="U1",
        power_nets={"VCC", "GND"},
        signal_paths=[["J1", "U1", "J2"]],
    )
    print(features.resistor_count)  # 1
    print(features.has_feedback_loop)  # True
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from volta.analysis.topology_graph import (
    NetClassification,
    TopologyEdge,
    TopologyNode,
)

logger = logging.getLogger(__name__)

# IC type mapping from lib_id for primary_ic_type feature
_IC_TYPE_MAP: dict[str, str] = {
    "NE5532": "opamp", "TL072": "opamp", "LM358": "opamp", "LM324": "opamp",
    "OPA2134": "opamp", "OP07": "opamp", "OP27": "opamp", "AD712": "opamp",
    "THAT4301": "vca", "THAT2181": "vca",
    "RP2040": "mcu", "ATMEGA": "mcu", "STM32": "mcu", "ESP32": "mcu",
    "LM7805": "regulator", "LM7812": "regulator", "LM317": "regulator",
    "7912": "regulator", "AMS1117": "regulator",
    "CD4066": "switch",
    "CD4060": "oscillator",
}


def _classify_ic_type(lib_id: str) -> str:
    """Map IC lib_id to a generic IC type for ML features."""
    upper = lib_id.upper()
    for pattern, ic_type in _IC_TYPE_MAP.items():
        if pattern.upper() in upper:
            return ic_type
    return "unknown"


@dataclass(frozen=True)
class SubcircuitFeatures:
    """Fixed-length feature vector for a subcircuit.

    All fields are primitives (int, bool, str, tuple) for JSON serialization
    and ML pipeline compatibility.

    Schema compatible with:
    - sklearn DictVectorizer (dict from asdict())
    - pytorch tensor conversion (list of numeric fields)
    - JSONL logging for training data
    """

    subcircuit_id: str

    # Component counts
    ic_count: int
    resistor_count: int
    capacitor_count: int
    inductor_count: int
    diode_count: int
    transistor_count: int
    total_component_count: int

    # Topology features
    has_feedback_loop: bool
    has_power_connection: bool
    has_crystal: bool
    feedback_capacitor_count: int       # Capacitors in feedback path
    feedback_resistor_count: int        # Resistors in feedback path
    coupling_capacitor_count: int       # Capacitors on signal path (not feedback)

    # Net features
    input_net_count: int
    output_net_count: int
    power_net_count: int
    ground_net_count: int
    control_net_count: int
    feedback_net_count: int
    net_count: int
    boundary_net_count: int

    # IC features
    ic_lib_ids: tuple[str, ...]         # All IC lib_ids
    primary_ic_type: str                # "opamp", "vca", "mcu", etc.

    # Path features
    max_signal_path_length: int         # Longest signal path through subcircuit

    # Density metric
    component_density: float            # total_components / net_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for sklearn DictVectorizer."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubcircuitFeatures:
        """Deserialize from dict (e.g., loaded from JSON)."""
        return cls(**data)

    def to_numeric_vector(self) -> list[float]:
        """Extract numeric fields only for tensor conversion.

        Returns list of floats in fixed order, excluding subcircuit_id
        and ic_lib_ids (categorical).
        """
        return [
            float(self.ic_count),
            float(self.resistor_count),
            float(self.capacitor_count),
            float(self.inductor_count),
            float(self.diode_count),
            float(self.transistor_count),
            float(self.total_component_count),
            float(self.has_feedback_loop),
            float(self.has_power_connection),
            float(self.has_crystal),
            float(self.feedback_capacitor_count),
            float(self.feedback_resistor_count),
            float(self.coupling_capacitor_count),
            float(self.input_net_count),
            float(self.output_net_count),
            float(self.power_net_count),
            float(self.ground_net_count),
            float(self.control_net_count),
            float(self.feedback_net_count),
            float(self.net_count),
            float(self.boundary_net_count),
            float(self.max_signal_path_length),
            self.component_density,
        ]


def extract_features(
    component_refs: list[str],
    nodes: dict[str, TopologyNode],
    edges: list[TopologyEdge],
    nets: list[str],
    boundary_nets: list[str],
    center_component: str,
    power_nets: set[str],
    signal_paths: list[list[str]],
    subcircuit_id: str = "SC-000",
    input_nets: set[str] | None = None,
    output_nets: set[str] | None = None,
) -> SubcircuitFeatures:
    """Extract feature vector from subcircuit data.

    Args:
        component_refs: Component refs in this subcircuit.
        nodes: All TopologyNode instances (keyed by ref).
        edges: All TopologyEdge instances.
        nets: Net names within this subcircuit.
        boundary_nets: Nets shared with other subcircuits.
        center_component: Primary IC ref.
        power_nets: Set of power/ground net names.
        signal_paths: Signal paths through the topology.
        subcircuit_id: ID for this subcircuit.
        input_nets: Topology-level input nets (optional).
        output_nets: Topology-level output nets (optional).

    Returns:
        SubcircuitFeatures with all computed fields.
    """
    if input_nets is None:
        input_nets = set()
    if output_nets is None:
        output_nets = set()

    # Count component types
    type_counts: dict[str, int] = {
        "ic": 0, "resistor": 0, "capacitor": 0, "inductor": 0,
        "diode": 0, "transistor": 0,
    }
    ic_lib_ids: list[str] = []
    has_crystal = False

    for ref in component_refs:
        node = nodes.get(ref)
        if node is None:
            continue
        ctype = node.component_type
        if ctype in type_counts:
            type_counts[ctype] += 1
        if ctype == "ic":
            ic_lib_ids.append(node.lib_id)
        if "crystal" in node.lib_id.lower() or "xtal" in node.lib_id.lower():
            has_crystal = True

    # Identify feedback edges (edges classified as FEEDBACK within subcircuit)
    sc_refs = set(component_refs)
    feedback_edges = [
        e for e in edges
        if e.source_ref in sc_refs
        and e.target_ref in sc_refs
        and e.classification == NetClassification.FEEDBACK
    ]
    has_feedback = len(feedback_edges) > 0

    # Count feedback capacitors/resistors
    feedback_net_refs: set[str] = set()
    for e in feedback_edges:
        feedback_net_refs.add(e.source_ref)
        feedback_net_refs.add(e.target_ref)

    feedback_cap_count = 0
    feedback_res_count = 0
    for ref in feedback_net_refs:
        node = nodes.get(ref)
        if node and node.component_type == "capacitor":
            feedback_cap_count += 1
        if node and node.component_type == "resistor":
            feedback_res_count += 1

    # Net classification counts
    sc_net_names = set(nets)
    net_by_class: dict[NetClassification, int] = {cls: 0 for cls in NetClassification}
    for e in edges:
        if e.net_name in sc_net_names:
            net_by_class[e.classification] += 1

    # Power connection check
    has_power = bool(sc_net_names & power_nets)

    # Max signal path length through this subcircuit
    max_path_len = 0
    for path in signal_paths:
        in_sc = [r for r in path if r in sc_refs]
        max_path_len = max(max_path_len, len(in_sc))

    # Coupling capacitors (on signal path, not in feedback)
    coupling_cap_count = sum(
        1 for ref in component_refs
        if nodes.get(ref) and nodes[ref].component_type == "capacitor"
        and ref not in feedback_net_refs
    )

    # Primary IC type
    center_node = nodes.get(center_component)
    primary_ic_type = _classify_ic_type(center_node.lib_id) if center_node else "unknown"

    # Density
    net_count = max(len(sc_net_names), 1)  # Avoid division by zero
    density = len(component_refs) / net_count

    return SubcircuitFeatures(
        subcircuit_id=subcircuit_id,
        ic_count=type_counts["ic"],
        resistor_count=type_counts["resistor"],
        capacitor_count=type_counts["capacitor"],
        inductor_count=type_counts["inductor"],
        diode_count=type_counts["diode"],
        transistor_count=type_counts["transistor"],
        total_component_count=len(component_refs),
        has_feedback_loop=has_feedback,
        has_power_connection=has_power,
        has_crystal=has_crystal,
        feedback_capacitor_count=feedback_cap_count,
        feedback_resistor_count=feedback_res_count,
        coupling_capacitor_count=coupling_cap_count,
        input_net_count=len(input_nets & sc_net_names),
        output_net_count=len(output_nets & sc_net_names),
        power_net_count=net_by_class.get(NetClassification.POWER, 0),
        ground_net_count=net_by_class.get(NetClassification.GROUND, 0),
        control_net_count=net_by_class.get(NetClassification.CONTROL, 0),
        feedback_net_count=net_by_class.get(NetClassification.FEEDBACK, 0),
        net_count=len(sc_net_names),
        boundary_net_count=len(boundary_nets),
        ic_lib_ids=tuple(ic_lib_ids),
        primary_ic_type=primary_ic_type,
        max_signal_path_length=max_path_len,
        component_density=density,
    )
