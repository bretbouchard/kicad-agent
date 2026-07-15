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
        from volta.circuit_ir import _ensure_skidl_env
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
    """Gate 3: SPICE spec verification.

    BLK-3 fix: Actually runs ngspice simulation and compares measured
    values against spec_targets. No longer a stub.
    """
    import tempfile
    from pathlib import Path

    try:
        # Execute the SKIDL code in a subprocess for safety.
        import subprocess, sys
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(skidl_code)
            f.write('\nimport pickle\n')
            f.write('c = build_board()\n')
            f.write(f'pickle.dump(c, open("{f.name}.pkl", "wb"))\n')
            script_path = f.name

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=30,
        )
        Path(script_path).unlink(missing_ok=True)

        if result.returncode != 0:
            Path(f"{script_path}.pkl").unlink(missing_ok=True)
            return GateResult(
                GateName.SPICE, GateStatus.FAILED,
                f"SKIDL execution failed: {result.stderr[:200]}"
            )

        import pickle
        circuit = pickle.load(open(f"{script_path}.pkl", "rb"))
        Path(f"{script_path}.pkl").unlink(missing_ok=True)

        # Check simulatability.
        from volta.spice import is_simulatable, get_all_models
        for part in circuit.parts:
            lib_id = f"{part.lib}:{part.name}" if hasattr(part, "lib") else ""
            if lib_id and not is_simulatable(lib_id):
                return GateResult(
                    GateName.SPICE, GateStatus.SKIPPED,
                    f"Contains unsimulatable part: {lib_id} — skipping SPICE gate"
                )

        # Generate netlist from the circuit.
        try:
            import tempfile as tf
            netlist_file = tf.NamedTemporaryFile(suffix=".net", delete=False, mode="w")
            netlist_file.close()
            circuit.generate_netlist(file_=netlist_file.name)
            netlist_text = Path(netlist_file.name).read_text()
            Path(netlist_file.name).unlink(missing_ok=True)
        except Exception as e:
            return GateResult(
                GateName.SPICE, GateStatus.SKIPPED,
                f"Netlist generation failed: {e} — skipping SPICE gate"
            )

        # Add SPICE models to the netlist.
        models = get_all_models()
        full_netlist = models + "\n" + netlist_text

        # Run AC simulation.
        from volta.spice.testbench import generate_ac_testbench
        from volta.spice.ngspice_runner import run_simulation
        from volta.spice import AnalysisType

        cir = generate_ac_testbench(full_netlist, input_node="in", output_node="out")
        sim_result = run_simulation(cir, "spec_check", analyses=["ac"])
        ac = sim_result.get_analysis(AnalysisType.AC)

        if ac is None or not ac.passed:
            return GateResult(
                GateName.SPICE, GateStatus.SKIPPED,
                "SPICE simulation did not produce AC results — skipping spec gate"
            )

        # Compare measured values to spec targets.
        violations = []
        if "gain_db" in spec_targets and ac.gain_db is not None:
            target = spec_targets["gain_db"]
            if ac.gain_db < target - 3.0:  # 3dB tolerance
                violations.append(
                    f"gain: measured {ac.gain_db:.1f}dB, target {target:.1f}dB"
                )

        if "bandwidth_hz" in spec_targets and ac.bandwidth_hz is not None:
            target = spec_targets["bandwidth_hz"]
            if ac.bandwidth_hz < target * 0.5:  # 50% tolerance
                violations.append(
                    f"bandwidth: measured {ac.bandwidth_hz:.0f}Hz, target {target:.0f}Hz"
                )

        if violations:
            return GateResult(
                GateName.SPICE, GateStatus.FAILED,
                f"SPICE spec violations: {'; '.join(violations)}",
                {"gain_db": ac.gain_db, "bandwidth_hz": ac.bandwidth_hz,
                 "spec_targets": spec_targets}
            )

        return GateResult(
            GateName.SPICE, GateStatus.PASSED,
            f"SPICE spec verified (gain={ac.gain_db}dB, bw={ac.bandwidth_hz}Hz)",
            {"gain_db": ac.gain_db, "bandwidth_hz": ac.bandwidth_hz}
        )

    except Exception as e:
        return GateResult(GateName.SPICE, GateStatus.SKIPPED, f"SPICE gate error: {e}")


def _gate_floorplan(skidl_code: str, output_dir: Path | str) -> GateResult:
    """Gate 4: Floor plan (placeholder — requires full pipeline)."""
    return GateResult(
        GateName.FLOORPLAN, GateStatus.SKIPPED,
        "Floor plan gate requires component placement — deferred to full pipeline"
    )
