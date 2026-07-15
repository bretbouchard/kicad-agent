"""Tests for bipartite placement graph construction and feature extraction.

Validates:
- Bipartite partition attributes
- Node and edge counts
- Power net criticality (lower than signal)
- Component and net feature shapes and values
- Adjacency matrix correctness
- Edge cases (empty netlist, count caps, invalid dims)
"""

import pytest

from volta.generation.intent import ComponentSpec, PositionSpec, NetSpec
from volta.placement.features import (
    COMP_FEATURE_DIM,
    NET_FEATURE_DIM,
    extract_component_features,
    extract_net_features,
)
from volta.placement.graph import (
    PlacementGraph,
    netlist_to_placement_graph,
)


# -----------------------------------------------------------------------
# Graph structure tests
# -----------------------------------------------------------------------


class TestBipartiteStructure:
    """Validate bipartite partition and node counts."""

    def test_netlist_to_graph_bipartite(
        self,
        sample_components: list[ComponentSpec],
        sample_nets: list[NetSpec],
        sample_board_dims: tuple[float, float],
    ):
        """Component nodes have bipartite=0, net nodes have bipartite=1."""
        width, height = sample_board_dims
        graph = netlist_to_placement_graph(
            sample_components, sample_nets, width, height
        )

        for node, data in graph.nodes(data=True):
            if data["node_type"] == "component":
                assert data["bipartite"] == 0, (
                    f"Component node {node} should have bipartite=0"
                )
            elif data["node_type"] == "net":
                assert data["bipartite"] == 1, (
                    f"Net node {node} should have bipartite=1"
                )

    def test_netlist_to_graph_node_counts(
        self,
        sample_components: list[ComponentSpec],
        sample_nets: list[NetSpec],
        sample_board_dims: tuple[float, float],
    ):
        """5 components + 3 nets = 8 total nodes."""
        width, height = sample_board_dims
        graph = netlist_to_placement_graph(
            sample_components, sample_nets, width, height
        )

        comp_nodes = [
            n for n, d in graph.nodes(data=True) if d.get("bipartite") == 0
        ]
        net_nodes = [
            n for n, d in graph.nodes(data=True) if d.get("bipartite") == 1
        ]

        assert len(comp_nodes) == 5
        assert len(net_nodes) == 3
        assert graph.number_of_nodes() == 8

    def test_netlist_to_graph_edge_counts(
        self,
        sample_components: list[ComponentSpec],
        sample_nets: list[NetSpec],
        sample_board_dims: tuple[float, float],
    ):
        """GND: 3 edges, SDA: 2 edges, VCC: 2 edges = 7 total."""
        width, height = sample_board_dims
        graph = netlist_to_placement_graph(
            sample_components, sample_nets, width, height
        )

        assert graph.number_of_edges() == 7

    def test_netlist_to_graph_power_net_criticality(
        self,
        sample_components: list[ComponentSpec],
        sample_nets: list[NetSpec],
        sample_board_dims: tuple[float, float],
    ):
        """Power nets have low criticality, signal nets have higher."""
        width, height = sample_board_dims
        graph = netlist_to_placement_graph(
            sample_components, sample_nets, width, height
        )

        for node, data in graph.nodes(data=True):
            if data["node_type"] != "net":
                continue
            if data["name"] in ("GND", "VCC"):
                assert data["criticality"] <= 1.5, (
                    f"Power net {data['name']} criticality should be <= 1.5, "
                    f"got {data['criticality']}"
                )
                assert data["is_power"] is True
            elif data["name"] == "SDA":
                assert data["criticality"] >= 1.5, (
                    f"SDA net criticality should be >= 1.5, "
                    f"got {data['criticality']}"
                )
                assert data["is_power"] is False


# -----------------------------------------------------------------------
# Component feature tests
# -----------------------------------------------------------------------


class TestComponentFeatures:
    """Validate component feature extraction."""

    def test_component_features_shape(self, sample_components: list[ComponentSpec]):
        """Feature vector has shape (32,)."""
        comp = sample_components[0]  # U1
        features = extract_component_features(comp, 100.0, 80.0)
        assert features.shape == (COMP_FEATURE_DIM,)
        assert COMP_FEATURE_DIM == 32

    def test_component_features_ic_size(self, sample_components: list[ComponentSpec]):
        """U1 (IC) has estimated_size == 10.0."""
        u1 = sample_components[0]
        features = extract_component_features(u1, 100.0, 80.0)
        assert features[0] == 10.0

    def test_component_features_passive_size(
        self, sample_components: list[ComponentSpec]
    ):
        """R1 (resistor) has estimated_size == 2.0."""
        r1 = sample_components[1]
        features = extract_component_features(r1, 100.0, 80.0)
        assert features[0] == 2.0

    def test_component_features_fixed_position(self):
        """Component with fixed position has is_fixed==1.0 and normalized coords."""
        comp = ComponentSpec(
            library_id="Device:R",
            reference="R10",
            value="1k",
            position=PositionSpec(x=50.0, y=40.0),
        )
        features = extract_component_features(comp, 100.0, 80.0)

        assert features[4] == 1.0  # is_fixed
        assert abs(features[5] - 0.5) < 1e-6  # normalized x = 50/100
        assert abs(features[6] - 0.5) < 1e-6  # normalized y = 40/80
        assert 0.0 <= features[5] <= 1.0
        assert 0.0 <= features[6] <= 1.0

    def test_component_features_type_flags(self, sample_components: list[ComponentSpec]):
        """Type flags set correctly for different component types."""
        u1 = sample_components[0]  # IC
        r1 = sample_components[1]  # Resistor
        c1 = sample_components[2]  # Capacitor
        j1 = sample_components[3]  # Connector

        u1_feat = extract_component_features(u1, 100.0, 80.0)
        r1_feat = extract_component_features(r1, 100.0, 80.0)
        c1_feat = extract_component_features(c1, 100.0, 80.0)
        j1_feat = extract_component_features(j1, 100.0, 80.0)

        # U1 is IC, not passive, not connector
        assert u1_feat[1] == 1.0  # is_ic
        assert u1_feat[2] == 0.0  # not passive
        assert u1_feat[3] == 0.0  # not connector

        # R1 is passive, not IC
        assert r1_feat[1] == 0.0  # not IC
        assert r1_feat[2] == 1.0  # is passive

        # C1 is passive, not IC
        assert c1_feat[2] == 1.0  # is passive

        # J1 is connector
        assert j1_feat[3] == 1.0  # is connector

    def test_component_features_library_hash(self, sample_components: list[ComponentSpec]):
        """Library ID character hash in features[7:15]."""
        u1 = sample_components[0]
        features = extract_component_features(u1, 100.0, 80.0)
        # First char of "MCU_ST:STM32F103" is 'M', ord('M')=77
        assert abs(features[7] - 77.0 / 255.0) < 1e-6


# -----------------------------------------------------------------------
# Net feature tests
# -----------------------------------------------------------------------


class TestNetFeatures:
    """Validate net feature extraction."""

    def test_net_features_shape(
        self,
        sample_nets: list[NetSpec],
        sample_components: list[ComponentSpec],
    ):
        """Feature vector has shape (16,)."""
        net = sample_nets[0]  # SDA
        features = extract_net_features(net, sample_components)
        assert features.shape == (NET_FEATURE_DIM,)
        assert NET_FEATURE_DIM == 16

    def test_net_features_power_flag(
        self,
        sample_nets: list[NetSpec],
        sample_components: list[ComponentSpec],
    ):
        """GND net has is_power==1.0."""
        gnd_net = sample_nets[1]  # GND
        features = extract_net_features(gnd_net, sample_components)
        assert features[2] == 1.0  # is_power

    def test_net_features_pin_count(
        self,
        sample_nets: list[NetSpec],
        sample_components: list[ComponentSpec],
    ):
        """GND net has 3 pins."""
        gnd_net = sample_nets[1]  # GND
        features = extract_net_features(gnd_net, sample_components)
        assert features[0] == 3.0  # pin_count

    def test_net_features_component_count(
        self,
        sample_nets: list[NetSpec],
        sample_components: list[ComponentSpec],
    ):
        """GND net connects U1, C1, J1 = 3 unique components."""
        gnd_net = sample_nets[1]  # GND
        features = extract_net_features(gnd_net, sample_components)
        assert features[1] == 3.0  # component_count

    def test_net_features_criticality_signal(
        self,
        sample_nets: list[NetSpec],
        sample_components: list[ComponentSpec],
    ):
        """SDA (high-speed signal) has criticality 3.0."""
        sda_net = sample_nets[0]  # SDA
        features = extract_net_features(sda_net, sample_components)
        assert features[3] == 3.0  # criticality for high-speed

    def test_net_features_criticality_power(
        self,
        sample_nets: list[NetSpec],
        sample_components: list[ComponentSpec],
    ):
        """GND (power) has criticality 1.0."""
        gnd_net = sample_nets[1]  # GND
        features = extract_net_features(gnd_net, sample_components)
        assert features[3] == 1.0  # criticality for power


# -----------------------------------------------------------------------
# PlacementGraph wrapper tests
# -----------------------------------------------------------------------


class TestPlacementGraph:
    """Validate PlacementGraph wrapper methods."""

    def test_placement_graph_adjacency(self, sample_placement_graph: PlacementGraph):
        """Adjacency matrix has correct shape (5, 3). U1 connects to all 3 nets."""
        adj = sample_placement_graph.get_adjacency_matrix()

        assert adj.shape == (5, 3)

        # U1 is at index 0 (first component node)
        u1_row = adj[0]
        assert u1_row.sum() == 3.0, "U1 should connect to all 3 nets"

    def test_placement_graph_properties(self, sample_placement_graph: PlacementGraph):
        """Properties return correct values from graph attributes."""
        assert sample_placement_graph.board_width == 100.0
        assert sample_placement_graph.board_height == 80.0
        assert sample_placement_graph.n_components == 5
        assert sample_placement_graph.n_nets == 3

    def test_placement_graph_features(
        self,
        sample_placement_graph: PlacementGraph,
        sample_board_dims: tuple[float, float],
    ):
        """Feature matrices have correct shapes."""
        width, height = sample_board_dims
        comp_features = sample_placement_graph.get_component_features(width, height)
        net_features = sample_placement_graph.get_net_features()

        assert comp_features.shape == (5, COMP_FEATURE_DIM)
        assert net_features.shape == (3, NET_FEATURE_DIM)

    def test_placement_graph_edge_weights(self, sample_placement_graph: PlacementGraph):
        """Edge weights matrix has correct shape and uses criticality values."""
        weights = sample_placement_graph.get_edge_weights()

        assert weights.shape == (5, 3)
        # All weights should be > 0 for connected pairs
        assert (weights > 0).any()


# -----------------------------------------------------------------------
# Edge cases and validation
# -----------------------------------------------------------------------


class TestEdgeCases:
    """Validate error handling and boundary conditions."""

    def test_empty_netlist(self):
        """Empty components + empty nets produces graph with 0 nodes."""
        graph = netlist_to_placement_graph([], [], 100.0, 80.0)
        pg = PlacementGraph(graph)

        assert pg.n_components == 0
        assert pg.n_nets == 0
        assert graph.number_of_nodes() == 0

    def test_component_count_cap(self):
        """501 components raises ValueError."""
        components = [
            ComponentSpec(library_id=f"Device:R", reference=f"R{i}")
            for i in range(501)
        ]
        with pytest.raises(ValueError, match="Component count 501 exceeds maximum"):
            netlist_to_placement_graph(components, [], 100.0, 80.0)

    def test_invalid_board_dims(self):
        """Zero or negative board dimensions raise ValueError."""
        with pytest.raises(ValueError, match="Board dimensions must be positive"):
            netlist_to_placement_graph([], [], 0.0, 80.0)

        with pytest.raises(ValueError, match="Board dimensions must be positive"):
            netlist_to_placement_graph([], [], 100.0, -10.0)

    def test_unfixed_component_zero_position(self):
        """Unfixed component features have zero normalized position."""
        comp = ComponentSpec(
            library_id="Device:R",
            reference="R99",
            value="1k",
        )
        features = extract_component_features(comp, 100.0, 80.0)

        assert features[4] == 0.0  # is_fixed
        assert features[5] == 0.0  # normalized_x
        assert features[6] == 0.0  # normalized_y
