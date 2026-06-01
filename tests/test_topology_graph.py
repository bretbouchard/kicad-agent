"""Tests for circuit topology graph with signal flow direction inference.

DOMAIN-01: TopologyBuilder produces CircuitTopology from SchematicGraph
with directed signal flow inferred from IC pin types.
"""

from kicad_agent.schematic_routing.schematic_graph import (
    SchematicGraph,
    PinPosition,
    Wire,
    Label,
)

from kicad_agent.analysis.types import NetClassification, PinRole


# ---------------------------------------------------------------------------
# Test helpers -- mock SchematicGraph factories
# ---------------------------------------------------------------------------


def _empty_graph() -> SchematicGraph:
    """Empty schematic with no components."""
    return SchematicGraph(filepath="test.kicad_sch")


def _single_resistor_graph() -> SchematicGraph:
    """Single resistor R1 with two pins."""
    return SchematicGraph(
        filepath="test.kicad_sch",
        pins=[
            PinPosition(
                ref="R1",
                pin_number="1",
                pin_name="1",
                position=(50.0, 50.0),
                body_position=(50.0, 45.0),
            ),
            PinPosition(
                ref="R1",
                pin_number="2",
                pin_name="2",
                position=(60.0, 50.0),
                body_position=(60.0, 45.0),
            ),
        ],
        ref_to_libid={"R1": "Device:R"},
    )


# ---------------------------------------------------------------------------
# Test: NetClassification enum values
# ---------------------------------------------------------------------------


class TestNetClassification:
    """NetClassification enum has required values."""

    def test_power_exists(self):
        assert NetClassification.POWER == "POWER"

    def test_ground_exists(self):
        assert NetClassification.GROUND == "GROUND"

    def test_signal_exists(self):
        assert NetClassification.SIGNAL == "SIGNAL"

    def test_control_exists(self):
        assert NetClassification.CONTROL == "CONTROL"

    def test_feedback_exists(self):
        assert NetClassification.FEEDBACK == "FEEDBACK"

    def test_clock_exists(self):
        assert NetClassification.CLOCK == "CLOCK"

    def test_unknown_exists(self):
        assert NetClassification.UNKNOWN == "UNKNOWN"


# ---------------------------------------------------------------------------
# Test: PinRole enum values
# ---------------------------------------------------------------------------


class TestPinRole:
    """PinRole enum has required values."""

    def test_input_exists(self):
        assert PinRole.INPUT == "INPUT"

    def test_output_exists(self):
        assert PinRole.OUTPUT == "OUTPUT"

    def test_power_exists(self):
        assert PinRole.POWER == "POWER"

    def test_bidirectional_exists(self):
        assert PinRole.BIDIRECTIONAL == "BIDIRECTIONAL"

    def test_control_exists(self):
        assert PinRole.CONTROL == "CONTROL"

    def test_unknown_exists(self):
        assert PinRole.UNKNOWN == "UNKNOWN"


# ---------------------------------------------------------------------------
# Test: TopologyNode schema
# ---------------------------------------------------------------------------


class TestTopologyNodeSchema:
    """TopologyNode frozen dataclass fields."""

    def test_create_node(self):
        from kicad_agent.analysis.topology_graph import TopologyNode

        node = TopologyNode(
            ref="U1",
            lib_id="NE5532",
            component_type="ic",
            pin_count=8,
            power_pins=("4", "8"),
            input_pins=("2", "3"),
            output_pins=("1",),
        )
        assert node.ref == "U1"
        assert node.component_type == "ic"
        assert node.pin_count == 8
        assert len(node.power_pins) == 2

    def test_node_is_frozen(self):
        from kicad_agent.analysis.topology_graph import TopologyNode

        node = TopologyNode(
            ref="R1",
            lib_id="Device:R",
            component_type="resistor",
            pin_count=2,
            power_pins=(),
            input_pins=(),
            output_pins=(),
        )
        try:
            node.ref = "R2"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Test: TopologyEdge schema
# ---------------------------------------------------------------------------


class TestTopologyEdgeSchema:
    """TopologyEdge frozen dataclass fields."""

    def test_create_edge(self):
        from kicad_agent.analysis.topology_graph import TopologyEdge

        edge = TopologyEdge(
            net_name="SIG_IN",
            source_ref="U1",
            source_pin="1",
            target_ref="R1",
            target_pin="1",
            classification=NetClassification.SIGNAL,
            signal_direction="forward",
        )
        assert edge.net_name == "SIG_IN"
        assert edge.source_ref == "U1"
        assert edge.classification == NetClassification.SIGNAL

    def test_edge_is_frozen(self):
        from kicad_agent.analysis.topology_graph import TopologyEdge

        edge = TopologyEdge(
            net_name="VCC",
            source_ref="PWR1",
            source_pin="1",
            target_ref="U1",
            target_pin="8",
            classification=NetClassification.POWER,
            signal_direction="power",
        )
        try:
            edge.net_name = "GND"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Test: CircuitTopology schema
# ---------------------------------------------------------------------------


class TestCircuitTopologySchema:
    """CircuitTopology frozen dataclass fields."""

    def test_create_empty_topology(self):
        from kicad_agent.analysis.topology_graph import CircuitTopology

        topo = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )
        assert len(topo.nodes) == 0
        assert len(topo.edges) == 0

    def test_topology_is_frozen(self):
        from kicad_agent.analysis.topology_graph import CircuitTopology

        topo = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )
        try:
            topo.nodes = ()  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Test: TopologyBuilder with empty graph
# ---------------------------------------------------------------------------


class TestTopologyBuilderEmpty:
    """TopologyBuilder handles empty schematic."""

    def test_empty_graph_returns_empty_topology(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_empty_graph())
        assert len(topo.nodes) == 0
        assert len(topo.edges) == 0
        assert len(topo.signal_paths) == 0

    def test_empty_stats(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_empty_graph())
        assert topo.stats["component_count"] == 0
        assert topo.stats["net_count"] == 0


# ---------------------------------------------------------------------------
# Test: TopologyBuilder with single component
# ---------------------------------------------------------------------------


class TestTopologyBuilderSingleNode:
    """TopologyBuilder creates a node for a single component."""

    def test_single_resistor_produces_one_node(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_single_resistor_graph())
        assert len(topo.nodes) == 1
        assert topo.nodes[0].ref == "R1"

    def test_single_resistor_no_edges(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_single_resistor_graph())
        assert len(topo.edges) == 0

    def test_single_resistor_is_passive(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_single_resistor_graph())
        assert topo.nodes[0].component_type == "resistor"

    def test_single_resistor_two_pins(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_single_resistor_graph())
        assert topo.nodes[0].pin_count == 2


# ---------------------------------------------------------------------------
# Test: Component type mapping from lib_id
# ---------------------------------------------------------------------------


class TestComponentTypeMapping:
    """Component type is correctly derived from lib_id."""

    def test_resistor(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:R") == "resistor"

    def test_capacitor(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:C") == "capacitor"

    def test_inductor(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:L") == "inductor"

    def test_diode(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:D") == "diode"

    def test_transistor(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:Q_NPN") == "transistor"

    def test_connector(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Connector:Conn_01x02") == "connector"

    def test_ic_from_lib_id(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Amplifier_Operational:NE5532") == "ic"

    def test_ic_from_part_number(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("NE5532") == "ic"

    def test_ic_rp2040(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("RP2040") == "ic"

    def test_misc_fallback(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("SomeUnknownPart") == "misc"

    def test_led(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:LED") == "diode"

    def test_crystal(self):
        from kicad_agent.analysis.topology_graph import _classify_component_type

        assert _classify_component_type("Device:Crystal") == "misc"
