"""Template-based question generation for PCB MMLU benchmark.

Generates multi-choice questions across 8 categories using deterministic
templates filled with schematic context data. No LLM needed for generation.

Categories:
    component_identification - Identify component types from reference designators
    topology_recognition - Recognize circuit functions from IC + passive context
    signal_flow - Determine signal path direction and type
    power_design - Identify power rail purpose and design patterns
    pin_function - Classify pin roles (input, output, power, control)
    net_purpose - Determine net function from connected components
    design_rules - Assess whether design rules are satisfied or violated
    troubleshooting - Diagnose issues from ERC violations

Usage:
    from kicad_agent.benchmarks.question_generator import generate_questions

    questions = generate_questions("topology_recognition", context_dict)
"""

from __future__ import annotations

import random
from typing import Any

from kicad_agent.benchmarks.schemas import BenchmarkQuestion

# Global ID counter for sequential question IDs.
_id_counter: int = 0

# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

_CATEGORY_TEMPLATES: dict[str, list[str]] = {
    "component_identification": [
        "What type of electronic component is {ref} ({lib_id})?",
        "In the schematic, {ref} has the library identifier {lib_id}. What component family does it belong to?",
        "Identify the component type for {ref} which uses {lib_id}.",
    ],
    "topology_recognition": [
        "What type of circuit is formed by {components}?",
        "Which circuit function does {ic_ref} ({ic_type}) serve in this design?",
        "Given {ic_ref} surrounded by {passive_count} passives, what is the subcircuit function?",
    ],
    "signal_flow": [
        "In the subcircuit containing {components}, what is the primary signal flow direction?",
        "How does the signal propagate through the {function} subcircuit with {component_count} components?",
        "What is the signal path through {components} in this {function} circuit?",
    ],
    "power_design": [
        "What role do the capacitors near {ic_ref} ({ic_type}) serve in this {function} circuit?",
        "In the {function} subcircuit, what is the primary power design consideration for {ic_ref}?",
        "How is power delivered to {ic_ref} in the {function} subcircuit?",
    ],
    "pin_function": [
        "What is the function of the pins on {ic_ref} ({ic_type}) in the {function} subcircuit?",
        "In the {function} circuit, which pins of {ic_ref} are used for signal input?",
        "Classify the primary pin functions on {ic_ref} ({ic_type}) in this design.",
    ],
    "net_purpose": [
        "What is the purpose of the net connecting {components} in this {function} subcircuit?",
        "The net between {ref_a} and {ref_b} in the {function} circuit serves what function?",
        "In the {function} subcircuit, what type of net connects {components}?",
    ],
    "design_rules": [
        "Does the {function} subcircuit with {component_count} components satisfy typical decoupling capacitor rules for {ic_ref}?",
        "For the {function} circuit containing {ic_ref}, is the power pin bypassing design rule satisfied?",
        "Does the {function} subcircuit follow best practices for {ic_type}-based designs?",
    ],
    "troubleshooting": [
        "ERC reports '{violation_type}'. What is the most likely root cause in this circuit?",
        "The schematic shows '{violation_description}'. How should this be resolved?",
        "An ERC error of type '{violation_type}' was detected. What design issue does this indicate?",
    ],
}

# ---------------------------------------------------------------------------
# Distractor pools -- plausible wrong answers per category and correct answer
# ---------------------------------------------------------------------------

_DISTRACTOR_POOLS: dict[str, dict[str, list[str]]] = {
    "component_identification": {
        "resistor": ["Capacitor", "Inductor", "Diode", "Transistor"],
        "capacitor": ["Resistor", "Inductor", "Diode", "Transistor"],
        "inductor": ["Resistor", "Capacitor", "Diode", "Transistor"],
        "opamp": ["Comparator", "ADC", "DAC", "Voltage regulator"],
        "switch": ["Multiplexer", "Demultiplexer", "Encoder", "Decoder"],
        "vca": ["Operational amplifier", "Comparator", "Voltage regulator", "ADC"],
        "mcu": ["FPGA", "CPLD", "DSP", "ASIC"],
        "transistor": ["Resistor", "Diode", "Capacitor", "Inductor"],
        "diode": ["Resistor", "Capacitor", "Inductor", "Transistor"],
        "voltage_regulator": ["Op-amp", "Comparator", "ADC", "DAC"],
    },
    "topology_recognition": {
        "amplifier": ["Filter", "Oscillator", "Compressor", "Mixer", "Power supply"],
        "filter": ["Amplifier", "Oscillator", "Compressor", "Mixer", "Power supply"],
        "compressor_vca": ["Amplifier", "Filter", "Oscillator", "Mixer", "Power supply"],
        "oscillator": ["Amplifier", "Filter", "Compressor", "Mixer", "Power supply"],
        "power_supply": ["Amplifier", "Filter", "Oscillator", "Compressor", "Mixer"],
        "mixer": ["Amplifier", "Filter", "Oscillator", "Compressor", "Power supply"],
        "bypass_switch": ["Amplifier", "Filter", "Oscillator", "Compressor", "Mixer"],
        "output_buffer": ["Oscillator", "Filter", "Compressor", "Mixer", "Power supply"],
        "envelope_generator": ["Amplifier", "Filter", "Oscillator", "Mixer", "Power supply"],
        "preamp": ["Oscillator", "Filter", "Compressor", "Mixer", "Power supply"],
        "delay": ["Amplifier", "Filter", "Oscillator", "Compressor", "Power supply"],
    },
    "signal_flow": {
        "input_to_output": ["Output to input", "Feedback loop", "Bypass path", "Bidirectional"],
        "series": ["Parallel", "Feedback", "Bypass", "Open-loop"],
        "feedback": ["Feedforward", "Open-loop", "Bypass", "Series"],
        "bidirectional": ["Unidirectional input", "Unidirectional output", "Feedback only", "Isolated"],
    },
    "power_design": {
        "decoupling": ["Bulk filtering", "Voltage regulation", "Current limiting", "Signal coupling"],
        "regulation": ["Decoupling", "Filtering", "Protection", "Signal coupling"],
        "protection": ["Regulation", "Filtering", "Decoupling", "Signal coupling"],
        "phantom_power": ["Decoupling", "Voltage regulation", "Current limiting", "Signal coupling"],
    },
    "pin_function": {
        "input": ["Output", "Power", "Control", "Ground"],
        "output": ["Input", "Power", "Control", "Ground"],
        "power": ["Input", "Output", "Control", "Ground"],
        "control": ["Input", "Output", "Power", "Ground"],
        "ground": ["Input", "Output", "Power", "Control"],
    },
    "net_purpose": {
        "signal": ["Power rail", "Ground return", "Control line", "Feedback"],
        "power": ["Signal path", "Ground return", "Control line", "Feedback"],
        "ground": ["Signal path", "Power rail", "Control line", "Feedback"],
        "feedback": ["Signal path", "Power rail", "Ground return", "Control line"],
        "control": ["Signal path", "Power rail", "Ground return", "Feedback"],
    },
    "design_rules": {
        "satisfied": ["Violated", "Partially met", "Not applicable", "Cannot determine"],
        "violated": ["Satisfied", "Partially met", "Not applicable", "Cannot determine"],
    },
    "troubleshooting": {
        "library_issue": ["Layout bug", "Missing connection", "Wrong value", "Power issue"],
        "layout_bug": ["Library issue", "Missing connection", "Wrong value", "Power issue"],
        "missing_connection": ["Library issue", "Layout bug", "Wrong value", "Power issue"],
        "wrong_value": ["Library issue", "Layout bug", "Missing connection", "Power issue"],
        "power_issue": ["Library issue", "Layout bug", "Missing connection", "Wrong value"],
        "pin_not_connected": ["Wrong pin assignment", "Symbol error", "Net label missing", "Power rail issue"],
        "pin_power_drive": ["Wrong supply voltage", "Missing decoupling", "Incorrect pin type", "Ground loop"],
        "erc_error": ["File corruption", "Version mismatch", "Symbol library missing", "Configuration error"],
    },
}

# ---------------------------------------------------------------------------
# Correct answer mappings per category
# ---------------------------------------------------------------------------

_FUNCTION_DISPLAY: dict[str, str] = {
    "compressor_vca": "VCA compressor",
    "bypass_switch": "Analog switch/bypass",
    "output_buffer": "Output buffer/amplifier",
    "oscillator": "Oscillator/timing",
    "envelope_generator": "Envelope generator (ADSR)",
    "preamp": "Microphone preamplifier",
    "state_variable_filter": "State variable filter",
    "moog_ladder": "Moog ladder filter",
    "delay": "Delay line (BBD/PT2399)",
    "class_a_gain": "Class A gain stage",
    "mcu_control": "MCU control interface",
    "phantom_power": "Phantom power supply",
    "power_regulation": "Power regulation",
    "vca": "VCA (voltage-controlled amplifier)",
}

_LIB_ID_TO_COMPONENT: dict[str, tuple[str, str]] = {
    "Device:R": ("resistor", "Resistor"),
    "Device:C": ("capacitor", "Capacitor"),
    "Device:L": ("inductor", "Inductor"),
    "Device:Q_NPN": ("transistor", "NPN Transistor"),
    "Device:Q_PNP": ("transistor", "PNP Transistor"),
    "Device:D": ("diode", "Diode"),
    "Device:LED": ("diode", "LED"),
    "Amplifier_Operational:NE5532": ("opamp", "Operational Amplifier"),
    "Amplifier_Operational:LM358": ("opamp", "Operational Amplifier"),
    "Amplifier_Operational:TL072": ("opamp", "Operational Amplifier"),
    "THAT4301": ("vca", "VCA IC (THAT4301)"),
    "CD4066BE": ("switch", "Analog Switch (CD4066)"),
    "CD4060": ("mcu", "Binary Counter/Oscillator (CD4060)"),
    "RP2040": ("mcu", "Microcontroller (RP2040)"),
    "Device:R_Potentiometer": ("resistor", "Potentiometer"),
    "Device:Crystal": ("inductor", "Crystal Oscillator"),
}

_REF_PREFIX_TO_COMPONENT: dict[str, tuple[str, str]] = {
    "R": ("resistor", "Resistor"),
    "C": ("capacitor", "Capacitor"),
    "L": ("inductor", "Inductor"),
    "Q": ("transistor", "Transistor"),
    "D": ("diode", "Diode"),
    "U": ("ic", "Integrated Circuit"),
    "IC": ("ic", "Integrated Circuit"),
    "Y": ("inductor", "Crystal"),
    "J": ("connector", "Connector"),
    "P": ("connector", "Connector"),
    "SW": ("switch", "Switch"),
    "K": ("inductor", "Relay"),
    "RV": ("resistor", "Potentiometer"),
    "FB": ("inductor", "Ferrite Bead"),
    "TP": ("connector", "Test Point"),
    "F": ("diode", "Fuse"),
    "T": ("inductor", "Transformer"),
}


def _generate_id(counter: int) -> str:
    """Format a sequential question ID as pcb-mmlu-NNNN."""
    return f"pcb-mmlu-{counter:04d}"


def _select_difficulty(
    component_count: int,
    rng: random.Random,
    *,
    is_cross_sheet: bool = False,
    is_multi_ic: bool = False,
) -> str:
    """Determine difficulty based on subcircuit complexity.

    Rules from plan:
        easy = 1-3 components
        medium = 4-8 components
        hard = 9+ components OR cross-sheet violation OR multi-IC interaction
    """
    if is_cross_sheet or is_multi_ic or component_count >= 9:
        return "hard"
    if component_count <= 3:
        return "easy"
    return "medium"


def _render_template(template: str, context: dict[str, Any]) -> str:
    """Fill a question template with context data using safe substitution.

    Missing keys are replaced with a descriptive placeholder rather than
    raising KeyError, so generation is resilient to incomplete context.
    """
    try:
        return template.format_map(context)
    except KeyError:
        # Fall back to individual format with safe defaults
        result = template
        for key in _extract_format_keys(template):
            value = context.get(key, f"<{key}>")
            result = result.replace("{" + key + "}", str(value))
        return result


def _extract_format_keys(template: str) -> list[str]:
    """Extract {key} format placeholders from a template string."""
    import re

    return re.findall(r"\{(\w+)\}", template)


def _get_component_type(lib_id: str, ref: str) -> tuple[str, str]:
    """Map a lib_id or ref prefix to (pool_key, display_name).

    Returns ("ic", "Integrated Circuit") as default for unknown ICs.
    """
    # Try exact lib_id match first
    if lib_id in _LIB_ID_TO_COMPONENT:
        return _LIB_ID_TO_COMPONENT[lib_id]
    # Try short name (after colon)
    short = lib_id.split(":")[-1] if ":" in lib_id else lib_id
    if short in _LIB_ID_TO_COMPONENT:
        return _LIB_ID_TO_COMPONENT[short]
    # Try ref prefix
    for prefix, mapping in sorted(
        _REF_PREFIX_TO_COMPONENT.items(), key=lambda x: -len(x[0])
    ):
        if ref.upper().startswith(prefix.upper()):
            return mapping
    return ("ic", "Integrated Circuit")


def _get_distractors(
    category: str,
    correct_key: str,
    correct_answer: str,
    rng: random.Random,
    count: int = 3,
) -> list[str]:
    """Select distractors from the pool, excluding the correct answer.

    Falls back to generic distractors if the pool doesn't have the key.
    """
    pool = _DISTRACTOR_POOLS.get(category, {})
    candidates = pool.get(correct_key, [])

    # Filter out the correct answer (case-insensitive)
    correct_lower = correct_answer.lower()
    candidates = [c for c in candidates if c.lower() != correct_lower]

    # Fall back to generic distractors if pool is exhausted
    _GENERIC = [
        "Unknown component",
        "Passive element",
        "Active element",
        "Interface circuit",
        "Timing circuit",
    ]
    if len(candidates) < count:
        extras = [c for c in _GENERIC if c.lower() != correct_lower]
        candidates = candidates + extras

    # Shuffle and take count
    rng.shuffle(candidates)
    return candidates[:count]


def _classify_net_type(context: dict[str, Any]) -> str:
    """Classify net purpose from context (signal, power, ground, feedback, control)."""
    refs = context.get("refs", [])
    lib_ids = context.get("lib_ids", [])
    ref_str = " ".join(refs + lib_ids).upper()

    if any(kw in ref_str for kw in ["GND", "GNDA", "GROUND"]):
        return "ground"
    if any(kw in ref_str for kw in ["VCC", "VDD", "+9V", "-9V", "+12V", "-12V", "3V3", "5V"]):
        return "power"
    if any(kw in ref_str for kw in ["FB", "FEEDBACK", "LOOP"]):
        return "feedback"
    if any(kw in ref_str for kw in ["CTL", "CTRL", "EN", "RST", "CS", "CLK"]):
        return "control"
    return "signal"


def _classify_pin_function(context: dict[str, Any]) -> str:
    """Classify pin function from context (input, output, power, control, ground)."""
    ref_str = (context.get("ref", "") + " " + context.get("pin_name", "")).upper()
    if any(kw in ref_str for kw in ["IN", "INPUT", "VIN", "NON_INV"]):
        return "input"
    if any(kw in ref_str for kw in ["OUT", "OUTPUT", "VOUT"]):
        return "output"
    if any(kw in ref_str for kw in ["VCC", "VDD", "V+", "POWER"]):
        return "power"
    if any(kw in ref_str for kw in ["GND", "VSS", "V-", "GROUND"]):
        return "ground"
    if any(kw in ref_str for kw in ["EN", "CS", "CLK", "CTRL", "RST"]):
        return "control"
    # Default to input for generic pins
    return "input"


def generate_questions(
    category: str,
    context: dict[str, Any],
    *,
    rng: random.Random | None = None,
    id_start: int = 0,
) -> list[BenchmarkQuestion]:
    """Generate benchmark questions for a given category from schematic context.

    Args:
        category: One of 8 benchmark categories.
        context: Dict with schematic context (refs, lib_ids, function, etc.).
        rng: Seeded random instance for reproducible generation.
        id_start: Starting counter for question IDs.

    Returns:
        List of BenchmarkQuestion instances for this category/context.
    """
    if rng is None:
        rng = random.Random(42)

    global _id_counter
    _id_counter = max(_id_counter, id_start)

    templates = _CATEGORY_TEMPLATES.get(category, [])
    if not templates:
        return []

    refs = context.get("refs", [])
    lib_ids = context.get("lib_ids", [])
    function = context.get("function", "unknown")
    ic_ref = context.get("ic_ref", refs[0] if refs else "U1")
    ic_type = context.get("ic_type", "IC")
    component_count = context.get("component_count", len(refs))
    passive_count = context.get("passive_count", max(0, component_count - 1))

    questions: list[BenchmarkQuestion] = []

    # Category-specific generation
    if category == "component_identification":
        questions = _gen_component_identification(
            refs, lib_ids, templates, rng
        )
    elif category == "topology_recognition":
        questions = _gen_topology_recognition(
            refs, lib_ids, function, ic_ref, ic_type,
            component_count, passive_count, templates, rng,
        )
    elif category == "signal_flow":
        questions = _gen_signal_flow(
            refs, function, ic_ref, component_count, templates, rng,
        )
    elif category == "power_design":
        questions = _gen_power_design(
            refs, lib_ids, function, ic_ref, ic_type,
            component_count, templates, rng,
        )
    elif category == "pin_function":
        questions = _gen_pin_function(
            refs, function, ic_ref, ic_type, templates, rng,
        )
    elif category == "net_purpose":
        questions = _gen_net_purpose(
            refs, lib_ids, function, templates, rng,
        )
    elif category == "design_rules":
        questions = _gen_design_rules(
            refs, function, ic_ref, ic_type,
            component_count, templates, rng,
        )
    elif category == "troubleshooting":
        violations = context.get("violations", [])
        # If no violations provided, synthesize one from context refs
        if not violations and refs:
            violations = [
                {
                    "type": "pin_not_connected",
                    "description": f"Pin of {refs[0]} is not connected",
                    "severity": "error",
                    "positions": [(100.0, 100.0)],
                },
            ]
        questions = _gen_troubleshooting(violations, templates, rng)

    # Assign sequential IDs
    for q in questions:
        _id_counter += 1
        # We need to rebuild with the correct ID since id is frozen
        questions[questions.index(q)] = BenchmarkQuestion(
            id=_generate_id(_id_counter),
            category=q.category,
            difficulty=q.difficulty,
            question=q.question,
            choices=q.choices,
            correct_index=q.correct_index,
            explanation=q.explanation,
            source=q.source,
            source_type=q.source_type,
            tags=q.tags,
        )

    return questions


# ---------------------------------------------------------------------------
# Category-specific generators
# ---------------------------------------------------------------------------


def _gen_component_identification(
    refs: list[str],
    lib_ids: list[str],
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate component_identification questions."""
    questions: list[BenchmarkQuestion] = []
    seen_types: set[str] = set()

    for i, ref in enumerate(refs):
        lib_id = lib_ids[i] if i < len(lib_ids) else ""
        pool_key, display_name = _get_component_type(lib_id, ref)

        # Avoid duplicate questions for same component type
        if pool_key in seen_types:
            continue
        seen_types.add(pool_key)

        template = rng.choice(templates)
        question_text = _render_template(template, {"ref": ref, "lib_id": lib_id})
        correct = display_name
        distractors = _get_distractors("component_identification", pool_key, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        difficulty = _select_difficulty(1, rng)  # single component = easy

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",  # placeholder, overwritten later
            category="component_identification",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=f"{ref} uses library identifier {lib_id}, which is a {display_name}.",
            source="template-generated",
            source_type="schematic",
            tags=["component", pool_key],
        ))

    return questions


def _gen_topology_recognition(
    refs: list[str],
    lib_ids: list[str],
    function: str,
    ic_ref: str,
    ic_type: str,
    component_count: int,
    passive_count: int,
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate topology_recognition questions."""
    questions: list[BenchmarkQuestion] = []
    components_str = ", ".join(refs[:5]) + ("..." if len(refs) > 5 else "")

    for template in templates:
        question_text = _render_template(template, {
            "components": components_str,
            "ic_ref": ic_ref,
            "ic_type": ic_type,
            "passive_count": passive_count,
            "component_count": component_count,
        })

        correct = _FUNCTION_DISPLAY.get(function, function.replace("_", " ").title())
        correct_key = function
        distractors = _get_distractors("topology_recognition", correct_key, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        difficulty = _select_difficulty(component_count, rng)

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",
            category="topology_recognition",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=(
                f"The subcircuit centered on {ic_ref} ({ic_type}) with "
                f"{passive_count} passive components functions as a {correct}."
            ),
            source="template-generated",
            source_type="schematic",
            tags=["topology", function],
        ))

    return questions


def _gen_signal_flow(
    refs: list[str],
    function: str,
    ic_ref: str,
    component_count: int,
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate signal_flow questions."""
    questions: list[BenchmarkQuestion] = []
    components_str = ", ".join(refs[:5])

    # Determine signal flow type
    if "feedback" in function or "regulator" in function:
        flow_key = "feedback"
        correct = "Feedback loop"
    elif "buffer" in function or "output" in function:
        flow_key = "input_to_output"
        correct = "Input to output (series)"
    elif "switch" in function:
        flow_key = "bidirectional"
        correct = "Bidirectional (switchable)"
    else:
        flow_key = "input_to_output"
        correct = "Input to output (series)"

    for template in templates:
        question_text = _render_template(template, {
            "components": components_str,
            "function": function.replace("_", " "),
            "component_count": component_count,
        })
        distractors = _get_distractors("signal_flow", flow_key, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        difficulty = _select_difficulty(component_count, rng)

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",
            category="signal_flow",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=f"In the {function} subcircuit, signal flows {correct.lower()}.",
            source="template-generated",
            source_type="schematic",
            tags=["signal_flow", flow_key],
        ))

    return questions


def _gen_power_design(
    refs: list[str],
    lib_ids: list[str],
    function: str,
    ic_ref: str,
    ic_type: str,
    component_count: int,
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate power_design questions."""
    questions: list[BenchmarkQuestion] = []

    # Determine power design role
    has_caps = any("C" in ref.upper() and ref[0].upper() == "C" for ref in refs)
    has_reg = any("reg" in lid.lower() or "lm78" in lid.lower() for lid in lib_ids)

    if has_reg:
        power_key = "regulation"
        correct = "Voltage regulation"
    elif has_caps:
        power_key = "decoupling"
        correct = "Decoupling/bypass capacitors"
    else:
        power_key = "protection"
        correct = "Power protection"

    for template in templates:
        components_str = ", ".join(refs[:5])
        question_text = _render_template(template, {
            "ic_ref": ic_ref,
            "ic_type": ic_type,
            "function": function.replace("_", " "),
            "components": components_str,
            "component_count": component_count,
        })
        distractors = _get_distractors("power_design", power_key, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        difficulty = _select_difficulty(component_count, rng)

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",
            category="power_design",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=f"The power design for {ic_ref} uses {correct.lower()} in this {function} circuit.",
            source="template-generated",
            source_type="schematic",
            tags=["power", power_key],
        ))

    return questions


def _gen_pin_function(
    refs: list[str],
    function: str,
    ic_ref: str,
    ic_type: str,
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate pin_function questions."""
    questions: list[BenchmarkQuestion] = []

    # Generate questions for different pin types
    pin_types = ["input", "output", "power"]
    for pin_type in pin_types:
        template = rng.choice(templates)
        question_text = _render_template(template, {
            "ic_ref": ic_ref,
            "ic_type": ic_type,
            "function": function.replace("_", " "),
        })

        # Add pin-specific wording
        pin_questions = {
            "input": f"What is the function of the signal input pins on {ic_ref} ({ic_type})?",
            "output": f"What is the function of the signal output pins on {ic_ref} ({ic_type})?",
            "power": f"What is the function of the power supply pins on {ic_ref} ({ic_type})?",
        }

        correct_map = {
            "input": "Signal input",
            "output": "Signal output",
            "power": "Power supply",
        }

        question_text = pin_questions[pin_type]
        correct = correct_map[pin_type]
        distractors = _get_distractors("pin_function", pin_type, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        component_count = len(refs)
        difficulty = _select_difficulty(component_count, rng)

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",
            category="pin_function",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=f"The {pin_type} pins on {ic_ref} ({ic_type}) serve as {correct.lower()} pins.",
            source="template-generated",
            source_type="datasheet",
            tags=["pins", pin_type],
        ))

    return questions


def _gen_net_purpose(
    refs: list[str],
    lib_ids: list[str],
    function: str,
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate net_purpose questions."""
    questions: list[BenchmarkQuestion] = []
    components_str = ", ".join(refs[:4])

    # Classify the net type
    net_context = {"refs": refs, "lib_ids": lib_ids}
    net_key = _classify_net_type(net_context)
    net_display = {
        "signal": "Signal path",
        "power": "Power rail",
        "ground": "Ground return",
        "feedback": "Feedback loop",
        "control": "Control line",
    }
    correct = net_display.get(net_key, "Signal path")

    ref_a = refs[0] if len(refs) > 0 else "U1"
    ref_b = refs[1] if len(refs) > 1 else "R1"

    for template in templates:
        question_text = _render_template(template, {
            "components": components_str,
            "function": function.replace("_", " "),
            "ref_a": ref_a,
            "ref_b": ref_b,
        })
        distractors = _get_distractors("net_purpose", net_key, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        component_count = len(refs)
        difficulty = _select_difficulty(component_count, rng)

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",
            category="net_purpose",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=f"The net connecting {components_str} is a {correct.lower()}.",
            source="template-generated",
            source_type="netlist",
            tags=["net", net_key],
        ))

    return questions


def _gen_design_rules(
    refs: list[str],
    function: str,
    ic_ref: str,
    ic_type: str,
    component_count: int,
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate design_rules questions."""
    questions: list[BenchmarkQuestion] = []

    # Check if design rules are satisfied (heuristic: has caps near IC = satisfied)
    has_caps = any(ref.upper().startswith("C") for ref in refs)
    rule_key = "satisfied" if has_caps else "violated"
    correct = "Satisfied" if has_caps else "Violated"

    for template in templates:
        question_text = _render_template(template, {
            "function": function.replace("_", " "),
            "component_count": component_count,
            "ic_ref": ic_ref,
            "ic_type": ic_type,
        })
        distractors = _get_distractors("design_rules", rule_key, correct, rng)
        choices, correct_index = _shuffle_choices(correct, distractors, rng)

        difficulty = _select_difficulty(component_count, rng)

        questions.append(BenchmarkQuestion(
            id="pcb-mmlu-0000",
            category="design_rules",
            difficulty=difficulty,
            question=question_text,
            choices=choices,
            correct_index=correct_index,
            explanation=(
                f"The decoupling capacitor rule for {ic_ref} is {correct.lower()} "
                f"in this {function} subcircuit."
            ),
            source="template-generated",
            source_type="schematic",
            tags=["design_rules", rule_key],
        ))

    return questions


def _gen_troubleshooting(
    violations: list[dict[str, Any]],
    templates: list[str],
    rng: random.Random,
) -> list[BenchmarkQuestion]:
    """Generate troubleshooting questions from ERC violations."""
    questions: list[BenchmarkQuestion] = []

    for violation in violations:
        v_type = violation.get("type", "unknown")
        v_desc = violation.get("description", "Unknown violation")
        v_severity = violation.get("severity", "error")

        # Map violation type to root cause category
        cause_map = {
            "pin_not_connected": ("missing_connection", "Missing net connection"),
            "pin_power_drive": ("power_issue", "Power pin drive conflict"),
            "erc_error": ("library_issue", "Library or configuration error"),
            "symbol_warning": ("library_issue", "Symbol library issue"),
        }
        cause_key, correct = cause_map.get(v_type, ("layout_bug", "Layout or wiring error"))

        for template in templates:
            question_text = _render_template(template, {
                "violation_type": v_type,
                "violation_description": v_desc,
            })
            distractors = _get_distractors("troubleshooting", cause_key, correct, rng)
            choices, correct_index = _shuffle_choices(correct, distractors, rng)

            # Violations with positions = medium, without = easy
            positions = violation.get("positions", [])
            difficulty = "medium" if positions else "easy"

            questions.append(BenchmarkQuestion(
                id="pcb-mmlu-0000",
                category="troubleshooting",
                difficulty=difficulty,
                question=question_text,
                choices=choices,
                correct_index=correct_index,
                explanation=(
                    f"ERC violation '{v_type}' ({v_severity}): {v_desc}. "
                    f"Root cause: {correct.lower()}."
                ),
                source="template-generated",
                source_type="erc_report",
                tags=["troubleshooting", v_type],
            ))

    return questions


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _shuffle_choices(
    correct: str,
    distractors: list[str],
    rng: random.Random,
) -> tuple[list[str], int]:
    """Combine correct answer with distractors, shuffle, return (choices, correct_index).

    Ensures distractors are different from the correct answer (case-insensitive).
    """
    # Final safety check: remove any distractor matching correct
    filtered = [d for d in distractors if d.lower() != correct.lower()]

    # Pad if we lost distractors
    while len(filtered) < 3:
        filtered.append(f"Other (incorrect)")

    choices = [correct] + filtered[:3]
    rng.shuffle(choices)
    correct_index = choices.index(correct)
    return choices, correct_index


def reset_id_counter(value: int = 0) -> None:
    """Reset the global ID counter (useful for testing or rebuilding)."""
    global _id_counter
    _id_counter = value
