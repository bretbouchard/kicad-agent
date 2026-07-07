"""Phase 204: matplotlib Bode plot for SPICE SimulationResult.

Two cases:
  1. AC has traces: magnitude subplot from vdb(out); phase subplot is an
     honest "not available" stub (WR-04 R2 — Phase 158 v1 measures vdb only,
     NOT vp(); deferred to Phase 204b).
  2. AC has empty traces (Phase 158 v1): scalar-marker fallback
     (horizontal gain line, vertical bandwidth line).
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
) -> None:
    """Plot magnitude + phase Bode, save PNG.

    Args:
        result: Phase 158 SimulationResult with an AC analysis.
        save_path: Output PNG path. Parent dirs are auto-created.
        title: Plot title prefix.
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    ac = result.get_analysis(AnalysisType.AC)
    gain_db = ac.gain_db if ac and ac.gain_db is not None else 0.0
    bw_hz = ac.bandwidth_hz if ac and ac.bandwidth_hz is not None else 0.0

    if ac is None or not ac.traces:
        # Scalar-marker fallback (Phase 158 v1 default)
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

    # Real Bode: traces[0] is vdb(out) magnitude
    freq = np.array(ac.traces[0].scale)
    mag = np.array(ac.traces[0].values)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

    # Magnitude subplot
    ax1.semilogx(freq, mag, color="C0", linewidth=1.5)
    if len(mag) > 0:
        ax1.axhline(mag.max() - 3, color="r", linestyle="--", linewidth=0.8,
                    label="-3 dB")
    ax1.set_ylabel("Magnitude [dB]")
    ax1.set_title(f"{title} — gain={gain_db:.1f} dB, bw={bw_hz:.0f} Hz")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(loc="lower left")

    # Phase subplot — WR-04 (Council R2 P2): Phase 158 v1 measures vdb()
    # (real-valued dB magnitude), NOT vp() (complex phase). np.angle() on real
    # values would return a flat 0 line — misleading. Emit an honest stub
    # instead, deferring real phase data to Phase 204b when generate_ac_testbench
    # learns to measure vp(out).
    if len(ac.traces) > 1:
        # Future: when Phase 158 v2 produces a complex vp(out) trace, restore:
        #   phase = np.angle(np.array(ac.traces[1].values), deg=True)
        # Until then, the second trace is still a vdb (real) — stub it.
        ax2.text(0.5, 0.5,
                 "Phase data not available\n"
                 "(Phase 158 v1 measures magnitude only;\n"
                 "vp() support deferred to Phase 204b)",
                 ha='center', va='center', transform=ax2.transAxes,
                 fontsize=9, color='gray')
    else:
        ax2.text(0.5, 0.5, "No phase trace",
                 ha='center', va='center', transform=ax2.transAxes,
                 fontsize=9, color='gray')
    ax2.set_xlabel("Frequency [Hz]")
    ax2.set_ylabel("Phase [deg]")
    ax2.grid(True, which="both", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
