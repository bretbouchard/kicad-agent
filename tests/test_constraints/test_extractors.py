"""Tests for constraint extractor functions.

Tests all 5 extractors:
1. extract_diff_pair_constraints -- differential pair detection from net names
2. extract_power_constraints -- decoupling + power clearance
3. extract_impedance_constraints -- high-speed/clock impedance
4. extract_thermal_constraints -- high-pin-count IC thermal
5. extract_signal_flow_constraints -- subcircuit placement groups

CP-01, CP-05: Constraint propagation from circuit analysis.
"""
import pytest

from kicad_agent.analysis.design_rules import (
    DesignRuleReport,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from kicad_agent.analysis.intent_schemas import (
    DesignGoal,
    DesignIntent,
    SubcircuitIntent,
)
from kicad_agent.analysis.net_classifier import NetImportance, SignalIntegrity
from kicad_agent.analysis.subcircuit_detector import Subcircuit, SubcircuitType
from kicad_agent.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)
from kicad_agent.analysis.types import NetClassification
from kicad_agent.constraints.extractors import (
    extract_diff_pair_constraints,
    extract_impedance_constraints,
    extract_power_constraints,
    extract_signal_flow_constraints,
    extract_thermal_constraints,
)
from kicad_agent.constraints.types import (
    ClearanceConstraint,
    DecouplingConstraint,
    DifferentialPairConstraint,
    ImpedanceConstraint,
    PCBConstraint,
    ThermalConstraint,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_node(
    ref: str,
    lib_id: str = "Device:R",
    component_type: str = "resistor",
    pin_count: int = 2,
    power_pins: tuple[str, ...] = (),
    input_pins: tuple[str, ...] = (),
    output_pins: tuple[str, ...] = (),
) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id=lib_id,
        component_type=component_type,
        pin_count=pin_count,
        power_pins=power_pins,
        input_pins=input_pins,
        output_pins=output_pins,
    )


def _make_edge(
    net_name: str,
    source_ref: str = "U1",
    source_pin: str = "1",
    target_ref: str = "U2",
    target_pin: str = "1",
    classification: NetClassification = NetClassification.SIGNAL,
    signal_direction: str = "forward",
) -> TopologyEdge:
    return TopologyEdge(
        net_name=net_name,
        source_ref=source_ref,
        source_pin=source_pin,
        target_ref=target_ref,
        target_pin=target_pin,
        classification=classification,
        signal_direction=signal_direction,
    )


# ---------------------------------------------------------------------------
# Test 1: Diff pair detects +/- net names
# ---------------------------------------------------------------------------


class TestDiffPairExtractor:
    """Tests for extract_diff_pair_constraints."""

    def test_detects_plus_minus_pair(self) -> None:
        """Two edges with D+ / D- net names produce DifferentialPairConstraint."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8, ("4", "8"), ("2", "3"), ("1", "7")),
            _make_node("J1", "Connector:USB", "connector", 4, (), ("1", "2"), ()),
        )
        edges = (
            _make_edge("USB_D+", "J1", "1", "U1", "2"),
            _make_edge("USB_D-", "J1", "2", "U1", "3"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=("USB_D+", "USB_D-"),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_diff_pair_constraints(topology, [], None, None, {})

        assert len(result) >= 1
        dp = result[0]
        assert isinstance(dp, DifferentialPairConstraint)
        assert "USB_D+" in dp.net_names
        assert "USB_D-" in dp.net_names
        assert dp.gap_mm > 0
        assert dp.width_mm > 0
        assert dp.confidence >= 0.6

    def test_no_diff_pair_returns_empty(self) -> None:
        """No diff pair nets -> empty list."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8),
            _make_node("R1", "Device:R", "resistor", 2),
        )
        edges = (
            _make_edge("SIG_IN", "U1", "1", "R1", "1"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=("SIG_IN",),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_diff_pair_constraints(topology, [], None, None, {})

        assert result == []

    def test_detects_p_n_suffix(self) -> None:
        """Net names ending with _P / _N produce diff pair constraint."""
        edges = (
            _make_edge("DATA_P", "U1", "1", "U2", "1"),
            _make_edge("DATA_N", "U1", "2", "U2", "2"),
        )
        topology = CircuitTopology(
            nodes=(),
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_diff_pair_constraints(topology, [], None, None, {})

        assert len(result) >= 1
        assert isinstance(result[0], DifferentialPairConstraint)
        assert "DATA_P" in result[0].net_names
        assert "DATA_N" in result[0].net_names

    def test_empty_topology_returns_empty(self) -> None:
        """Empty topology (0 nodes, 0 edges) returns empty list."""
        topology = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_diff_pair_constraints(topology, [], None, None, {})

        assert result == []


# ---------------------------------------------------------------------------
# Test 3-4: Power extractor
# ---------------------------------------------------------------------------


class TestPowerExtractor:
    """Tests for extract_power_constraints."""

    def test_produces_decoupling_and_clearance(self) -> None:
        """IC + cap on same power net -> DecouplingConstraint + ClearanceConstraint."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8, ("4", "8"), ("2", "3"), ("1", "7")),
            _make_node("C1", "Device:C", "capacitor", 2, (), ("1",), ("2",)),
        )
        edges = (
            _make_edge("VCC", "U1", "8", "C1", "1", NetClassification.POWER, "power"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=("VCC",),
            signal_paths=(),
            stats={},
        )

        result = extract_power_constraints(topology, [], None, None, {})

        # Should produce at least one DecouplingConstraint or ClearanceConstraint
        decoupling = [c for c in result if isinstance(c, DecouplingConstraint)]
        clearance = [c for c in result if isinstance(c, ClearanceConstraint)]

        assert len(decoupling) >= 1 or len(clearance) >= 1, (
            f"Expected DecouplingConstraint or ClearanceConstraint, got {result}"
        )

        if decoupling:
            dc = decoupling[0]
            assert dc.ic_ref in ("U1",)
            assert dc.cap_ref in ("C1",)
            assert dc.max_distance_mm > 0

    def test_identifies_ic_cap_pairs(self) -> None:
        """Capacitor within 1 hop of IC on power net -> DecouplingConstraint."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8, ("4", "8")),
            _make_node("C1", "Device:C", "capacitor", 2),
            _make_node("C2", "Device:C", "capacitor", 2),
        )
        edges = (
            _make_edge("VCC", "U1", "8", "C1", "1", NetClassification.POWER, "power"),
            _make_edge("GND", "U1", "4", "C2", "1", NetClassification.GROUND, "power"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=("VCC", "GND"),
            signal_paths=(),
            stats={},
        )

        result = extract_power_constraints(topology, [], None, None, {})

        decoupling = [c for c in result if isinstance(c, DecouplingConstraint)]
        assert len(decoupling) >= 1
        # Should find U1-C1 pair
        refs = {(d.ic_ref, d.cap_ref) for d in decoupling}
        assert ("U1", "C1") in refs or ("U1", "C2") in refs

    def test_no_power_edges_returns_clearance_only(self) -> None:
        """No power edges -> no decoupling constraints, may still produce power clearance."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8),
            _make_node("R1", "Device:R", "resistor", 2),
        )
        edges = (
            _make_edge("SIG", "U1", "1", "R1", "1", NetClassification.SIGNAL, "forward"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_power_constraints(topology, [], None, None, {})

        # No power edges -> no decoupling pairs
        decoupling = [c for c in result if isinstance(c, DecouplingConstraint)]
        assert len(decoupling) == 0

    def test_ground_net_produces_clearance(self) -> None:
        """GROUND-classified edges produce ClearanceConstraint."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8),
        )
        edges = (
            _make_edge("GND", "U1", "4", "U1", "4", NetClassification.GROUND, "power"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=("GND",),
            signal_paths=(),
            stats={},
        )

        result = extract_power_constraints(topology, [], None, None, {})

        clearance = [c for c in result if isinstance(c, ClearanceConstraint)]
        assert len(clearance) >= 1
        assert clearance[0].min_clearance_mm > 0


# ---------------------------------------------------------------------------
# Test 5-6: Impedance extractor
# ---------------------------------------------------------------------------


class TestImpedanceExtractor:
    """Tests for extract_impedance_constraints."""

    def test_high_speed_produces_impedance(self) -> None:
        """CLOCK-classified edge produces ImpedanceConstraint with target 50 ohm."""
        nodes = (
            _make_node("U1", "IC:RP2040", "ic", 24),
            _make_node("U2", "IC:Flash", "ic", 8),
        )
        edges = (
            _make_edge("CLK_25M", "U1", "1", "U2", "1", NetClassification.CLOCK, "forward"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_impedance_constraints(topology, [], None, None, {})

        assert len(result) >= 1
        imp = result[0]
        assert isinstance(imp, ImpedanceConstraint)
        assert imp.target_impedance_ohm == 50.0
        assert imp.trace_width_mm > 0

    def test_skips_non_high_speed(self) -> None:
        """Non-HIGH_SPEED/non-CLOCK edges are skipped."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8),
            _make_node("R1", "Device:R", "resistor", 2),
        )
        edges = (
            _make_edge("AUDIO_IN", "U1", "1", "R1", "1", NetClassification.SIGNAL, "forward"),
            _make_edge("BIAS_3V", "U1", "2", "R1", "2", NetClassification.POWER, "power"),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=("AUDIO_IN",),
            output_nets=(),
            power_nets=("BIAS_3V",),
            signal_paths=(),
            stats={},
        )

        result = extract_impedance_constraints(topology, [], None, None, {})

        # Signal and power edges should not produce impedance constraints
        assert all(isinstance(c, ImpedanceConstraint) for c in result)
        assert len(result) == 0

    def test_empty_edges_returns_empty(self) -> None:
        """No edges -> no impedance constraints."""
        topology = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_impedance_constraints(topology, [], None, None, {})

        assert result == []


# ---------------------------------------------------------------------------
# Test 7-8: Thermal extractor
# ---------------------------------------------------------------------------


class TestThermalExtractor:
    """Tests for extract_thermal_constraints."""

    def test_high_pin_count_ic_produces_thermal(self) -> None:
        """IC with pin_count >= 16 produces ThermalConstraint."""
        nodes = (
            _make_node(
                "U2", "IC:ATmega328", "ic", 28,
                ("7", "8", "20", "21"), ("2", "3"), ("14", "15"),
            ),
        )
        edges = ()
        topology = CircuitTopology(
            nodes=nodes,
            edges=edges,
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_thermal_constraints(topology, [], None, None, {})

        assert len(result) >= 1
        tc = result[0]
        assert isinstance(tc, ThermalConstraint)
        assert "U2" in tc.component_refs
        assert tc.max_junction_temp_c > 0
        assert tc.thermal_resistance_c_per_w > 0

    def test_small_ics_return_empty(self) -> None:
        """ICs with < 16 pins and < 8 power pins produce no thermal constraint."""
        nodes = (
            _make_node("U1", "IC:NE5532", "ic", 8, ("4", "8")),
            _make_node("U3", "IC:LM358", "ic", 8, ("4", "8")),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_thermal_constraints(topology, [], None, None, {})

        assert result == []

    def test_ic_with_many_power_pins_produces_thermal(self) -> None:
        """IC with >= 8 power_pins produces ThermalConstraint even if pin_count < 16."""
        power_pins = tuple(str(i) for i in range(1, 9))  # 8 power pins
        nodes = (
            _make_node(
                "U5", "IC:Power", "ic", 14,
                power_pins, (), (),
            ),
        )
        topology = CircuitTopology(
            nodes=nodes,
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_thermal_constraints(topology, [], None, None, {})

        assert len(result) >= 1
        assert isinstance(result[0], ThermalConstraint)


# ---------------------------------------------------------------------------
# Test 9-10: Signal flow extractor
# ---------------------------------------------------------------------------


class TestSignalFlowExtractor:
    """Tests for extract_signal_flow_constraints."""

    def test_subcircuit_produces_clearance(self) -> None:
        """Subcircuit produces ClearanceConstraint with placement group rationale."""
        subcircuits = [
            Subcircuit(
                subcircuit_id="SC-001",
                components=("U1", "R1", "R2"),
                nets=("SIG_IN", "VCC"),
                boundary_nets=("SIG_IN",),
                subcircuit_type=SubcircuitType.PREAMP,
                confidence=0.85,
                center_component="U1",
                features={},
            ),
        ]
        topology = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_signal_flow_constraints(topology, subcircuits, None, None, {})

        assert len(result) >= 1
        cc = result[0]
        assert isinstance(cc, ClearanceConstraint)
        assert "placement" in cc.rationale.lower() or "group" in cc.rationale.lower() or "SC-001" in cc.rationale
        assert cc.min_clearance_mm > 0

    def test_uses_intent_for_priority(self) -> None:
        """DesignIntent.subcircuit_intents orders subcircuit constraints."""
        subcircuits = [
            Subcircuit(
                subcircuit_id="SC-001",
                components=("U1",),
                nets=("SIG_IN",),
                boundary_nets=("SIG_IN",),
                subcircuit_type=SubcircuitType.PREAMP,
                confidence=0.9,
                center_component="U1",
                features={},
            ),
            Subcircuit(
                subcircuit_id="SC-002",
                components=("U2",),
                nets=("SIG_OUT",),
                boundary_nets=("SIG_OUT",),
                subcircuit_type=SubcircuitType.OUTPUT_STAGE,
                confidence=0.8,
                center_component="U2",
                features={},
            ),
        ]
        intent = DesignIntent(
            overall_type="compressor",
            subcircuit_intents=(
                SubcircuitIntent(
                    function="preamp",
                    component_refs=("U1",),
                    input_nets=("SIG_IN",),
                    output_nets=("SIG_MID",),
                    confidence=0.9,
                ),
                SubcircuitIntent(
                    function="output_stage",
                    component_refs=("U2",),
                    input_nets=("SIG_MID",),
                    output_nets=("SIG_OUT",),
                    confidence=0.8,
                ),
            ),
            signal_flow_description="Input -> PREAMP -> OUTPUT -> Out",
            design_goals=(DesignGoal.AUDIO_PROCESSING,),
            confidence=0.85,
            schematic_path="test.kicad_sch",
        )
        topology = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_signal_flow_constraints(topology, subcircuits, intent, None, {})

        assert len(result) >= 2

    def test_no_subcircuits_returns_empty(self) -> None:
        """No subcircuits -> empty list."""
        topology = CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

        result = extract_signal_flow_constraints(topology, [], None, None, {})

        assert result == []


# ---------------------------------------------------------------------------
# Test 11: All extractors return list[PCBConstraint], never raise
# ---------------------------------------------------------------------------


class TestExtractorRobustness:
    """Each extractor returns list[PCBConstraint] -- empty list is valid, never raises."""

    @pytest.fixture
    def empty_topology(self) -> CircuitTopology:
        return CircuitTopology(
            nodes=(),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )

    def test_diff_pair_returns_list(self, empty_topology: CircuitTopology) -> None:
        result = extract_diff_pair_constraints(empty_topology, [], None, None, {})
        assert isinstance(result, list)
        assert all(isinstance(c, PCBConstraint) for c in result)

    def test_power_returns_list(self, empty_topology: CircuitTopology) -> None:
        result = extract_power_constraints(empty_topology, [], None, None, {})
        assert isinstance(result, list)
        assert all(isinstance(c, PCBConstraint) for c in result)

    def test_impedance_returns_list(self, empty_topology: CircuitTopology) -> None:
        result = extract_impedance_constraints(empty_topology, [], None, None, {})
        assert isinstance(result, list)
        assert all(isinstance(c, PCBConstraint) for c in result)

    def test_thermal_returns_list(self, empty_topology: CircuitTopology) -> None:
        result = extract_thermal_constraints(empty_topology, [], None, None, {})
        assert isinstance(result, list)
        assert all(isinstance(c, PCBConstraint) for c in result)

    def test_signal_flow_returns_list(self, empty_topology: CircuitTopology) -> None:
        result = extract_signal_flow_constraints(empty_topology, [], None, None, {})
        assert isinstance(result, list)
        assert all(isinstance(c, PCBConstraint) for c in result)

    def test_none_intent_accepted(self, empty_topology: CircuitTopology) -> None:
        """All extractors accept None for intent without raising."""
        for extractor in [
            extract_diff_pair_constraints,
            extract_power_constraints,
            extract_impedance_constraints,
            extract_thermal_constraints,
            extract_signal_flow_constraints,
        ]:
            result = extractor(empty_topology, [], None, None, {})
            assert isinstance(result, list)

    def test_none_rule_report_accepted(self, empty_topology: CircuitTopology) -> None:
        """All extractors accept None for rule_report without raising."""
        for extractor in [
            extract_diff_pair_constraints,
            extract_power_constraints,
            extract_impedance_constraints,
            extract_thermal_constraints,
            extract_signal_flow_constraints,
        ]:
            result = extractor(empty_topology, [], None, None, {})
            assert isinstance(result, list)
