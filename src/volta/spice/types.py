"""Phase 158: SPICE pipeline types.

Immutable dataclasses for simulation results, modeled on ltspice/types.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnalysisType(str, Enum):
    AC = "ac"
    TRAN = "tran"
    NOISE = "noise"
    DISTO = "disto"  # THD via distortion analysis
    DC = "dc"
    OP = "op"


@dataclass(frozen=True)
class Trace:
    """A single simulation trace (e.g. voltage at a node over frequency)."""
    name: str
    values: tuple[float, ...]
    scale: tuple[float, ...]  # x-axis (frequency, time, etc.)


@dataclass(frozen=True)
class AnalysisResult:
    """Result of a single analysis type.

    Attributes:
        analysis_type: AC, TRAN, NOISE, etc.
        traces: Named traces from the simulation.
        gain_db: AC gain in dB (for AC analysis, None otherwise).
        bandwidth_hz: -3dB bandwidth (for AC analysis).
        phase_margin_deg: Phase margin (for AC analysis).
        noise_floor_v_sqrt_hz: Input-referred noise (for NOISE).
        thd_percent: Total harmonic distortion (for DISTO).
        passed: True if the simulation completed without errors.
        error_message: Error description if not passed.
    """
    analysis_type: AnalysisType
    traces: tuple[Trace, ...]
    gain_db: float | None = None
    bandwidth_hz: float | None = None
    phase_margin_deg: float | None = None
    noise_floor_v_sqrt_hz: float | None = None
    thd_percent: float | None = None
    passed: bool = True
    error_message: str = ""


@dataclass(frozen=True)
class SimulationResult:
    """Complete simulation result from a testbench run.

    Attributes:
        circuit_name: Name of the simulated circuit.
        analyses: Tuple of AnalysisResults (one per analysis type run).
        elapsed_s: Wall-clock time for the simulation.
        ngspice_version: Version string of ngspice used.
        log: Raw ngspice log output.
    """
    circuit_name: str
    analyses: tuple[AnalysisResult, ...]
    elapsed_s: float = 0.0
    ngspice_version: str = ""
    log: str = ""

    @property
    def passed(self) -> bool:
        """True if all analyses passed."""
        return all(a.passed for a in self.analyses)

    def get_analysis(self, atype: AnalysisType) -> AnalysisResult | None:
        """Get a specific analysis result by type."""
        for a in self.analyses:
            if a.analysis_type == atype:
                return a
        return None


@dataclass(frozen=True)
class DegradationReport:
    """Pre-route vs post-route SPICE degradation (Phase 159 reward signal).

    Attributes:
        gain_delta_db: Gain change in dB (negative = degradation).
        bandwidth_delta_pct: Bandwidth change as percentage.
        noise_delta_db: Noise floor change in dB.
        thd_delta_pct: THD change in percentage points.
        sim_score: Overall simulation quality score (0.0-1.0, 1.0=perfect).
    """
    gain_delta_db: float = 0.0
    bandwidth_delta_pct: float = 0.0
    noise_delta_db: float = 0.0
    thd_delta_pct: float = 0.0
    sim_score: float = 1.0
