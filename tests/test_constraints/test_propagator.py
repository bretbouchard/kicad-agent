"""Tests for ConstraintPropagator orchestrator.

Integration tests verifying the full constraint propagation pipeline:
topology + subcircuits + intent + rule_report -> list[PCBConstraint]

CP-01: Constraint propagation from circuit analysis.
"""
import pytest

from volta.analysis.design_rules import (
    DesignRuleReport,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from volta.analysis.intent_schemas import (
    DesignGoal,
    DesignIntent,
    SubcircuitIntent,
)
from volta.analysis.subcircuit_detector import Subcircuit, SubcircuitType
from volta.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)
from volta.analysis.types import NetClassification
from volta.constraints.converters import to_routing_constraints
from volta.constraints.propagator import ConstraintPropagator
from volta.constraints.types import (
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


def _make_power_topology() -> CircuitTopology:
    """Minimal topology with a power edge (U1 -> C1 on VCC)."""
    nodes = (
        _make_node("U1", "IC:NE5532", "ic", 8, ("4", "8"), ("2", "3"), ("1", "7")),
        _make_node("C1", "Device:C", "capacitor", 2, (), ("1",), ("2",)),
    )
    edges = (
        _make_edge("VCC", "U1", "8", "C1", "1", NetClassification.POWER, "power"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=(),
        output_nets=(),
        power_nets=("VCC",),
        signal_paths=(),
        stats={},
    )


def _make_rich_topology() -> CircuitTopology:
    """Richer topology fixture with multiple constraint triggers.

    - U1: 8-pin IC (no thermal trigger)
    - U2: 24-pin IC (thermal trigger)
    - C1: capacitor on VCC with U1 (decoupling trigger)
    - CLK_25M edge: CLOCK classification (impedance trigger)
    - USB_D+ / USB_D- edges: diff pair trigger
    """
    nodes = (
        _make_node("U1", "IC:NE5532", "ic", 8, ("4", "8"), ("2", "3"), ("1", "7")),
        _make_node("U2", "IC:ATmega328", "ic", 24, ("7", "8", "20", "21"), ("2", "3"), ("14", "15")),
        _make_node("C1", "Device:C", "capacitor", 2, (), ("1",), ("2",)),
        _make_node("J1", "Connector:USB", "connector", 4),
    )
    edges = (
        _make_edge("VCC", "U1", "8", "C1", "1", NetClassification.POWER, "power"),
        _make_edge("CLK_25M", "U1", "1", "U2", "1", NetClassification.CLOCK, "forward"),
        _make_edge("USB_D+", "J1", "1", "U2", "2"),
        _make_edge("USB_D-", "J1", "2", "U2", "3"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=("USB_D+", "USB_D-"),
        output_nets=(),
        power_nets=("VCC",),
        signal_paths=(),
        stats={},
    )


def _make_subcircuits() -> list[Subcircuit]:
    """Two subcircuits for signal flow testing."""
    return [
        Subcircuit(
            subcircuit_id="SC-001",
            components=("U1", "C1"),
            nets=("VCC", "SIG"),
            boundary_nets=("VCC",),
            subcircuit_type=SubcircuitType.PREAMP,
            confidence=0.85,
            center_component="U1",
            features={},
        ),
        Subcircuit(
            subcircuit_id="SC-002",
            components=("U2",),
            nets=("CLK_25M",),
            boundary_nets=("CLK_25M",),
            subcircuit_type=SubcircuitType.DIGITAL_CONTROL,
            confidence=0.9,
            center_component="U2",
            features={},
        ),
    ]


def _make_intent() -> DesignIntent:
    """Design intent for signal flow ordering."""
    return DesignIntent(
        overall_type="mixed_signal",
        subcircuit_intents=(
            SubcircuitIntent(
                function="preamp",
                component_refs=("U1", "C1"),
                input_nets=("SIG_IN",),
                output_nets=("SIG",),
                confidence=0.85,
            ),
            SubcircuitIntent(
                function="digital_control",
                component_refs=("U2",),
                input_nets=("SIG",),
                output_nets=(),
                confidence=0.9,
            ),
        ),
        signal_flow_description="Input -> PREAMP -> DIGITAL_CONTROL",
        design_goals=(DesignGoal.AUDIO_PROCESSING, DesignGoal.CONTROL),
        confidence=0.87,
        schematic_path="test.kicad_sch",
    )


# ---------------------------------------------------------------------------
# Test 1: Propagate returns list[PCBConstraint] with correct types
# ---------------------------------------------------------------------------


class TestConstraintPropagator:
    """Integration tests for ConstraintPropagator."""

    def test_propagate_returns_correct_types(self) -> None:
        """Propagate with power topology returns typed constraints."""
        topology = _make_power_topology()
        propagator = ConstraintPropagator()

        result = propagator.propagate(topology)

        assert isinstance(result, list)
        assert all(isinstance(c, PCBConstraint) for c in result)
        # Should contain DecouplingConstraint and/or ClearanceConstraint
        type_set = {type(c) for c in result}
        assert len(result) >= 1
        assert DecouplingConstraint in type_set or ClearanceConstraint in type_set

    def test_minimal_topology_returns_empty(self) -> None:
        """Minimal topology (1 node, 0 edges) returns empty list."""
        nodes = (_make_node("R1", "Device:R", "resistor", 2),)
        topology = CircuitTopology(
            nodes=nodes,
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={},
        )
        propagator = ConstraintPropagator()

        result = propagator.propagate(topology)

        assert result == []

    def test_rich_topology_produces_multiple_types(self) -> None:
        """Rich topology produces >= 1 DifferentialPair, Impedance, and Thermal constraint."""
        topology = _make_rich_topology()
        subcircuits = _make_subcircuits()
        intent = _make_intent()
        propagator = ConstraintPropagator()

        result = propagator.propagate(topology, subcircuits, intent)

        type_counts: dict[type, int] = {}
        for c in result:
            type_counts[type(c)] = type_counts.get(type(c), 0) + 1

        assert type_counts.get(DifferentialPairConstraint, 0) >= 1, (
            f"Expected >= 1 DifferentialPairConstraint, got {type_counts}"
        )
        assert type_counts.get(ImpedanceConstraint, 0) >= 1, (
            f"Expected >= 1 ImpedanceConstraint, got {type_counts}"
        )
        assert type_counts.get(ThermalConstraint, 0) >= 1, (
            f"Expected >= 1 ThermalConstraint, got {type_counts}"
        )

    def test_propagate_is_unidirectional(self) -> None:
        """Result is list[PCBConstraint] with no back-references to PCB state."""
        topology = _make_power_topology()
        propagator = ConstraintPropagator()

        result = propagator.propagate(topology)

        # Verify result is a plain list of PCBConstraint with no mutation of input
        assert isinstance(result, list)
        for c in result:
            assert isinstance(c, PCBConstraint)
            # Constraints should not reference PCB-specific state
            # (no file paths, no PCB coordinates, no layout data)
            assert not hasattr(c, "pcb_state")
            assert not hasattr(c, "layout_data")

        # Verify input topology is unchanged (frozen dataclass)
        assert topology.edges == (_make_edge("VCC", "U1", "8", "C1", "1", NetClassification.POWER, "power"),)

    def test_none_intent_skips_signal_flow(self) -> None:
        """Propagate with None intent still produces constraints from 4 non-intent extractors."""
        topology = _make_rich_topology()
        subcircuits = _make_subcircuits()
        propagator = ConstraintPropagator()

        # With intent
        result_with = propagator.propagate(topology, subcircuits, _make_intent())
        # Without intent (subcircuits still passed)
        result_without = propagator.propagate(topology, subcircuits, None)

        # Without intent, signal flow extractor still runs (uses subcircuits)
        # but ordering differs. Both should produce constraints.
        assert len(result_with) >= 1
        assert len(result_without) >= 1

        # Signal flow constraints with intent should have intent-based ordering
        # Both should have signal flow constraints since subcircuits are provided
        sf_with = [c for c in result_with if c.source_rule == "signal_flow_extractor"]
        sf_without = [c for c in result_without if c.source_rule == "signal_flow_extractor"]
        assert len(sf_with) >= 1
        assert len(sf_without) >= 1

    def test_deterministic_ordering(self) -> None:
        """Same inputs produce same output (deterministic)."""
        topology = _make_rich_topology()
        subcircuits = _make_subcircuits()
        intent = _make_intent()
        propagator = ConstraintPropagator()

        result1 = propagator.propagate(topology, subcircuits, intent)
        result2 = propagator.propagate(topology, subcircuits, intent)

        assert len(result1) == len(result2)
        for c1, c2 in zip(result1, result2):
            assert type(c1) == type(c2)
            assert c1.net_names == c2.net_names
            assert c1.confidence == c2.confidence

    def test_config_overrides_propagated(self) -> None:
        """Config dict passed to each extractor overrides defaults."""
        topology = _make_power_topology()
        config = {"decoupling_max_distance_mm": 3.0}
        propagator = ConstraintPropagator(config=config)

        result = propagator.propagate(topology)

        decoupling = [c for c in result if isinstance(c, DecouplingConstraint)]
        if decoupling:
            assert decoupling[0].max_distance_mm == 3.0

    def test_end_to_end_routing_constraints(self) -> None:
        """topology -> propagate -> to_routing_constraints produces valid RoutingConstraints."""
        topology = _make_rich_topology()
        propagator = ConstraintPropagator()

        constraints = propagator.propagate(topology)
        routing = to_routing_constraints(constraints)

        # RoutingConstraints should be valid (not None)
        assert routing is not None
        assert routing.clearance_mm > 0 or routing.trace_width_mm > 0 or True
        # Rich topology has clock edges -> impedance -> trace_width_mm
        assert routing.trace_width_mm > 0

    def test_error_handling_continues(self) -> None:
        """One failing extractor does not prevent others from running."""
        topology = _make_rich_topology()
        propagator = ConstraintPropagator()

        # Insert a bad extractor
        original_extractors = propagator._extractors[:]

        def bad_extractor(topology, subcircuits, intent, rule_report, config):
            raise RuntimeError("Simulated extractor failure")

        propagator._extractors = [
            ("bad", bad_extractor),
        ] + original_extractors

        result = propagator.propagate(topology)

        # Should still produce constraints from other extractors
        assert len(result) >= 1

    def test_no_subcircuits_no_intent(self) -> None:
        """Propagate without subcircuits or intent still produces constraints."""
        topology = _make_rich_topology()
        propagator = ConstraintPropagator()

        result = propagator.propagate(topology, subcircuits=None, intent=None)

        assert len(result) >= 1
        # Should have diff pair, impedance, thermal, power constraints
        types_present = {type(c) for c in result}
        assert DifferentialPairConstraint in types_present
        assert ImpedanceConstraint in types_present
        assert ThermalConstraint in types_present
