"""Phase 158: ngspice simulation runner.

Headless subprocess wrapper for ngspice 45.2. Takes a .cir netlist,
runs the simulation, and returns structured results.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

from kicad_agent.spice.types import AnalysisResult, AnalysisType, SimulationResult, Trace

logger = logging.getLogger(__name__)

_NGSPICE_TIMEOUT = 120  # seconds


def run_simulation(
    cir_content: str,
    circuit_name: str = "circuit",
    analyses: list[str] | None = None,
) -> SimulationResult:
    """Run an ngspice simulation from a .cir netlist.

    Args:
        cir_content: SPICE netlist content (the .cir file body).
        circuit_name: Name for the circuit (used in results).
        analyses: List of analysis types to run (e.g. ["ac", "tran"]).

    Returns:
        SimulationResult with traces and derived metrics.
    """
    analyses = analyses or ["ac"]

    # Write the .cir to a temp file.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cir", delete=False
    ) as cir_file:
        cir_file.write(cir_content)
        cir_path = Path(cir_file.name)

    raw_path = cir_path.with_suffix(".raw")
    log_path = cir_path.with_suffix(".log")

    t0 = time.time()
    log_output = ""

    try:
        # Run ngspice in batch mode.
        cmd = ["ngspice", "-b", "-o", str(log_path), str(cir_path)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_NGSPICE_TIMEOUT,
        )
        log_output = result.stdout + result.stderr
        # Also read the ngspice log file (measurement output goes there).
        if log_path.exists():
            log_output += "\n" + log_path.read_text(encoding="utf-8", errors="ignore")
        elapsed = time.time() - t0

        if result.returncode != 0:
            logger.warning("ngspice exited %d for %s", result.returncode, circuit_name)

        # Parse results. If ngspice exited non-zero, mark analyses as failed.
        analysis_results: list[AnalysisResult] = []
        sim_failed = result.returncode != 0
        for atype_str in analyses:
            try:
                atype = AnalysisType(atype_str)
                ar = _parse_analysis(atype, log_output)
                if sim_failed:
                    ar = AnalysisResult(
                        analysis_type=atype,
                        traces=ar.traces,
                        gain_db=ar.gain_db,
                        bandwidth_hz=ar.bandwidth_hz,
                        noise_floor_v_sqrt_hz=ar.noise_floor_v_sqrt_hz,
                        thd_percent=ar.thd_percent,
                        passed=False,
                        error_message=f"ngspice exited {result.returncode}",
                    )
                analysis_results.append(ar)
            except ValueError:
                logger.debug("Unknown analysis type: %s", atype_str)

        return SimulationResult(
            circuit_name=circuit_name,
            analyses=tuple(analysis_results),
            elapsed_s=elapsed,
            ngspice_version=_extract_ngspice_version(log_output),
            log=log_output,
        )

    except subprocess.TimeoutExpired:
        return SimulationResult(
            circuit_name=circuit_name,
            analyses=(AnalysisResult(
                analysis_type=AnalysisType.OP,
                traces=(),
                passed=False,
                error_message=f"ngspice timed out after {_NGSPICE_TIMEOUT}s",
            ),),
            elapsed_s=time.time() - t0,
            log=log_output,
        )
    except FileNotFoundError:
        return SimulationResult(
            circuit_name=circuit_name,
            analyses=(AnalysisResult(
                analysis_type=AnalysisType.OP,
                traces=(),
                passed=False,
                error_message="ngspice not found on PATH",
            ),),
            elapsed_s=0.0,
        )
    finally:
        cir_path.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)


def _parse_analysis(
    atype: AnalysisType,
    log: str,
) -> AnalysisResult:
    """Parse ngspice log output for analysis-specific results."""
    if atype == AnalysisType.AC:
        return _parse_ac(log)
    elif atype == AnalysisType.TRAN:
        return _parse_tran(log)
    elif atype == AnalysisType.NOISE:
        return _parse_noise(log)
    else:
        return AnalysisResult(
            analysis_type=atype,
            traces=(),
            passed=True,
        )


def _parse_ac(log: str) -> AnalysisResult:
    """Parse AC analysis results from ngspice log.

    Handles both .MEAS format (gain_db = -1.7e-04 dB) and
    control-block meas format (gain_db = -1.714492e-04 at= ...).
    """
    import re

    gain_db = None
    # Match "gain_db = <number>" from ngspice meas output.
    gain_match = re.search(r"gain_db\s*=\s*([-\d.eE+]+)", log, re.IGNORECASE)
    if gain_match:
        try:
            gain_db = float(gain_match.group(1))
        except ValueError:
            pass
    # Fallback: older format with explicit dB unit.
    if gain_db is None:
        gain_match = re.search(r"gain.*?=\s*([-\d.]+)\s*dB", log, re.IGNORECASE)
        if gain_match:
            gain_db = float(gain_match.group(1))

    bandwidth = None
    # Match "bw_3db = <number>" from control-block meas output.
    bw_match = re.search(r"bw_3db\s*=\s*([\d.eE+-]+)", log, re.IGNORECASE)
    if bw_match:
        try:
            bandwidth = float(bw_match.group(1))
        except ValueError:
            pass
    # Fallback: older "bandwidth" format.
    if bandwidth is None:
        bw_match = re.search(r"bandwidth.*?=\s*([\d.eE+-]+)\s*Hz", log, re.IGNORECASE)
        if bw_match:
            bandwidth = float(bw_match.group(1))

    return AnalysisResult(
        analysis_type=AnalysisType.AC,
        traces=(),
        gain_db=gain_db,
        bandwidth_hz=bandwidth,
        passed="fatal error" not in log.lower(),
    )


def _parse_tran(log: str) -> AnalysisResult:
    """Parse transient analysis results."""
    return AnalysisResult(
        analysis_type=AnalysisType.TRAN,
        traces=(),
        passed="error" not in log.lower(),
    )


def _parse_noise(log: str) -> AnalysisResult:
    """Parse noise analysis results."""
    import re

    noise_floor = None
    noise_match = re.search(
        r"onoise.*?=\s*([\d.eE+-]+)", log, re.IGNORECASE
    )
    if noise_match:
        noise_floor = float(noise_match.group(1))

    return AnalysisResult(
        analysis_type=AnalysisType.NOISE,
        traces=(),
        noise_floor_v_sqrt_hz=noise_floor,
        passed="error" not in log.lower(),
    )


def _extract_ngspice_version(log: str) -> str:
    """Extract ngspice version from log output."""
    import re
    match = re.search(r"ngspice[-\s]*(\d+(?:\.\d+)*)", log)
    return match.group(0) if match else ""
