"""Template data for Circuit QA pair generation.

Contains question templates, answer templates, root cause mappings,
component role mappings, and difficulty rules used by qa_generator.py.
Extracted to keep qa_generator.py under the 800-line limit.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Question templates per QA type
# ---------------------------------------------------------------------------

QUESTION_TEMPLATES: dict[str, list[str]] = {
    "violation_diagnosis": [
        "Why does this schematic have a {violation_type} violation at ({x}, {y})?",
        "What is the root cause of the {violation_type} error reported by ERC?",
        "Explain the {violation_type} violation in this {severity} ERC report.",
        "How should the {violation_type} at position ({x}, {y}) be resolved?",
        "What design issue causes the {violation_type} in this circuit?",
    ],
    "signal_flow": [
        "What is the signal path from {input_net} to {output_net}?",
        "Trace the signal flow through the {subcircuit_name} subcircuit.",
        "How does the signal propagate from {input_net} through the {subcircuit_name}?",
        "Describe the signal path in the {subcircuit_name} from input to output.",
        "What components does the signal pass through from {input_net} to {output_net}?",
    ],
    "component_function": [
        "What is the purpose of {ref} ({value}) in this {circuit_type}?",
        "Explain the role of {ref} in the {circuit_type} circuit.",
        "What function does {ref} ({value}) serve in this design?",
        "How does {ref} contribute to the {circuit_type} operation?",
        "Describe the function of {ref} in the signal path of the {circuit_type}.",
    ],
    "net_purpose": [
        "What is the purpose of the {net_name} net?",
        "Explain the function of the {net_name} net in this circuit.",
        "What role does the {net_name} net play in the {subcircuit}?",
        "Describe the connectivity of the {net_name} net.",
        "What signals or power does the {net_name} net carry?",
    ],
    "design_review": [
        "What improvements could be made to the {subcircuit}?",
        "Suggest enhancements for the {subcircuit} in this design.",
        "What design changes would improve the {subcircuit}?",
        "Review the {subcircuit} and suggest optimizations.",
        "What limitations exist in the {subcircuit} and how could they be addressed?",
    ],
    "value_calculation": [
        "What value should {ref} be for {spec} with {constraint}?",
        "Calculate the required value of {ref} to achieve {spec}.",
        "Given {constraint}, what should {ref} be for {spec}?",
        "Determine the appropriate value for {ref} in this circuit.",
        "What component value is needed for {ref} to satisfy {spec}?",
    ],
}

# ---------------------------------------------------------------------------
# Answer templates per QA type
# ---------------------------------------------------------------------------

ANSWER_TEMPLATES: dict[str, list[str]] = {
    "violation_diagnosis": [
        "The {violation_type} is caused by {root_cause}. The component at ({x}, {y}) "
        "has an issue where {explanation}. This is {category} because {reason}. "
        "To fix this, {fix_suggestion}.",

        "This {violation_type} violation occurs because {root_cause}. "
        "The {severity}-level issue is at position ({x}, {y}) where {explanation}. "
        "This violation {category} because {reason}. "
        "The recommended fix is to {fix_suggestion}.",
    ],
    "signal_flow": [
        "The path: {input_net} -> {path_components} -> {output_net}. "
        "{first_component} {first_function}, then {second_component} {second_function}. "
        "The overall signal flow through the {subcircuit_name} is {flow_description}.",

        "Signal flow in the {subcircuit_name}: {input_net} -> {path_components} -> {output_net}. "
        "Starting from {input_net}, the signal passes through {first_component} which {first_function}. "
        "Then {second_component} {second_function} before reaching {output_net}. "
        "This path implements {flow_description}.",
    ],
    "component_function": [
        "{ref} is a {role} that {function}. It connects {net_a} to {net_b}, "
        "serving to {purpose}. In the {circuit_type} circuit, this component "
        "is essential for {essential_function}.",

        "The component {ref} ({value}) serves as a {role} in the {circuit_type}. "
        "Its primary function is to {function}, connecting {net_a} and {net_b}. "
        "This {purpose}, which is critical for proper circuit operation.",
    ],
    "net_purpose": [
        "{net_name} is {function} connecting {pin_list}. It serves to {purpose} "
        "in the {subcircuit}. This net is important because it {importance}.",

        "The {net_name} net {function}. It connects the following pins: {pin_list}. "
        "In the {subcircuit}, this net {purpose}. "
        "Without this net, the circuit would {consequence}.",
    ],
    "design_review": [
        "The {subcircuit} could benefit from: 1) {imp1}, 2) {imp2}. "
        "Currently {state}, which {limitation}. "
        "Implementing these changes would {benefit}.",

        "Improvements for the {subcircuit}: First, {imp1} -- this addresses the current "
        "{state} limitation. Second, {imp2} would resolve the issue where {limitation}. "
        "These modifications would {benefit}.",
    ],
    "value_calculation": [
        "{ref} = {formula} = {result}. Given {values}, {explanation}. "
        "This ensures the circuit meets the {spec} requirement.",

        "For {spec}: {ref} = {formula} = {result}. "
        "With {values}, the calculation shows {explanation}. "
        "The standard E-series value closest to {result} should be selected.",
    ],
}

# ---------------------------------------------------------------------------
# Root cause mappings for violation_diagnosis
# ---------------------------------------------------------------------------

VIOLATION_ROOT_CAUSES: dict[str, dict[str, str]] = {
    "power_pin_not_driven": {
        "root_cause": "a power input pin has no driving source connected",
        "category": "a power integrity issue",
        "reason": "the power symbol or voltage source is missing or disconnected from the net",
        "fix_suggestion": "connect a power symbol or voltage source to drive the power pin",
    },
    "multiple_net_names": {
        "root_cause": "two or more net labels are placed at the same electrical point",
        "category": "a net naming conflict",
        "reason": "different labels on connected wires create ambiguous net identities",
        "fix_suggestion": "resolve the conflict by removing duplicate labels or ensuring consistent naming",
    },
    "pin_not_connected": {
        "root_cause": "a component pin is left floating without any connection",
        "category": "a connectivity issue",
        "reason": "unconnected pins can cause unpredictable behavior and noise coupling",
        "fix_suggestion": "connect the pin to its intended net or add a no-connect marker if intentionally unused",
    },
    "erc_error": {
        "root_cause": "a general ERC configuration or parsing error occurred",
        "category": "a configuration issue",
        "reason": "the ERC rules may be improperly configured or the schematic has an invalid element",
        "fix_suggestion": "review the ERC configuration and check for invalid schematic elements",
    },
}

DEFAULT_ROOT_CAUSE: dict[str, str] = {
    "root_cause": "an unspecified design issue",
    "category": "a design issue",
    "reason": "the violation indicates a potential problem in the circuit design",
    "fix_suggestion": "review the schematic for the reported issue and apply the appropriate fix",
}

# ---------------------------------------------------------------------------
# Component role mappings for component_function
# ---------------------------------------------------------------------------

COMPONENT_ROLES: dict[str, str] = {
    "Device:R": "resistor",
    "Device:C": "capacitor",
    "Device:L": "inductor",
    "THAT4301": "VCA (voltage-controlled amplifier)",
    "Amplifier_Operational:NE5532": "operational amplifier",
    "Amplifier_Operational:LM358": "operational amplifier",
    "Amplifier_Operational:TL072": "operational amplifier",
    "CD4066BE": "analog switch",
    "RP2040": "microcontroller",
}

# ---------------------------------------------------------------------------
# Difficulty assignment helpers
# ---------------------------------------------------------------------------

DIFFICULTY_RULES: dict[str, dict[str, str]] = {
    "violation_diagnosis": {"easy": "simple pin connection", "medium": "power integrity", "hard": "multi-pin bus"},
    "signal_flow": {"easy": "2-3 component path", "medium": "4-6 component path", "hard": "feedback loop path"},
    "component_function": {"easy": "passive component", "medium": "IC with clear role", "hard": "multi-function IC"},
    "net_purpose": {"easy": "power/ground net", "medium": "signal net", "hard": "feedback/control net"},
    "design_review": {"easy": "single improvement", "medium": "multi-point review", "hard": "architectural change"},
    "value_calculation": {"easy": "Ohm's law", "medium": "RC time constant", "hard": "multi-variable derivation"},
}
