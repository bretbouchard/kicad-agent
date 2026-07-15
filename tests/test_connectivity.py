"""Test suite for connectivity graph analysis.

Tests NetGraph construction from PcbIR and all query methods
against the Arduino_Mega PCB fixture (79 nets, 14 footprints).
"""

from pathlib import Path

import pytest

from volta.analysis.connectivity import NetGraph, PadRef
from volta.ir.base import _clear_registry
from volta.ir.pcb_ir import PcbIR
from volta.parser import parse_pcb
from volta.parser.uuid_extractor import extract_uuids


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_pcb_ir(pcb_path: Path) -> PcbIR:
    """Build a PcbIR from a PCB file path (fresh registry each call)."""
    _clear_registry()
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


@pytest.fixture
def pcb_ir(arduino_mega_pcb: Path) -> PcbIR:
    """PcbIR built from Arduino_Mega.kicad_pcb."""
    return _make_pcb_ir(arduino_mega_pcb)


@pytest.fixture
def net_graph(pcb_ir: PcbIR) -> NetGraph:
    """NetGraph built from the Arduino_Mega PcbIR."""
    return NetGraph.from_pcb_ir(pcb_ir)


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


class TestGraphConstruction:
    """Tests 1-6: Graph is built correctly from PcbIR data."""

    def test_graph_non_empty(self, net_graph: NetGraph) -> None:
        """Test 1: NetGraph.from_pcb_ir creates a non-empty graph with nodes and edges."""
        assert net_graph.graph.number_of_nodes() > 0
        assert net_graph.graph.number_of_edges() > 0

    def test_nodes_are_pad_refs(self, net_graph: NetGraph) -> None:
        """Test 2: Graph nodes represent pads as (footprint_ref, pad_number) tuples."""
        for node in net_graph.graph.nodes():
            assert isinstance(node, tuple), f"Node {node!r} is not a tuple"
            assert len(node) == 2, f"Node {node!r} does not have 2 elements"
            footprint_ref, pad_number = node
            assert isinstance(footprint_ref, str), f"Footprint ref {footprint_ref!r} is not str"
            assert isinstance(pad_number, str), f"Pad number {pad_number!r} is not str"

    def test_edges_connect_same_net(self, net_graph: NetGraph) -> None:
        """Test 3: Graph edges connect pads that share the same net."""
        for u, v, data in net_graph.graph.edges(data=True):
            assert "net_name" in data, f"Edge ({u}, {v}) missing net_name attribute"
            net_name = data["net_name"]
            # Both endpoint nodes should have the same net_name
            u_net = net_graph.graph.nodes[u].get("net_name")
            v_net = net_graph.graph.nodes[v].get("net_name")
            assert u_net == net_name, f"Node {u} net_name {u_net} != edge net_name {net_name}"
            assert v_net == net_name, f"Node {v} net_name {v_net} != edge net_name {net_name}"

    def test_net_zero_excluded(self, pcb_ir: PcbIR) -> None:
        """Test 4: Net 0 (unconnected) pads are NOT connected by edges.

        Mounting holes (MH1-MH6) each have 1 pad with no net (or net 0).
        These pads should NOT appear as nodes in the graph.
        """
        graph = NetGraph.from_pcb_ir(pcb_ir)
        # Collect all pad numbers from mounting holes
        mh_pads: list[PadRef] = []
        for fp in pcb_ir.footprints:
            ref = fp.properties.get("Reference", "")
            if ref.startswith("MH"):
                for pad in fp.pads:
                    if pad.net is None or pad.net.number == 0:
                        mh_pads.append((ref, pad.number))

        # None of these should be graph nodes
        for mh_pad in mh_pads:
            assert mh_pad not in graph.graph.nodes(), (
                f"Unconnected pad {mh_pad} should not be a graph node"
            )

    def test_edge_has_net_name_attribute(self, net_graph: NetGraph) -> None:
        """Test 5: Each edge has a 'net_name' attribute."""
        for u, v, data in net_graph.graph.edges(data=True):
            assert "net_name" in data, f"Edge ({u}, {v}) has no net_name"
            assert isinstance(data["net_name"], str), f"Edge net_name is not str: {data['net_name']!r}"
            assert len(data["net_name"]) > 0, f"Edge net_name is empty"

    def test_node_has_attributes(self, net_graph: NetGraph) -> None:
        """Test 6: Each node has 'footprint_libid' and 'net_name' attributes."""
        for node, data in net_graph.graph.nodes(data=True):
            assert "footprint_libid" in data, f"Node {node} missing footprint_libid"
            assert "net_name" in data, f"Node {node} missing net_name"
            assert isinstance(data["footprint_libid"], str), (
                f"Node {node} footprint_libid is not str"
            )
            assert isinstance(data["net_name"], str), (
                f"Node {node} net_name is not str"
            )


# ---------------------------------------------------------------------------
# Connectivity Queries
# ---------------------------------------------------------------------------


class TestConnectivityQueries:
    """Tests 7-16: Query methods for connectivity analysis."""

    def test_get_connected_pads_gnd(self, net_graph: NetGraph) -> None:
        """Test 7: get_connected_pads('GND') returns all pad nodes on GND net.

        Arduino_Mega has 5 pads connected to GND.
        """
        gnd_pads = net_graph.get_connected_pads("GND")
        assert len(gnd_pads) == 5, f"Expected 5 GND pads, got {len(gnd_pads)}"
        # All returned pads should be PadRef tuples
        for pad_ref in gnd_pads:
            assert isinstance(pad_ref, tuple)
            assert len(pad_ref) == 2

    def test_get_connected_pads_nonexistent(self, net_graph: NetGraph) -> None:
        """Test 8: get_connected_pads for non-existent net returns empty list."""
        result = net_graph.get_connected_pads("NONEXISTENT_NET_XYZ")
        assert result == []

    def test_shortest_path_same_net(self, net_graph: NetGraph) -> None:
        """Test 9: shortest_path between pads on same net returns path.

        GND connects J7 pad 1, J7 pad 2, J1 pad 6, J1 pad 7, J2 pad 4.
        Path from J7 pad 1 to J1 pad 6 should exist.
        """
        source: PadRef = ("J7", "1")
        target: PadRef = ("J1", "6")
        path = net_graph.shortest_path(source, target)
        assert len(path) > 0, "Expected a path between GND-connected pads"
        assert path[0] == source, f"Path should start at {source}"
        assert path[-1] == target, f"Path should end at {target}"

    def test_shortest_path_different_nets(self, net_graph: NetGraph) -> None:
        """Test 10: shortest_path between pads on different nets returns empty list."""
        # J7 pad 1 is GND, J7 pad 3 is /*52 -- different nets, no path
        source: PadRef = ("J7", "1")
        target: PadRef = ("J7", "3")
        path = net_graph.shortest_path(source, target)
        assert path == [], f"Expected empty path for pads on different nets, got {path}"

    def test_shortest_path_direct_connection(self, net_graph: NetGraph) -> None:
        """Test 11: shortest_path between pads on same net returns direct connection.

        Two pads on the same net should be directly connected (path length 2:
        source -> target).
        """
        source: PadRef = ("J7", "1")
        target: PadRef = ("J7", "2")
        # Both on GND
        path = net_graph.shortest_path(source, target)
        assert len(path) == 2, f"Expected direct connection (path len 2), got {path}"

    def test_get_connectivity_components(self, net_graph: NetGraph) -> None:
        """Test 12: get_connectivity_components returns list of sets, each is an island."""
        components = net_graph.get_connectivity_components()
        assert len(components) > 0, "Expected at least one connectivity component"
        for comp in components:
            assert isinstance(comp, set), f"Component {comp!r} is not a set"
            assert len(comp) > 0, "Component should not be empty"

    def test_gnd_is_single_component(self, net_graph: NetGraph) -> None:
        """Test 13: GND net (many pads) forms a single connectivity component.

        All GND pads should be in the same component.
        """
        gnd_pads = set(net_graph.get_connected_pads("GND"))
        assert len(gnd_pads) > 0, "GND should have connected pads"

        components = net_graph.get_connectivity_components()
        # Find the component containing the first GND pad
        first_gnd = next(iter(gnd_pads))
        containing_component = None
        for comp in components:
            if first_gnd in comp:
                containing_component = comp
                break

        assert containing_component is not None, "GND pad not found in any component"
        # All GND pads should be in the same component
        for pad in gnd_pads:
            assert pad in containing_component, (
                f"GND pad {pad} not in same component as {first_gnd}"
            )

    def test_get_net_stats(self, net_graph: NetGraph) -> None:
        """Test 14: get_net_stats returns dict with total_nets, total_pads, total_connections."""
        stats = net_graph.get_net_stats()
        assert "total_nets" in stats
        assert "total_pads" in stats
        assert "total_connections" in stats

        assert isinstance(stats["total_nets"], int)
        assert isinstance(stats["total_pads"], int)
        assert isinstance(stats["total_connections"], int)

        assert stats["total_nets"] > 0, "Expected at least one net"
        assert stats["total_pads"] > 0, "Expected at least one pad"
        assert stats["total_connections"] > 0, "Expected at least one connection"

        # total_pads should match node count
        assert stats["total_pads"] == net_graph.graph.number_of_nodes()
        # total_connections should match edge count
        assert stats["total_connections"] == net_graph.graph.number_of_edges()

    def test_are_connected_same_net(self, net_graph: NetGraph) -> None:
        """Test 15: are_connected(pad_a, pad_b) returns True for pads on same net."""
        # J7 pad 1 and J7 pad 2 are both on GND
        result = net_graph.are_connected(("J7", "1"), ("J7", "2"))
        assert result is True, "Expected GND pads to be connected"

    def test_are_connected_different_nets(self, net_graph: NetGraph) -> None:
        """Test 16: are_connected(pad_a, pad_b) returns False for pads on different nets."""
        # J7 pad 1 is GND, J7 pad 3 is /*52
        result = net_graph.are_connected(("J7", "1"), ("J7", "3"))
        assert result is False, "Expected pads on different nets to not be connected"
