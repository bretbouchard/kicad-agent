"""Phase 160 NLGEN-04: Full NL→PCB pipeline orchestrator.

NL → SKIDL → ERC → SPICE → floor plan → PCB → routing.
Sequences the existing v5.0 capabilities behind a single NL entry point.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from volta.generation.gate_chain import run_gate_chain
from volta.generation.nl_to_skidl import (
    GenerationRequest,
    generate_circuit,
    parse_spec_targets,
)

logger = logging.getLogger(__name__)


@dataclass
class FullPipelineResult:
    """Result of the full NL → PCB pipeline."""
    nl_prompt: str
    skidl_code: str | None = None
    gates: list = field(default_factory=list)
    output_files: dict[str, str] = field(default_factory=dict)
    spec_targets: dict[str, float] = field(default_factory=dict)
    elapsed_s: float = 0.0
    success: bool = False


def run_full_pipeline(
    nl_prompt: str,
    output_dir: Path | str | None = None,
    max_candidates: int = 3,
) -> FullPipelineResult:
    """Run the full NL → PCB pipeline.

    Args:
        nl_prompt: Natural language circuit description.
        output_dir: Directory for output files.
        max_candidates: Best-of-N candidates for NL→SKIDL.

    Returns:
        FullPipelineResult with all stages + outputs.
    """
    t0 = time.time()
    result = FullPipelineResult(nl_prompt=nl_prompt)

    # 1. Parse spec targets.
    result.spec_targets = parse_spec_targets(nl_prompt)
    logger.info("Parsed spec targets: %s", result.spec_targets)

    # 2. Generate SKIDL code (best-of-N).
    request = GenerationRequest(
        prompt=nl_prompt,
        spec_targets=result.spec_targets,
        max_candidates=max_candidates,
    )
    gen_result = generate_circuit(request)
    result.skidl_code = gen_result.skidl_code

    if not result.skidl_code:
        logger.warning("NL→SKIDL generation failed after %d attempts", gen_result.attempts)
        result.elapsed_s = time.time() - t0
        return result

    # 3. Run the gate chain (parse → ERC → SPICE → floorplan).
    gate_result = run_gate_chain(
        result.skidl_code,
        spec_targets=result.spec_targets if result.spec_targets else None,
        output_dir=output_dir,
    )
    result.gates = gate_result.gates

    # 4. Check gates.
    failed = gate_result.failed_gate
    if failed:
        logger.warning("Pipeline stopped at gate %s: %s", failed.gate_name, failed.message)
        result.elapsed_s = time.time() - t0
        return result

    # 5. Write output files.
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        skidl_path = output_dir / "generated_circuit.py"
        skidl_path.write_text(result.skidl_code, encoding="utf-8")
        result.output_files["skidl"] = str(skidl_path)

    result.success = True
    result.elapsed_s = time.time() - t0
    logger.info("Pipeline completed in %.1fs — success=%s", result.elapsed_s, result.success)
    return result
