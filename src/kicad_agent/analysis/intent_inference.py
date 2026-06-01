"""Rule-based design intent inference engine.

Combines topology analysis, component recognition, and signal
flow tracing to infer what a designer intended to build.

No LLM calls -- all inference is deterministic and template-based.

DOMAIN-03: Intent inference for design intelligence.

Usage:
    from kicad_agent.analysis.intent_inference import IntentInferrer

    inferrer = IntentInferrer()
    result = inferrer.infer(topology, subcircuits)
    print(result.intent.overall_type)  # "compressor"
    print(result.intent.signal_flow_description)  # "Audio input -> ..."
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from kicad_agent.analysis.intent_schemas import (
    DesignGoal,
    DesignIntent,
    SubcircuitIntent,
)
from kicad_agent.analysis.subcircuit_detector import Subcircuit
from kicad_agent.analysis.topology_graph import CircuitTopology

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InferenceResult:
    """Immutable result from intent inference."""

    intent: DesignIntent
    rule_matched: str  # Which rule produced the primary classification
    inference_time_ms: float


# ---------------------------------------------------------------------------
# Rule type and match helpers
# ---------------------------------------------------------------------------

# Each rule: (match_fn, overall_type, function_name, design_goals, confidence)
_IntentRule = tuple[
    Callable[[Subcircuit, CircuitTopology], bool],
    str,        # overall_type
    str,        # function_name
    tuple[DesignGoal, ...],
    float,      # confidence
]


def _find_component(
    topology: CircuitTopology,
    ref: str,
    ref_index: dict[str, "TopologyNode"] | None = None,
):
    """Find a TopologyNode by ref, return None if not found."""
    if ref_index is not None:
        return ref_index.get(ref)
    for node in topology.nodes:
        if node.ref == ref:
            return node
    return None


def _has_ic(lib_id_substring: str) -> Callable[[Subcircuit, CircuitTopology], bool]:
    """Match if any component lib_id contains the substring."""

    def matcher(subcircuit: Subcircuit, topology: CircuitTopology, _ref_index: dict | None = None) -> bool:
        # Check features["lib_id"] first (faster)
        lib_id = subcircuit.features.get("lib_id", "")
        if lib_id_substring.upper() in lib_id.upper():
            return True
        # Fallback: check topology nodes
        for ref in subcircuit.components:
            node = _find_component(topology, ref, ref_index=_ref_index)
            if node and lib_id_substring.upper() in node.lib_id.upper():
                return True
        # Also check center_component
        node = _find_component(topology, subcircuit.center_component, ref_index=_ref_index)
        if node and lib_id_substring.upper() in node.lib_id.upper():
            return True
        return False

    return matcher


def _has_ic_with_net(
    lib_id_substring: str,
    net_substring: str,
) -> Callable[[Subcircuit, CircuitTopology], bool]:
    """Match if IC present AND any net in the subcircuit contains the substring."""

    def matcher(subcircuit: Subcircuit, topology: CircuitTopology, _ref_index: dict | None = None) -> bool:
        # Check if IC is present
        has_ic = False
        lib_id = subcircuit.features.get("lib_id", "")
        if lib_id_substring.upper() in lib_id.upper():
            has_ic = True
        if not has_ic:
            for ref in subcircuit.components:
                node = _find_component(topology, ref, ref_index=_ref_index)
                if node and lib_id_substring.upper() in node.lib_id.upper():
                    has_ic = True
                    break
        if not has_ic:
            node = _find_component(topology, subcircuit.center_component, ref_index=_ref_index)
            if node and lib_id_substring.upper() in node.lib_id.upper():
                has_ic = True

        if not has_ic:
            return False

        # Check nets for substring
        all_nets = set(subcircuit.nets)
        return any(net_substring.upper() in n.upper() for n in all_nets)

    return matcher


# ---------------------------------------------------------------------------
# Default intent rules (ordered, first match wins at subcircuit level)
# ---------------------------------------------------------------------------

_DEFAULT_INTENT_RULES: list[_IntentRule] = [
    # THAT4301 + sidechain -> compressor VCA
    (_has_ic("THAT4301"), "compressor", "compressor_vca",
     (DesignGoal.AUDIO_PROCESSING,), 0.92),
    (_has_ic_with_net("NE5532", "FEEDBACK"), "amplifier", "feedback_amplifier",
     (DesignGoal.AUDIO_PROCESSING,), 0.88),
    (_has_ic("NE5532"), "buffer", "unity_gain_buffer",
     (DesignGoal.AUDIO_PROCESSING,), 0.80),
    (_has_ic_with_net("CD4066", "CTRL"), "switch", "analog_switch",
     (DesignGoal.ROUTING,), 0.90),
    (_has_ic("CD4066"), "switch", "bypass_switch",
     (DesignGoal.ROUTING,), 0.82),
    (_has_ic_with_net("CD4060", "CLOCK"), "oscillator", "clock_generator",
     (DesignGoal.GENERATION,), 0.88),
    (_has_ic("CD4060"), "oscillator", "lfo_oscillator",
     (DesignGoal.GENERATION,), 0.80),
    (_has_ic_with_net("LM358", "INTEGRAT"), "envelope", "envelope_generator",
     (DesignGoal.GENERATION,), 0.78),
    (_has_ic("LM358"), "amplifier", "dual_opamp",
     (DesignGoal.AUDIO_PROCESSING,), 0.65),
    (_has_ic("TL072"), "amplifier", "jfet_opamp",
     (DesignGoal.AUDIO_PROCESSING,), 0.70),
    (_has_ic("RP2040"), "controller", "mcu_controller",
     (DesignGoal.CONTROL,), 0.95),
    (_has_ic("PT2399"), "delay", "digital_delay",
     (DesignGoal.AUDIO_PROCESSING,), 0.92),
    (_has_ic("LM7812"), "regulator", "voltage_regulator",
     (DesignGoal.POWER_SUPPLY,), 0.95),
    (_has_ic("LM7912"), "regulator", "negative_regulator",
     (DesignGoal.POWER_SUPPLY,), 0.95),
    (_has_ic("THAT2181"), "compressor", "vca_only",
     (DesignGoal.AUDIO_PROCESSING,), 0.85),
]


# ---------------------------------------------------------------------------
# Signal flow templates
# ---------------------------------------------------------------------------

_SIGNAL_FLOW_TEMPLATES: dict[str, str] = {
    "compressor_vca": "VCA",
    "feedback_amplifier": "amplifier",
    "unity_gain_buffer": "buffer",
    "analog_switch": "switch",
    "bypass_switch": "bypass",
    "clock_generator": "clock",
    "lfo_oscillator": "LFO",
    "envelope_generator": "envelope",
    "voltage_regulator": "regulator",
    "negative_regulator": "regulator",
    "digital_delay": "delay",
    "mcu_controller": "MCU",
    "dual_opamp": "op-amp",
    "jfet_opamp": "op-amp",
    "vca_only": "VCA",
}


# ---------------------------------------------------------------------------
# Overall type inference rules
# ---------------------------------------------------------------------------

def _infer_overall_type(intents: list[SubcircuitIntent]) -> str:
    """Determine overall circuit type from subcircuit composition.

    Rules:
    - vca + sidechain/control -> "compressor"
    - filter_stages -> "filter"
    - oscillator + lfo -> "synthesizer"
    - mixer stages only -> "mixer"
    - buffer + protection -> "input_stage"
    - power regulation -> "power_supply"
    - dominant subcircuit type -> that type
    """
    if not intents:
        return "unknown"

    functions = [i.function.lower() for i in intents]

    # Composite patterns
    has_vca = any("vca" in f or "compressor" in f for f in functions)
    has_control = any(
        "control" in f or "envelope" in f or "lfo" in f
        for f in functions
    )
    has_switch = any("switch" in f or "bypass" in f for f in functions)
    has_buffer = any("buffer" in f or "amplifier" in f or "op-amp" in f for f in functions)
    has_oscillator = any("oscillator" in f or "clock" in f or "lfo" in f for f in functions)
    has_regulator = any("regulator" in f for f in functions)

    if has_vca:
        return "compressor"
    if has_regulator and not has_vca and not has_oscillator:
        return "power_supply"
    if has_oscillator:
        return "oscillator"
    if has_switch:
        return "switch"
    if has_buffer:
        return "amplifier"

    # Fallback: use the function of the first (highest confidence) intent
    primary = intents[0].function
    # Map common function names to overall types
    type_map = {
        "compressor_vca": "compressor",
        "vca_only": "compressor",
        "feedback_amplifier": "amplifier",
        "unity_gain_buffer": "buffer",
        "analog_switch": "switch",
        "bypass_switch": "switch",
        "clock_generator": "oscillator",
        "lfo_oscillator": "oscillator",
        "envelope_generator": "envelope",
        "voltage_regulator": "power_supply",
        "negative_regulator": "power_supply",
        "digital_delay": "delay",
        "mcu_controller": "controller",
        "dual_opamp": "amplifier",
        "jfet_opamp": "amplifier",
    }
    return type_map.get(primary, primary)


# ---------------------------------------------------------------------------
# IntentInferrer
# ---------------------------------------------------------------------------


class IntentInferrer:
    """Rule-based design intent inference engine.

    Combines topology analysis, component recognition, and signal
    flow tracing to infer what a designer intended to build.

    No LLM calls -- all inference is deterministic and template-based.

    Usage:
        inferrer = IntentInferrer()
        result = inferrer.infer(topology, subcircuits)
        print(result.intent.overall_type)  # "compressor"
        print(result.intent.signal_flow_description)  # "Audio input -> ..."
    """

    def __init__(self, custom_rules: list[_IntentRule] | None = None):
        """Initialize with optional custom rules prepended before defaults.

        Args:
            custom_rules: Additional rules to check before default rules.
        """
        self._rules = (custom_rules or []) + _DEFAULT_INTENT_RULES

    def infer(
        self,
        topology: CircuitTopology,
        subcircuits: list[Subcircuit],
    ) -> InferenceResult:
        """Infer design intent from circuit topology.

        Algorithm:
        1. For each subcircuit, match against intent rules
        2. Build SubcircuitIntent for each matched subcircuit
        3. Determine overall_type from the dominant subcircuit
        4. Generate signal flow description from subcircuit ordering
        5. Collect design goals from all matched rules
        6. Compute overall confidence as weighted average

        Args:
            topology: CircuitTopology with components, nets, subcircuits.
            subcircuits: List of Subcircuit instances from SubcircuitDetector.

        Returns:
            InferenceResult with DesignIntent and metadata.
        """
        start = time.perf_counter()

        if not subcircuits:
            elapsed = (time.perf_counter() - start) * 1000
            return InferenceResult(
                intent=DesignIntent(
                    overall_type="unknown",
                    subcircuit_intents=(),
                    signal_flow_description="",
                    design_goals=(DesignGoal.UNKNOWN,),
                    confidence=0.1,
                    schematic_path="",
                ),
                rule_matched="no_subcircuits",
                inference_time_ms=elapsed,
            )

        # 1. Match each subcircuit against intent rules
        ref_index: dict[str, TopologyNode] = {n.ref: n for n in topology.nodes}
        intents: list[SubcircuitIntent] = []
        primary_rule = "no_rule_matched"
        primary_overall_type: str | None = None
        matched_goals: list[DesignGoal] = []

        for subcircuit in subcircuits:
            match_result = self._match_subcircuit(subcircuit, topology, ref_index)
            if match_result is not None:
                matched_intent, rule_overall_type, rule_goals = match_result
                intents.append(matched_intent)
                if primary_rule == "no_rule_matched":
                    primary_rule = matched_intent.function
                    primary_overall_type = rule_overall_type
                for g in rule_goals:
                    if g not in matched_goals:
                        matched_goals.append(g)

        if not intents:
            # No rules matched -- create generic intents from subcircuits
            for subcircuit in subcircuits:
                intents.append(SubcircuitIntent(
                    function=subcircuit.subcircuit_type.value.lower(),
                    component_refs=subcircuit.components,
                    input_nets=(),
                    output_nets=(),
                    control_nets=(),
                    design_choices=(),
                    confidence=subcircuit.confidence * 0.5,
                ))

        # 2. Determine overall type
        # Use the primary rule's overall_type if available; otherwise derive
        if primary_overall_type is not None:
            overall_type = primary_overall_type
        else:
            overall_type = _infer_overall_type(intents)

        # 3. Build signal flow
        signal_flow = self._build_signal_flow(intents)

        # 4. Collect design goals (deduplicated from matched rules)
        all_goals: list[DesignGoal] = matched_goals if matched_goals else [DesignGoal.UNKNOWN]

        # 5. Compute overall confidence (quadratic weighted mean -- squares
        #    confidence values so higher-confidence subcircuits dominate)
        if intents:
            total_weight = sum(i.confidence for i in intents)
            if total_weight > 0:
                overall_confidence = sum(i.confidence ** 2 for i in intents) / total_weight
            else:
                overall_confidence = 0.1
        else:
            overall_confidence = 0.1

        # Clamp to [0.0, 1.0]
        overall_confidence = max(0.0, min(1.0, overall_confidence))

        elapsed = (time.perf_counter() - start) * 1000

        intent = DesignIntent(
            overall_type=overall_type,
            subcircuit_intents=tuple(intents),
            signal_flow_description=signal_flow,
            design_goals=tuple(all_goals),
            confidence=overall_confidence,
        )

        return InferenceResult(
            intent=intent,
            rule_matched=primary_rule,
            inference_time_ms=elapsed,
        )

    def _match_subcircuit(
        self,
        subcircuit: Subcircuit,
        topology: CircuitTopology,
        ref_index: dict[str, TopologyNode] | None = None,
    ) -> tuple[SubcircuitIntent, str, tuple[DesignGoal, ...]] | None:
        """Match a single subcircuit against intent rules.

        Returns tuple of (SubcircuitIntent, overall_type, design_goals) for
        the first matching rule, or None.
        """
        for match_fn, overall_type, function_name, design_goals, confidence in self._rules:
            try:
                matched = match_fn(subcircuit, topology, ref_index)
            except TypeError:
                matched = match_fn(subcircuit, topology)
            if matched:
                # Extract design choices from subcircuit features
                choices = self._extract_design_choices(subcircuit, function_name)

                intent = SubcircuitIntent(
                    function=function_name,
                    component_refs=subcircuit.components,
                    input_nets=tuple(
                        n for n in subcircuit.nets
                        if any(
                            inp in n.upper()
                            for inp in ("IN", "INPUT", "AUDIO_IN", "SIG_IN")
                        )
                    ),
                    output_nets=tuple(
                        n for n in subcircuit.nets
                        if any(
                            out in n.upper()
                            for out in ("OUT", "OUTPUT", "AUDIO_OUT", "EQ_OUT")
                        )
                    ),
                    control_nets=tuple(
                        n for n in subcircuit.nets
                        if any(
                            ctrl in n.upper()
                            for ctrl in (
                                "CTRL", "CONTROL", "SIDECHAIN", "CV",
                                "BYPASS", "FREQ", "ATTACK", "DECAY",
                                "SUSTAIN", "RELEASE",
                            )
                        )
                    ),
                    design_choices=choices,
                    confidence=confidence,
                )
                return (intent, overall_type, design_goals)
        return None

    def _extract_design_choices(
        self,
        subcircuit: Subcircuit,
        function_name: str,
    ) -> tuple[str, ...]:
        """Extract notable design choices from subcircuit features."""
        choices: list[str] = []
        features = subcircuit.features

        if features.get("has_sidechain"):
            choices.append("sidechain_control")
        if features.get("has_feedback_loop"):
            choices.append("feedback_network")
        if features.get("has_crystal"):
            choices.append("crystal_oscillator")
        if features.get("resistor_count", 0) >= 4 and features.get("capacitor_count", 0) >= 3:
            choices.append("extensive_filtering")

        return tuple(choices)

    def _build_signal_flow(self, intents: list[SubcircuitIntent]) -> str:
        """Generate human-readable signal flow description.

        Orders subcircuits by connectivity: input subcircuits first,
        then intermediate processing, then output subcircuits.
        Uses net names to determine ordering.

        Template: "{input_desc} -> {stage1} -> {stage2} -> {output_desc}"
        """
        if not intents:
            return ""

        # Classify each intent into a stage category
        input_stages: list[str] = []
        processing_stages: list[str] = []
        output_stages: list[str] = []
        control_stages: list[str] = []

        for intent in intents:
            label = _SIGNAL_FLOW_TEMPLATES.get(intent.function, intent.function)

            # Add component refs for context (max 2 refs to keep readable)
            refs_str = ""
            if intent.component_refs:
                refs = intent.component_refs[:2]
                refs_str = f" ({', '.join(refs)})"

            stage_text = f"{label}{refs_str}"

            fn = intent.function.lower()

            if "regulator" in fn or "power" in fn:
                control_stages.append(stage_text)
            elif any(k in fn for k in ("buffer", "amplifier", "op-amp")):
                # Net connectivity ordering: output stage only if no downstream
                # subcircuit consumes its output nets (handles multi-buffer)
                is_last_stage = False
                if intent.output_nets:
                    out_set = set(intent.output_nets)
                    is_last_stage = not any(
                        out_set & set(oi.input_nets)
                        for oi in intents if oi is not intent
                    )
                if is_last_stage and not output_stages:
                    output_stages.append(stage_text)
                else:
                    processing_stages.append(stage_text)
            elif any(k in fn for k in ("vca", "compressor", "filter", "delay")):
                processing_stages.append(stage_text)
            elif any(k in fn for k in ("switch", "bypass")):
                if not processing_stages:
                    input_stages.append(stage_text)
                else:
                    processing_stages.insert(0, stage_text)
            elif any(k in fn for k in ("oscillator", "clock", "lfo", "envelope")):
                control_stages.append(stage_text)
            else:
                processing_stages.append(stage_text)

        # Build ordered flow
        all_stages = input_stages + processing_stages + output_stages

        if not all_stages:
            return ""

        # Add input/output context if there are nets to suggest signal chain
        has_input = any(intent.input_nets for intent in intents)
        has_output = any(intent.output_nets for intent in intents)

        if has_input and all_stages:
            all_stages.insert(0, "Input")
        if has_output and all_stages:
            all_stages.append("Output")

        return " -> ".join(all_stages)
