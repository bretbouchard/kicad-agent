"""Bipartite component-net graph construction from schematic netlist.

Converts ComponentSpec and NetSpec lists into a networkx bipartite graph
where component nodes (bipartite=0) connect to net nodes (bipartite=1).
This representation avoids O(n^2) edge explosion from power nets by routing
connectivity through net nodes instead of direct pairwise component edges.

Security (threat model):
  T-16-01: Component count cap at 500, net count cap at 200.
  T-16-02: Bipartite structure avoids O(n^2) power-net edge explosion.

Usage::

    from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph

    graph = netlist_to_placement_graph(components, nets, board_width=100, board_height=80)
    pg = PlacementGraph(graph)
    features = pg.get_component_features(100.0, 80.0)
    adjacency = pg.get_adjacency_matrix()
"""

from __future__ import annotations

import networkx as nx
import numpy
from numpy import float32

from kicad_agent.generation.intent import ComponentSpec, NetSpec
from kicad_agent.placement.features import (
    COMP_FEATURE_DIM,
    NET_FEATURE_DIM,
    extract_component_features,
    extract_net_features,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_COMPONENTS = 500
"""Maximum component count (matches GenerationIntent.components max_length)."""

_MAX_NETS = 200
"""Maximum net count (matches GenerationIntent.nets max_length)."""

_POWER_NETS: frozenset[str] = frozenset(
    {"GND", "VCC", "+3V3", "+5V", "VDD", "VSS", "GNDA", "VCCA"}
)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def netlist_to_placement_graph(
    components: list[ComponentSpec],
    nets: list[NetSpec],
    board_width: float,
    board_height: float,
) -> nx.Graph:
    """Build a bipartite component-net graph from a schematic netlist.

    Creates an undirected networkx Graph with:
    - Component nodes (bipartite=0) keyed as ``"comp:{reference}"``
    - Net nodes (bipartite=1) keyed as ``"net:{name}"``
    - Edges connecting components to the nets they participate in

    Args:
        components: List of ComponentSpec instances.
        nets: List of NetSpec instances.
        board_width: Board width in mm (must be positive).
        board_height: Board height in mm (must be positive).

    Returns:
        Undirected networkx Graph with bipartite partition attributes.

    Raises:
        ValueError: If board dimensions are not positive, component count
            exceeds 500, or net count exceeds 200.
    """
    # Validate inputs
    if board_width <= 0 or board_height <= 0:
        raise ValueError(
            f"Board dimensions must be positive, got "
            f"width={board_width}, height={board_height}"
        )
    if len(components) > _MAX_COMPONENTS:
        raise ValueError(
            f"Component count {len(components)} exceeds maximum {_MAX_COMPONENTS}"
        )
    if len(nets) > _MAX_NETS:
        raise ValueError(
            f"Net count {len(nets)} exceeds maximum {_MAX_NETS}"
        )

    graph = nx.Graph()
    graph.graph["board_width"] = board_width
    graph.graph["board_height"] = board_height
    graph.graph["component_count"] = len(components)
    graph.graph["net_count"] = len(nets)

    # Add component nodes (bipartite=0)
    for comp in components:
        node_id = f"comp:{comp.reference}"
        is_fixed = comp.position is not None
        graph.add_node(
            node_id,
            bipartite=0,
            node_type="component",
            reference=comp.reference,
            library_id=comp.library_id,
            value=comp.value,
            estimated_size=_estimate_size_inline(comp),
            is_fixed=is_fixed,
            fixed_x=comp.position.x if is_fixed else None,
            fixed_y=comp.position.y if is_fixed else None,
            comp_spec=comp,
        )

    # Build component lookup for net resolution
    comp_map = {comp.reference: comp for comp in components}

    # Add net nodes (bipartite=1) and edges
    for net in nets:
        net_node_id = f"net:{net.name}"

        # Extract unique component references from pins
        comp_refs_in_net: dict[str, int] = {}  # ref -> pin count on this net
        for pin in net.pins:
            parts = pin.split(".")
            if parts:
                ref = parts[0]
                comp_refs_in_net[ref] = comp_refs_in_net.get(ref, 0) + 1

        is_power = net.name in _POWER_NETS

        graph.add_node(
            net_node_id,
            bipartite=1,
            node_type="net",
            name=net.name,
            pin_count=len(net.pins),
            is_power=is_power,
            criticality=_compute_criticality(net.name, is_power),
            net_spec=net,
        )

        # Add edges from components to net
        for ref, pin_count in comp_refs_in_net.items():
            comp_node_id = f"comp:{ref}"
            if graph.has_node(comp_node_id):
                graph.add_edge(
                    comp_node_id,
                    net_node_id,
                    weight=1.0,
                    pin_count=pin_count,
                )

    return graph


# ---------------------------------------------------------------------------
# PlacementGraph wrapper
# ---------------------------------------------------------------------------


class PlacementGraph:
    """Wrapper around a bipartite component-net placement graph.

    Provides typed access to node partitions, feature matrices, and
    adjacency structures for downstream GNN consumption.

    Args:
        graph: A networkx Graph with bipartite partition attributes.

    Raises:
        ValueError: If the graph lacks bipartite attributes.
    """

    def __init__(self, graph: nx.Graph) -> None:
        # Validate bipartite structure (or allow empty graph)
        if graph.number_of_nodes() > 0:
            bipartite_values = {
                data.get("bipartite") for _, data in graph.nodes(data=True)
            }
            if None in bipartite_values:
                raise ValueError(
                    "Graph contains nodes without bipartite attribute"
                )
        self._graph = graph

    @property
    def graph(self) -> nx.Graph:
        """Underlying networkx bipartite placement graph.

        Public read-only accessor for the internal graph. Prefer typed
        accessors (component_nodes, net_nodes, get_node_data, neighbors)
        when possible.
        """
        return self._graph

    @property
    def board_width(self) -> float:
        """Board width in mm from graph attributes."""
        return float(self._graph.graph.get("board_width", 0.0))

    @property
    def board_height(self) -> float:
        """Board height in mm from graph attributes."""
        return float(self._graph.graph.get("board_height", 0.0))

    @property
    def n_components(self) -> int:
        """Number of component nodes."""
        return len(self.component_nodes())

    @property
    def n_nets(self) -> int:
        """Number of net nodes."""
        return len(self.net_nodes())

    def component_nodes(self) -> list[str]:
        """Return node IDs where bipartite == 0 (component partition)."""
        return [
            node
            for node, data in self._graph.nodes(data=True)
            if data.get("bipartite") == 0
        ]

    def net_nodes(self) -> list[str]:
        """Return node IDs where bipartite == 1 (net partition)."""
        return [
            node
            for node, data in self._graph.nodes(data=True)
            if data.get("bipartite") == 1
        ]

    def get_component_features(
        self,
        board_width: float,
        board_height: float,
    ) -> numpy.ndarray:
        """Compute feature matrix for all component nodes.

        Args:
            board_width: Board width for position normalization.
            board_height: Board height for position normalization.

        Returns:
            float32 array of shape (n_components, COMP_FEATURE_DIM).
        """
        comp_ids = self.component_nodes()
        if not comp_ids:
            return numpy.zeros((0, COMP_FEATURE_DIM), dtype=float32)

        features = numpy.zeros((len(comp_ids), COMP_FEATURE_DIM), dtype=float32)
        for i, node_id in enumerate(comp_ids):
            data = self._graph.nodes[node_id]
            comp_spec: ComponentSpec = data["comp_spec"]
            features[i] = extract_component_features(
                comp_spec, board_width, board_height
            )
        return features

    def get_net_features(self) -> numpy.ndarray:
        """Compute feature matrix for all net nodes.

        Returns:
            float32 array of shape (n_nets, NET_FEATURE_DIM).
        """
        net_ids = self.net_nodes()
        if not net_ids:
            return numpy.zeros((0, NET_FEATURE_DIM), dtype=float32)

        # Collect all component specs for reference lookup
        comp_ids = self.component_nodes()
        all_components: list[ComponentSpec] = []
        for node_id in comp_ids:
            all_components.append(self._graph.nodes[node_id]["comp_spec"])

        features = numpy.zeros((len(net_ids), NET_FEATURE_DIM), dtype=float32)
        for i, node_id in enumerate(net_ids):
            data = self._graph.nodes[node_id]
            net_spec: NetSpec = data["net_spec"]
            features[i] = extract_net_features(net_spec, all_components)
        return features

    def get_adjacency_matrix(self) -> numpy.ndarray:
        """Compute binary adjacency matrix between components and nets.

        Returns:
            Binary array of shape (n_components, n_nets).
            Entry [i, j] = 1 if component i connects to net j.
        """
        comp_ids = self.component_nodes()
        net_ids = self.net_nodes()
        n_comp = len(comp_ids)
        n_net = len(net_ids)

        if n_comp == 0 or n_net == 0:
            return numpy.zeros((n_comp, n_net), dtype=float32)

        adj = numpy.zeros((n_comp, n_net), dtype=float32)
        net_index = {nid: j for j, nid in enumerate(net_ids)}

        for i, comp_id in enumerate(comp_ids):
            for neighbor in self._graph.neighbors(comp_id):
                if neighbor in net_index:
                    adj[i, net_index[neighbor]] = 1.0
        return adj

    def get_edge_weights(self) -> numpy.ndarray:
        """Compute weighted adjacency matrix with criticality weights.

        Returns:
            float32 array of shape (n_components, n_nets).
            Entry [i, j] = net j's criticality if connected, 0 otherwise.
        """
        comp_ids = self.component_nodes()
        net_ids = self.net_nodes()
        n_comp = len(comp_ids)
        n_net = len(net_ids)

        if n_comp == 0 or n_net == 0:
            return numpy.zeros((n_comp, n_net), dtype=float32)

        weights = numpy.zeros((n_comp, n_net), dtype=float32)
        net_index = {nid: j for j, nid in enumerate(net_ids)}

        for i, comp_id in enumerate(comp_ids):
            for neighbor in self._graph.neighbors(comp_id):
                if neighbor in net_index:
                    net_data = self._graph.nodes[neighbor]
                    criticality = net_data.get("criticality", 1.0)
                    weights[i, net_index[neighbor]] = criticality
        return weights


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _estimate_size_inline(comp: ComponentSpec) -> float:
    """Estimate component size (mirrors PlacementEngine._estimate_size)."""
    ref = comp.reference.upper()
    if ref.startswith("U"):
        return 10.0
    if ref.startswith("Q") or ref.startswith("TR"):
        return 8.0
    if ref.startswith("L") or ref.startswith("D"):
        return 5.0
    if ref.startswith("R") or ref.startswith("C"):
        return 2.0
    return 3.0


def _compute_criticality(net_name: str, is_power: bool) -> float:
    """Compute net criticality weight.

    Power nets get lower criticality (1.0) to avoid clustering artifacts.
    High-speed signal nets get higher criticality (3.0).
    Default signal nets get moderate criticality (2.0).
    """
    if is_power:
        return 1.0

    _HIGH_SPEED_KEYWORDS = frozenset({
        "SDA", "SCL", "CLK", "MOSI", "MISO", "CS", "TX", "RX",
        "USB", "HDMI", "SPI", "UART", "ETH", "SDIO",
    })
    name_upper = net_name.upper()
    if any(kw in name_upper for kw in _HIGH_SPEED_KEYWORDS):
        return 3.0

    return 2.0
