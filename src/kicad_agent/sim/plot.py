"""Phase 204: matplotlib Bode plot for SPICE SimulationResult.

Two cases:
  1. AC has v(out)_mag_db + v(out)_phase_deg traces (post-obp fix): real
     Bode plot with magnitude + phase subplots sharing the frequency axis.
  2. AC has empty traces (pre-obp fallback): scalar-marker fallback
     (horizontal gain line, vertical bandwidth line).

kicad-agent-qss fix: phase subplot now plots real vp(out) data extracted
by spicelib.RawRead (was: honest "Phase data not available" stub). The
obp fix populates v(out)_phase_deg as a Trace; this module just renders it.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — no display required
import matplotlib.pyplot as plt
import numpy as np

from kicad_agent.spice import AnalysisType, SimulationResult


def plot_bode(
    result: SimulationResult,
    save_path: str | Path = "bode.png",
    *,
    title: str = "Eurorack Preamp",
    output_node: str = "out",
) -> None:
    """Plot magnitude + phase Bode, save PNG.

    Args:
        result: Phase 158 SimulationResult with an AC analysis.
        save_path: Output PNG path. Parent dirs are auto-created.
        title: Plot title prefix.
        output_node: Net name to plot (default "out"). Looks up
            v({output_node})_mag_db and v({output_node})_phase_deg traces.
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    ac = result.get_analysis(AnalysisType.AC)
    gain_db = ac.gain_db if ac and ac.gain_db is not None else 0.0
    bw_hz = ac.bandwidth_hz if ac and ac.bandwidth_hz is not None else 0.0

    # Find the output node's magnitude + phase traces by name.
    # obp fix emits "{name}_mag_db" + "{name}_phase_deg" pairs per net.
    mag_trace = None
    phase_trace = None
    if ac is not None:
        mag_name = f"v({output_node})_mag_db"
        phase_name = f"v({output_node})_phase_deg"
        mag_trace = next((t for t in ac.traces if t.name == mag_name), None)
        phase_trace = next((t for t in ac.traces if t.name == phase_name), None)

    if ac is None or mag_trace is None:
        # Scalar-marker fallback (pre-obp, or AnalysisResult with no traces)
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.axhline(gain_db, color="C0", linewidth=2, label=f"gain = {gain_db:.1f} dB")
        if bw_hz > 0:
            ax.axvline(bw_hz, color="r", linestyle="--", linewidth=1.0,
                       label=f"-3 dB @ {bw_hz:.0f} Hz")
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("Gain [dB]")
        ax.set_xscale("log")
        ax.set_title(f"{title} — gain={gain_db:.1f} dB, bw={bw_hz:.0f} Hz")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return

    # Real Bode: magnitude (dB) + phase (deg) from actual ngspice AC sim.
    freq = np.asarray(mag_trace.scale, dtype=float)
    mag = np.asarray(mag_trace.values, dtype=float)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

    # Magnitude subplot
    ax1.semilogx(freq, mag, color="C0", linewidth=1.5, label=f"v({output_node})")
    if len(mag) > 0:
        ax1.axhline(mag.max() - 3, color="r", linestyle="--", linewidth=0.8,
                    label="-3 dB")
    ax1.set_ylabel("Magnitude [dB]")
    ax1.set_title(f"{title} — gain={gain_db:.1f} dB, bw={bw_hz:.0f} Hz")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(loc="lower left")

    # Phase subplot — qss fix: real vp(out) data from RawRead (was stub).
    if phase_trace is not None:
        phase = np.asarray(phase_trace.values, dtype=float)
        ax2.semilogx(freq, phase, color="C1", linewidth=1.5)
    else:
        # Magnitude trace exists but phase doesn't — unusual but possible
        # if a future code path emits only magnitude. Honest note.
        ax2.text(0.5, 0.5,
                 f"Magnitude trace present but no v({output_node})_phase_deg\n"
                 f"trace found in AnalysisResult.traces",
                 ha='center', va='center', transform=ax2.transAxes,
                 fontsize=9, color='gray')
    ax2.set_xlabel("Frequency [Hz]")
    ax2.set_ylabel("Phase [deg]")
    ax2.grid(True, which="both", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
