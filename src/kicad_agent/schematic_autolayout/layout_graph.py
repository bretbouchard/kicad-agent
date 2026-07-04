"""LayoutGraph data structures + CircuitTopology adapter (Task 1).

Frozen dataclasses per Phase 100 CR-01 (immutable throughout layout lifetime).
Adapter converts a CircuitTopology + subcircuit_map into a LayoutGraph
ready for the 5-stage Sugiyama algorithm (Task 2).

KiCad coordinate gotchas (from MEMORY.md + Phase 38 finding):
  - KICAD_GRID_MM = 2.54     (default schematic grid)
  - RC_PIN_OFFSET_MM = 3.81  (Device:R/C pin1->pin2 distance)
  - Schematic Y is INVERTED (handled in stage 5 coordinate assignment)
  - Pin (at X Y) = wire connection point, NOT pin graphic tip

D-01 (108-CONTEXT.md): Pure Python + networkx 3.1. No Graphviz.
D-02 (108-CONTEXT.md): Always split by functional group via SubcircuitDetector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import networkx as nx

from kicad_agent.analysis.topology_graph import CircuitTopology

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KiCad coordinate constants (Phase 38 finding + MEMORY.md)
# ---------------------------------------------------------------------------

KICAD_GRID_MM: float = 2.54
RC_PIN_OFFSET_MM: float = 3.81  # Device:R/C pin1 -> pin2 distance


# ---------------------------------------------------------------------------
# LayoutCoordinate — frozen NamedTuple for type-safe (x, y) pairs
# ---------------------------------------------------------------------------


class LayoutCoordinate(NamedTuple):
    """A 2D coordinate in KiCad schematic space (millimeters).

    All fields are float — never int mixing (Test 6).
    """

    x: float
    y: float


# ---------------------------------------------------------------------------
# Frozen dataclasses (Phase 100 CR-01)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutNode:
    """A component in the layout graph.

    Layer/order/position fields are mutated via dataclasses.replace() only.
    """

    ref: str
    lib_id: str
    component_type: str  # "resistor", "capacitor", "ic", "power", "connector"
    subcircuit_id: str  # "SC-001" — from SubcircuitDetector
    layer: int = -1  # assigned by stage 2; -1 = unassigned
    order_in_layer: int = -1  # assigned by stage 4
    position: LayoutCoordinate | None = None  # assigned by stage 5


@dataclass(frozen=True)
class LayoutEdge:
    """A signal connection between two components.

    signal_direction values:
      "forward"      — net flows source -> target
      "feedback"     — feedback path (reversed in stage 1)
      "bidirectional" — passive net without clear direction
      "unknown"      — topology inference uncertain (MED-2 fix: preserved,
                       treated as forward during crossing minimization)

    "power" edges are filtered into LayoutGraph.power_edges and never enter
    the Sugiyama signal-flow digraph.
    """

    source_ref: str
    target_ref: str
    net_name: str
    signal_direction: str
    is_power: bool = False


@dataclass(frozen=True)
class LayoutGraph:
    """Frozen layout graph.

    Signal edges populate `edges`; power-only edges populate `power_edges`
    (D-02: power rails are placed separately, not in signal-flow digraph).
    """

    nodes: tuple[LayoutNode, ...]
    edges: tuple[LayoutEdge, ...]
    power_edges: tuple[LayoutEdge, ...]
    subcircuit_ids: tuple[str, ...]

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    def to_networkx(self) -> nx.DiGraph:
        """Convert signal edges (non-power) into a networkx DiGraph.

        Node `ref` is the DiGraph node identifier. Edges carry net_name and
        signal_direction as edge attributes.
        """
        g = nx.DiGraph()
        for node in self.nodes:
            g.add_node(node.ref)
        for edge in self.edges:
            g.add_edge(
                edge.source_ref,
                edge.target_ref,
                net_name=edge.net_name,
                signal_direction=edge.signal_direction,
            )
        return g

    def subgraph_for(self, subcircuit_id: str) -> LayoutGraph:
        """Return a LayoutGraph containing only nodes/edges in one subcircuit.

        D-02: hierarchical split — Wave 3 emits one sheet per subcircuit.
        Edges crossing subcircuit boundaries are excluded from the subgraph
        (they become hierarchical pins in the parent sheet).
        """
        sub_refs = {n.ref for n in self.nodes if n.subcircuit_id == subcircuit_id}
        sub_nodes = tuple(n for n in self.nodes if n.ref in sub_refs)
        # Only edges where BOTH endpoints live in the subcircuit
        sub_edges = tuple(
            e
            for e in self.edges
            if e.source_ref in sub_refs and e.target_ref in sub_refs
        )
        sub_power = tuple(
            e
            for e in self.power_edges
            if e.source_ref in sub_refs and e.target_ref in sub_refs
        )
        return LayoutGraph(
            nodes=sub_nodes,
            edges=sub_edges,
            power_edges=sub_power,
            subcircuit_ids=(subcircuit_id,),
        )

    # ------------------------------------------------------------------
    # Adapter: CircuitTopology -> LayoutGraph
    # ------------------------------------------------------------------

    @classmethod
    def from_topology(
        cls,
        topology: CircuitTopology,
        subcircuit_map: dict[str, str],
    ) -> LayoutGraph:
        """Build a LayoutGraph from a CircuitTopology + subcircuit assignment.

        Args:
            topology: Phase 45 CircuitTopology (frozen dataclass)
            subcircuit_map: {ref: "SC-001"} from SubcircuitDetector

        Edge partitioning:
            - signal_direction == "power" -> power_edges (excluded from Sugiyama)
            - everything else (forward/feedback/bidirectional/unknown) -> edges
              (MED-2 fix: "unknown" preserved, treated as forward in stage 4)

        Threat mitigations:
            - T-108-01: validates subcircuit_map keys are subset of topology refs
            - Adversarial self-loop: raises ValueError before stage 1 runs

        Raises:
            ValueError: if subcircuit_map references unknown refs, or if a
                self-loop (source_ref == target_ref) is present in topology.edges
        """
        # T-108-01 mitigation: validate subcircuit_map keys
        topo_refs = {n.ref for n in topology.nodes}
        for ref in subcircuit_map:
            if ref not in topo_refs:
                raise ValueError(
                    f"subcircuit_map references ref '{ref}' not present in "
                    f"topology.nodes ({sorted(topo_refs)})"
                )

        # Adversarial self-loop detection
        for edge in topology.edges:
            if edge.source_ref == edge.target_ref:
                raise ValueError(
                    f"Self-loop detected on {edge.source_ref} (net "
                    f"'{edge.net_name}') — invalid topology, cannot layout"
                )

        # Build LayoutNodes, attaching subcircuit_id from the caller-provided map
        layout_nodes_list: list[LayoutNode] = []
        for tnode in topology.nodes:
            sc_id = subcircuit_map.get(tnode.ref, "SC-DEFAULT")
            layout_nodes_list.append(
                LayoutNode(
                    ref=tnode.ref,
                    lib_id=tnode.lib_id,
                    component_type=tnode.component_type,
                    subcircuit_id=sc_id,
                )
            )
        layout_nodes = tuple(layout_nodes_list)

        # Partition edges by signal_direction
        signal_edges: list[LayoutEdge] = []
        power_edges: list[LayoutEdge] = []
        warned_unknown = False
        for edge in topology.edges:
            # Skip self-loops defensively (already raised above, but if the
            # topology was mutated after construction this guards stage 1)
            if edge.source_ref == edge.target_ref:
                continue
            layout_edge = LayoutEdge(
                source_ref=edge.source_ref,
                target_ref=edge.target_ref,
                net_name=edge.net_name,
                signal_direction=edge.signal_direction,
                is_power=(edge.signal_direction == "power"),
            )
            if edge.signal_direction == "power":
                power_edges.append(layout_edge)
            else:
                # MED-2 fix: accept "unknown" — treat as forward in stage 4
                if edge.signal_direction == "unknown" and not warned_unknown:
                    logger.warning(
                        "LayoutGraph.from_topology: edge '%s' has "
                        "signal_direction='unknown' — will be treated as "
                        "'forward' during crossing minimization",
                        edge.net_name,
                    )
                    warned_unknown = True
                signal_edges.append(layout_edge)

        # Build sorted unique subcircuit_ids
        all_sc_ids = {sc for sc in subcircuit_map.values()}
        subcircuit_ids = tuple(sorted(all_sc_ids))

        return cls(
            nodes=layout_nodes,
            edges=tuple(signal_edges),
            power_edges=tuple(power_edges),
            subcircuit_ids=subcircuit_ids,
        )
