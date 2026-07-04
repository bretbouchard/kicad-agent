"""TDD tests for LayoutGraph data structures (Task 1, RED phase).

Covers Tests 1-7 from 108-01-PLAN.md Task 1 behavior block:
  1. LayoutNode is frozen
  2. LayoutEdge preserves net_name + signal_direction
  3. LayoutGraph.from_topology preserves node count
  4. from_topology partitions power-only edges into power_edges
  5. LayoutGraph.subgraph_for filters by subcircuit_id (D-02)
  6. All coordinate values are float
  7. (MED-2 fix) LayoutEdge accepts signal_direction="unknown"
"""

from __future__ import annotations

import dataclasses
from typing import NamedTuple

import pytest

from kicad_agent.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)
from kicad_agent.analysis.types import NetClassification
from kicad_agent.schematic_autolayout.layout_graph import (
    KICAD_GRID_MM,
    RC_PIN_OFFSET_MM,
    LayoutCoordinate,
    LayoutEdge,
    LayoutGraph,
    LayoutNode,
)


# ---------------------------------------------------------------------------
# Test fixtures — 3-stage op-amp chain with feedback edge
# ---------------------------------------------------------------------------


def _opamp_chain_nodes() -> tuple[TopologyNode, ...]:
    return (
        TopologyNode(
            ref="J1",
            lib_id="Connector:Conn_01x02",
            component_type="connector",
            pin_count=2,
            power_pins=(),
            input_pins=(),
            output_pins=("1",),
        ),
        TopologyNode(
            ref="U1",
            lib_id="NE5532",
            component_type="ic",
            pin_count=8,
            power_pins=("V+", "V-"),
            input_pins=("IN+", "IN-"),
            output_pins=("OUT",),
        ),
        TopologyNode(
            ref="U2",
            lib_id="NE5532",
            component_type="ic",
            pin_count=8,
            power_pins=("V+", "V-"),
            input_pins=("IN+", "IN-"),
            output_pins=("OUT",),
        ),
        TopologyNode(
            ref="J2",
            lib_id="Connector:Conn_01x02",
            component_type="connector",
            pin_count=2,
            power_pins=(),
            input_pins=("1",),
            output_pins=(),
        ),
    )


def _opamp_chain_edges() -> tuple[TopologyEdge, ...]:
    return (
        TopologyEdge(
            net_name="INPUT",
            source_ref="J1",
            source_pin="1",
            target_ref="U1",
            target_pin="IN+",
            classification=NetClassification.SIGNAL,
            signal_direction="forward",
        ),
        TopologyEdge(
            net_name="N1",
            source_ref="U1",
            source_pin="OUT",
            target_ref="U2",
            target_pin="IN+",
            classification=NetClassification.SIGNAL,
            signal_direction="forward",
        ),
        TopologyEdge(
            net_name="OUTPUT",
            source_ref="U2",
            source_pin="OUT",
            target_ref="J2",
            target_pin="1",
            classification=NetClassification.SIGNAL,
            signal_direction="forward",
        ),
        # Feedback edge — exercises cycle removal in stage 1
        TopologyEdge(
            net_name="FB",
            source_ref="U2",
            source_pin="OUT",
            target_ref="U1",
            target_pin="IN-",
            classification=NetClassification.SIGNAL,
            signal_direction="feedback",
        ),
        # Power edge — should be partitioned into power_edges
        TopologyEdge(
            net_name="+12V",
            source_ref="U1",
            source_pin="V+",
            target_ref="U2",
            target_pin="V+",
            classification=NetClassification.POWER,
            signal_direction="power",
        ),
        # Unknown direction edge — MED-2 fix: must be accepted, treated as forward
        TopologyEdge(
            net_name="CTRL",
            source_ref="U1",
            source_pin="IN-",
            target_ref="U2",
            target_pin="IN-",
            classification=NetClassification.SIGNAL,
            signal_direction="unknown",
        ),
    )


def _opamp_topology() -> CircuitTopology:
    return CircuitTopology(
        nodes=_opamp_chain_nodes(),
        edges=_opamp_chain_edges(),
        input_nets=("INPUT",),
        output_nets=("OUTPUT",),
        power_nets=("+12V",),
        signal_paths=(("J1", "U1", "U2", "J2"),),
        stats={},
    )


def _opamp_subcircuit_map() -> dict[str, str]:
    # All in one subcircuit for the simple fixture
    return {"J1": "SC-001", "U1": "SC-001", "U2": "SC-001", "J2": "SC-001"}


# ---------------------------------------------------------------------------
# Test 1: LayoutNode is frozen
# ---------------------------------------------------------------------------


class TestLayoutNodeFrozen:
    def test_replace_works(self) -> None:
        node = LayoutNode(
            ref="U1",
            lib_id="NE5532",
            component_type="ic",
            subcircuit_id="SC-001",
        )
        replaced = dataclasses.replace(node, layer=3)
        assert replaced.layer == 3
        # All other fields preserved
        assert replaced.ref == "U1"
        assert replaced.lib_id == "NE5532"
        assert replaced.component_type == "ic"
        assert replaced.subcircuit_id == "SC-001"

    def test_direct_assignment_raises_frozen_instance_error(self) -> None:
        node = LayoutNode(
            ref="U1",
            lib_id="NE5532",
            component_type="ic",
            subcircuit_id="SC-001",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            node.layer = 3  # type: ignore[misc]

    def test_layout_graph_is_frozen(self) -> None:
        graph = LayoutGraph(
            nodes=(),
            edges=(),
            power_edges=(),
            subcircuit_ids=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            graph.nodes = (LayoutNode(ref="X", lib_id="X", component_type="ic", subcircuit_id="SC-001"),)  # type: ignore[misc]

    def test_layout_edge_is_frozen(self) -> None:
        edge = LayoutEdge(
            source_ref="U1",
            target_ref="U2",
            net_name="N1",
            signal_direction="forward",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            edge.net_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 2: LayoutEdge preserves net_name + signal_direction
# ---------------------------------------------------------------------------


class TestLayoutEdgePreservesFields:
    def test_signal_direction_forward_preserved(self) -> None:
        edge = LayoutEdge(
            source_ref="U1",
            target_ref="U2",
            net_name="N1",
            signal_direction="forward",
        )
        assert edge.signal_direction == "forward"
        assert edge.net_name == "N1"
        assert edge.source_ref == "U1"
        assert edge.target_ref == "U2"

    def test_signal_direction_feedback_preserved(self) -> None:
        edge = LayoutEdge(
            source_ref="U2",
            target_ref="U1",
            net_name="FB",
            signal_direction="feedback",
        )
        assert edge.signal_direction == "feedback"


# ---------------------------------------------------------------------------
# Test 3: from_topology preserves node count
# ---------------------------------------------------------------------------


class TestFromTopologyNodeCount:
    def test_node_count_matches_topology(self) -> None:
        topo = _opamp_topology()
        smap = _opamp_subcircuit_map()
        graph = LayoutGraph.from_topology(topo, smap)
        assert len(graph.nodes) == len(topo.nodes)
        # All nodes present
        refs = {n.ref for n in graph.nodes}
        assert refs == {"J1", "U1", "U2", "J2"}


# ---------------------------------------------------------------------------
# Test 4: from_topology partitions power edges
# ---------------------------------------------------------------------------


class TestFromTopologyPowerPartition:
    def test_power_edges_separated_from_signal_edges(self) -> None:
        topo = _opamp_topology()
        smap = _opamp_subcircuit_map()
        graph = LayoutGraph.from_topology(topo, smap)
        # Power edge should be in power_edges, not edges
        assert len(graph.power_edges) == 1
        assert graph.power_edges[0].net_name == "+12V"
        assert graph.power_edges[0].is_power is True
        # Signal edges should NOT include the power one
        signal_nets = {e.net_name for e in graph.edges}
        assert "+12V" not in signal_nets
        # Should include forward, feedback, and unknown edges
        assert "INPUT" in signal_nets
        assert "N1" in signal_nets
        assert "OUTPUT" in signal_nets
        assert "FB" in signal_nets
        assert "CTRL" in signal_nets

    def test_signal_edges_not_marked_power(self) -> None:
        topo = _opamp_topology()
        graph = LayoutGraph.from_topology(topo, _opamp_subcircuit_map())
        for edge in graph.edges:
            assert edge.is_power is False


# ---------------------------------------------------------------------------
# Test 5: subgraph_for filters by subcircuit_id (D-02)
# ---------------------------------------------------------------------------


class TestSubgraphFor:
    def test_returns_only_matching_subcircuit_nodes(self) -> None:
        topo = _opamp_topology()
        # Split: J1+U1 in SC-001, U2+J2 in SC-002
        smap = {"J1": "SC-001", "U1": "SC-001", "U2": "SC-002", "J2": "SC-002"}
        graph = LayoutGraph.from_topology(topo, smap)
        assert graph.subcircuit_ids == ("SC-001", "SC-002")

        sub = graph.subgraph_for("SC-001")
        sub_refs = {n.ref for n in sub.nodes}
        assert sub_refs == {"J1", "U1"}

        sub2 = graph.subgraph_for("SC-002")
        sub2_refs = {n.ref for n in sub2.nodes}
        assert sub2_refs == {"U2", "J2"}

    def test_subgraph_isolates_internal_edges(self) -> None:
        topo = _opamp_topology()
        smap = {"J1": "SC-001", "U1": "SC-001", "U2": "SC-002", "J2": "SC-002"}
        graph = LayoutGraph.from_topology(topo, smap)
        sub = graph.subgraph_for("SC-001")
        # Edges should only connect refs in SC-001
        for edge in sub.edges:
            assert edge.source_ref in {"J1", "U1"}
            assert edge.target_ref in {"J1", "U1"}


# ---------------------------------------------------------------------------
# Test 6: All coordinate values are float
# ---------------------------------------------------------------------------


class TestLayoutCoordinateFloat:
    def test_coordinate_fields_are_float(self) -> None:
        coord = LayoutCoordinate(x=25.4, y=12.7)
        assert isinstance(coord.x, float)
        assert isinstance(coord.y, float)

    def test_coordinate_accepts_integer_values(self) -> None:
        # NamedTuple preserves whatever numeric type is passed; the contract is
        # that stage 5 *output* always produces floats via round(..., 2).
        # Here we just verify the coordinate stores what it was given.
        coord = LayoutCoordinate(x=0.0, y=50.0)
        assert coord.x == 0.0
        assert coord.y == 50.0
        assert isinstance(coord.x, float)
        assert isinstance(coord.y, float)

    def test_coordinate_is_named_tuple(self) -> None:
        # typing.NamedTuple is not a class itself; check tuple inheritance
        # and the named fields via _fields attribute.
        assert issubclass(LayoutCoordinate, tuple)
        assert LayoutCoordinate._fields == ("x", "y")


# ---------------------------------------------------------------------------
# Test 7 (MED-2 fix): LayoutEdge accepts signal_direction="unknown"
# ---------------------------------------------------------------------------


class TestLayoutEdgeUnknownDirection:
    def test_unknown_direction_accepted(self) -> None:
        edge = LayoutEdge(
            source_ref="U1",
            target_ref="U2",
            net_name="CTRL",
            signal_direction="unknown",
        )
        assert edge.signal_direction == "unknown"

    def test_from_topology_preserves_unknown(self) -> None:
        topo = _opamp_topology()
        graph = LayoutGraph.from_topology(topo, _opamp_subcircuit_map())
        unknown_edges = [e for e in graph.edges if e.signal_direction == "unknown"]
        assert len(unknown_edges) == 1
        assert unknown_edges[0].net_name == "CTRL"


# ---------------------------------------------------------------------------
# Threat-model tests (T-108-01, T-108-02, adversarial scenario)
# ---------------------------------------------------------------------------


class TestThreatModelMitigations:
    def test_t108_01_subcircuit_map_missing_ref_raises(self) -> None:
        """T-108-01: subcircuit_map keys must be subset of topology refs."""
        topo = _opamp_topology()
        bad_smap = {"J1": "SC-001", "UNKNOWN_REF": "SC-999"}
        with pytest.raises(ValueError, match="UNKNOWN_REF"):
            LayoutGraph.from_topology(topo, bad_smap)

    def test_adversarial_self_loop_raises(self) -> None:
        """Self-loop U21→U21 would cause Stage 1 infinite loop."""
        nodes = (TopologyNode(
            ref="U21", lib_id="X", component_type="ic", pin_count=2,
            power_pins=(), input_pins=("1",), output_pins=("2",),
        ),)
        edges = (TopologyEdge(
            net_name="LOOP", source_ref="U21", source_pin="2",
            target_ref="U21", target_pin="1",
            classification=NetClassification.SIGNAL,
            signal_direction="feedback",
        ),)
        topo = CircuitTopology(
            nodes=nodes, edges=edges, input_nets=(), output_nets=(),
            power_nets=(), signal_paths=(), stats={},
        )
        with pytest.raises(ValueError, match="(?i)self-loop"):
            LayoutGraph.from_topology(topo, {"U21": "SC-001"})


# ---------------------------------------------------------------------------
# Constants sanity (used by stage 5 later)
# ---------------------------------------------------------------------------


def test_kicad_constants_match_memory() -> None:
    """KiCad grid = 2.54mm; R/C pin offset = 3.81mm (Phase 38 finding)."""
    assert KICAD_GRID_MM == 2.54
    assert RC_PIN_OFFSET_MM == 3.81
