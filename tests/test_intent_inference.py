"""Tests for circuit intent inference.

TDD tests for IntentInferrer with real analog-ecosystem circuit patterns.
Covers schema validation, rule-based inference, signal flow generation,
and edge cases.

DOMAIN-03: Design intent inference from circuit topology.
"""

from __future__ import annotations

import pytest

from kicad_agent.analysis.intent_schemas import (
    DesignGoal,
    DesignIntent,
    SubcircuitIntent,
)
from kicad_agent.analysis.intent_inference import (
    InferenceResult,
    IntentInferrer,
)
from kicad_agent.analysis.subcircuit_detector import Subcircuit
from kicad_agent.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)
from kicad_agent.analysis.types import NetClassification


# ---------------------------------------------------------------------------
# Mock topology helpers
# ---------------------------------------------------------------------------


def _make_node(ref: str, lib_id: str, component_type: str = "ic") -> TopologyNode:
    """Create a TopologyNode with sensible defaults for testing."""
    return TopologyNode(
        ref=ref,
        lib_id=lib_id,
        component_type=component_type,
        pin_count=8,
        power_pins=("VCC", "GND"),
        input_pins=(),
        output_pins=(),
    )


def _make_edge(
    source_ref: str,
    target_ref: str,
    net_name: str,
) -> TopologyEdge:
    """Create a TopologyEdge with sensible defaults for testing."""
    return TopologyEdge(
        net_name=net_name,
        source_ref=source_ref,
        source_pin="1",
        target_ref=target_ref,
        target_pin="1",
        classification=NetClassification.SIGNAL,
        signal_direction="forward",
    )


def _make_subcircuit(
    function: str = "vca",
    components: tuple[str, ...] = (),
    input_nets: tuple[str, ...] = (),
    output_nets: tuple[str, ...] = (),
    control_nets: tuple[str, ...] = (),
    confidence: float = 0.9,
) -> Subcircuit:
    """Create a Subcircuit with sensible defaults for testing."""
    return Subcircuit(
        subcircuit_id="SC-001",
        components=components,
        nets=input_nets + output_nets + control_nets,
        boundary_nets=(),
        subcircuit_type=_function_to_subcircuit_type(function),
        confidence=confidence,
        center_component=components[0] if components else "U1",
        features={
            "lib_id": "",
            "has_sidechain": "SIDECHAIN" in " ".join(control_nets).upper(),
        },
    )


def _function_to_subcircuit_type(function: str):
    """Map function string to SubcircuitType."""
    from kicad_agent.analysis.subcircuit_detector import SubcircuitType

    mapping = {
        "vca": SubcircuitType.VCA,
        "compressor": SubcircuitType.COMPRESSOR,
        "buffer": SubcircuitType.OUTPUT_STAGE,
        "switch": SubcircuitType.ANALOG_SWITCH,
        "oscillator": SubcircuitType.OSCILLATOR,
        "integrator": SubcircuitType.ENVELOPE,
        "filter": SubcircuitType.FILTER,
        "power_supply": SubcircuitType.POWER_SUPPLY,
        "unknown": SubcircuitType.UNKNOWN,
    }
    return mapping.get(function, SubcircuitType.UNKNOWN)


def _make_empty_topology() -> CircuitTopology:
    """Create an empty CircuitTopology."""
    return CircuitTopology(
        nodes=(),
        edges=(),
        input_nets=(),
        output_nets=(),
        power_nets=(),
        signal_paths=(),
        stats={"component_count": 0, "net_count": 0, "signal_path_count": 0,
               "feedback_count": 0, "net_stats": {}},
    )


# ---------------------------------------------------------------------------
# Subcircuit fixtures
# ---------------------------------------------------------------------------

COMPRESSOR_SUBCIRCUIT = _make_subcircuit(
    function="vca",
    components=("U22", "R60", "R61", "R62", "R63", "C46", "C47", "C48"),
    input_nets=("AUDIO_IN",),
    output_nets=("AUDIO_OUT",),
    control_nets=("SIDECHAIN", "CV_IN"),
    confidence=0.9,
)

SWITCH_SUBCIRCUIT = _make_subcircuit(
    function="switch",
    components=("U21",),
    input_nets=("AUDIO_IN", "BYPASS_IN"),
    output_nets=("SWITCH_OUT",),
    control_nets=("BYPASS_CTRL",),
    confidence=0.85,
)

BUFFER_SUBCIRCUIT = _make_subcircuit(
    function="buffer",
    components=("U24", "R67", "R68", "R69", "C50"),
    input_nets=("BUFFER_IN",),
    output_nets=("EQ_OUT",),
    control_nets=(),
    confidence=0.92,
)

OSCILLATOR_SUBCIRCUIT = _make_subcircuit(
    function="oscillator",
    components=("U10", "R20", "R21", "C15", "C16"),
    input_nets=(),
    output_nets=("CLOCK_OUT", "LFO_SQUARE"),
    control_nets=("FREQ_CTRL",),
    confidence=0.88,
)

ENVELOPE_SUBCIRCUIT = _make_subcircuit(
    function="integrator",
    components=("U5", "R10", "R11", "C8", "D1", "D2"),
    input_nets=("TRIGGER_IN",),
    output_nets=("ENVELOPE_OUT",),
    control_nets=("ATTACK", "DECAY", "SUSTAIN", "RELEASE"),
    confidence=0.75,
)


# ---------------------------------------------------------------------------
# Topology builders for specific IC patterns
# ---------------------------------------------------------------------------


def _make_compressor_topology() -> CircuitTopology:
    """Topology with THAT4301 VCA + sidechain (compressor)."""
    nodes = (
        _make_node("U22", "THAT4301"),
        _make_node("R60", "Device:R", "resistor"),
        _make_node("R61", "Device:R", "resistor"),
        _make_node("R62", "Device:R", "resistor"),
        _make_node("R63", "Device:R", "resistor"),
        _make_node("C46", "Device:C", "capacitor"),
        _make_node("C47", "Device:C", "capacitor"),
        _make_node("C48", "Device:C", "capacitor"),
    )
    edges = (
        _make_edge("R60", "U22", "AUDIO_IN"),
        _make_edge("U22", "R61", "AUDIO_OUT"),
        _make_edge("R62", "U22", "SIDECHAIN"),
        _make_edge("R63", "U22", "CV_IN"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=("AUDIO_IN",),
        output_nets=("AUDIO_OUT",),
        power_nets=("VCC",),
        signal_paths=(("R60", "U22", "R61"),),
        stats={"component_count": 8, "net_count": 4, "signal_path_count": 1,
               "feedback_count": 0, "net_stats": {}},
    )


def _make_buffer_topology() -> CircuitTopology:
    """Topology with NE5532 buffer with feedback network."""
    nodes = (
        _make_node("U24", "NE5532"),
        _make_node("R67", "Device:R", "resistor"),
        _make_node("R68", "Device:R", "resistor"),
        _make_node("R69", "Device:R", "resistor"),
        _make_node("C50", "Device:C", "capacitor"),
    )
    edges = (
        _make_edge("R67", "U24", "BUFFER_IN"),
        _make_edge("U24", "R68", "EQ_OUT"),
        _make_edge("R68", "R69", "FEEDBACK_NET"),
        _make_edge("R69", "U24", "FEEDBACK_NET"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=("BUFFER_IN",),
        output_nets=("EQ_OUT",),
        power_nets=("VCC",),
        signal_paths=(("R67", "U24", "R68"),),
        stats={"component_count": 5, "net_count": 3, "signal_path_count": 1,
               "feedback_count": 1, "net_stats": {}},
    )


def _make_switch_topology() -> CircuitTopology:
    """Topology with CD4066 analog switch with control nets."""
    nodes = (
        _make_node("U21", "CD4066"),
    )
    edges = (
        _make_edge("U21", "U21", "AUDIO_IN"),
        _make_edge("U21", "U21", "SWITCH_OUT"),
        _make_edge("U21", "U21", "BYPASS_CTRL"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=("AUDIO_IN", "BYPASS_IN"),
        output_nets=("SWITCH_OUT",),
        power_nets=("VCC",),
        signal_paths=(),
        stats={"component_count": 1, "net_count": 3, "signal_path_count": 0,
               "feedback_count": 0, "net_stats": {}},
    )


def _make_oscillator_topology() -> CircuitTopology:
    """Topology with CD4060 oscillator + RC timing."""
    nodes = (
        _make_node("U10", "CD4060"),
        _make_node("R20", "Device:R", "resistor"),
        _make_node("R21", "Device:R", "resistor"),
        _make_node("C15", "Device:C", "capacitor"),
        _make_node("C16", "Device:C", "capacitor"),
    )
    edges = (
        _make_edge("U10", "R20", "CLOCK_OUT"),
        _make_edge("U10", "R21", "LFO_SQUARE"),
        _make_edge("R20", "C15", "FREQ_CTRL"),
        _make_edge("C15", "U10", "FREQ_CTRL"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=(),
        output_nets=("CLOCK_OUT", "LFO_SQUARE"),
        power_nets=("VCC",),
        signal_paths=(),
        stats={"component_count": 5, "net_count": 3, "signal_path_count": 0,
               "feedback_count": 0, "net_stats": {}},
    )


def _make_envelope_topology() -> CircuitTopology:
    """Topology with LM358 integrator (envelope generator)."""
    nodes = (
        _make_node("U5", "LM358"),
        _make_node("R10", "Device:R", "resistor"),
        _make_node("R11", "Device:R", "resistor"),
        _make_node("C8", "Device:C", "capacitor"),
        _make_node("D1", "Device:D", "diode"),
        _make_node("D2", "Device:D", "diode"),
    )
    edges = (
        _make_edge("R10", "U5", "TRIGGER_IN"),
        _make_edge("U5", "C8", "ENVELOPE_OUT"),
        _make_edge("R11", "U5", "INTEGRAT_NET"),
        _make_edge("C8", "U5", "INTEGRAT_NET"),
    )
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=("TRIGGER_IN",),
        output_nets=("ENVELOPE_OUT",),
        power_nets=("VCC",),
        signal_paths=(),
        stats={"component_count": 6, "net_count": 3, "signal_path_count": 0,
               "feedback_count": 0, "net_stats": {}},
    )


# ===========================================================================
# TestSubcircuitIntentSchema
# ===========================================================================


class TestSubcircuitIntentSchema:
    """Validation tests for SubcircuitIntent schema."""

    def test_validates_with_all_required_fields(self):
        """SubcircuitIntent validates with function, nets, confidence."""
        intent = SubcircuitIntent(
            function="compressor_vca",
            component_refs=("U22", "R60"),
            input_nets=("AUDIO_IN",),
            output_nets=("AUDIO_OUT",),
            control_nets=("SIDECHAIN",),
            design_choices=("class_A_bias",),
            confidence=0.92,
        )
        assert intent.function == "compressor_vca"
        assert intent.component_refs == ("U22", "R60")
        assert intent.input_nets == ("AUDIO_IN",)
        assert intent.output_nets == ("AUDIO_OUT",)
        assert intent.control_nets == ("SIDECHAIN",)
        assert intent.design_choices == ("class_A_bias",)
        assert intent.confidence == 0.92

    def test_rejects_empty_function(self):
        """SubcircuitIntent rejects empty function string."""
        with pytest.raises(ValueError):
            SubcircuitIntent(
                function="",
                component_refs=(),
                input_nets=(),
                output_nets=(),
                control_nets=(),
                design_choices=(),
                confidence=0.5,
            )

    def test_rejects_whitespace_only_function(self):
        """SubcircuitIntent rejects whitespace-only function string."""
        with pytest.raises(ValueError, match="function must not be empty"):
            SubcircuitIntent(
                function="   ",
                component_refs=(),
                input_nets=(),
                output_nets=(),
                control_nets=(),
                design_choices=(),
                confidence=0.5,
            )

    def test_confidence_clamped_to_range(self):
        """SubcircuitIntent confidence must be in [0.0, 1.0]."""
        with pytest.raises(ValueError):
            SubcircuitIntent(
                function="test",
                confidence=-0.1,
            )
        with pytest.raises(ValueError):
            SubcircuitIntent(
                function="test",
                confidence=1.5,
            )

    def test_defaults_for_optional_fields(self):
        """SubcircuitIntent provides defaults for optional fields."""
        intent = SubcircuitIntent(
            function="test_function",
            confidence=0.8,
        )
        assert intent.component_refs == ()
        assert intent.input_nets == ()
        assert intent.output_nets == ()
        assert intent.control_nets == ()
        assert intent.design_choices == ()


# ===========================================================================
# TestDesignIntentSchema
# ===========================================================================


class TestDesignIntentSchema:
    """Validation tests for DesignIntent schema."""

    def test_validates_with_all_required_fields(self):
        """DesignIntent validates with overall_type, subcircuit_intents, confidence."""
        sub_intent = SubcircuitIntent(
            function="compressor_vca",
            confidence=0.92,
        )
        intent = DesignIntent(
            overall_type="compressor",
            subcircuit_intents=(sub_intent,),
            signal_flow_description="Input -> VCA -> Output",
            design_goals=(DesignGoal.AUDIO_PROCESSING,),
            confidence=0.88,
            schematic_path="test.kicad_sch",
        )
        assert intent.overall_type == "compressor"
        assert len(intent.subcircuit_intents) == 1
        assert intent.signal_flow_description == "Input -> VCA -> Output"
        assert intent.confidence == 0.88
        assert intent.schematic_path == "test.kicad_sch"

    def test_confidence_clamped_to_range(self):
        """DesignIntent confidence is clamped to [0.0, 1.0]."""
        with pytest.raises(ValueError):
            DesignIntent(
                overall_type="test",
                confidence=-0.1,
            )
        with pytest.raises(ValueError):
            DesignIntent(
                overall_type="test",
                confidence=2.0,
            )

    def test_subcircuit_intents_capped_at_50(self):
        """DesignIntent subcircuit_intents capped at 50 (T-47-01 DoS prevention)."""
        intents = tuple(
            SubcircuitIntent(function=f"func_{i}", confidence=0.5)
            for i in range(51)
        )
        with pytest.raises(ValueError):
            DesignIntent(
                overall_type="test",
                subcircuit_intents=intents,
                confidence=0.5,
            )

    def test_signal_flow_description_max_length(self):
        """DesignIntent signal_flow_description capped at 2000 chars (T-47-02)."""
        with pytest.raises(ValueError):
            DesignIntent(
                overall_type="test",
                signal_flow_description="x" * 2001,
                confidence=0.5,
            )


# ===========================================================================
# TestDesignGoalEnum
# ===========================================================================


class TestDesignGoalEnum:
    """Tests for DesignGoal enum values."""

    def test_all_expected_goals_exist(self):
        """DesignGoal enum has all expected values."""
        expected = [
            "AUDIO_PROCESSING", "POWER_SUPPLY", "CONTROL", "MIXING",
            "FILTERING", "GENERATION", "ROUTING", "PROTECTION", "UNKNOWN",
        ]
        for goal_name in expected:
            assert hasattr(DesignGoal, goal_name), f"Missing DesignGoal.{goal_name}"

    def test_goal_values_are_lowercase(self):
        """DesignGoal values are lowercase strings."""
        assert DesignGoal.AUDIO_PROCESSING.value == "audio_processing"
        assert DesignGoal.POWER_SUPPLY.value == "power_supply"
        assert DesignGoal.UNKNOWN.value == "unknown"


# ===========================================================================
# TestIntentInferrer
# ===========================================================================


class TestIntentInferrer:
    """Inference tests using mock topology data with real IC patterns."""

    def test_compressor_vca_intent(self):
        """THAT4301 + sidechain topology classified as compressor intent."""
        topology = _make_compressor_topology()
        subcircuits = [COMPRESSOR_SUBCIRCUIT]
        # Set lib_id in features for the subcircuit
        subcircuits[0].features["lib_id"] = "THAT4301"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert result.intent.overall_type == "compressor"
        assert result.intent.confidence >= 0.8
        assert len(result.intent.subcircuit_intents) >= 1
        # The first subcircuit intent should be a compressor VCA
        vca_intent = result.intent.subcircuit_intents[0]
        assert "compressor" in vca_intent.function or "vca" in vca_intent.function

    def test_buffer_amplifier_intent(self):
        """NE5532 + feedback network classified as buffer/amplifier intent."""
        topology = _make_buffer_topology()
        subcircuits = [BUFFER_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "NE5532"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert result.intent.overall_type in ("buffer", "amplifier")
        assert result.intent.confidence >= 0.5
        assert len(result.intent.subcircuit_intents) >= 1

    def test_switch_bypass_intent(self):
        """CD4066 + control nets classified as switch/bypass intent."""
        topology = _make_switch_topology()
        subcircuits = [SWITCH_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "CD4066"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert result.intent.overall_type == "switch"
        assert result.intent.confidence >= 0.7
        assert len(result.intent.subcircuit_intents) >= 1

    def test_oscillator_intent(self):
        """CD4060 + RC timing classified as oscillator intent."""
        topology = _make_oscillator_topology()
        subcircuits = [OSCILLATOR_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "CD4060"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert result.intent.overall_type == "oscillator"
        assert result.intent.confidence >= 0.7
        assert len(result.intent.subcircuit_intents) >= 1

    def test_envelope_generator_intent(self):
        """LM358 + integrator classified as envelope_generator intent."""
        topology = _make_envelope_topology()
        subcircuits = [ENVELOPE_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "LM358"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert result.intent.overall_type in ("envelope", "amplifier")
        assert result.intent.confidence >= 0.5

    def test_unknown_component_low_confidence(self):
        """Unknown component patterns produce low confidence."""
        topology = CircuitTopology(
            nodes=(_make_node("U99", "MYSTERY_CHIP"),),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={"component_count": 1, "net_count": 0, "signal_path_count": 0,
                   "feedback_count": 0, "net_stats": {}},
        )
        subcircuits = [_make_subcircuit(
            function="unknown",
            components=("U99",),
            confidence=0.3,
        )]
        subcircuits[0].features["lib_id"] = "MYSTERY_CHIP"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert result.intent.confidence < 0.5

    def test_empty_topology_returns_unknown(self):
        """Empty topology returns unknown intent."""
        topology = _make_empty_topology()
        inferrer = IntentInferrer()
        result = inferrer.infer(topology, [])

        assert result.intent.overall_type == "unknown"
        assert result.intent.confidence < 0.3
        assert len(result.intent.subcircuit_intents) == 0

    def test_custom_rules_prepend(self):
        """Custom rules are checked before default rules."""
        custom_matcher = (
            lambda subcircuit, topology: True,
            "custom_type",
            "custom_function",
            (DesignGoal.CONTROL,),
            0.99,
        )
        inferrer = IntentInferrer(custom_rules=[custom_matcher])

        topology = _make_compressor_topology()
        subcircuits = [COMPRESSOR_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "THAT4301"

        result = inferrer.infer(topology, subcircuits)
        assert result.intent.overall_type == "custom_type"
        assert result.intent.confidence == 0.99


# ===========================================================================
# TestSignalFlowGeneration
# ===========================================================================


class TestSignalFlowGeneration:
    """Signal flow description tests."""

    def test_compressor_signal_flow(self):
        """Compressor produces human-readable signal flow with arrow notation."""
        topology = _make_compressor_topology()
        subcircuits = [COMPRESSOR_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "THAT4301"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        flow = result.intent.signal_flow_description
        assert len(flow) > 0
        assert "->" in flow
        # Should mention VCA or compressor somewhere
        flow_lower = flow.lower()
        assert "vca" in flow_lower or "compressor" in flow_lower

    def test_multi_stage_signal_flow(self):
        """Multi-stage circuit produces ordered signal flow."""
        topology = _make_compressor_topology()
        switch_sc = _make_subcircuit(
            function="switch",
            components=("U21",),
            input_nets=("AUDIO_IN",),
            output_nets=("SWITCH_OUT",),
            control_nets=("CTRL",),
            confidence=0.85,
        )
        switch_sc.features["lib_id"] = "CD4066"
        vca_sc = _make_subcircuit(
            function="vca",
            components=("U22",),
            input_nets=("SWITCH_OUT",),
            output_nets=("VCA_OUT",),
            control_nets=("SIDECHAIN",),
            confidence=0.9,
        )
        vca_sc.features["lib_id"] = "THAT4301"
        buffer_sc = _make_subcircuit(
            function="buffer",
            components=("U24",),
            input_nets=("VCA_OUT",),
            output_nets=("AUDIO_OUT",),
            control_nets=(),
            confidence=0.92,
        )
        buffer_sc.features["lib_id"] = "NE5532"

        subcircuits = [switch_sc, vca_sc, buffer_sc]

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        flow = result.intent.signal_flow_description
        assert "->" in flow
        # Should have multiple stages separated by arrows
        stages = [s.strip() for s in flow.split("->")]
        assert len(stages) >= 2

    def test_empty_subcircuits_no_signal_flow(self):
        """No subcircuits produce empty signal flow."""
        topology = _make_empty_topology()
        inferrer = IntentInferrer()
        result = inferrer.infer(topology, [])

        assert result.intent.signal_flow_description == ""


# ===========================================================================
# TestInferenceResult
# ===========================================================================


class TestInferenceResult:
    """Tests for InferenceResult dataclass."""

    def test_result_has_metadata(self):
        """InferenceResult includes rule_matched and inference_time_ms."""
        topology = _make_compressor_topology()
        subcircuits = [COMPRESSOR_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "THAT4301"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        assert isinstance(result, InferenceResult)
        assert isinstance(result.intent, DesignIntent)
        assert isinstance(result.rule_matched, str)
        assert len(result.rule_matched) > 0
        assert isinstance(result.inference_time_ms, float)
        assert result.inference_time_ms >= 0

    def test_result_is_immutable(self):
        """InferenceResult is frozen (immutable)."""
        topology = _make_compressor_topology()
        subcircuits = [COMPRESSOR_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "THAT4301"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        import dataclasses
        assert dataclasses.is_dataclass(result)
        # Frozen dataclass should raise on attribute assignment
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.rule_matched = "modified"


# ===========================================================================
# TestEdgeCases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests for intent inference."""

    def test_no_subcircuits_with_nodes(self):
        """Topology with nodes but no subcircuits returns unknown."""
        topology = CircuitTopology(
            nodes=(_make_node("R1", "Device:R", "resistor"),),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={"component_count": 1, "net_count": 0, "signal_path_count": 0,
                   "feedback_count": 0, "net_stats": {}},
        )
        inferrer = IntentInferrer()
        result = inferrer.infer(topology, [])

        assert result.intent.overall_type == "unknown"

    def test_deterministic_results(self):
        """Same input produces same output every time."""
        topology = _make_compressor_topology()
        subcircuits = [COMPRESSOR_SUBCIRCUIT]
        subcircuits[0].features["lib_id"] = "THAT4301"

        inferrer = IntentInferrer()
        result1 = inferrer.infer(topology, subcircuits)
        result2 = inferrer.infer(topology, subcircuits)

        assert result1.intent.overall_type == result2.intent.overall_type
        assert result1.intent.confidence == result2.intent.confidence
        assert result1.intent.signal_flow_description == result2.intent.signal_flow_description

    def test_subcircuit_with_no_ic_lib_id(self):
        """Subcircuit with no lib_id in features uses fallback matching."""
        topology = CircuitTopology(
            nodes=(_make_node("U1", "UNKNOWN_IC"),),
            edges=(),
            input_nets=(),
            output_nets=(),
            power_nets=(),
            signal_paths=(),
            stats={"component_count": 1, "net_count": 0, "signal_path_count": 0,
                   "feedback_count": 0, "net_stats": {}},
        )
        subcircuits = [_make_subcircuit(
            function="unknown",
            components=("U1",),
            confidence=0.2,
        )]
        subcircuits[0].features["lib_id"] = "UNKNOWN_IC"

        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)

        # Should not crash, should return some result
        assert isinstance(result.intent, DesignIntent)
