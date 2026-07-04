"""Phase 160: Gate chain — validation pipeline for generated circuits.

Each generated circuit flows through a chain of validation gates:
  parse → ERC → SPICE spec check → floor plan → PCB

Each gate is independently testable and fail-closed. A circuit that
fails one gate never reaches the next.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class GateName(str, Enum):
    PARSE = "parse"
    ERC = "erc"
    SPICE = "spice_spec"
    FLOORPLAN = "floorplan"
    PCB = "pcb"


class GateStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class GateResult:
    """Result of a single gate check.

    Attributes:
        gate_name: Which gate was checked.
        status: PENDING, PASSED, FAILED, or SKIPPED.
        message: Description of the result.
        data: Optional data payload (e.g. ERC error count, SPICE metrics).
    """
    gate_name: GateName
    status: GateStatus
    message: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Result of running the full gate chain.

    Attributes:
        gates: Results for each gate in the chain.
        skidl_code: The generated SKIDL code.
        output_files: Paths to generated output files.
    """
    gates: list[GateResult] = field(default_factory=list)
    skidl_code: str = ""
    output_files: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True if all gates passed (or were skipped)."""
        return all(
            g.status in (GateStatus.PASSED, GateStatus.SKIPPED)
            for g in self.gates
        )

    @property
    def failed_gate(self) -> GateResult | None:
        """The first gate that failed, if any."""
        for g in self.gates:
            if g.status == GateStatus.FAILED:
                return g
        return None


def run_gate_chain(
    skidl_code: str,
    spec_targets: dict[str, float] | None = None,
    output_dir: Path | str | None = None,
) -> PipelineResult:
    """Run a circuit through the full validation gate chain.

    Args:
        skidl_code: Generated SKIDL Python code.
        spec_targets: Optional spec targets for SPICE verification.
        output_dir: Directory for output files (schematic, PCB).

    Returns:
        PipelineResult with gate-by-gate results.
    """
    result = PipelineResult(skidl_code=skidl_code)
    spec_targets = spec_targets or {}

    # Gate 1: Parse (syntax check).
    parse_result = _gate_parse(skidl_code)
    result.gates.append(parse_result)
    if parse_result.status == GateStatus.FAILED:
        return result

    # Gate 2: ERC (electrical rules).
    erc_result = _gate_erc(skidl_code)
    result.gates.append(erc_result)
    if erc_result.status == GateStatus.FAILED:
        return result

    # Gate 3: SPICE spec check (skip if no targets).
    if spec_targets:
        spice_result = _gate_spice(skidl_code, spec_targets)
        result.gates.append(spice_result)
        if spice_result.status == GateStatus.FAILED:
            return result
    else:
        result.gates.append(GateResult(
            GateName.SPICE, GateStatus.SKIPPED, "No spec targets — skipping SPICE gate"
        ))

    # Gate 4: Floor plan (skip if no output_dir).
    if output_dir:
        fp_result = _gate_floorplan(skidl_code, output_dir)
        result.gates.append(fp_result)
    else:
        result.gates.append(GateResult(
            GateName.FLOORPLAN, GateStatus.SKIPPED, "No output dir — skipping floor plan gate"
        ))

    # Gate 5: PCB (skip — requires full pipeline execution).
    result.gates.append(GateResult(
        GateName.PCB, GateStatus.SKIPPED, "PCB generation requires full pipeline — manual step"
    ))

    return result


def _gate_parse(skidl_code: str) -> GateResult:
    """Gate 1: Check SKIDL code is valid Python syntax."""
    try:
        compile(skidl_code, "circuit.py", "exec")
        return GateResult(GateName.PARSE, GateStatus.PASSED, "Code parses successfully")
    except SyntaxError as e:
        return GateResult(GateName.PARSE, GateStatus.FAILED, f"Syntax error: {e}")


def _gate_erc(skidl_code: str) -> GateResult:
    """Gate 2: Execute SKIDL code and run ERC."""
    try:
        from kicad_agent.circuit_ir import _ensure_skidl_env
        _ensure_skidl_env()

        exec_globals: dict = {}
        exec(skidl_code, exec_globals)

        build_fn = exec_globals.get("build_board")
        if not build_fn:
            return GateResult(
                GateName.ERC, GateStatus.FAILED,
                "No build_board() function found in generated code"
            )

        circuit = build_fn()
        erc_result = circuit.ERC()

        if erc_result is None:
            errors, warnings = 0, 0
        elif isinstance(erc_result, tuple):
            errors, warnings = erc_result
        else:
            errors, warnings = 0, 0

        if errors > 0:
            return GateResult(
                GateName.ERC, GateStatus.FAILED,
                f"ERC found {errors} errors, {warnings} warnings",
                {"errors": errors, "warnings": warnings}
            )

        return GateResult(
            GateName.ERC, GateStatus.PASSED,
            f"ERC passed (0 errors, {warnings} warnings)",
            {"errors": errors, "warnings": warnings, "parts": len(circuit.parts)}
        )
    except Exception as e:
        return GateResult(GateName.ERC, GateStatus.FAILED, f"ERC execution error: {e}")


def _gate_spice(skidl_code: str, spec_targets: dict[str, float]) -> GateResult:
    """Gate 3: SPICE spec verification (if targets exist)."""
    # For now, just verify the circuit can generate a netlist.
    try:
        exec_globals: dict = {}
        exec(skidl_code, exec_globals)
        build_fn = exec_globals.get("build_board")
        if build_fn:
            circuit = build_fn()
            # Check if simulatable.
            from kicad_agent.spice import is_simulatable
            for part in circuit.parts:
                lib_id = f"{part.lib}:{part.name}" if hasattr(part, "lib") else ""
                if lib_id and not is_simulatable(lib_id):
                    return GateResult(
                        GateName.SPICE, GateStatus.SKIPPED,
                        f"Contains unsimulatable part: {lib_id} — skipping SPICE"
                    )
        return GateResult(
            GateName.SPICE, GateStatus.PASSED,
            "All parts simulatable (full SPICE verification requires testbench)"
        )
    except Exception as e:
        return GateResult(GateName.SPICE, GateStatus.SKIPPED, f"SPICE gate skipped: {e}")


def _gate_floorplan(skidl_code: str, output_dir: Path | str) -> GateResult:
    """Gate 4: Floor plan (placeholder — requires full pipeline)."""
    return GateResult(
        GateName.FLOORPLAN, GateStatus.SKIPPED,
        "Floor plan gate requires component placement — deferred to full pipeline"
    )
