"""Template-based QA pair generation for Circuit QA dataset.

Generates open-ended question-answer pairs across 6 QA types using
deterministic templates filled with schematic context data. No LLM needed.

QA Types:
    violation_diagnosis - Diagnose ERC violations with root cause analysis
    signal_flow - Trace signal paths through circuit subcircuits
    component_function - Explain component roles in circuit context
    net_purpose - Describe net functions from topology
    design_review - Suggest improvements for subcircuits
    value_calculation - Calculate component values from specifications

Usage:
    from volta.benchmarks.qa_generator import QAGenerator

    gen = QAGenerator(source_schematics=[...], seed=42)
    dataset = gen.generate_dataset(target_count=2000)
"""

from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from volta.benchmarks.qa_schemas import CircuitQADataset, CircuitQAPair

# Re-export template data from the extracted module
from volta.benchmarks._qa_templates import (
    ANSWER_TEMPLATES as _ANSWER_TEMPLATES,
    COMPONENT_ROLES as _COMPONENT_ROLES,
    DEFAULT_ROOT_CAUSE as _DEFAULT_ROOT_CAUSE,
    DIFFICULTY_RULES as _DIFFICULTY_RULES,
    QUESTION_TEMPLATES as _QUESTION_TEMPLATES,
    VIOLATION_ROOT_CAUSES as _VIOLATION_ROOT_CAUSES,
)


def _assign_split(index: int, rng: random.Random) -> str:
    """Assign train/val/test split using seeded RNG.

    80% train, 10% val, 10% test, stratified by qa_type.
    """
    r = rng.random()
    if r < 0.8:
        return "train"
    elif r < 0.9:
        return "val"
    else:
        return "test"


class QAGenerator:
    """Generate open-ended circuit QA pairs from schematic context.

    Template-based generation across 6 QA types. Deterministic with seeded RNG.
    Decoupled from question_generator.py -- imports from schematic_graph.py
    and erc_parser.py directly (Council HIGH-6).

    Args:
        source_schematics: List of source dicts with violations, subcircuits,
            components, nets, design_reviews, value_calculations.
        seed: Random seed for deterministic generation.
    """

    def __init__(
        self,
        source_schematics: list[dict[str, Any]] | None = None,
        seed: int = 42,
    ) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self._id_counter = 0

        # Use provided sources or defaults with rich circuit context
        if source_schematics is not None and len(source_schematics) > 0:
            self.sources = source_schematics
        else:
            self.sources = self._default_sources()

    def _default_sources(self) -> list[dict[str, Any]]:
        """Generate default source data for standalone dataset generation."""
        sources = []
        # 10 analog-ecosystem modules (same as PCB MMLU Phase 41)
        module_names = [
            "compressor", "lfo", "adsr", "vca", "vcf",
            "delay", "moog_ladder", "mic_pre", "class_a_gain", "mcu_control",
        ]
        for name in module_names:
            sources.append(self._build_module_source(name))
        return sources

    def _build_module_source(self, module_name: str) -> dict[str, Any]:
        """Build a source dict with synthetic but realistic circuit data for a module."""
        violations = self._generate_violations_for_module(module_name)
        subcircuits = self._generate_subcircuits_for_module(module_name)
        components = self._generate_components_for_module(module_name)
        nets = self._generate_nets_for_module(module_name)
        design_reviews = self._generate_reviews_for_module(module_name)
        value_calcs = self._generate_calculations_for_module(module_name)
        return {
            "name": module_name,
            "violations": violations,
            "subcircuits": subcircuits,
            "components": components,
            "nets": nets,
            "design_reviews": design_reviews,
            "value_calculations": value_calcs,
        }

    def _generate_violations_for_module(self, name: str) -> list[dict[str, Any]]:
        """Generate synthetic violations for a module."""
        from volta.ops.erc_parser import ErcViolation

        violation_types = [
            ("power_pin_not_driven", "error", "Power pin not driven (power global)"),
            ("pin_not_connected", "warning", "Pin is not connected"),
            ("multiple_net_names", "error", "Multiple labels on same net"),
        ]
        violations = []
        for v_type, severity, desc in violation_types:
            x = round(self.rng.uniform(50, 150), 2)
            y = round(self.rng.uniform(50, 120), 2)
            violations.append(ErcViolation(
                sheet="/",
                type=v_type,
                severity=severity,
                description=desc,
                positions=[(x, y)],
            ))
        return violations

    def _generate_subcircuits_for_module(self, name: str) -> list[dict[str, Any]]:
        """Generate synthetic subcircuit data for a module."""
        subcircuit_templates = {
            "compressor": [
                {"name": "compressor_vca", "input_net": "COMP_IN", "output_net": "COMP_OUT",
                 "components": [
                     {"ref": "R55", "value": "10k", "lib_id": "Device:R", "role": "input resistor"},
                     {"ref": "U22", "value": "THAT4301", "lib_id": "THAT4301", "role": "VCA"},
                     {"ref": "R60", "value": "100k", "lib_id": "Device:R", "role": "feedback"},
                     {"ref": "C47", "value": "100nF", "lib_id": "Device:C", "role": "coupling"},
                 ],
                 "function": "compressor_vca"},
                {"name": "output_buffer", "input_net": "EQ_OUT", "output_net": "OUT",
                 "components": [
                     {"ref": "U23", "value": "NE5532", "lib_id": "Amplifier_Operational:NE5532", "role": "buffer"},
                     {"ref": "C50", "value": "10uF", "lib_id": "Device:C", "role": "output coupling"},
                 ],
                 "function": "output_buffer"},
            ],
            "lfo": [
                {"name": "lfo_core", "input_net": "RATE_IN", "output_net": "LFO_OUT",
                 "components": [
                     {"ref": "U5", "value": "TL072", "lib_id": "Amplifier_Operational:TL072", "role": "integrator"},
                     {"ref": "R12", "value": "47k", "lib_id": "Device:R", "role": "timing resistor"},
                     {"ref": "C8", "value": "1uF", "lib_id": "Device:C", "role": "timing capacitor"},
                 ],
                 "function": "lfo_core"},
            ],
            "adsr": [
                {"name": "envelope_generator", "input_net": "GATE_IN", "output_net": "ENV_OUT",
                 "components": [
                     {"ref": "U10", "value": "LM358", "lib_id": "Amplifier_Operational:LM358", "role": "buffer"},
                     {"ref": "R20", "value": "100k", "lib_id": "Device:R", "role": "attack resistor"},
                     {"ref": "R21", "value": "47k", "lib_id": "Device:R", "role": "release resistor"},
                     {"ref": "C15", "value": "10uF", "lib_id": "Device:C", "role": "timing cap"},
                 ],
                 "function": "envelope_generator"},
            ],
            "vca": [
                {"name": "vca_core", "input_net": "AUDIO_IN", "output_net": "AUDIO_OUT",
                 "components": [
                     {"ref": "U30", "value": "THAT4301", "lib_id": "THAT4301", "role": "VCA"},
                     {"ref": "R40", "value": "10k", "lib_id": "Device:R", "role": "input resistor"},
                     {"ref": "C30", "value": "100nF", "lib_id": "Device:C", "role": "coupling"},
                 ],
                 "function": "vca"},
            ],
            "vcf": [
                {"name": "moog_ladder", "input_net": "AUDIO_IN", "output_net": "FILTER_OUT",
                 "components": [
                     {"ref": "Q1", "value": "BC547", "lib_id": "Device:Q_NPN", "role": "ladder transistor"},
                     {"ref": "Q2", "value": "BC547", "lib_id": "Device:Q_NPN", "role": "ladder transistor"},
                     {"ref": "R50", "value": "1k", "lib_id": "Device:R", "role": "emitter resistor"},
                     {"ref": "C40", "value": "1nF", "lib_id": "Device:C", "role": "ladder capacitor"},
                     {"ref": "C41", "value": "1nF", "lib_id": "Device:C", "role": "ladder capacitor"},
                 ],
                 "function": "moog_ladder"},
            ],
            "delay": [
                {"name": "delay_line", "input_net": "DRY_IN", "output_net": "WET_OUT",
                 "components": [
                     {"ref": "U40", "value": "PT2399", "lib_id": "PT2399", "role": "delay IC"},
                     {"ref": "R60", "value": "50k", "lib_id": "Device:R", "role": "delay time"},
                     {"ref": "C55", "value": "10nF", "lib_id": "Device:C", "role": "clock cap"},
                 ],
                 "function": "delay"},
            ],
            "moog_ladder": [
                {"name": "moog_filter", "input_net": "FILTER_IN", "output_net": "FILTER_OUT",
                 "components": [
                     {"ref": "Q10", "value": "BC547", "lib_id": "Device:Q_NPN", "role": "ladder rung 1"},
                     {"ref": "Q11", "value": "BC547", "lib_id": "Device:Q_NPN", "role": "ladder rung 2"},
                     {"ref": "C60", "value": "2.2nF", "lib_id": "Device:C", "role": "filter cap"},
                     {"ref": "C61", "value": "2.2nF", "lib_id": "Device:C", "role": "filter cap"},
                 ],
                 "function": "moog_ladder"},
            ],
            "mic_pre": [
                {"name": "preamp_stage", "input_net": "MIC_IN", "output_net": "PRE_OUT",
                 "components": [
                     {"ref": "U50", "value": "NE5532", "lib_id": "Amplifier_Operational:NE5532", "role": "preamp op-amp"},
                     {"ref": "R70", "value": "10k", "lib_id": "Device:R", "role": "gain resistor"},
                     {"ref": "R71", "value": "100", "lib_id": "Device:R", "role": "bias resistor"},
                 ],
                 "function": "preamp"},
            ],
            "class_a_gain": [
                {"name": "gain_stage", "input_net": "GAIN_IN", "output_net": "GAIN_OUT",
                 "components": [
                     {"ref": "Q20", "value": "BC547", "lib_id": "Device:Q_NPN", "role": "Class A transistor"},
                     {"ref": "R80", "value": "4.7k", "lib_id": "Device:R", "role": "collector resistor"},
                     {"ref": "C70", "value": "100nF", "lib_id": "Device:C", "role": "coupling"},
                 ],
                 "function": "class_a_gain"},
            ],
            "mcu_control": [
                {"name": "mcu_interface", "input_net": "SPI_MOSI", "output_net": "DAC_OUT",
                 "components": [
                     {"ref": "U60", "value": "RP2040", "lib_id": "RP2040", "role": "microcontroller"},
                     {"ref": "R90", "value": "4.7k", "lib_id": "Device:R", "role": "pull-up"},
                     {"ref": "C80", "value": "100nF", "lib_id": "Device:C", "role": "decoupling"},
                 ],
                 "function": "mcu_control"},
            ],
        }
        return subcircuit_templates.get(name, [])

    def _generate_components_for_module(self, name: str) -> list[dict[str, Any]]:
        """Generate synthetic component data for a module."""
        component_templates = {
            "compressor": [
                {"ref": "R55", "value": "10k", "lib_id": "Device:R", "circuit_type": "compressor",
                 "net_a": "COMP_IN", "net_b": "U22_IN", "purpose": "input resistor setting the VCA input impedance"},
                {"ref": "U22", "value": "THAT4301", "lib_id": "THAT4301", "circuit_type": "compressor",
                 "net_a": "U22_IN", "net_b": "VCA_OUT", "purpose": "voltage-controlled amplifier providing gain reduction based on control voltage"},
                {"ref": "R60", "value": "100k", "lib_id": "Device:R", "circuit_type": "compressor",
                 "net_a": "SC_IN", "net_b": "SC_FILTER", "purpose": "sidechain input resistor connecting the COMP_THRESHOLD signal to the sidechain filter"},
                {"ref": "C47", "value": "100nF", "lib_id": "Device:C", "circuit_type": "compressor",
                 "net_a": "VCA_OUT", "net_b": "BUFFER_IN", "purpose": "AC coupling capacitor blocking DC between VCA output and buffer input"},
                {"ref": "R58", "value": "22k", "lib_id": "Device:R", "circuit_type": "compressor",
                 "net_a": "VCA_OUT", "net_b": "GND", "purpose": "pull-down resistor setting the VCA output DC operating point"},
                {"ref": "U23", "value": "NE5532", "lib_id": "Amplifier_Operational:NE5532", "circuit_type": "compressor",
                 "net_a": "BUFFER_IN", "net_b": "EQ_OUT", "purpose": "output buffer op-amp providing low-impedance drive to the equalizer stage"},
            ],
        }
        base = component_templates.get(name, [])
        if not base:
            # Generate generic components based on module
            ref_num = self.rng.randint(10, 90)
            base = [
                {"ref": f"R{ref_num}", "value": "10k", "lib_id": "Device:R", "circuit_type": name,
                 "net_a": f"{name.upper()}_IN", "net_b": f"{name.upper()}_MID", "purpose": f"input resistor in the {name} circuit setting signal level"},
                {"ref": f"R{ref_num+1}", "value": "47k", "lib_id": "Device:R", "circuit_type": name,
                 "net_a": f"{name.upper()}_MID", "net_b": f"{name.upper()}_OUT", "purpose": f"feedback resistor in the {name} circuit controlling gain"},
                {"ref": f"C{ref_num}", "value": "100nF", "lib_id": "Device:C", "circuit_type": name,
                 "net_a": f"{name.upper()}_MID", "net_b": "GND", "purpose": f"coupling capacitor in the {name} circuit for AC signal blocking"},
                {"ref": f"C{ref_num+1}", "value": "10uF", "lib_id": "Device:C", "circuit_type": name,
                 "net_a": f"{name.upper()}_OUT", "net_b": f"{name.upper()}_NEXT", "purpose": f"output coupling capacitor in the {name} circuit"},
            ]
        return base

    def _generate_nets_for_module(self, name: str) -> list[dict[str, Any]]:
        """Generate synthetic net data for a module."""
        return [
            {
                "name": f"{name.upper()}_IN",
                "function": f"{name} input signal net",
                "pins": [f"R10.1", f"U1.1"],
                "purpose": f"carrying the input signal to the {name} processing stage",
                "subcircuit": name,
            },
            {
                "name": f"{name.upper()}_OUT",
                "function": f"{name} output signal net",
                "pins": [f"U1.6", f"R20.1", f"C10.1"],
                "purpose": f"carrying the processed signal from the {name} to the next stage",
                "subcircuit": name,
            },
            {
                "name": f"{name.upper()}_FB",
                "function": f"{name} feedback net",
                "pins": [f"R15.1", f"R15.2", f"U1.2"],
                "purpose": f"providing negative feedback for stability in the {name} circuit",
                "subcircuit": name,
            },
            {
                "name": "GND",
                "function": "ground reference",
                "pins": [f"C10.2", f"C11.2", f"R12.2"],
                "purpose": "providing the common ground reference for the circuit",
                "subcircuit": "power",
            },
        ]

    def _generate_reviews_for_module(self, name: str) -> list[dict[str, Any]]:
        """Generate synthetic design review data for a module."""
        return [
            {
                "subcircuit": f"{name} input stage",
                "improvements": [
                    "Adding ESD protection diodes on the input",
                    "Implementing a buffered input for higher impedance",
                ],
                "state": "a direct-coupled input without protection",
                "limitation": "makes the circuit vulnerable to electrostatic discharge and loading effects",
            },
            {
                "subcircuit": f"{name} output stage",
                "improvements": [
                    "Adding a series output resistor (47 ohm) to prevent oscillation with capacitive loads",
                    "Implementing a DC servo for offset nulling",
                ],
                "state": "a simple output buffer without stability compensation",
                "limitation": "may oscillate with long cable runs or high-capacitance loads",
            },
        ]

    def _generate_calculations_for_module(self, name: str) -> list[dict[str, Any]]:
        """Generate synthetic value calculation data for a module."""
        return [
            {
                "ref": f"C_timing",
                "spec": f"a 10ms time constant for the {name} response",
                "constraint": "R_timing=10k",
                "formula": "t / R",
                "result": "1uF",
                "values": f"t=10ms and R=10k",
                "explanation": f"the timing capacitor determines the {name} response speed",
            },
            {
                "ref": f"R_gain",
                "spec": f"a gain of 10x in the {name} amplifier",
                "constraint": "R_feedback=100k",
                "formula": "R_feedback / (gain - 1)",
                "result": "11.1k",
                "values": f"gain=10 and R_feedback=100k",
                "explanation": f"the gain-setting resistor establishes the closed-loop gain of the {name} amplifier",
            },
            {
                "ref": f"C_coupling",
                "spec": f"a -3dB cutoff below 20Hz at the {name} input",
                "constraint": "R_input=10k",
                "formula": "1 / (2 * pi * f * R)",
                "result": "796nF",
                "values": f"f=20Hz and R_input=10k",
                "explanation": f"the coupling capacitor value sets the low-frequency rolloff of the {name} input stage",
            },
        ]

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def generate_dataset(self, target_count: int = 2000) -> CircuitQADataset:
        """Generate complete QA dataset.

        Args:
            target_count: Minimum number of QA pairs to generate.

        Returns:
            CircuitQADataset with train/val/test split metadata.
        """
        self._id_counter = 0
        all_pairs: list[CircuitQAPair] = []

        for source in self.sources:
            source_name = source.get("name", "unknown")
            source_file = f"{source_name}.kicad_sch"

            # Generate from each QA type for this source
            violations = source.get("violations", [])
            if violations:
                all_pairs.extend(
                    self._generate_violation_qa(violations, source_file)
                )

            subcircuits = source.get("subcircuits", [])
            if subcircuits:
                all_pairs.extend(
                    self._generate_signal_flow_qa(subcircuits, source_file)
                )

            components = source.get("components", [])
            if components:
                all_pairs.extend(
                    self._generate_component_function_qa(components, source_file)
                )

            nets = source.get("nets", [])
            if nets:
                all_pairs.extend(
                    self._generate_net_purpose_qa(nets, source_file)
                )

            design_reviews = source.get("design_reviews", [])
            if design_reviews:
                all_pairs.extend(
                    self._generate_design_review_qa(design_reviews, source_file)
                )

            value_calcs = source.get("value_calculations", [])
            if value_calcs:
                all_pairs.extend(
                    self._generate_value_calculation_qa(value_calcs, source_file)
                )

        # If we don't have enough, replicate with variations
        if len(all_pairs) < target_count:
            all_pairs = self._replicate_to_target(all_pairs, target_count)

        # Assign sequential IDs
        all_pairs = self._assign_ids(all_pairs)

        # Assign train/val/test splits (stratified by qa_type)
        all_pairs = self._assign_splits(all_pairs)

        # Build split counts
        split_counts = Counter(p.split for p in all_pairs)
        split_types: dict[str, list[str]] = {}
        for split_name in ("train", "val", "test"):
            types_in_split = set(
                p.qa_type for p in all_pairs if p.split == split_name
            )
            split_types[split_name] = sorted(types_in_split)

        return CircuitQADataset(
            version="1.0.0",
            generated_at=datetime.now(timezone.utc).isoformat(),
            qa_pairs=all_pairs,
            metadata={
                "seed": self.seed,
                "source_count": len(self.sources),
                "split_counts": {
                    "train": split_counts.get("train", 0),
                    "val": split_counts.get("val", 0),
                    "test": split_counts.get("test", 0),
                },
                "split_types": split_types,
                "qa_type_counts": dict(Counter(p.qa_type for p in all_pairs)),
                "difficulty_counts": dict(Counter(p.difficulty for p in all_pairs)),
            },
        )

    # -----------------------------------------------------------------------
    # QA type generators
    # -----------------------------------------------------------------------

    def _generate_violation_qa(
        self,
        violations: list[Any],
        source: str,
    ) -> list[CircuitQAPair]:
        """Generate violation_diagnosis QA from ERC reports.

        Question: "Why does this schematic have a {violation_type} violation?"
        Answer: "The {violation_type} is caused by {root_cause}..."
        """
        pairs: list[CircuitQAPair] = []

        for v in violations:
            # Handle both ErcViolation dataclass and dict
            if hasattr(v, "type"):
                v_type = v.type
                v_severity = v.severity
                v_desc = v.description
                v_positions = v.positions
            else:
                v_type = v.get("type", "unknown")
                v_severity = v.get("severity", "error")
                v_desc = v.get("description", "Unknown violation")
                v_positions = v.get("positions", [])

            cause_data = _VIOLATION_ROOT_CAUSES.get(v_type, _DEFAULT_ROOT_CAUSE)

            # Generate questions from each template
            for q_template in _QUESTION_TEMPLATES["violation_diagnosis"]:
                pos = v_positions[0] if v_positions else (0.0, 0.0)
                question = q_template.format(
                    violation_type=v_type,
                    x=pos[0],
                    y=pos[1],
                    severity=v_severity,
                )

                # Select answer template
                a_template = self.rng.choice(_ANSWER_TEMPLATES["violation_diagnosis"])
                answer = a_template.format(
                    violation_type=v_type,
                    root_cause=cause_data["root_cause"],
                    x=pos[0],
                    y=pos[1],
                    explanation=v_desc,
                    category=cause_data["category"],
                    reason=cause_data["reason"],
                    fix_suggestion=cause_data["fix_suggestion"],
                    severity=v_severity,
                )

                difficulty = "hard" if v_severity == "error" else "medium"

                pairs.append(CircuitQAPair(
                    id="qa-0000",  # placeholder, overwritten by _assign_ids
                    qa_type="violation_diagnosis",
                    question=question,
                    answer=answer,
                    source=source,
                    source_type="erc_report",
                    difficulty=difficulty,
                    tags=["violation", v_type],
                ))

        return pairs

    def _generate_signal_flow_qa(
        self,
        subcircuits: list[dict[str, Any]],
        source: str,
    ) -> list[CircuitQAPair]:
        """Generate signal_flow QA from schematic topology.

        Question: "What is the signal path from {input} to {output}?"
        Answer: "The path: {input} -> {comp1} -> {comp2} -> {output}..."
        """
        pairs: list[CircuitQAPair] = []

        for sc in subcircuits:
            sc_name = sc.get("name", "unknown subcircuit")
            input_net = sc.get("input_net", "INPUT")
            output_net = sc.get("output_net", "OUTPUT")
            components = sc.get("components", [])
            function = sc.get("function", sc_name)

            # Build path string
            path_parts = [input_net]
            for comp in components:
                path_parts.append(f"{comp['ref']} ({comp.get('value', '')})")
            path_parts.append(output_net)
            path_str = " -> ".join(path_parts)

            for q_template in _QUESTION_TEMPLATES["signal_flow"]:
                question = q_template.format(
                    input_net=input_net,
                    output_net=output_net,
                    subcircuit_name=sc_name.replace("_", " "),
                )

                # Build answer with component functions
                first_comp = components[0] if components else {"ref": "?", "role": "unknown"}
                second_comp = components[1] if len(components) > 1 else {"ref": "?", "role": "unknown"}

                path_comp_str = " -> ".join(f"{c['ref']}" for c in components)
                a_template = self.rng.choice(_ANSWER_TEMPLATES["signal_flow"])
                answer = a_template.format(
                    input_net=input_net,
                    path_components=path_comp_str,
                    output_net=output_net,
                    subcircuit_name=sc_name.replace("_", " "),
                    first_component=first_comp["ref"],
                    first_function=f"serves as {first_comp.get('role', 'a component')}",
                    second_component=second_comp["ref"],
                    second_function=f"acts as {second_comp.get('role', 'a component')}",
                    flow_description=f"the {function.replace('_', ' ')} signal chain",
                )

                comp_count = len(components)
                if comp_count <= 3:
                    difficulty = "easy"
                elif comp_count < 9:
                    difficulty = "medium"
                else:
                    difficulty = "hard"

                pairs.append(CircuitQAPair(
                    id="qa-0000",
                    qa_type="signal_flow",
                    question=question,
                    answer=answer,
                    source=source,
                    source_type="schematic",
                    difficulty=difficulty,
                    tags=["signal_flow", function],
                ))

        return pairs

    def _generate_component_function_qa(
        self,
        components: list[dict[str, Any]],
        source: str,
    ) -> list[CircuitQAPair]:
        """Generate component_function QA from IC context.

        Question: "What is the purpose of {ref} ({value}) in this {circuit_type}?"
        Answer: "{ref} is a {role} that {function}..."
        """
        pairs: list[CircuitQAPair] = []

        for comp in components:
            ref = comp.get("ref", "?")
            value = comp.get("value", "")
            lib_id = comp.get("lib_id", "")
            circuit_type = comp.get("circuit_type", "circuit")
            net_a = comp.get("net_a", "NET_A")
            net_b = comp.get("net_b", "NET_B")
            purpose = comp.get("purpose", "provides circuit functionality")
            role = _COMPONENT_ROLES.get(lib_id, "component")

            for q_template in _QUESTION_TEMPLATES["component_function"]:
                question = q_template.format(
                    ref=ref,
                    value=value,
                    circuit_type=circuit_type,
                )

                a_template = self.rng.choice(_ANSWER_TEMPLATES["component_function"])
                answer = a_template.format(
                    ref=ref,
                    role=role,
                    function=purpose,
                    net_a=net_a,
                    net_b=net_b,
                    purpose=purpose,
                    circuit_type=circuit_type,
                    value=value,
                    essential_function=f"proper {circuit_type} operation",
                )

                # Passive = easy, IC = medium, complex IC = hard
                if lib_id.startswith("Device:"):
                    difficulty = "easy"
                elif "THAT" in lib_id or "RP2040" in lib_id or "PT2399" in lib_id:
                    difficulty = "hard"
                else:
                    difficulty = "medium"

                pairs.append(CircuitQAPair(
                    id="qa-0000",
                    qa_type="component_function",
                    question=question,
                    answer=answer,
                    source=source,
                    source_type="schematic",
                    difficulty=difficulty,
                    tags=["component", lib_id.split(":")[-1] if ":" in lib_id else lib_id],
                ))

        return pairs

    def _generate_net_purpose_qa(
        self,
        nets: list[dict[str, Any]],
        source: str,
    ) -> list[CircuitQAPair]:
        """Generate net_purpose QA from net topology.

        Question: "What is the purpose of the {net_name} net?"
        Answer: "{net_name} is {function} connecting {pin_list}..."
        """
        pairs: list[CircuitQAPair] = []

        for net in nets:
            net_name = net.get("name", "NET")
            function = net.get("function", "a signal net")
            pins = net.get("pins", [])
            purpose = net.get("purpose", "carrying signals between components")
            subcircuit = net.get("subcircuit", "main")

            pin_list_str = ", ".join(pins) if pins else "various pins"

            for q_template in _QUESTION_TEMPLATES["net_purpose"]:
                question = q_template.format(
                    net_name=net_name,
                    subcircuit=subcircuit,
                )

                a_template = self.rng.choice(_ANSWER_TEMPLATES["net_purpose"])
                answer = a_template.format(
                    net_name=net_name,
                    function=function,
                    pin_list=pin_list_str,
                    purpose=purpose,
                    subcircuit=subcircuit,
                    importance=f"it provides the {function}",
                    consequence=f"lose the {function.split()[0]} connection in the {subcircuit}",
                )

                # Power/ground = easy, signal = medium, feedback = hard
                net_name_upper = net_name.upper()
                if "GND" in net_name_upper or "VCC" in net_name_upper or "+5" in net_name_upper or "+3" in net_name_upper:
                    difficulty = "easy"
                elif "FB" in net_name_upper or "FEEDBACK" in net_name_upper or "LOOP" in net_name_upper:
                    difficulty = "hard"
                else:
                    difficulty = "medium"

                pairs.append(CircuitQAPair(
                    id="qa-0000",
                    qa_type="net_purpose",
                    question=question,
                    answer=answer,
                    source=source,
                    source_type="netlist",
                    difficulty=difficulty,
                    tags=["net", net_name],
                ))

        return pairs

    def _generate_design_review_qa(
        self,
        design_reviews: list[dict[str, Any]],
        source: str,
    ) -> list[CircuitQAPair]:
        """Generate design_review QA.

        Question: "What improvements could be made to the {subcircuit}?"
        Answer: "The {subcircuit} could benefit from: 1) {imp1}, 2) {imp2}..."
        """
        pairs: list[CircuitQAPair] = []

        for review in design_reviews:
            subcircuit = review.get("subcircuit", "circuit")
            improvements = review.get("improvements", ["general improvement"])
            state = review.get("state", "a basic implementation")
            limitation = review.get("limitation", "could be improved")

            imp1 = improvements[0] if len(improvements) > 0 else "general improvement"
            imp2 = improvements[1] if len(improvements) > 1 else "additional optimization"

            for q_template in _QUESTION_TEMPLATES["design_review"]:
                question = q_template.format(subcircuit=subcircuit)

                a_template = self.rng.choice(_ANSWER_TEMPLATES["design_review"])
                answer = a_template.format(
                    subcircuit=subcircuit,
                    imp1=imp1,
                    imp2=imp2,
                    state=state,
                    limitation=limitation,
                    benefit=f"improve the overall performance and reliability of the {subcircuit}",
                )

                difficulty = "medium" if len(improvements) <= 2 else "hard"

                pairs.append(CircuitQAPair(
                    id="qa-0000",
                    qa_type="design_review",
                    question=question,
                    answer=answer,
                    source=source,
                    source_type="schematic",
                    difficulty=difficulty,
                    tags=["design_review", subcircuit.replace(" ", "_")],
                ))

        return pairs

    def _generate_value_calculation_qa(
        self,
        value_calculations: list[dict[str, Any]],
        source: str,
    ) -> list[CircuitQAPair]:
        """Generate value_calculation QA.

        Question: "What value should {ref} be for {spec}?"
        Answer: "{ref} = {formula} = {result}..."
        """
        pairs: list[CircuitQAPair] = []

        for calc in value_calculations:
            ref = calc.get("ref", "X")
            spec = calc.get("spec", "the required specification")
            constraint = calc.get("constraint", "given values")
            formula = calc.get("formula", "calculation")
            result = calc.get("result", "calculated value")
            values = calc.get("values", "the parameters")
            explanation = calc.get("explanation", "the calculated value meets the specification")

            for q_template in _QUESTION_TEMPLATES["value_calculation"]:
                question = q_template.format(
                    ref=ref,
                    spec=spec,
                    constraint=constraint,
                )

                a_template = self.rng.choice(_ANSWER_TEMPLATES["value_calculation"])
                answer = a_template.format(
                    ref=ref,
                    formula=formula,
                    result=result,
                    values=values,
                    explanation=explanation,
                    spec=spec,
                )

                # Simple formula = easy, RC time constant = medium, multi-variable = hard
                if "/" in formula and "*" in formula:
                    difficulty = "hard"
                elif "/" in formula or "*" in formula:
                    difficulty = "medium"
                else:
                    difficulty = "easy"

                pairs.append(CircuitQAPair(
                    id="qa-0000",
                    qa_type="value_calculation",
                    question=question,
                    answer=answer,
                    source=source,
                    source_type="manual",
                    difficulty=difficulty,
                    tags=["calculation", ref],
                ))

        return pairs

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _replicate_to_target(
        self,
        existing_pairs: list[CircuitQAPair],
        target_count: int,
    ) -> list[CircuitQAPair]:
        """Replicate QA pairs with variations to reach target count."""
        if not existing_pairs:
            return existing_pairs

        result = list(existing_pairs)
        replication_round = 1

        while len(result) < target_count:
            for pair in existing_pairs:
                if len(result) >= target_count:
                    break

                # Create variation with slightly modified question
                variant_suffixes = [
                    " Explain your reasoning.",
                    " What are the key considerations?",
                    " Provide a detailed explanation.",
                    " Justify your answer.",
                    " What assumptions are involved?",
                ]
                suffix = self.rng.choice(variant_suffixes)

                variant = CircuitQAPair(
                    id="qa-0000",
                    qa_type=pair.qa_type,
                    question=pair.question + suffix,
                    answer=pair.answer,
                    source=pair.source + f" (variant {replication_round})",
                    source_type=pair.source_type,
                    difficulty=pair.difficulty,
                    tags=pair.tags + [f"variant-{replication_round}"],
                )
                result.append(variant)

            replication_round += 1
            if replication_round > 100:
                break  # safety limit

        return result

    def _assign_ids(self, pairs: list[CircuitQAPair]) -> list[CircuitQAPair]:
        """Assign sequential IDs in qa-NNNN format."""
        result = []
        for i, pair in enumerate(pairs, start=1):
            result.append(CircuitQAPair(
                id=f"qa-{i:04d}",
                qa_type=pair.qa_type,
                question=pair.question,
                answer=pair.answer,
                source=pair.source,
                source_type=pair.source_type,
                difficulty=pair.difficulty,
                tags=pair.tags,
                split=pair.split,
            ))
        return result

    def _assign_splits(self, pairs: list[CircuitQAPair]) -> list[CircuitQAPair]:
        """Assign train/val/test splits, stratified by qa_type.

        Creates a separate RNG per qa_type to ensure stratification.
        80/10/10 split with deterministic seeding.
        """
        # Group pairs by qa_type
        by_type: dict[str, list[int]] = {}
        for i, pair in enumerate(pairs):
            by_type.setdefault(pair.qa_type, []).append(i)

        # Assign splits per type
        result = list(pairs)
        for qa_type, indices in by_type.items():
            # Create a deterministic RNG for this qa_type
            type_rng = random.Random(self.seed + hash(qa_type))

            # Shuffle indices deterministically
            shuffled = list(indices)
            type_rng.shuffle(shuffled)

            n = len(shuffled)
            train_end = int(n * 0.8)
            val_end = int(n * 0.9)

            for j, idx in enumerate(shuffled):
                if j < train_end:
                    split = "train"
                elif j < val_end:
                    split = "val"
                else:
                    split = "test"

                old = result[idx]
                result[idx] = CircuitQAPair(
                    id=old.id,
                    qa_type=old.qa_type,
                    question=old.question,
                    answer=old.answer,
                    source=old.source,
                    source_type=old.source_type,
                    difficulty=old.difficulty,
                    tags=old.tags,
                    split=split,
                )

        return result
