"""Phase 158: ngspice simulation runner.

Headless subprocess wrapper for ngspice 45.2. Takes a .cir netlist,
runs the simulation, and returns structured results.

volta-obp fix: AC analysis parses .raw binary file via spicelib.RawRead
(was: regex against ngspice log). Populates AnalysisResult.traces with real
complex-valued v(in), v(out), etc. and computes gain_db/bandwidth_hz from
actual data. Regex retained as fallback for ngspice versions where -r flag
fails.
"""
from __future__ import annotations

import logging
import math
import subprocess
import tempfile
import time
from pathlib import Path

from volta.spice.types import AnalysisResult, AnalysisType, SimulationResult, Trace

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
        # Run ngspice in batch mode with explicit -r to dump .raw binary.
        # volta-obp: previously omitted -r, so .raw only existed when
        # the .cir file had a .print/.write statement. Now we ALWAYS dump
        # the raw to a known path so spicelib.RawRead can parse it.
        cmd = ["ngspice", "-b", "-r", str(raw_path), "-o", str(log_path), str(cir_path)]
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
                ar = _parse_analysis(atype, log_output, raw_path)
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
    raw_path: Path | None = None,
) -> AnalysisResult:
    """Parse ngspice log + .raw file for analysis-specific results.

    volta-obp: AC analysis now prefers .raw binary parse via
    spicelib.RawRead over regex against ngspice log. Falls back to regex
    if .raw file is missing (e.g., older ngspice without -r flag support
    or when ngspice errored before writing .raw).
    """
    if atype == AnalysisType.AC:
        return _parse_ac(log, raw_path)
    elif atype == AnalysisType.TRAN:
        return _parse_tran(log, raw_path)
    elif atype == AnalysisType.NOISE:
        return _parse_noise(log)
    else:
        return AnalysisResult(
            analysis_type=atype,
            traces=(),
            passed=True,
        )


def _build_traces_from_raw(raw) -> tuple[Trace, ...]:
    """Convert spicelib.RawRead output to Phase 158 Trace tuples.

    RawRead returns complex-valued v(in), v(out), etc. for AC analysis.
    For each voltage/current trace, we emit TWO Trace objects:
      - "{name}_mag_db" — magnitude in dB (real-valued)
      - "{name}_phase_deg" — phase in degrees (real-valued)
    Frequency axis is the shared scale.
    """
    import numpy as np

    traces: list[Trace] = []
    freq_axis = None

    for name in raw.get_trace_names():
        wave = raw.get_wave(name)
        arr = np.asarray(wave)

        # Detect frequency axis (ngspice AC mode: real part is freq, imag is junk).
        if name.lower() in ("frequency", "time") and freq_axis is None:
            freq_axis = arr.real
            continue

        # For complex traces, split into magnitude (dB) + phase (deg).
        if arr.dtype == complex or arr.dtype == complex128:
            mag = np.abs(arr)
            phase_deg = np.degrees(np.angle(arr))
            # Guard against log10(0) on the magnitude.
            mag_safe = np.where(mag > 0, mag, 1e-30)
            mag_db = 20.0 * np.log10(mag_safe)
            traces.append(Trace(
                name=f"{name}_mag_db",
                values=tuple(float(v) for v in mag_db),
                scale=tuple(float(v) for v in (freq_axis if freq_axis is not None else range(len(mag_db)))),
            ))
            traces.append(Trace(
                name=f"{name}_phase_deg",
                values=tuple(float(v) for v in phase_deg),
                scale=tuple(float(v) for v in (freq_axis if freq_axis is not None else range(len(phase_deg)))),
            ))
        else:
            # Real-valued trace (DC operating point, real-valued measurement).
            traces.append(Trace(
                name=name,
                values=tuple(float(v) for v in arr),
                scale=tuple(float(v) for v in (freq_axis if freq_axis is not None else range(len(arr)))),
            ))

    return tuple(traces)


def _compute_gain_and_bandwidth(traces: tuple[Trace, ...], input_node: str = "in", output_node: str = "out") -> tuple[float | None, float | None]:
    """Compute gain_db (peak) and bandwidth_hz (high-freq -3dB from peak) from traces.

    Looks for v(in)_mag_db and v(out)_mag_db. gain = v(out) - v(in) in dB.
    Falls back to v(out)_mag_db alone if v(in) absent (assumes 1V stimulus).

    Bandwidth is the HIGH-frequency -3dB point — i.e., the first frequency
    AFTER the peak where gain drops below (peak - 3dB). For amplifiers with
    coupling caps, gain rises from low freq (cap blocks) → peaks mid-band →
    rolls off at high freq (transistor fT). The "bandwidth" is the upper
    edge of the passband, not the low-freq pole.
    """
    import numpy as np

    out_mag = next((t for t in traces if t.name == f"v({output_node})_mag_db"), None)
    if out_mag is None:
        return None, None

    in_mag = next((t for t in traces if t.name == f"v({input_node})_mag_db"), None)

    out_arr = np.asarray(out_mag.values)
    if in_mag is not None:
        in_arr = np.asarray(in_mag.values)
        gain_arr = out_arr - in_arr  # dB subtraction = ratio
    else:
        gain_arr = out_arr

    gain_db = float(np.max(gain_arr))
    peak_idx = int(np.argmax(gain_arr))

    # Bandwidth: scan FORWARD from peak to find high-freq -3dB roll-off.
    freq = np.asarray(out_mag.scale, dtype=float)
    threshold = gain_db - 3.0
    for i in range(peak_idx, len(gain_arr)):
        if gain_arr[i] <= threshold and freq[i] > freq[peak_idx]:
            bandwidth_hz = float(freq[i])
            break
    else:
        bandwidth_hz = None

    return gain_db, bandwidth_hz


def _extract_op_traces(raw) -> tuple[Trace, ...]:
    """Extract Operating Point plot data from a multi-plot .raw file.

    volta-8vv: ngspice testbench (per generate_ac_testbench
    include_op=True) produces TWO plots: 'AC Analysis' + 'Operating Point'.
    The OP plot contains single-value v(node) and i(vsource) entries —
    the DC bias point computed before AC linearization.

    Returns Trace tuple like:
        (Trace(name='op:v(collector)', values=(4.41,), scale=(0,)),
         Trace(name='op:i(vcc)_ma', values=(1.77,), scale=(0,)), ...)
    where currents are negated + scaled to mA (VCC/VEE sources flow OUT
    of the supply INTO the circuit, so i(vcc) < 0 means positive Ic).
    """
    op_traces: list[Trace] = []
    for plot in getattr(raw, "plots", []):
        # PlotData exposes get_plot_name() + get_trace_names() + get_trace(name).
        plot_name = ""
        if hasattr(plot, "get_plot_name"):
            try:
                plot_name = plot.get_plot_name() or ""
            except Exception:
                plot_name = ""
        if "operating point" not in plot_name.lower():
            continue

        trace_names = []
        if hasattr(plot, "get_trace_names"):
            try:
                trace_names = list(plot.get_trace_names())
            except Exception:
                trace_names = []

        for trace_name in trace_names:
            if trace_name.lower() in ("frequency", "time"):
                continue
            try:
                trace_obj = plot.get_trace(trace_name)
                wave = trace_obj.get_wave() if hasattr(trace_obj, "get_wave") else trace_obj
                # OP plot has single-value traces.
                arr_val = float(wave[0]) if hasattr(wave, "__getitem__") else float(wave)
            except (TypeError, ValueError, IndexError, AttributeError):
                continue

            # Convert currents from VCC/VEE sources to mA (positive = into circuit).
            if trace_name.lower().startswith("i("):
                arr_val_ma = -arr_val * 1000.0  # negate + scale to mA
                op_traces.append(Trace(
                    name=f"op:{trace_name}_ma",
                    values=(arr_val_ma,),
                    scale=(0.0,),
                ))
            else:
                op_traces.append(Trace(
                    name=f"op:{trace_name}",
                    values=(arr_val,),
                    scale=(0.0,),
                ))
        break
    return tuple(op_traces)


def _parse_ac(log: str, raw_path: Path | None = None) -> AnalysisResult:
    """Parse AC analysis results — prefer .raw, fall back to regex.

    volta-obp: was regex-only against ngspice log. Now uses
    spicelib.RawRead when raw_path exists, populating AnalysisResult.traces
    with real v(in)/v(out) magnitude and phase data. gain_db + bandwidth_hz
    computed from actual data, not regex-matched text.

    volta-8vv: when generate_ac_testbench was called with
    include_op=True (the default), the .raw contains a second 'Operating
    Point' plot. _extract_op_traces pulls those single-value entries
    (op:v(collector), op:i(vcc)_ma, etc.) and appends them to AC traces.
    The optimizer looks up op:i(vcc)_ma by name to get the measured
    collector current, replacing the (12-0.2)/R1 heuristic.
    """
    import re

    # Try .raw parse first (volta-obp fix).
    traces: tuple[Trace, ...] = ()
    gain_db: float | None = None
    bandwidth_hz: float | None = None

    if raw_path is not None and raw_path.exists():
        try:
            from spicelib import RawRead
            raw = RawRead(str(raw_path), verbose=False)
            ac_traces = _build_traces_from_raw(raw)
            op_traces = _extract_op_traces(raw)
            traces = ac_traces + op_traces
            gain_db, bandwidth_hz = _compute_gain_and_bandwidth(ac_traces)
        except Exception as exc:
            logger.debug("RawRead failed (%s) — falling back to regex", exc)

    # Regex fallback if .raw parsing didn't yield metrics.
    if gain_db is None:
        gain_match = re.search(r"gain_db\s*=\s*([-\d.eE+]+)", log, re.IGNORECASE)
        if gain_match:
            try:
                gain_db = float(gain_match.group(1))
            except ValueError:
                pass
        if gain_db is None:
            gain_match = re.search(r"gain.*?=\s*([-\d.]+)\s*dB", log, re.IGNORECASE)
            if gain_match:
                gain_db = float(gain_match.group(1))

    if bandwidth_hz is None:
        bw_match = re.search(r"bw_3db\s*=\s*([\d.eE+-]+)", log, re.IGNORECASE)
        if bw_match:
            try:
                bandwidth_hz = float(bw_match.group(1))
            except ValueError:
                pass
        if bandwidth_hz is None:
            bw_match = re.search(r"bandwidth.*?=\s*([\d.eE+-]+)\s*Hz", log, re.IGNORECASE)
            if bw_match:
                bandwidth_hz = float(bw_match.group(1))

    return AnalysisResult(
        analysis_type=AnalysisType.AC,
        traces=traces,
        gain_db=gain_db,
        bandwidth_hz=bandwidth_hz,
        passed="fatal error" not in log.lower(),
    )


def _parse_tran(log: str, raw_path: Path | None = None) -> AnalysisResult:
    """Parse transient analysis results.

    volta-obp: now also parses .raw if present to populate traces
    (was: empty traces). Real-valued time-domain traces use the time axis.
    """
    traces: tuple[Trace, ...] = ()
    if raw_path is not None and raw_path.exists():
        try:
            from spicelib import RawRead
            raw = RawRead(str(raw_path), verbose=False)
            traces = _build_traces_from_raw(raw)
        except Exception as exc:
            logger.debug("TRAN RawRead failed (%s)", exc)

    return AnalysisResult(
        analysis_type=AnalysisType.TRAN,
        traces=traces,
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
