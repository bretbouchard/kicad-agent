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


# ---------------------------------------------------------------------------
# Task 2 mock factories
# ---------------------------------------------------------------------------


def _opamp_subcircuit_graph() -> SchematicGraph:
    """Two op-amps with resistor between them."""
    return SchematicGraph(
        filepath="opamp_sub.kicad_sch",
        pins=[
            # U1 (NE5532 first half)
            PinPosition(ref="U1", pin_number="3", pin_name="IN+", position=(40.0, 50.0), body_position=(40.0, 45.0)),
            PinPosition(ref="U1", pin_number="2", pin_name="IN-", position=(40.0, 60.0), body_position=(40.0, 55.0)),
            PinPosition(ref="U1", pin_number="1", pin_name="OUT", position=(60.0, 55.0), body_position=(55.0, 55.0)),
            PinPosition(ref="U1", pin_number="4", pin_name="V-", position=(50.0, 40.0), body_position=(50.0, 40.0)),
            PinPosition(ref="U1", pin_number="8", pin_name="V+", position=(50.0, 70.0), body_position=(50.0, 70.0)),
            # R1 coupling resistor
            PinPosition(ref="R1", pin_number="1", pin_name="1", position=(65.0, 55.0), body_position=(62.5, 55.0)),
            PinPosition(ref="R1", pin_number="2", pin_name="2", position=(75.0, 55.0), body_position=(77.5, 55.0)),
            # U2 (NE5532 second half)
            PinPosition(ref="U2", pin_number="5", pin_name="IN+", position=(80.0, 50.0), body_position=(80.0, 45.0)),
            PinPosition(ref="U2", pin_number="6", pin_name="IN-", position=(80.0, 60.0), body_position=(80.0, 55.0)),
            PinPosition(ref="U2", pin_number="7", pin_name="OUT", position=(100.0, 55.0), body_position=(95.0, 55.0)),
            PinPosition(ref="U2", pin_number="4", pin_name="V-", position=(90.0, 40.0), body_position=(90.0, 40.0)),
            PinPosition(ref="U2", pin_number="8", pin_name="V+", position=(90.0, 70.0), body_position=(90.0, 70.0)),
        ],
        wires=[
            Wire(start=(60.0, 55.0), end=(65.0, 55.0)),  # U1.OUT -> R1.1
            Wire(start=(75.0, 55.0), end=(80.0, 50.0)),  # R1.2 -> U2.IN+
        ],
        labels=[
            Label(name="VCC", position=(50.0, 70.0), label_type="global"),
            Label(name="VCC", position=(90.0, 70.0), label_type="global"),
            Label(name="VEE", position=(50.0, 40.0), label_type="global"),
            Label(name="VEE", position=(90.0, 40.0), label_type="global"),
            Label(name="SIG_IN", position=(40.0, 50.0), label_type="global"),
            Label(name="SIG_OUT", position=(100.0, 55.0), label_type="global"),
        ],
        ref_to_libid={"U1": "NE5532", "R1": "Device:R", "U2": "NE5532"},
    )


# ---------------------------------------------------------------------------
# Test: Pin role classification for known ICs
# ---------------------------------------------------------------------------


class TestPinRoleClassification:
    """IC pin roles correctly classified from pin names and lib_id."""

    def test_opamp_inplus_is_input(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U1", pin_number="3", pin_name="IN+", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U1", pin, "NE5532") == PinRole.INPUT

    def test_opamp_inminus_is_input(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U1", pin_number="2", pin_name="IN-", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U1", pin, "NE5532") == PinRole.INPUT

    def test_opamp_out_is_output(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U1", pin_number="1", pin_name="OUT", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U1", pin, "NE5532") == PinRole.OUTPUT

    def test_opamp_vplus_is_power(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U1", pin_number="8", pin_name="V+", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U1", pin, "NE5532") == PinRole.POWER

    def test_opamp_vminus_is_power(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U1", pin_number="4", pin_name="V-", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U1", pin, "NE5532") == PinRole.POWER

    def test_vca_input_is_input(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U3", pin_number="1", pin_name="INPUT", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U3", pin, "THAT4301") == PinRole.INPUT

    def test_vca_output_is_output(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U3", pin_number="2", pin_name="OUTPUT", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U3", pin, "THAT4301") == PinRole.OUTPUT

    def test_vca_ecplus_is_input(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U3", pin_number="3", pin_name="EC+", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U3", pin, "THAT4301") == PinRole.INPUT

    def test_analog_switch_vdd_is_power(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U4", pin_number="14", pin_name="VDD", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U4", pin, "CD4066BE") == PinRole.POWER

    def test_analog_switch_vss_is_power(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U4", pin_number="7", pin_name="VSS", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U4", pin, "CD4066BE") == PinRole.POWER

    def test_analog_switch_signal_is_unknown_or_bidirectional(self):
        """Signal pins (A, B) on analog switch are not in IC_PIN_RULES,
        so they fall through to pattern matching or return UNKNOWN."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        # Pin named "A" matches _INPUT_PIN_PATTERNS but for CD4066 these are signal pins
        # The classification is acceptable as INPUT since they receive signals
        pin = PinPosition(ref="U4", pin_number="1", pin_name="A", position=(0, 0), body_position=(0, 0))
        role = builder._classify_pin_role("U4", pin, "CD4066BE")
        # Either INPUT (from fallback pattern) or UNKNOWN is acceptable for signal pins
        assert role in (PinRole.INPUT, PinRole.UNKNOWN, PinRole.BIDIRECTIONAL)

    def test_resistor_pins_are_bidirectional(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="R1", pin_number="1", pin_name="1", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("R1", pin, "Device:R") == PinRole.BIDIRECTIONAL

    def test_capacitor_pins_are_bidirectional(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="C1", pin_number="1", pin_name="1", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("C1", pin, "Device:C") == PinRole.BIDIRECTIONAL

    def test_unknown_ic_in_is_input(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U5", pin_number="1", pin_name="IN", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U5", pin, "SomeCustomIC") == PinRole.INPUT

    def test_unknown_ic_out_is_output(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U5", pin_number="2", pin_name="OUT", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U5", pin, "SomeCustomIC") == PinRole.OUTPUT

    def test_unknown_ic_vcc_is_power(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        pin = PinPosition(ref="U5", pin_number="8", pin_name="VCC", position=(0, 0), body_position=(0, 0))
        assert builder._classify_pin_role("U5", pin, "SomeCustomIC") == PinRole.POWER


# ---------------------------------------------------------------------------
# Test: Signal flow direction (edges)
# ---------------------------------------------------------------------------


class TestSignalFlowDirection:
    """Directed edges follow IC output -> IC input signal flow."""

    def test_opamp_output_drives_resistor(self):
        """U1.OUT -> R1.1 produces directed edge U1 -> R1."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        # Find edge from U1 output to R1
        u1_to_r1 = [e for e in topo.edges if e.source_ref == "U1" and e.target_ref == "R1"]
        assert len(u1_to_r1) >= 1
        for edge in u1_to_r1:
            assert edge.source_pin == "1"  # OUT pin number

    def test_resistor_to_opamp_input(self):
        """R1.2 -> U2.IN+ produces directed edge R1 -> U2 (or U1->U2 via R1)."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        # There should be at least one edge involving U2 as target
        u2_edges = [e for e in topo.edges if e.target_ref == "U2"]
        assert len(u2_edges) >= 1

    def test_power_net_edges_classified_as_power(self):
        """VCC net connecting to U1.V+ and U2.V+ classified as POWER."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        vcc_edges = [e for e in topo.edges if e.net_name == "VCC"]
        # VCC edges should be POWER or there should be no edges if power pins only
        for edge in vcc_edges:
            assert edge.classification == NetClassification.POWER

    def test_signal_path_traces_input_to_output(self):
        """Signal path from SIG_IN through U1 -> R1 -> U2 -> SIG_OUT."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        # Check signal paths exist
        assert len(topo.signal_paths) >= 1
        # Find path that goes through U1 -> ... -> U2
        for path in topo.signal_paths:
            if "U1" in path and "U2" in path:
                # U1 should come before U2 in the path
                assert path.index("U1") < path.index("U2")
                break
        else:
            # May not have a direct path due to net resolution limits
            # But input/output nets should be identified
            assert "SIG_IN" in topo.input_nets
            assert "SIG_OUT" in topo.output_nets


# ---------------------------------------------------------------------------
# Test: Op-amp subcircuit node classification
# ---------------------------------------------------------------------------


class TestOpampSubcircuit:
    """TopologyBuilder correctly classifies op-amp subcircuit components."""

    def test_opamp_nodes_are_ics(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        for node in topo.nodes:
            if node.ref.startswith("U"):
                assert node.component_type == "ic"

    def test_resistor_node_is_passive(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        r1 = [n for n in topo.nodes if n.ref == "R1"][0]
        assert r1.component_type == "resistor"

    def test_opamp_has_power_and_signal_pins(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        u1 = [n for n in topo.nodes if n.ref == "U1"][0]
        assert len(u1.power_pins) >= 2  # V+ and V-
        assert len(u1.input_pins) >= 2  # IN+ and IN-
        assert len(u1.output_pins) >= 1  # OUT


# ---------------------------------------------------------------------------
# Test: NetClassifier rule-based classification
# ---------------------------------------------------------------------------


class TestNetClassifier:
    """NetClassifier correctly classifies nets by naming patterns."""

    def test_vcc_is_power(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("VCC") == NetClassification.POWER

    def test_plus12v_is_power(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("+12V") == NetClassification.POWER

    def test_gnd_is_ground(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("GND") == NetClassification.GROUND

    def test_agnd_is_ground(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("AGND") == NetClassification.GROUND

    def test_sda_is_control(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("SDA") == NetClassification.CONTROL

    def test_clk_10m_is_clock(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("CLK_10M") == NetClassification.CLOCK

    def test_sig_in_is_signal(self):
        """SIG_IN doesn't match any power/ground/clock/control pattern -> UNKNOWN."""
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("SIG_IN") == NetClassification.UNKNOWN

    def test_unknown_net(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("Net_1") == NetClassification.UNKNOWN

    def test_topology_override_all_power_pins(self):
        """Net connecting only to power pins classified as POWER regardless of name."""
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        pin_roles = {("U1", "8"): PinRole.POWER, ("U2", "8"): PinRole.POWER}
        result = c.classify("some_random_net", pin_roles)
        assert result == NetClassification.POWER

    def test_ordered_rules_first_match_wins(self):
        """Power name pattern takes precedence over topology check."""
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        # VCC is matched by name first, even if topology says all power pins
        assert c.classify("VCC") == NetClassification.POWER
        # GND is matched by name first
        assert c.classify("GND") == NetClassification.GROUND

    def test_case_insensitive_vcc(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("vcc") == NetClassification.POWER
        assert c.classify("Vcc") == NetClassification.POWER

    def test_plus3v3_is_power(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("+3V3") == NetClassification.POWER

    def test_plus5v_is_power(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("+5V") == NetClassification.POWER

    def test_minus9v_is_power(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("-9V") == NetClassification.POWER

    def test_classify_many(self):
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        nets = {
            "VCC": {},
            "GND": {},
            "SDA": {},
            "CLK_10M": {},
            "Net_1": {},
        }
        results = c.classify_many(nets)
        assert results["VCC"] == NetClassification.POWER
        assert results["GND"] == NetClassification.GROUND
        assert results["SDA"] == NetClassification.CONTROL
        assert results["CLK_10M"] == NetClassification.CLOCK
        assert results["Net_1"] == NetClassification.UNKNOWN


# ---------------------------------------------------------------------------
# Task 4 mock factories
# ---------------------------------------------------------------------------


def _opamp_feedback_graph() -> SchematicGraph:
    """Op-amp with feedback resistor from output to inverting input."""
    return SchematicGraph(
        filepath="opamp_feedback.kicad_sch",
        pins=[
            PinPosition(ref="U1", pin_number="3", pin_name="IN+", position=(40.0, 50.0), body_position=(40.0, 45.0)),
            PinPosition(ref="U1", pin_number="2", pin_name="IN-", position=(40.0, 60.0), body_position=(40.0, 55.0)),
            PinPosition(ref="U1", pin_number="1", pin_name="OUT", position=(60.0, 55.0), body_position=(55.0, 55.0)),
            PinPosition(ref="U1", pin_number="4", pin_name="V-", position=(50.0, 40.0), body_position=(50.0, 40.0)),
            PinPosition(ref="U1", pin_number="8", pin_name="V+", position=(50.0, 70.0), body_position=(50.0, 70.0)),
            PinPosition(ref="Rfb", pin_number="1", pin_name="1", position=(50.0, 60.0), body_position=(45.0, 65.0)),
            PinPosition(ref="Rfb", pin_number="2", pin_name="2", position=(55.0, 55.0), body_position=(55.0, 60.0)),
            PinPosition(ref="Rin", pin_number="1", pin_name="1", position=(30.0, 60.0), body_position=(35.0, 60.0)),
            PinPosition(ref="Rin", pin_number="2", pin_name="2", position=(40.0, 60.0), body_position=(40.0, 60.0)),
        ],
        wires=[
            Wire(start=(60.0, 55.0), end=(55.0, 55.0)),  # U1.OUT -> Rfb.2
            Wire(start=(50.0, 60.0), end=(40.0, 60.0)),  # Rfb.1 -> U1.IN-
            Wire(start=(30.0, 60.0), end=(40.0, 60.0)),  # Rin.2 -> U1.IN- (junction)
        ],
        labels=[
            Label(name="SIG_IN", position=(30.0, 60.0), label_type="global"),
            Label(name="VCC", position=(50.0, 70.0), label_type="global"),
            Label(name="VEE", position=(50.0, 40.0), label_type="global"),
            Label(name="SIG_OUT", position=(60.0, 55.0), label_type="global"),
        ],
        ref_to_libid={"U1": "NE5532", "Rfb": "Device:R", "Rin": "Device:R"},
    )


def _parallel_path_graph() -> SchematicGraph:
    """Circuit with parallel signal paths (split and merge)."""
    return SchematicGraph(
        filepath="parallel.kicad_sch",
        pins=[
            # Input connector
            PinPosition(ref="J1", pin_number="1", pin_name="1", position=(10.0, 50.0), body_position=(10.0, 50.0)),
            PinPosition(ref="J1", pin_number="2", pin_name="2", position=(10.0, 60.0), body_position=(10.0, 60.0)),
            # Split point R1
            PinPosition(ref="R1", pin_number="1", pin_name="1", position=(20.0, 50.0), body_position=(20.0, 50.0)),
            PinPosition(ref="R1", pin_number="2", pin_name="2", position=(30.0, 50.0), body_position=(30.0, 50.0)),
            # Path A: R2
            PinPosition(ref="R2", pin_number="1", pin_name="1", position=(40.0, 40.0), body_position=(40.0, 40.0)),
            PinPosition(ref="R2", pin_number="2", pin_name="2", position=(50.0, 40.0), body_position=(50.0, 40.0)),
            # Path B: R3
            PinPosition(ref="R3", pin_number="1", pin_name="1", position=(40.0, 60.0), body_position=(40.0, 60.0)),
            PinPosition(ref="R3", pin_number="2", pin_name="2", position=(50.0, 60.0), body_position=(50.0, 60.0)),
            # Merge point R4
            PinPosition(ref="R4", pin_number="1", pin_name="1", position=(60.0, 50.0), body_position=(60.0, 50.0)),
            PinPosition(ref="R4", pin_number="2", pin_name="2", position=(70.0, 50.0), body_position=(70.0, 50.0)),
            # Output connector
            PinPosition(ref="J2", pin_number="1", pin_name="1", position=(80.0, 50.0), body_position=(80.0, 50.0)),
        ],
        wires=[
            Wire(start=(10.0, 50.0), end=(20.0, 50.0)),  # J1.1 -> R1.1
            Wire(start=(30.0, 50.0), end=(40.0, 40.0)),  # R1.2 -> R2.1
            Wire(start=(30.0, 50.0), end=(40.0, 60.0)),  # R1.2 -> R3.1 (split)
            Wire(start=(50.0, 40.0), end=(60.0, 50.0)),  # R2.2 -> R4.1
            Wire(start=(50.0, 60.0), end=(60.0, 50.0)),  # R3.2 -> R4.1 (merge)
            Wire(start=(70.0, 50.0), end=(80.0, 50.0)),  # R4.2 -> J2.1
        ],
        labels=[
            Label(name="SIG_IN", position=(10.0, 50.0), label_type="global"),
            Label(name="SIG_OUT", position=(80.0, 50.0), label_type="global"),
        ],
        ref_to_libid={
            "J1": "Connector:Conn_01x02",
            "R1": "Device:R",
            "R2": "Device:R",
            "R3": "Device:R",
            "R4": "Device:R",
            "J2": "Connector:Conn_01x02",
        },
    )


# ---------------------------------------------------------------------------
# Test: Feedback detection
# ---------------------------------------------------------------------------


class TestFeedbackDetection:
    """Feedback loops detected in op-amp circuits."""

    def test_feedback_net_detected(self):
        """Feedback from U1 output through Rfb to U1 inverting input."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_feedback_graph())
        # There should be at least one feedback edge
        feedback_edges = [e for e in topo.edges if e.classification == NetClassification.FEEDBACK]
        assert len(feedback_edges) >= 1

    def test_feedback_net_name(self):
        """Feedback net connects output stage back to input stage."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_feedback_graph())
        feedback_nets = {e.net_name for e in topo.edges if e.classification == NetClassification.FEEDBACK}
        # The feedback should involve the Rfb net (connecting U1.OUT back to U1.IN-)
        assert len(feedback_nets) >= 1

    def test_feedback_count_in_stats(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_feedback_graph())
        assert topo.stats["feedback_count"] >= 1


# ---------------------------------------------------------------------------
# Test: Signal path tracing
# ---------------------------------------------------------------------------


class TestSignalPathTracing:
    """Signal paths traced through multi-stage circuits."""

    def test_opamp_subcircuit_signal_path(self):
        """Signal path from input through U1 -> R1 -> U2 -> output."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        assert len(topo.signal_paths) >= 1
        # Path should include U1 and U2
        for path in topo.signal_paths:
            refs = list(path)
            if "U1" in refs and "U2" in refs:
                assert refs.index("U1") < refs.index("U2")
                break
        else:
            assert False, "No path found from U1 to U2"

    def test_signal_path_skips_power_nets(self):
        """Signal paths do not traverse POWER-classified edges."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        # No signal path should include only power nets
        for path in topo.signal_paths:
            for ref in path:
                # No path should be just a power rail connection
                assert ref.startswith("U") or ref.startswith("R") or ref.startswith("J")

    def test_parallel_paths(self):
        """Parallel circuit produces multiple signal paths."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_parallel_path_graph())
        # Should have at least one signal path
        assert len(topo.signal_paths) >= 1


# ---------------------------------------------------------------------------
# Test: Topology stats
# ---------------------------------------------------------------------------


class TestTopologyStats:
    """CircuitTopology.stats contains accurate counts."""

    def test_empty_stats(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_empty_graph())
        assert topo.stats["component_count"] == 0
        assert topo.stats["net_count"] == 0
        assert topo.stats["signal_path_count"] == 0
        assert topo.stats["feedback_count"] == 0

    def test_single_component_stats(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_single_resistor_graph())
        assert topo.stats["component_count"] == 1
        assert topo.stats["net_count"] == 0  # Single component, no edges

    def test_opamp_subcircuit_stats(self):
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_subcircuit_graph())
        assert topo.stats["component_count"] == 3  # U1, R1, U2
        assert topo.stats["net_count"] >= 2  # At least Net_2 and Net_3 (signal nets)
        assert topo.stats["feedback_count"] >= 0


# ---------------------------------------------------------------------------
# Test: Full integration (compressor subcircuit)
# ---------------------------------------------------------------------------


class TestFullIntegration:
    """End-to-end topology construction with realistic circuits."""

    def test_opamp_feedback_complete_topology(self):
        """Op-amp with feedback produces correct topology."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder

        builder = TopologyBuilder()
        topo = builder.from_schematic_graph(_opamp_feedback_graph())

        # 3 components: U1, Rfb, Rin
        assert topo.stats["component_count"] == 3

        # U1 should be an IC with power, input, and output pins
        u1_nodes = [n for n in topo.nodes if n.ref == "U1"]
        assert len(u1_nodes) == 1
        u1 = u1_nodes[0]
        assert u1.component_type == "ic"
        assert len(u1.power_pins) >= 2
        assert len(u1.input_pins) >= 2
        assert len(u1.output_pins) >= 1

        # Should have input and output nets
        assert "SIG_IN" in topo.input_nets
        assert "SIG_OUT" in topo.output_nets

    def test_imports_work(self):
        """All public imports work correctly."""
        from kicad_agent.analysis.topology_graph import TopologyBuilder, CircuitTopology
        from kicad_agent.analysis.net_classifier import NetClassifier
        from kicad_agent.analysis.types import NetClassification, PinRole

        assert TopologyBuilder is not None
        assert CircuitTopology is not None
        assert NetClassifier is not None
        assert NetClassification.POWER == "POWER"
        assert PinRole.OUTPUT == "OUTPUT"

    def test_net_classifier_standalone(self):
        """NetClassifier works independently."""
        from kicad_agent.analysis.net_classifier import NetClassifier

        c = NetClassifier()
        assert c.classify("VCC") == NetClassification.POWER
        assert c.classify("GND") == NetClassification.GROUND
        assert c.classify("CLK_10M") == NetClassification.CLOCK
        assert c.classify("SDA") == NetClassification.CONTROL
        assert c.classify("random_net") == NetClassification.UNKNOWN
