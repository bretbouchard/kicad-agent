"""Subcircuit detection via IC-centric clustering on topology graph.

Identifies functional blocks within a schematic by clustering components
around ICs using the CircuitTopology from Phase 45.

DOMAIN-02: Subcircuit detection for component function recognition.

Usage:
    from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
    from kicad_agent.analysis.topology_graph import TopologyBuilder

    builder = TopologyBuilder()
    topology = builder.from_schematic_graph(graph)
    detector = SubcircuitDetector()
    subcircuits = detector.detect(topology)
    for sc in subcircuits:
        print(f"{sc.subcircuit_id}: {sc.subcircuit_type.value} "
              f"({len(sc.components)} components, confidence={sc.confidence:.2f})")
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

from kicad_agent.analysis.feature_extraction import SubcircuitFeatures, extract_features
from kicad_agent.analysis.topology_graph import (
    CircuitTopology,
    NetClassification,
    TopologyEdge,
    TopologyNode,
)

logger = logging.getLogger(__name__)


class SubcircuitType(str, Enum):
    """Classification of subcircuit function."""

    PREAMP = "PREAMP"
    COMPRESSOR = "COMPRESSOR"
    EQ = "EQ"
    FILTER = "FILTER"
    VCA = "VCA"
    ENVELOPE = "ENVELOPE"
    LFO = "LFO"
    MIXER = "MIXER"
    OUTPUT_STAGE = "OUTPUT_STAGE"
    POWER_SUPPLY = "POWER_SUPPLY"
    OSCILLATOR = "OSCILLATOR"
    DIGITAL_CONTROL = "DIGITAL_CONTROL"
    ANALOG_SWITCH = "ANALOG_SWITCH"
    PROTECTION = "PROTECTION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Subcircuit:
    """A functional block within a circuit."""

    subcircuit_id: str  # "SC-001"
    components: tuple[str, ...]  # Component refs
    nets: tuple[str, ...]  # Net names within subcircuit
    boundary_nets: tuple[str, ...]  # Nets connecting to other subcircuits
    subcircuit_type: SubcircuitType
    confidence: float  # 0.0 - 1.0
    center_component: str  # Primary IC ref
    features: dict  # Extracted features


class SubcircuitDetector:
    """Detects functional subcircuits by clustering around ICs.

    Algorithm:
    1. Identify all IC nodes in the topology
    2. For each IC, collect components within 1-2 hops on signal/control nets
    3. Assign each component to exactly one subcircuit (greedy, closest IC wins)
    4. Identify boundary nets (nets shared between subcircuits or external)
    5. Classify each subcircuit using CircuitClassifier
    6. Handle passive-only groups (no IC): assign to nearest IC subcircuit
    """

    def __init__(self, max_hops: int = 2):
        """Initialize detector.

        Args:
            max_hops: Maximum hop distance from IC for component clustering.
        """
        self._max_hops = max_hops

    def detect(self, topology: CircuitTopology) -> list[Subcircuit]:
        """Detect subcircuits in a topology.

        Returns:
            List of Subcircuit instances, sorted by subcircuit_id.
        """
        if not topology.nodes:
            return []

        # Build adjacency from edges
        adjacency = self._build_adjacency(topology)

        # 1. Find IC nodes
        ic_nodes = self._find_ic_nodes(topology.nodes)

        if not ic_nodes:
            # No ICs -- can't form subcircuits
            return []

        # 2. Cluster components around each IC using BFS
        assigned: set[str] = set()
        subcircuit_data: list[dict[str, Any]] = []
        ic_refs = {ic.ref for ic in ic_nodes}

        for ic_node in ic_nodes:
            comp_refs, net_names = self._cluster_around_ic(
                ic_node, topology, assigned, adjacency, ic_refs
            )

            # Mark components as assigned
            assigned.update(comp_refs)
            assigned.add(ic_node.ref)

            subcircuit_data.append({
                "center_component": ic_node.ref,
                "ic_node": ic_node,
                "components": comp_refs,
                "nets": net_names,
            })

        # 3. Assign unassigned passive components to nearest IC subcircuit
        subcircuit_data = self._assign_passive_groups(
            topology, assigned, subcircuit_data, adjacency
        )

        # 4. Identify boundary nets
        all_sc_nets: list[set[str]] = []
        for sc_data in subcircuit_data:
            all_sc_nets.append(set(sc_data["nets"]))

        all_nets = {e.net_name for e in topology.edges}

        # 5. Classify each subcircuit and build final results
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier

        classifier = CircuitClassifier()
        results: list[Subcircuit] = []

        for idx, sc_data in enumerate(subcircuit_data):
            sc_id = f"SC-{idx + 1:03d}"
            sc_nets = set(sc_data["nets"])
            other_nets = [all_sc_nets[j] for j in range(len(all_sc_nets)) if j != idx]
            boundary = self._find_boundary_nets(sc_nets, all_nets, other_nets)

            # Extract features using legacy method for classifier compatibility
            classifier_features = self._extract_features(
                sc_data["ic_node"],
                sc_data["components"],
                sc_data["nets"],
                topology,
            )

            # Extract ML-ready features using new feature extraction module
            node_map = {n.ref: n for n in topology.nodes}
            sc_features = extract_features(
                component_refs=list(sc_data["components"]) + [sc_data["center_component"]],
                nodes=node_map,
                edges=list(topology.edges),
                nets=list(sc_nets),
                boundary_nets=list(boundary),
                center_component=sc_data["center_component"],
                power_nets=set(topology.power_nets),
                signal_paths=[list(p) for p in topology.signal_paths],
                subcircuit_id=sc_id,
                input_nets=set(topology.input_nets),
                output_nets=set(topology.output_nets),
            )

            # Merge: legacy fields first, then ML-ready features overwrite for
            # overlapping keys (resistor_count, capacitor_count, etc.) so the
            # SubcircuitFeatures computed values are the single source of truth.
            features = {**classifier_features, **sc_features.to_dict()}

            # Classify
            classification = classifier.classify(features)

            # Build final component list (center IC + clustered components)
            all_comps = tuple(sorted(set(list(sc_data["components"]) + [sc_data["center_component"]])))

            results.append(Subcircuit(
                subcircuit_id=sc_id,
                components=all_comps,
                nets=tuple(sorted(sc_nets)),
                boundary_nets=tuple(sorted(boundary)),
                subcircuit_type=classification.subcircuit_type,
                confidence=classification.confidence,
                center_component=sc_data["center_component"],
                features=features,
            ))

        return sorted(results, key=lambda sc: sc.subcircuit_id)

    def _build_adjacency(self, topology: CircuitTopology) -> dict[str, list[tuple[str, str]]]:
        """Build adjacency list from topology edges.

        Returns:
            Dict mapping ref -> [(neighbor_ref, net_name), ...]
        """
        adj: dict[str, list[tuple[str, str]]] = {}
        for edge in topology.edges:
            adj.setdefault(edge.source_ref, []).append((edge.target_ref, edge.net_name))
            adj.setdefault(edge.target_ref, []).append((edge.source_ref, edge.net_name))
        return adj

    def _find_ic_nodes(self, nodes: tuple[TopologyNode, ...]) -> list[TopologyNode]:
        """Find all IC nodes (component_type == 'ic')."""
        return [n for n in nodes if n.component_type == "ic"]

    def _cluster_around_ic(
        self,
        ic: TopologyNode,
        topology: CircuitTopology,
        assigned: set[str],
        adjacency: dict[str, list[tuple[str, str]]],
        ic_refs: set[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Collect component refs and net names within max_hops of IC.

        BFS does not traverse through other ICs -- each IC gets its own cluster.

        Returns:
            (component_refs, net_names) tuple.
        """
        if ic_refs is None:
            ic_refs = {ic.ref}

        visited: set[str] = {ic.ref}
        comp_refs: list[str] = []
        net_names: list[str] = []

        # BFS from IC
        queue: deque[tuple[str, int]] = deque()
        queue.append((ic.ref, 0))

        while queue:
            current_ref, depth = queue.popleft()

            if depth >= self._max_hops:
                continue

            for neighbor_ref, net_name in adjacency.get(current_ref, []):
                if neighbor_ref in visited:
                    continue
                if neighbor_ref in assigned:
                    continue
                # Don't traverse through other ICs
                if neighbor_ref in ic_refs:
                    # But record the net as a boundary
                    if net_name not in net_names:
                        net_names.append(net_name)
                    visited.add(neighbor_ref)
                    continue

                visited.add(neighbor_ref)
                comp_refs.append(neighbor_ref)
                net_names.append(net_name)

                queue.append((neighbor_ref, depth + 1))

        # Also collect nets from edges connecting IC directly
        for edge in topology.edges:
            if edge.source_ref == ic.ref or edge.target_ref == ic.ref:
                if edge.net_name not in net_names:
                    net_names.append(edge.net_name)

        return comp_refs, net_names

    def _find_boundary_nets(
        self,
        subcircuit_nets: set[str],
        all_nets: set[str],
        other_subcircuit_nets: list[set[str]],
    ) -> list[str]:
        """Identify nets shared with other subcircuits or external connections."""
        boundary = []
        for net in subcircuit_nets:
            # Check if this net appears in any other subcircuit
            for other_nets in other_subcircuit_nets:
                if net in other_nets:
                    boundary.append(net)
                    break
        return boundary

    def _assign_passive_groups(
        self,
        topology: CircuitTopology,
        assigned: set[str],
        subcircuit_data: list[dict[str, Any]],
        adjacency: dict[str, list[tuple[str, str]]],
    ) -> list[dict[str, Any]]:
        """Assign unassigned passive components to nearest IC subcircuit."""
        # Find unassigned components
        unassigned = [
            n.ref for n in topology.nodes
            if n.ref not in assigned and n.component_type != "ic"
        ]

        if not unassigned:
            return subcircuit_data

        # For each unassigned component, find nearest IC subcircuit via BFS
        for ref in unassigned:
            nearest_idx = self._find_nearest_subcircuit(ref, subcircuit_data, adjacency)
            if nearest_idx is not None:
                sc = subcircuit_data[nearest_idx]
                sc["components"] = list(sc["components"]) + [ref]
                # Also add nets connecting this component
                for edge in topology.edges:
                    if (edge.source_ref == ref or edge.target_ref == ref) and edge.net_name not in sc["nets"]:
                        sc["nets"] = list(sc["nets"]) + [edge.net_name]
                assigned.add(ref)

        return subcircuit_data

    def _find_nearest_subcircuit(
        self,
        ref: str,
        subcircuit_data: list[dict[str, Any]],
        adjacency: dict[str, list[tuple[str, str]]],
    ) -> int | None:
        """Find the index of the nearest IC subcircuit for a given ref."""
        # BFS from ref to find nearest IC center
        visited: set[str] = {ref}
        queue: deque[tuple[str, int]] = deque([(ref, 0)])

        while queue:
            current, depth = queue.popleft()
            if depth > self._max_hops + 2:
                break

            # Check if this ref is a center component of any subcircuit
            for idx, sc_data in enumerate(subcircuit_data):
                if current == sc_data["center_component"] or current in sc_data["components"]:
                    return idx

            for neighbor_ref, _net_name in adjacency.get(current, []):
                if neighbor_ref not in visited:
                    visited.add(neighbor_ref)
                    queue.append((neighbor_ref, depth + 1))

        # Default: assign to first subcircuit if any exist
        return 0 if subcircuit_data else None

    def _extract_features(
        self,
        ic_node: TopologyNode,
        component_refs: tuple[str, ...],
        nets: list[str],
        topology: CircuitTopology,
    ) -> dict[str, Any]:
        """Extract features for circuit classification.

        Features extracted:
        - lib_id, component_type from center IC
        - Counts of each component type in cluster
        - Feedback loop presence (from topology edges)
        - Power/ground net connections
        - Capacitor/resistor counts in feedback paths
        """
        # Build ref -> node map
        node_map = {n.ref: n for n in topology.nodes}

        # Count component types
        resistor_count = 0
        capacitor_count = 0
        inductor_count = 0
        diode_count = 0
        transistor_count = 0
        connector_count = 0
        has_crystal = False

        all_refs = set(component_refs) | {ic_node.ref}
        for ref in all_refs:
            node = node_map.get(ref)
            if node is None:
                continue
            ct = node.component_type
            if ct == "resistor":
                resistor_count += 1
            elif ct == "capacitor":
                capacitor_count += 1
            elif ct == "inductor":
                inductor_count += 1
            elif ct == "diode":
                diode_count += 1
            elif ct == "transistor":
                transistor_count += 1
            elif ct == "connector":
                connector_count += 1
            # Check for crystal
            if "crystal" in node.lib_id.lower():
                has_crystal = True

        # Detect feedback
        feedback_nets = set()
        for edge in topology.edges:
            if edge.classification == NetClassification.FEEDBACK:
                feedback_nets.add(edge.net_name)
        has_feedback = bool(feedback_nets & set(nets))

        # Count feedback resistors/capacitors
        feedback_resistor_count = 0
        feedback_capacitor_count = 0
        for edge in topology.edges:
            if edge.net_name not in feedback_nets:
                continue
            # Check if source or target is a resistor or capacitor
            for ref in (edge.source_ref, edge.target_ref):
                node = node_map.get(ref)
                if node is None:
                    continue
                if node.component_type == "resistor" and ref in all_refs:
                    feedback_resistor_count += 1
                    break
                if node.component_type == "capacitor" and ref in all_refs:
                    feedback_capacitor_count += 1
                    break

        # Detect power connections
        has_power_connection = any(
            edge.classification == NetClassification.POWER
            and (edge.source_ref in all_refs or edge.target_ref in all_refs)
            for edge in topology.edges
        )

        # Detect sidechain (for VCA ICs): additional RC network not in main signal path
        has_sidechain = False
        lib_id_upper = ic_node.lib_id.upper()
        if any(vca in lib_id_upper for vca in ["THAT4301", "THAT2181"]):
            # Sidechain heuristic: more resistors + capacitors than needed for basic VCA
            has_sidechain = resistor_count >= 4 and capacitor_count >= 2

        # Detect VCA input
        has_vca_input = any(
            vca in lib_id_upper for vca in ["THAT4301", "THAT2181"]
        )

        # Detect multiple inputs (for mixer classification)
        input_signal_nets = set()
        for edge in topology.edges:
            if edge.classification != NetClassification.POWER and edge.target_ref in all_refs:
                target_node = node_map.get(edge.target_ref)
                if target_node and target_node.ref == ic_node.ref and edge.target_pin in ic_node.input_pins:
                    input_signal_nets.add(edge.net_name)
        has_multiple_inputs = len(input_signal_nets) >= 2

        # Count coupling capacitors (capacitors not in feedback path)
        coupling_capacitor_count = capacitor_count - feedback_capacitor_count
        if coupling_capacitor_count < 0:
            coupling_capacitor_count = 0

        return {
            "center_component": ic_node.ref,
            "lib_id": ic_node.lib_id,
            "component_type": ic_node.component_type,
            "resistor_count": resistor_count,
            "capacitor_count": capacitor_count,
            "inductor_count": inductor_count,
            "diode_count": diode_count,
            "transistor_count": transistor_count,
            "connector_count": connector_count,
            "has_crystal": has_crystal,
            "has_feedback_loop": has_feedback,
            "has_power_connection": has_power_connection,
            "feedback_resistor_count": feedback_resistor_count,
            "feedback_capacitor_count": feedback_capacitor_count,
            "coupling_capacitor_count": coupling_capacitor_count,
            "has_sidechain": has_sidechain,
            "has_vca_input": has_vca_input,
            "has_multiple_inputs": has_multiple_inputs,
        }

    def to_jsonl(self, subcircuits: list[Subcircuit], output_path: str) -> int:
        """Export feature vectors to JSONL for ML training data.

        Each line is a JSON object with:
        - subcircuit_id, subcircuit_type, confidence
        - All feature fields from the subcircuit's features dict

        Args:
            subcircuits: List of Subcircuit instances from detect().
            output_path: File path to write JSONL output.

        Returns:
            Number of lines written.
        """
        if len(subcircuits) > 500:
            logger.warning("Large JSONL export: %d subcircuits", len(subcircuits))

        count = 0
        with open(output_path, "w") as f:
            for sc in subcircuits:
                record = {
                    "subcircuit_id": sc.subcircuit_id,
                    "subcircuit_type": sc.subcircuit_type.value,
                    "confidence": sc.confidence,
                    **sc.features,
                }
                f.write(json.dumps(record, default=str) + "\n")
                count += 1
        return count
