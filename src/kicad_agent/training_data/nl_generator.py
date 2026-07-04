"""Phase 159: AI Training Data Factory.

Turns the Phase 156 SKIDL converter into a training data factory:
  1. Convert KiCad schematics → SKIDL Python code
  2. Generate natural-language descriptions from circuit topology
  3. Pair them as SFT training examples for Qwen text model

Output: ChatML JSONL (NL → SKIDL code pairs).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from kicad_agent.circuit_ir.types import CircuitIR
from kicad_agent.circuit_ir.skidl_emitter import emit_build_py

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainingExample:
    """A single NL→code training example.

    Attributes:
        user_message: Natural language circuit description.
        assistant_message: SKIDL Python code.
        task_type: "nl_to_skidl".
        source_file: Origin .kicad_sch path.
        part_count: Number of parts in the circuit.
        net_count: Number of nets.
    """
    user_message: str
    assistant_message: str
    task_type: str
    source_file: str
    part_count: int
    net_count: int

    def to_chatml(self) -> dict:
        """Convert to ChatML JSONL format."""
        return {
            "messages": [
                {"role": "user", "content": self.user_message},
                {"role": "assistant", "content": self.assistant_message},
            ],
            "task_type": self.task_type,
            "source_file": self.source_file,
            "metadata": {
                "part_count": self.part_count,
                "net_count": self.net_count,
            },
        }


def generate_nl_description(circuit_ir: CircuitIR) -> str:
    """Generate a natural-language description from circuit topology.

    Analyzes the CircuitIR to infer the circuit's function and produce
    a human-readable description suitable for LLM training.

    Args:
        circuit_ir: The circuit intermediate representation.

    Returns:
        Natural language description (1-3 sentences).
    """
    parts = circuit_ir.parts
    nets = circuit_ir.nets

    if not parts:
        return "An empty circuit with no components."

    # Classify parts.
    resistors = [p for p in parts if "R" in p.lib_id.split(":")[-1]]
    capacitors = [p for p in parts if "C" in p.lib_id.split(":")[-1]][:1]
    inductors = [p for p in parts if "L" == p.lib_id.split(":")[-1][:1]]
    diodes = [p for p in parts if "LED" in p.lib_id or "D_" in p.lib_id]
    opamps = [p for p in parts if any(o in p.lib_id.upper() for o in ("OPAMP", "NE5532", "TL072", "LM358"))]
    ics = [p for p in parts if p not in resistors + capacitors + inductors + diodes + opamps]

    lines: list[str] = []

    # Infer function from dominant components.
    if opamps:
        lines.append(f"An analog circuit with {len(opamps)} opamp(s)")
        if resistors:
            lines.append(f" and {len(resistors)} resistor(s)")
        if capacitors:
            lines.append(f" — likely an amplifier or filter")
    elif diodes and resistors:
        lines.append(f"An LED circuit with {len(resistors)} current-limiting resistor(s)")
    elif len(resistors) > 2 and len(capacitors) > 1:
        lines.append(f"A passive filter network with {len(resistors)} resistor(s) and {len(capacitors)} capacitor(s)")
    elif ics and len(ics) > len(parts) * 0.5:
        ic_names = [p.value or p.lib_id.split(":")[-1] for p in ics[:3]]
        lines.append(f"A digital circuit centered on {', '.join(ic_names)}")
    else:
        lines.append(f"A circuit with {len(parts)} component(s)")

    lines.append(f" and {len(nets)} net(s).")

    # Add specific part details.
    part_summary = []
    if resistors:
        values = [r.value for r in resistors if r.value]
        if values:
            part_summary.append(f"resistors: {', '.join(values[:5])}")
    if opamps:
        part_summary.append(f"opamps: {', '.join(o.value or 'unknown' for o in opamps[:3])}")

    if part_summary:
        lines.append(f" Key parts: {'; '.join(part_summary)}.")

    return "".join(lines)


def create_training_example(
    circuit_ir: CircuitIR,
    representation: str = "L1",
) -> TrainingExample:
    """Create a single NL→SKIDL training example.

    Args:
        circuit_ir: The circuit IR from build_circuit().
        representation: "L1" (pin-level) or "L2" (component-level).

    Returns:
        TrainingExample ready for SFT.
    """
    nl_description = generate_nl_description(circuit_ir)
    skidl_code = emit_build_py(circuit_ir, mode=representation)

    # Format as NL prompt → SKIDL code response.
    user_msg = (
        f"Design a circuit: {nl_description}\n\n"
        f"Generate SKIDL Python code that implements this circuit."
    )

    return TrainingExample(
        user_message=user_msg,
        assistant_message=skidl_code,
        task_type="nl_to_skidl",
        source_file=circuit_ir.source_file,
        part_count=len(circuit_ir.parts),
        net_count=len(circuit_ir.nets),
    )


def convert_schematic_to_training_data(
    sch_path: Path | str,
    output_path: Path | str,
    representation: str = "L1",
) -> int:
    """Convert a single .kicad_sch to a training data JSONL.

    Args:
        sch_path: Path to .kicad_sch file.
        output_path: Output JSONL file path.
        representation: "L1" or "L2".

    Returns:
        1 on success, 0 on failure.
    """
    from kicad_agent.circuit_ir import build_circuit

    try:
        circuit, circuit_ir = build_circuit(sch_path)
        example = create_training_example(circuit_ir, representation)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(example.to_chatml()) + "\n")

        logger.info("Converted %s: %d parts → training example", sch_path, len(circuit_ir.parts))
        return 1
    except Exception as e:
        logger.warning("Failed to convert %s: %s", sch_path, e)
        return 0


def batch_convert_schematics(
    sch_paths: list[Path | str],
    output_path: Path | str,
    representation: str = "L1",
) -> tuple[int, int]:
    """Convert multiple schematics to training data.

    Args:
        sch_paths: List of .kicad_sch paths.
        output_path: Output JSONL file path.
        representation: "L1" or "L2".

    Returns:
        Tuple of (success_count, failure_count).
    """
    # Clear the output file.
    Path(output_path).write_text("", encoding="utf-8")

    success = 0
    failure = 0

    for sch_path in sch_paths:
        if convert_schematic_to_training_data(sch_path, output_path, representation):
            success += 1
        else:
            failure += 1

    logger.info("Batch conversion: %d success, %d failure → %s", success, failure, output_path)
    return success, failure
