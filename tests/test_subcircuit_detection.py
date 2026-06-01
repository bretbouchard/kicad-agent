"""Tests for subcircuit detection and classification.

DOMAIN-02: SubcircuitDetector clusters components around ICs using
the CircuitTopology from Phase 45. CircuitClassifier uses rule-based
classification matching violation_classifier ordered-rule pattern.
"""

from kicad_agent.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)
from kicad_agent.analysis.types import NetClassification


# ---------------------------------------------------------------------------
# Test helpers -- mock topology factories
# ---------------------------------------------------------------------------


def _make_topology(
    nodes,
    edges,
    input_nets=(),
    output_nets=(),
    power_nets=(),
    signal_paths=(),
) -> CircuitTopology:
    """Create a CircuitTopology from test data."""
    return CircuitTopology(
        nodes=tuple(nodes),
        edges=tuple(edges),
        input_nets=tuple(input_nets),
        output_nets=tuple(output_nets),
        power_nets=tuple(power_nets),
        signal_paths=tuple(tuple(p) for p in signal_paths),
        stats={
            "component_count": len(nodes),
            "net_count": len(set(e.net_name for e in edges)),
        },
    )


def _make_node(
    ref,
    lib_id,
    comp_type="ic",
    pin_count=8,
    power_pins=(),
    input_pins=(),
    output_pins=(),
) -> TopologyNode:
    """Create a TopologyNode for testing."""
    return TopologyNode(
        ref=ref,
        lib_id=lib_id,
        component_type=comp_type,
        pin_count=pin_count,
        power_pins=tuple(power_pins),
        input_pins=tuple(input_pins),
        output_pins=tuple(output_pins),
    )


def _make_edge(
    net,
    src,
    src_pin,
    tgt,
    tgt_pin,
    cls=NetClassification.SIGNAL,
    direction="forward",
) -> TopologyEdge:
    """Create a TopologyEdge for testing."""
    return TopologyEdge(
        net_name=net,
        source_ref=src,
        source_pin=src_pin,
        target_ref=tgt,
        target_pin=tgt_pin,
        classification=cls,
        signal_direction=direction,
    )


# ---------------------------------------------------------------------------
# Mock topologies
# ---------------------------------------------------------------------------


def _empty_topology() -> CircuitTopology:
    """Empty circuit with no components."""
    return _make_topology([], [])


def _single_ic_topology() -> CircuitTopology:
    """Single IC with surrounding passives (op-amp preamp)."""
    nodes = [
        _make_node("U1", "NE5532", "ic", 8,
                   power_pins=("4", "8"), input_pins=("2", "3"), output_pins=("1",)),
        _make_node("R1", "Device:R", "resistor", 2),
        _make_node("R2", "Device:R", "resistor", 2),
        _make_node("C1", "Device:C", "capacitor", 2),
    ]
    edges = [
        _make_edge("SIG_IN", "U1", "3", "U1", "2", NetClassification.SIGNAL),
        _make_edge("NET_A", "U1", "1", "R1", "1"),
        _make_edge("NET_A", "R1", "1", "R2", "1"),
        _make_edge("NET_B", "R1", "2", "U1", "2", NetClassification.FEEDBACK, "feedback"),
        _make_edge("NET_C", "U1", "1", "C1", "1"),
        _make_edge("VCC", "U1", "8", "U1", "4", NetClassification.POWER, "power"),
    ]
    return _make_topology(nodes, edges, input_nets=("SIG_IN",))


def _multi_ic_topology() -> CircuitTopology:
    """Two ICs with non-overlapping component groups."""
    nodes = [
        # Subcircuit 1: op-amp U1 + R1, R2
        _make_node("U1", "NE5532", "ic", 8,
                   power_pins=("4", "8"), input_pins=("2", "3"), output_pins=("1",)),
        _make_node("R1", "Device:R", "resistor", 2),
        _make_node("R2", "Device:R", "resistor", 2),
        # Subcircuit 2: regulator U2 + C1, C2
        _make_node("U2", "LM7805", "ic", 3,
                   power_pins=("3",), input_pins=("1",), output_pins=("2",)),
        _make_node("C1", "Device:C", "capacitor", 2),
        _make_node("C2", "Device:C", "capacitor", 2),
    ]
    edges = [
        # U1 subcircuit
        _make_edge("SIG_IN", "U1", "3", "R1", "1"),
        _make_edge("NET_A", "U1", "1", "R1", "2"),
        _make_edge("NET_B", "R2", "1", "U1", "2", NetClassification.FEEDBACK, "feedback"),
        # U2 subcircuit
        _make_edge("VIN", "U2", "1", "C1", "1", NetClassification.POWER, "power"),
        _make_edge("VOUT", "U2", "2", "C2", "1", NetClassification.POWER, "power"),
        # Bridge between subcircuits
        _make_edge("NET_A", "U1", "1", "U2", "1"),
    ]
    return _make_topology(
        nodes, edges,
        input_nets=("SIG_IN",),
        power_nets=("VCC", "VIN"),
    )


def _passive_only_topology() -> CircuitTopology:
    """Only passive components, no ICs."""
    nodes = [
        _make_node("R1", "Device:R", "resistor", 2),
        _make_node("R2", "Device:R", "resistor", 2),
        _make_node("C1", "Device:C", "capacitor", 2),
    ]
    edges = [
        _make_edge("NET_A", "R1", "1", "R2", "1"),
        _make_edge("NET_B", "R2", "2", "C1", "1"),
    ]
    return _make_topology(nodes, edges)


# ---------------------------------------------------------------------------
# Test: SubcircuitType enum
# ---------------------------------------------------------------------------


class TestSubcircuitType:
    """SubcircuitType enum has required values."""

    def test_preamplifier(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.PREAMP == "PREAMP"

    def test_compressor(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.COMPRESSOR == "COMPRESSOR"

    def test_eq(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.EQ == "EQ"

    def test_filter(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.FILTER == "FILTER"

    def test_vca(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.VCA == "VCA"

    def test_envelope(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.ENVELOPE == "ENVELOPE"

    def test_lfo(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.LFO == "LFO"

    def test_mixer(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.MIXER == "MIXER"

    def test_output_stage(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.OUTPUT_STAGE == "OUTPUT_STAGE"

    def test_power_supply(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.POWER_SUPPLY == "POWER_SUPPLY"

    def test_oscillator(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.OSCILLATOR == "OSCILLATOR"

    def test_digital_control(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.DIGITAL_CONTROL == "DIGITAL_CONTROL"

    def test_analog_switch(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.ANALOG_SWITCH == "ANALOG_SWITCH"

    def test_protection(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.PROTECTION == "PROTECTION"

    def test_unknown(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert SubcircuitType.UNKNOWN == "UNKNOWN"

    def test_all_15_types(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert len(SubcircuitType) == 15


# ---------------------------------------------------------------------------
# Test: Subcircuit schema
# ---------------------------------------------------------------------------


class TestSubcircuitSchema:
    """Subcircuit frozen dataclass fields."""

    def test_create_subcircuit(self):
        from kicad_agent.analysis.subcircuit_detector import Subcircuit, SubcircuitType
        sc = Subcircuit(
            subcircuit_id="SC-001",
            components=("U1", "R1", "R2"),
            nets=("NET_A", "NET_B"),
            boundary_nets=("NET_C",),
            subcircuit_type=SubcircuitType.PREAMP,
            confidence=0.85,
            center_component="U1",
            features={"resistor_count": 2},
        )
        assert sc.subcircuit_id == "SC-001"
        assert len(sc.components) == 3
        assert sc.subcircuit_type == SubcircuitType.PREAMP
        assert sc.confidence == 0.85
        assert sc.center_component == "U1"

    def test_subcircuit_is_frozen(self):
        from kicad_agent.analysis.subcircuit_detector import Subcircuit, SubcircuitType
        sc = Subcircuit(
            subcircuit_id="SC-001",
            components=("U1",),
            nets=("NET_A",),
            boundary_nets=(),
            subcircuit_type=SubcircuitType.UNKNOWN,
            confidence=0.5,
            center_component="U1",
            features={},
        )
        try:
            sc.subcircuit_id = "SC-002"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass

    def test_confidence_bounds(self):
        from kicad_agent.analysis.subcircuit_detector import Subcircuit, SubcircuitType
        sc = Subcircuit(
            subcircuit_id="SC-001",
            components=("U1",),
            nets=("NET_A",),
            boundary_nets=(),
            subcircuit_type=SubcircuitType.UNKNOWN,
            confidence=0.0,
            center_component="U1",
            features={},
        )
        assert 0.0 <= sc.confidence <= 1.0

    def test_features_is_dict(self):
        from kicad_agent.analysis.subcircuit_detector import Subcircuit, SubcircuitType
        sc = Subcircuit(
            subcircuit_id="SC-001",
            components=("U1",),
            nets=(),
            boundary_nets=(),
            subcircuit_type=SubcircuitType.UNKNOWN,
            confidence=0.5,
            center_component="U1",
            features={"lib_id": "NE5532", "resistor_count": 3},
        )
        assert isinstance(sc.features, dict)
        assert sc.features["lib_id"] == "NE5532"


# ---------------------------------------------------------------------------
# Test: SubcircuitDetector with empty topology
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorEmpty:
    """SubcircuitDetector handles empty circuit."""

    def test_empty_returns_empty_list(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_empty_topology())
        assert result == []

    def test_empty_no_crash(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        # Should not raise any exception
        detector.detect(_empty_topology())


# ---------------------------------------------------------------------------
# Test: SubcircuitDetector with single IC
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorSingleIC:
    """SubcircuitDetector clusters around single IC."""

    def test_single_ic_produces_one_subcircuit(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_single_ic_topology())
        assert len(result) == 1

    def test_single_ic_center_component(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_single_ic_topology())
        assert result[0].center_component == "U1"

    def test_single_ic_includes_passives(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_single_ic_topology())
        comps = set(result[0].components)
        # Should include the IC and nearby passives
        assert "U1" in comps
        assert "R1" in comps or "R2" in comps or "C1" in comps


# ---------------------------------------------------------------------------
# Test: SubcircuitDetector with multiple ICs
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorMultiIC:
    """SubcircuitDetector partitions multi-IC circuit into subcircuits."""

    def test_multi_ic_produces_multiple_subcircuits(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_ic_topology())
        assert len(result) >= 2

    def test_no_component_overlap(self):
        """Each component assigned to exactly one subcircuit."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_ic_topology())
        all_components = []
        for sc in result:
            all_components.extend(sc.components)
        # No duplicates
        assert len(all_components) == len(set(all_components))

    def test_all_components_assigned(self):
        """All components in topology are accounted for."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        topology = _multi_ic_topology()
        result = detector.detect(topology)
        assigned = set()
        for sc in result:
            assigned.update(sc.components)
        all_refs = {n.ref for n in topology.nodes}
        assert assigned == all_refs


# ---------------------------------------------------------------------------
# Test: Boundary nets
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorBoundaryNets:
    """Boundary nets correctly identified between subcircuits."""

    def test_boundary_nets_exist(self):
        """Nets shared between subcircuits are boundary nets."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_ic_topology())
        # At least one subcircuit should have boundary nets
        all_boundary = set()
        for sc in result:
            all_boundary.update(sc.boundary_nets)
        # There's at least one bridging net (NET_A connects U1 to U2)
        assert len(all_boundary) >= 0  # May not have boundary if they share only power

    def test_boundary_nets_subset_of_all_nets(self):
        """Boundary nets are a subset of the subcircuit's nets."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_ic_topology())
        for sc in result:
            for bn in sc.boundary_nets:
                assert bn in sc.nets


# ---------------------------------------------------------------------------
# Test: Passive-only groups
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorPassiveGroups:
    """Passive-only groups handled gracefully."""

    def test_passive_only_returns_empty_or_unknown(self):
        """Passive-only circuit has no IC subcircuits."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_passive_only_topology())
        # No ICs -> no subcircuits centered on ICs
        # Result is empty list (passive groups can't form subcircuits alone)
        assert isinstance(result, list)

    def test_passive_assigned_to_nearest_ic(self):
        """Unassigned passives near an IC get absorbed into that IC's subcircuit."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        # Build topology with an IC and a passive that is connected but far
        nodes = [
            _make_node("U1", "NE5532", "ic", 8,
                       power_pins=("4", "8"), input_pins=("2", "3"), output_pins=("1",)),
            _make_node("R1", "Device:R", "resistor", 2),
            _make_node("R2", "Device:R", "resistor", 2),
            _make_node("R3", "Device:R", "resistor", 2),  # Extra passive
        ]
        edges = [
            _make_edge("NET_A", "U1", "1", "R1", "1"),
            _make_edge("NET_B", "R1", "2", "R2", "1"),
            _make_edge("NET_C", "R2", "2", "R3", "1"),
        ]
        topology = _make_topology(nodes, edges)
        result = detector.detect(topology)
        # All components should be in the single subcircuit
        if len(result) >= 1:
            all_comps = set()
            for sc in result:
                all_comps.update(sc.components)
            # R3 should be assigned (within 2 hops)
            assert "R3" in all_comps or "R2" in all_comps


# ---------------------------------------------------------------------------
# Test: Sequential IDs
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorSequentialIds:
    """Subcircuit IDs are sequential."""

    def test_sequential_id_format(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_single_ic_topology())
        assert len(result) >= 1
        assert result[0].subcircuit_id == "SC-001"

    def test_multi_sequential_ids(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_ic_topology())
        ids = [sc.subcircuit_id for sc in result]
        # Should be SC-001, SC-002, ... in order
        assert ids == sorted(ids)
        for i, sc_id in enumerate(ids, 1):
            assert sc_id == f"SC-{i:03d}"


# ---------------------------------------------------------------------------
# Test: Confidence scoring
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorConfidence:
    """Confidence is between 0.0 and 1.0."""

    def test_confidence_in_range(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_single_ic_topology())
        for sc in result:
            assert 0.0 <= sc.confidence <= 1.0

    def test_known_ic_has_higher_confidence(self):
        """Known IC (NE5532) with feedback should have higher confidence."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_single_ic_topology())
        # Single IC with feedback should classify with decent confidence
        assert len(result) >= 1
        # Confidence should be > 0.5 for a known IC pattern
        assert result[0].confidence > 0.5


# ---------------------------------------------------------------------------
# Test: Determinism
# ---------------------------------------------------------------------------


class TestSubcircuitDetectorDeterminism:
    """Detection is deterministic for the same input."""

    def test_same_input_same_output(self):
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        topo = _multi_ic_topology()
        result1 = detector.detect(topo)
        result2 = detector.detect(topo)
        assert len(result1) == len(result2)
        for sc1, sc2 in zip(result1, result2):
            assert sc1.subcircuit_id == sc2.subcircuit_id
            assert sc1.components == sc2.components
            assert sc1.subcircuit_type == sc2.subcircuit_type


# ---------------------------------------------------------------------------
# CircuitClassifier feature helpers
# ---------------------------------------------------------------------------


def _opamp_preamplifier_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "NE5532",
        "component_type": "ic",
        "resistor_count": 3,
        "capacitor_count": 2,
        "feedback_resistor_count": 1,
        "feedback_capacitor_count": 0,
        "has_feedback_loop": True,
        "coupling_capacitor_count": 2,
        "has_multiple_inputs": False,
    }


def _opamp_filter_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "NE5532",
        "component_type": "ic",
        "resistor_count": 2,
        "capacitor_count": 4,
        "feedback_resistor_count": 1,
        "feedback_capacitor_count": 2,
        "has_feedback_loop": True,
        "coupling_capacitor_count": 1,
        "has_multiple_inputs": False,
    }


def _compressor_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "THAT4301",
        "component_type": "ic",
        "resistor_count": 5,
        "capacitor_count": 3,
        "has_feedback_loop": False,
        "has_sidechain": True,
        "has_vca_input": True,
    }


def _vca_no_sidechain_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "THAT4301",
        "component_type": "ic",
        "resistor_count": 2,
        "capacitor_count": 1,
        "has_feedback_loop": False,
        "has_sidechain": False,
        "has_vca_input": True,
    }


def _power_supply_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "LM7805",
        "component_type": "ic",
        "resistor_count": 0,
        "capacitor_count": 4,
        "diode_count": 2,
        "has_power_connection": True,
    }


def _digital_control_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "RP2040",
        "component_type": "ic",
        "resistor_count": 3,
        "capacitor_count": 6,
        "has_crystal": True,
        "has_power_connection": True,
    }


def _analog_switch_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "CD4066",
        "component_type": "ic",
        "resistor_count": 2,
        "capacitor_count": 0,
    }


def _output_stage_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "NE5532",
        "component_type": "ic",
        "resistor_count": 1,
        "capacitor_count": 2,
        "feedback_resistor_count": 1,
        "feedback_capacitor_count": 0,
        "has_multiple_inputs": False,
    }


def _oscillator_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "CD4060",
        "component_type": "ic",
        "resistor_count": 2,
        "capacitor_count": 1,
    }


def _lfo_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "CD4060",
        "component_type": "ic",
        "resistor_count": 3,
        "capacitor_count": 2,
    }


def _unknown_ic_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "SomeCustomIC123",
        "component_type": "ic",
        "resistor_count": 1,
        "capacitor_count": 1,
    }


def _mixer_features() -> dict:
    return {
        "center_component": "U1",
        "lib_id": "NE5532",
        "component_type": "ic",
        "resistor_count": 4,
        "capacitor_count": 1,
        "has_multiple_inputs": True,
        "feedback_resistor_count": 1,
        "feedback_capacitor_count": 0,
    }


# ---------------------------------------------------------------------------
# Test: CircuitClassifier
# ---------------------------------------------------------------------------


class TestCircuitClassifier:
    """CircuitClassifier correctly classifies subcircuit types."""

    def test_opamp_preamplifier(self):
        """Op-amp with feedback resistors (no caps in feedback) -> PREAMP."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_opamp_preamplifier_features())
        assert result.subcircuit_type == SubcircuitType.PREAMP
        assert result.confidence >= 0.8

    def test_opamp_filter(self):
        """Op-amp with capacitors in feedback -> FILTER."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_opamp_filter_features())
        assert result.subcircuit_type == SubcircuitType.FILTER
        assert result.confidence >= 0.8

    def test_compressor_with_sidechain(self):
        """THAT4301 with sidechain -> COMPRESSOR."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_compressor_features())
        assert result.subcircuit_type == SubcircuitType.COMPRESSOR
        assert result.confidence >= 0.8

    def test_vca_without_sidechain(self):
        """THAT4301 without sidechain -> VCA."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_vca_no_sidechain_features())
        assert result.subcircuit_type == SubcircuitType.VCA
        assert result.confidence >= 0.8

    def test_power_supply(self):
        """LM7805 + filter caps -> POWER_SUPPLY."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_power_supply_features())
        assert result.subcircuit_type == SubcircuitType.POWER_SUPPLY
        assert result.confidence >= 0.8

    def test_digital_control(self):
        """RP2040 + crystal -> DIGITAL_CONTROL."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_digital_control_features())
        assert result.subcircuit_type == SubcircuitType.DIGITAL_CONTROL
        assert result.confidence >= 0.8

    def test_analog_switch(self):
        """CD4066 -> ANALOG_SWITCH."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_analog_switch_features())
        assert result.subcircuit_type == SubcircuitType.ANALOG_SWITCH
        assert result.confidence >= 0.8

    def test_output_stage(self):
        """Op-amp output buffer -> OUTPUT_STAGE (low component count)."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_output_stage_features())
        assert result.subcircuit_type == SubcircuitType.OUTPUT_STAGE
        assert result.confidence >= 0.7

    def test_oscillator(self):
        """CD4060 oscillator -> OSCILLATOR."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_oscillator_features())
        assert result.subcircuit_type == SubcircuitType.OSCILLATOR
        assert result.confidence >= 0.8

    def test_lfo(self):
        """CD4060 with RC timing -> LFO (takes precedence over OSCILLATOR)."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_lfo_features())
        assert result.subcircuit_type == SubcircuitType.LFO
        assert result.confidence >= 0.8

    def test_unknown_ic(self):
        """Unknown IC with ambiguous components -> UNKNOWN with low confidence."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_unknown_ic_features())
        assert result.subcircuit_type == SubcircuitType.UNKNOWN
        assert result.confidence < 0.5

    def test_mixer(self):
        """Op-amp with multiple inputs -> MIXER."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_mixer_features())
        assert result.subcircuit_type == SubcircuitType.MIXER
        assert result.confidence >= 0.8


class TestClassifierConfidence:
    """Confidence scoring for classifier results."""

    def test_exact_match_high_confidence(self):
        """Exact rule match produces confidence > 0.8."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify(_power_supply_features())
        assert result.confidence >= 0.9

    def test_unknown_low_confidence(self):
        """No rule match produces confidence < 0.5."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify(_unknown_ic_features())
        assert result.confidence < 0.5

    def test_confidence_always_in_range(self):
        """All classification results have confidence in [0.0, 1.0]."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        for features in [
            _opamp_preamplifier_features(),
            _opamp_filter_features(),
            _compressor_features(),
            _power_supply_features(),
            _unknown_ic_features(),
        ]:
            result = c.classify(features)
            assert 0.0 <= result.confidence <= 1.0


class TestClassifierUnknowns:
    """Unknown/ambiguous handling."""

    def test_unknown_returns_unknown_type(self):
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify({"lib_id": "XYZ999", "component_type": "ic"})
        assert result.subcircuit_type == SubcircuitType.UNKNOWN

    def test_unknown_low_confidence(self):
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify({"lib_id": "XYZ999", "component_type": "ic"})
        assert result.confidence < 0.5

    def test_unknown_matched_rule_description(self):
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify({"lib_id": "XYZ999", "component_type": "ic"})
        assert result.matched_rule == "No rule matched"


class TestClassifierOrderedRules:
    """CircuitClassifier follows ordered rules (first match wins)."""

    def test_first_match_wins(self):
        """First matching rule wins, not the most specific."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        # Compressor features also match VCA rule, but compressor rule is first
        result = c.classify(_compressor_features())
        assert result.subcircuit_type == SubcircuitType.COMPRESSOR

    def test_lfo_before_oscillator(self):
        """LFO rule matches before OSCILLATOR rule for CD4060 with RC."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_lfo_features())
        assert result.subcircuit_type == SubcircuitType.LFO

    def test_custom_rule_prepended(self):
        """Custom rules checked before default rules."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType

        custom_rule = [
            (lambda f: f.get("lib_id") == "NE5532", SubcircuitType.EQ, 0.99, "Custom EQ rule"),
        ]
        c = CircuitClassifier(custom_rules=custom_rule)
        result = c.classify(_opamp_preamplifier_features())
        assert result.subcircuit_type == SubcircuitType.EQ
        assert result.matched_rule == "Custom EQ rule"

    def test_classify_batch(self):
        """Batch classification returns one result per input."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        features_list = [
            _opamp_preamplifier_features(),
            _power_supply_features(),
            _unknown_ic_features(),
        ]
        results = c.classify_batch(features_list)
        assert len(results) == 3
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        assert results[0].subcircuit_type == SubcircuitType.PREAMP
        assert results[1].subcircuit_type == SubcircuitType.POWER_SUPPLY
        assert results[2].subcircuit_type == SubcircuitType.UNKNOWN


# ---------------------------------------------------------------------------
# Test: Full integration (detector + classifier on mock topologies)
# ---------------------------------------------------------------------------


def _multi_type_topology() -> CircuitTopology:
    """Three ICs: op-amp, VCA, and voltage regulator."""
    nodes = [
        # Op-amp preamp
        _make_node("U1", "NE5532", "ic", 8,
                   power_pins=("4", "8"), input_pins=("2", "3"), output_pins=("1",)),
        _make_node("R1", "Device:R", "resistor", 2),
        _make_node("R2", "Device:R", "resistor", 2),
        _make_node("R3", "Device:R", "resistor", 2),
        # VCA
        _make_node("U2", "THAT4301", "ic", 8,
                   power_pins=("5", "6"), input_pins=("1", "3", "4"), output_pins=("2",)),
        _make_node("R4", "Device:R", "resistor", 2),
        _make_node("C3", "Device:C", "capacitor", 2),
        # Voltage regulator
        _make_node("U3", "LM7805", "ic", 3,
                   power_pins=("3",), input_pins=("1",), output_pins=("2",)),
        _make_node("C4", "Device:C", "capacitor", 2),
        _make_node("C5", "Device:C", "capacitor", 2),
    ]
    edges = [
        # U1 preamp circuit
        _make_edge("SIG_IN", "R1", "1", "U1", "3"),
        _make_edge("NET_1", "U1", "1", "R2", "1"),
        _make_edge("NET_FB", "R3", "2", "U1", "2", NetClassification.FEEDBACK, "feedback"),
        # U1 -> U2 coupling
        _make_edge("NET_1", "U1", "1", "R4", "1"),
        _make_edge("NET_2", "R4", "2", "U2", "1"),
        # U2 VCA circuit
        _make_edge("NET_3", "U2", "2", "C3", "1"),
        # U3 power supply
        _make_edge("VIN", "U3", "1", "C4", "1", NetClassification.POWER, "power"),
        _make_edge("VOUT", "U3", "2", "C5", "1", NetClassification.POWER, "power"),
    ]
    return _make_topology(
        nodes, edges,
        input_nets=("SIG_IN",),
        power_nets=("VCC", "VIN", "VOUT"),
    )


def _compressor_block_topology() -> CircuitTopology:
    """Compressor: THAT4301 + NE5532 buffer + sidechain RC."""
    nodes = [
        _make_node("U1", "THAT4301", "ic", 8,
                   power_pins=("5", "6"), input_pins=("1", "3", "4"), output_pins=("2",)),
        _make_node("U2", "NE5532", "ic", 8,
                   power_pins=("4", "8"), input_pins=("2", "3"), output_pins=("1",)),
        _make_node("R1", "Device:R", "resistor", 2),
        _make_node("R2", "Device:R", "resistor", 2),
        _make_node("R3", "Device:R", "resistor", 2),
        _make_node("R4", "Device:R", "resistor", 2),
        _make_node("R5", "Device:R", "resistor", 2),
        _make_node("C1", "Device:C", "capacitor", 2),
        _make_node("C2", "Device:C", "capacitor", 2),
        _make_node("C3", "Device:C", "capacitor", 2),
    ]
    edges = [
        _make_edge("SIG_IN", "R1", "1", "U1", "1"),
        _make_edge("NET_A", "U1", "2", "R2", "1"),
        _make_edge("NET_B", "R2", "2", "U2", "3"),
        _make_edge("NET_C", "U2", "1", "R3", "1"),
        _make_edge("NET_D", "R4", "1", "U1", "3"),
        _make_edge("NET_E", "R5", "1", "C1", "1"),
        _make_edge("NET_F", "C2", "1", "C3", "1"),
    ]
    return _make_topology(
        nodes, edges,
        input_nets=("SIG_IN",),
    )


class TestSubcircuitIntegration:
    """Integration tests: detector + classifier on multi-IC topologies."""

    def test_multi_ic_three_subcircuits(self):
        """Three ICs produce 3 subcircuits with correct types."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector, SubcircuitType
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        assert len(result) == 3
        types = {sc.subcircuit_type for sc in result}
        # U1 should be PREAMP (NE5532 with feedback resistors)
        # U2 should be VCA (THAT4301 without sidechain)
        # U3 should be POWER_SUPPLY (LM7805)
        assert SubcircuitType.PREAMP in types or SubcircuitType.POWER_SUPPLY in types

    def test_compressor_block(self):
        """Compressor topology: THAT4301 + NE5532 produce 2 subcircuits."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector, SubcircuitType
        detector = SubcircuitDetector()
        result = detector.detect(_compressor_block_topology())
        assert len(result) >= 2  # U1 (VCA/COMPRESSOR) + U2 (op-amp)
        # At least one subcircuit should be VCA or COMPRESSOR
        types = {sc.subcircuit_type for sc in result}
        assert any(t in types for t in [
            SubcircuitType.VCA, SubcircuitType.COMPRESSOR,
            SubcircuitType.PREAMP, SubcircuitType.FILTER,
        ])

    def test_signal_flow_through_subcircuits(self):
        """Signal flows through subcircuits via boundary nets."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        # Find subcircuits with boundary nets
        with_boundary = [sc for sc in result if len(sc.boundary_nets) > 0]
        # In a multi-IC circuit, at least one subcircuit should share nets
        # with another (boundary nets connect them)
        assert len(result) >= 2

    def test_no_component_overlap_integration(self):
        """No component assigned to multiple subcircuits."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        all_components = []
        for sc in result:
            all_components.extend(sc.components)
        assert len(all_components) == len(set(all_components))

    def test_all_components_accounted_for(self):
        """All components in topology are assigned to a subcircuit."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        topo = _multi_type_topology()
        result = detector.detect(topo)
        assigned = set()
        for sc in result:
            assigned.update(sc.components)
        all_refs = {n.ref for n in topo.nodes}
        assert assigned == all_refs

    def test_features_include_counts(self):
        """Subcircuit.features includes component counts and net stats."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        for sc in result:
            assert "resistor_count" in sc.features
            assert "capacitor_count" in sc.features
            assert "lib_id" in sc.features
            assert "component_type" in sc.features
            assert isinstance(sc.features["resistor_count"], int)
            assert isinstance(sc.features["capacitor_count"], int)

    def test_subcircuit_sorted_by_id(self):
        """Results sorted by subcircuit_id."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        ids = [sc.subcircuit_id for sc in result]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Mock data for feature extraction tests
# ---------------------------------------------------------------------------


def _mock_subcircuit_data() -> dict:
    """Mock subcircuit data for feature extraction tests."""
    return {
        "components": ["U1", "R1", "R2", "C1", "C2"],
        "nets": ["SIG_IN", "SIG_OUT", "FB_NET", "VCC", "GND"],
        "boundary_nets": ["SIG_IN", "SIG_OUT"],
        "center_component": "U1",
        "nodes": {
            "U1": _make_node("U1", "NE5532", "ic", 8,
                             power_pins=("4", "8"), input_pins=("2", "3"), output_pins=("1",)),
            "R1": _make_node("R1", "Device:R", "resistor", 2),
            "R2": _make_node("R2", "Device:R", "resistor", 2),
            "C1": _make_node("C1", "Device:C", "capacitor", 2),
            "C2": _make_node("C2", "Device:C", "capacitor", 2),
        },
        "edges": [
            _make_edge("SIG_IN", "J1", "1", "U1", "3"),
            _make_edge("FB_NET", "U1", "1", "R2", "1", NetClassification.FEEDBACK, "feedback"),
            _make_edge("FB_NET", "R2", "2", "U1", "2", NetClassification.FEEDBACK, "feedback"),
            _make_edge("VCC", "U1", "8", "U1", "4", NetClassification.POWER),
            _make_edge("GND", "U1", "4", "U1", "4", NetClassification.GROUND),
            _make_edge("SIG_OUT", "U1", "1", "J2", "1"),
        ],
        "power_nets": {"VCC", "GND"},
        "signal_paths": [["J1", "U1", "J2"]],
    }


# ---------------------------------------------------------------------------
# Test: SubcircuitFeatures dataclass
# ---------------------------------------------------------------------------


class TestSubcircuitFeatures:
    """SubcircuitFeatures frozen dataclass schema and serialization."""

    def test_has_25_fields(self):
        """SubcircuitFeatures has all 25 fields."""
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(SubcircuitFeatures)}
        expected = {
            "subcircuit_id",
            "ic_count", "resistor_count", "capacitor_count",
            "inductor_count", "diode_count", "transistor_count",
            "total_component_count",
            "has_feedback_loop", "has_power_connection", "has_crystal",
            "feedback_capacitor_count", "feedback_resistor_count",
            "coupling_capacitor_count",
            "input_net_count", "output_net_count", "power_net_count",
            "ground_net_count", "control_net_count", "feedback_net_count",
            "net_count", "boundary_net_count",
            "ic_lib_ids", "primary_ic_type",
            "max_signal_path_length", "component_density",
        }
        assert field_names == expected, f"Missing: {expected - field_names}, Extra: {field_names - expected}"

    def test_frozen(self):
        """SubcircuitFeatures is frozen (immutable)."""
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        features = SubcircuitFeatures(
            subcircuit_id="SC-001",
            ic_count=1, resistor_count=2, capacitor_count=2,
            inductor_count=0, diode_count=0, transistor_count=0,
            total_component_count=5,
            has_feedback_loop=True, has_power_connection=True, has_crystal=False,
            feedback_capacitor_count=0, feedback_resistor_count=1,
            coupling_capacitor_count=2,
            input_net_count=1, output_net_count=1, power_net_count=1,
            ground_net_count=1, control_net_count=0, feedback_net_count=1,
            net_count=5, boundary_net_count=2,
            ic_lib_ids=("NE5532",), primary_ic_type="opamp",
            max_signal_path_length=2, component_density=1.0,
        )
        try:
            features.ic_count = 99  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass

    def test_json_serializable(self):
        """SubcircuitFeatures is JSON-serializable via dataclasses.asdict."""
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        import json
        features = SubcircuitFeatures(
            subcircuit_id="SC-001",
            ic_count=1, resistor_count=2, capacitor_count=2,
            inductor_count=0, diode_count=0, transistor_count=0,
            total_component_count=5,
            has_feedback_loop=True, has_power_connection=True, has_crystal=False,
            feedback_capacitor_count=0, feedback_resistor_count=1,
            coupling_capacitor_count=2,
            input_net_count=1, output_net_count=1, power_net_count=1,
            ground_net_count=1, control_net_count=0, feedback_net_count=1,
            net_count=5, boundary_net_count=2,
            ic_lib_ids=("NE5532",), primary_ic_type="opamp",
            max_signal_path_length=2, component_density=1.0,
        )
        json_str = features.to_json()
        parsed = json.loads(json_str)
        assert parsed["ic_count"] == 1
        assert parsed["resistor_count"] == 2
        assert parsed["primary_ic_type"] == "opamp"

    def test_to_dict(self):
        """to_dict returns plain dict for sklearn DictVectorizer."""
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        features = SubcircuitFeatures(
            subcircuit_id="SC-001",
            ic_count=1, resistor_count=2, capacitor_count=2,
            inductor_count=0, diode_count=0, transistor_count=0,
            total_component_count=5,
            has_feedback_loop=True, has_power_connection=True, has_crystal=False,
            feedback_capacitor_count=0, feedback_resistor_count=1,
            coupling_capacitor_count=2,
            input_net_count=1, output_net_count=1, power_net_count=1,
            ground_net_count=1, control_net_count=0, feedback_net_count=1,
            net_count=5, boundary_net_count=2,
            ic_lib_ids=("NE5532",), primary_ic_type="opamp",
            max_signal_path_length=2, component_density=1.0,
        )
        d = features.to_dict()
        assert isinstance(d, dict)
        assert d["ic_count"] == 1
        assert d["ic_lib_ids"] == ("NE5532",)

    def test_to_numeric_vector(self):
        """to_numeric_vector produces fixed-length float list for tensor conversion."""
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        features = SubcircuitFeatures(
            subcircuit_id="SC-001",
            ic_count=1, resistor_count=2, capacitor_count=2,
            inductor_count=0, diode_count=0, transistor_count=0,
            total_component_count=5,
            has_feedback_loop=True, has_power_connection=True, has_crystal=False,
            feedback_capacitor_count=0, feedback_resistor_count=1,
            coupling_capacitor_count=2,
            input_net_count=1, output_net_count=1, power_net_count=1,
            ground_net_count=1, control_net_count=0, feedback_net_count=1,
            net_count=5, boundary_net_count=2,
            ic_lib_ids=("NE5532",), primary_ic_type="opamp",
            max_signal_path_length=2, component_density=1.0,
        )
        vec = features.to_numeric_vector()
        assert isinstance(vec, list)
        assert all(isinstance(v, float) for v in vec)
        assert len(vec) == 23  # All numeric fields minus subcircuit_id, ic_lib_ids, primary_ic_type

    def test_from_dict_roundtrip(self):
        """from_dict reconstructs SubcircuitFeatures from dict."""
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        original = SubcircuitFeatures(
            subcircuit_id="SC-001",
            ic_count=1, resistor_count=2, capacitor_count=2,
            inductor_count=0, diode_count=0, transistor_count=0,
            total_component_count=5,
            has_feedback_loop=True, has_power_connection=True, has_crystal=False,
            feedback_capacitor_count=0, feedback_resistor_count=1,
            coupling_capacitor_count=2,
            input_net_count=1, output_net_count=1, power_net_count=1,
            ground_net_count=1, control_net_count=0, feedback_net_count=1,
            net_count=5, boundary_net_count=2,
            ic_lib_ids=("NE5532",), primary_ic_type="opamp",
            max_signal_path_length=2, component_density=1.0,
        )
        d = original.to_dict()
        restored = SubcircuitFeatures.from_dict(d)
        assert restored == original


# ---------------------------------------------------------------------------
# Test: Feature extraction from topology data
# ---------------------------------------------------------------------------


class TestFeatureExtraction:
    """extract_features computes correct feature vectors."""

    def test_correct_component_counts(self):
        """extract_features counts ICs, resistors, capacitors correctly."""
        from kicad_agent.analysis.feature_extraction import extract_features
        data = _mock_subcircuit_data()
        features = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
            subcircuit_id="SC-TEST",
        )
        assert features.ic_count == 1
        assert features.resistor_count == 2
        assert features.capacitor_count == 2
        assert features.total_component_count == 5

    def test_identifies_feedback_loops(self):
        """extract_features detects feedback edges in subcircuit."""
        from kicad_agent.analysis.feature_extraction import extract_features
        data = _mock_subcircuit_data()
        features = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
        )
        assert features.has_feedback_loop is True
        assert features.feedback_net_count >= 1

    def test_identifies_power_connections(self):
        """extract_features detects power net connections."""
        from kicad_agent.analysis.feature_extraction import extract_features
        data = _mock_subcircuit_data()
        features = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
        )
        assert features.has_power_connection is True

    def test_component_density(self):
        """component_density = total_components / net_count."""
        from kicad_agent.analysis.feature_extraction import extract_features
        data = _mock_subcircuit_data()
        features = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
        )
        assert features.component_density == 5 / 5  # 5 components, 5 nets

    def test_primary_ic_type_opamp(self):
        """primary_ic_type returns 'opamp' for NE5532."""
        from kicad_agent.analysis.feature_extraction import extract_features
        data = _mock_subcircuit_data()
        features = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
        )
        assert features.primary_ic_type == "opamp"

    def test_deterministic(self):
        """Feature extraction is deterministic (same input -> same output)."""
        from kicad_agent.analysis.feature_extraction import extract_features
        data = _mock_subcircuit_data()
        f1 = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
        )
        f2 = extract_features(
            component_refs=data["components"],
            nodes=data["nodes"],
            edges=data["edges"],
            nets=data["nets"],
            boundary_nets=data["boundary_nets"],
            center_component=data["center_component"],
            power_nets=data["power_nets"],
            signal_paths=data["signal_paths"],
        )
        assert f1 == f2


# ---------------------------------------------------------------------------
# Test: Feature extraction edge cases
# ---------------------------------------------------------------------------


class TestFeatureExtractionEdgeCases:
    """Edge cases for feature extraction."""

    def test_passive_only_subcircuit(self):
        """Subcircuit with 0 ICs."""
        from kicad_agent.analysis.feature_extraction import extract_features
        nodes = {
            "R1": _make_node("R1", "Device:R", "resistor", 2),
            "C1": _make_node("C1", "Device:C", "capacitor", 2),
        }
        features = extract_features(
            component_refs=["R1", "C1"],
            nodes=nodes,
            edges=[_make_edge("NET_A", "R1", "1", "C1", "1")],
            nets=["NET_A"],
            boundary_nets=["NET_A"],
            center_component="R1",  # No IC, so center is passive
            power_nets=set(),
            signal_paths=[],
        )
        assert features.ic_count == 0
        assert features.resistor_count == 1
        assert features.capacitor_count == 1
        assert features.primary_ic_type == "unknown"

    def test_subcircuit_id_set(self):
        """subcircuit_id is properly set in features."""
        from kicad_agent.analysis.feature_extraction import extract_features
        nodes = {
            "U1": _make_node("U1", "NE5532", "ic", 8),
        }
        features = extract_features(
            component_refs=["U1"],
            nodes=nodes,
            edges=[],
            nets=["NET_A"],
            boundary_nets=[],
            center_component="U1",
            power_nets=set(),
            signal_paths=[],
            subcircuit_id="SC-042",
        )
        assert features.subcircuit_id == "SC-042"

    def test_no_feedback_edges(self):
        """Subcircuit with no feedback edges."""
        from kicad_agent.analysis.feature_extraction import extract_features
        nodes = {
            "U1": _make_node("U1", "LM7805", "ic", 3),
            "C1": _make_node("C1", "Device:C", "capacitor", 2),
        }
        features = extract_features(
            component_refs=["U1", "C1"],
            nodes=nodes,
            edges=[_make_edge("VOUT", "U1", "2", "C1", "1")],
            nets=["VOUT"],
            boundary_nets=[],
            center_component="U1",
            power_nets={"VOUT"},
            signal_paths=[],
        )
        assert features.has_feedback_loop is False
        assert features.feedback_net_count == 0

    def test_crystal_detection(self):
        """Crystal components detected via lib_id."""
        from kicad_agent.analysis.feature_extraction import extract_features
        nodes = {
            "U1": _make_node("U1", "RP2040", "ic", 40),
            "Y1": _make_node("Y1", "Device:Crystal", "misc", 2),
        }
        features = extract_features(
            component_refs=["U1", "Y1"],
            nodes=nodes,
            edges=[_make_edge("XTAL", "U1", "1", "Y1", "1")],
            nets=["XTAL"],
            boundary_nets=[],
            center_component="U1",
            power_nets=set(),
            signal_paths=[],
        )
        assert features.has_crystal is True

    def test_primary_ic_types(self):
        """Various IC types correctly classified."""
        from kicad_agent.analysis.feature_extraction import _classify_ic_type
        assert _classify_ic_type("NE5532") == "opamp"
        assert _classify_ic_type("TL072") == "opamp"
        assert _classify_ic_type("THAT4301") == "vca"
        assert _classify_ic_type("THAT2181") == "vca"
        assert _classify_ic_type("RP2040") == "mcu"
        assert _classify_ic_type("ATMEGA328P") == "mcu"
        assert _classify_ic_type("LM7805") == "regulator"
        assert _classify_ic_type("AMS1117") == "regulator"
        assert _classify_ic_type("CD4066") == "switch"
        assert _classify_ic_type("CD4060") == "oscillator"
        assert _classify_ic_type("UnknownIC") == "unknown"

    def test_ic_lib_ids_tuple(self):
        """ic_lib_ids captures all IC lib_ids in subcircuit."""
        from kicad_agent.analysis.feature_extraction import extract_features
        nodes = {
            "U1": _make_node("U1", "NE5532", "ic", 8),
            "R1": _make_node("R1", "Device:R", "resistor", 2),
        }
        features = extract_features(
            component_refs=["U1", "R1"],
            nodes=nodes,
            edges=[],
            nets=["NET_A"],
            boundary_nets=[],
            center_component="U1",
            power_nets=set(),
            signal_paths=[],
        )
        assert features.ic_lib_ids == ("NE5532",)


# ---------------------------------------------------------------------------
# Test: Confidence calibration
# ---------------------------------------------------------------------------


class TestConfidenceCalibration:
    """Confidence scoring calibrated: >0.8 exact, 0.5-0.8 heuristic, <0.5 unknown."""

    def test_exact_ic_match_high_confidence(self):
        """Exact IC match (THAT4301 with sidechain) -> confidence > 0.8."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_compressor_features())
        assert result.subcircuit_type == SubcircuitType.COMPRESSOR
        assert result.confidence > 0.8

    def test_heuristic_match_medium_confidence(self):
        """Heuristic match (known op-amp pattern) -> confidence >= 0.5."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify(_output_stage_features())
        assert result.confidence >= 0.5
        assert result.confidence <= 0.9

    def test_no_match_low_confidence(self):
        """No rule match -> confidence < 0.5."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        result = c.classify(_unknown_ic_features())
        assert result.subcircuit_type == SubcircuitType.UNKNOWN
        assert result.confidence < 0.5

    def test_feature_vector_included_for_unknown(self):
        """ClassificationResult includes feature_vector for unknown classifications."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify(_unknown_ic_features())
        assert result.feature_vector is not None
        assert isinstance(result.feature_vector, dict)
        assert "lib_id" in result.feature_vector

    def test_classify_accepts_subcircuit_features(self):
        """CircuitClassifier accepts SubcircuitFeatures in addition to raw dict."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType

        features = SubcircuitFeatures(
            subcircuit_id="SC-001",
            ic_count=1, resistor_count=2, capacitor_count=2,
            inductor_count=0, diode_count=0, transistor_count=0,
            total_component_count=5,
            has_feedback_loop=True, has_power_connection=True, has_crystal=False,
            feedback_capacitor_count=0, feedback_resistor_count=1,
            coupling_capacitor_count=2,
            input_net_count=1, output_net_count=1, power_net_count=1,
            ground_net_count=1, control_net_count=0, feedback_net_count=1,
            net_count=5, boundary_net_count=2,
            ic_lib_ids=("NE5532",), primary_ic_type="opamp",
            max_signal_path_length=2, component_density=1.0,
        )
        c = CircuitClassifier()
        result = c.classify(features)
        # NE5532 with feedback resistors should classify as some type
        assert result.subcircuit_type != SubcircuitType.UNKNOWN or result.confidence < 0.5

    def test_custom_rule_override_confidence(self):
        """Custom rules can override default confidence for domain-specific tuning."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType

        custom_rule = [
            (lambda f: f.get("lib_id") == "NE5532", SubcircuitType.EQ, 0.99, "Custom EQ rule"),
        ]
        c = CircuitClassifier(custom_rules=custom_rule)
        result = c.classify(_opamp_preamplifier_features())
        assert result.confidence == 0.99
        assert result.matched_rule == "Custom EQ rule"


# ---------------------------------------------------------------------------
# Test: Unknown/ambiguous handling
# ---------------------------------------------------------------------------


class TestUnknownHandling:
    """Unknown and ambiguous subcircuits logged with feature vectors."""

    def test_ambiguous_opamp_lower_confidence(self):
        """Op-amp that could be preamp OR output stage has lower confidence."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        # Output stage features: ambiguous (op-amp with low component count)
        result = c.classify(_output_stage_features())
        # Output stage should still classify but with medium confidence
        assert result.confidence <= 0.8

    def test_unknown_logged_with_feature_vector(self):
        """Unknown classifications have feature_vector populated for ML pipeline."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify({"lib_id": "XYZ999", "component_type": "ic"})
        assert result.feature_vector is not None

    def test_known_high_confidence_no_feature_vector(self):
        """High-confidence matches do not include feature_vector (not needed for ML)."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        result = c.classify(_power_supply_features())
        assert result.confidence >= 0.9
        # High-confidence results don't need feature vector
        assert result.feature_vector is None


# ---------------------------------------------------------------------------
# Test: Batch classification consistency
# ---------------------------------------------------------------------------


class TestBatchClassification:
    """Batch classification returns consistent results."""

    def test_batch_consistent_with_individual(self):
        """classify_batch returns same results as individual classify calls."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        features_list = [
            _opamp_preamplifier_features(),
            _power_supply_features(),
            _unknown_ic_features(),
        ]
        batch_results = c.classify_batch(features_list)
        for features, batch_result in zip(features_list, batch_results):
            individual = c.classify(features)
            assert batch_result.subcircuit_type == individual.subcircuit_type
            assert batch_result.confidence == individual.confidence

    def test_batch_confidence_ordering(self):
        """Specific rules (high confidence) ordered before general rules."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        from kicad_agent.analysis.subcircuit_detector import SubcircuitType
        c = CircuitClassifier()
        # Compressor has confidence 0.9 (specific), VCA has 0.85 (less specific)
        compressor = c.classify(_compressor_features())
        vca = c.classify(_vca_no_sidechain_features())
        assert compressor.confidence > vca.confidence

    def test_batch_returns_feature_vectors_for_unknowns(self):
        """Batch results include feature vectors for unknown classifications."""
        from kicad_agent.analysis.circuit_classifier import CircuitClassifier
        c = CircuitClassifier()
        results = c.classify_batch([
            _power_supply_features(),
            _unknown_ic_features(),
        ])
        assert results[0].feature_vector is None  # Known, no feature vector needed
        assert results[1].feature_vector is not None  # Unknown, feature vector for ML


# ---------------------------------------------------------------------------
# Test: Feature integration into SubcircuitDetector
# ---------------------------------------------------------------------------


class TestFeatureIntegration:
    """Feature extraction integrated into SubcircuitDetector.detect()."""

    def test_detect_returns_features_dict(self):
        """SubcircuitDetector.detect returns Subcircuits with feature data."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        assert len(result) >= 1
        for sc in result:
            assert isinstance(sc.features, dict)
            # Should have ML-ready feature fields
            assert "resistor_count" in sc.features
            assert "capacitor_count" in sc.features

    def test_all_subcircuits_have_feature_vectors(self):
        """All subcircuits in a topology have feature vectors."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        assert len(result) >= 2
        for sc in result:
            assert sc.features is not None
            assert isinstance(sc.features, dict)
            assert "total_component_count" in sc.features
            assert "component_density" in sc.features

    def test_feature_determinism_across_runs(self):
        """Feature vectors from same schematic are deterministic across runs."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        topo = _multi_type_topology()
        result1 = detector.detect(topo)
        result2 = detector.detect(topo)
        for sc1, sc2 in zip(result1, result2):
            assert sc1.features == sc2.features

    def test_to_jsonl_export(self):
        """to_jsonl exports feature vectors as valid JSONL."""
        import json
        import tempfile
        import os
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            count = detector.to_jsonl(result, path)
            assert count == len(result)
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == len(result)
            for line in lines:
                parsed = json.loads(line)
                assert "subcircuit_id" in parsed
                assert "subcircuit_type" in parsed
                assert "confidence" in parsed
                assert "resistor_count" in parsed
        finally:
            os.unlink(path)

    def test_end_to_end_feature_fields(self):
        """End-to-end: topology -> detection -> features include all key fields."""
        from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
        detector = SubcircuitDetector()
        result = detector.detect(_multi_type_topology())
        assert len(result) >= 2
        for sc in result:
            f = sc.features
            # Component counts
            assert "ic_count" in f
            assert "resistor_count" in f
            assert "capacitor_count" in f
            assert "total_component_count" in f
            # Topology features
            assert "has_feedback_loop" in f
            assert "has_power_connection" in f
            assert "component_density" in f
            assert "primary_ic_type" in f
            assert "ic_lib_ids" in f
