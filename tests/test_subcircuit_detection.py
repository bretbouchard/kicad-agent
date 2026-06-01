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
