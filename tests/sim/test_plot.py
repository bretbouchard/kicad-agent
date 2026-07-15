"""Phase 204: Bode plot PNG generation."""
from __future__ import annotations

import os
import tempfile

from volta.spice import AnalysisResult, AnalysisType, SimulationResult, Trace
from volta.sim.plot import plot_bode


def _result_with_trace() -> SimulationResult:
    # Simulate a typical AC trace: 3 dB points across 100Hz..100kHz
    trace = Trace(
        name="vdb(out)",
        values=(0.0, 20.0, 17.0),  # DC, peak, -3 dB point
        scale=(100.0, 1000.0, 100_000.0),
    )
    ac = AnalysisResult(
        analysis_type=AnalysisType.AC,
        traces=(trace,),
        gain_db=20.0,
        bandwidth_hz=100_000.0,
    )
    return SimulationResult(circuit_name="test", analyses=(ac,))


def _result_without_traces() -> SimulationResult:
    ac = AnalysisResult(
        analysis_type=AnalysisType.AC,
        traces=(),
        gain_db=20.0,
        bandwidth_hz=100_000.0,
    )
    return SimulationResult(circuit_name="test", analyses=(ac,))


def test_plot_bode_writes_png_with_traces() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bode.png")
        plot_bode(_result_with_trace(), save_path=path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 10_000, "PNG too small — plot failed"


def test_plot_bode_handles_empty_traces() -> None:
    """Phase 158 v1 default: empty traces, scalar gain_db/bandwidth_hz only."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bode_scalar.png")
        plot_bode(_result_without_traces(), save_path=path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 5_000


def test_plot_bode_uses_save_path_argument() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        custom = os.path.join(tmp, "subdir", "custom.png")
        os.makedirs(os.path.dirname(custom))
        plot_bode(_result_with_trace(), save_path=custom)
        assert os.path.exists(custom)
