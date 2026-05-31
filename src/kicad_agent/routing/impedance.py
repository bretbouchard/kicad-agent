"""IPC-2141 impedance calculator for controlled-impedance trace routing.

Provides microstrip and symmetric stripline impedance formulas from the
IPC-2141 standard, along with a bisection solver that finds the trace
width needed to hit a target characteristic impedance.

All dimensions in millimeters. Results are immutable ImpedanceResult
frozen dataclasses.

Usage:
    from kicad_agent.routing.impedance import (
        microstrip_z0,
        stripline_z0,
        solve_trace_width,
        ImpedanceResult,
    )

    z0 = microstrip_z0(w=0.47, h=0.2, t=0.035, er=4.5)
    result = solve_trace_width(target_z0=50.0, h=0.2, t=0.035, er=4.5)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ImpedanceResult:
    """Immutable result of a trace-width impedance solve.

    Attributes:
        trace_width_mm: Computed trace width in mm.
        target_z0: Target characteristic impedance in ohms.
        achieved_z0: Impedance at the computed trace width in ohms.
        impedance_error_percent: |achieved - target| / target * 100.
        model: Transmission line model used ("microstrip" or "stripline").
        valid: True if impedance_error_percent <= tolerance_percent.
    """

    trace_width_mm: float
    target_z0: float
    achieved_z0: float
    impedance_error_percent: float
    model: str
    valid: bool


def microstrip_z0(w: float, h: float, t: float, er: float) -> float:
    """Compute characteristic impedance of a surface microstrip (IPC-2141).

    Uses the effective dielectric constant formula and the impedance
    equation from IPC-2141 for a surface microstrip trace.

    Args:
        w: Trace width in mm.
        h: Dielectric height (substrate thickness) in mm.
        t: Copper trace thickness in mm.
        er: Relative dielectric constant of the substrate.

    Returns:
        Characteristic impedance in ohms.
    """
    eff_er = ((er + 1) / 2
              + (er - 1) / 2 * math.pow(1 + 12 * h / w, -0.5))
    log_arg = 5.98 * h / (0.8 * w + t)
    if log_arg <= 0:
        raise ValueError(
            f"Microstrip formula invalid: 5.98*h/(0.8*w+t) = {log_arg:.4f} <= 0. "
            f"w={w}, h={h}, t={t} are outside IPC-2141 valid range."
        )
    z0 = (87 / math.sqrt(eff_er)
          * math.log(log_arg))
    return z0


def stripline_z0(w: float, h: float, t: float, er: float) -> float:
    """Compute characteristic impedance of a symmetric stripline (IPC-2141).

    Uses the IPC-2141 formula for a trace centered between two ground
    planes with dielectric material above and below.

    Args:
        w: Trace width in mm.
        h: Distance from trace center to each ground plane in mm.
        t: Copper trace thickness in mm.
        er: Relative dielectric constant of the substrate.

    Returns:
        Characteristic impedance in ohms.
    """
    z0 = (60 / math.sqrt(er)
          * math.log(1.9 * (2 * h + t) / (0.8 * w + t)))
    return z0


def solve_trace_width(
    target_z0: float,
    h: float,
    t: float,
    er: float,
    model: str = "microstrip",
    tolerance_percent: float = 1.0,
    min_width: float = 0.1,
    max_width: float = 2.0,
) -> ImpedanceResult:
    """Find trace width for a target impedance via bisection.

    Iteratively bisects the [min_width, max_width] interval to find a
    trace width whose impedance is within tolerance_percent of the
    target. Up to 50 iterations guarantee convergence well within 1%
    for standard PCB stackups.

    Args:
        target_z0: Target characteristic impedance in ohms.
        h: Dielectric height in mm.
        t: Copper thickness in mm.
        er: Relative dielectric constant.
        model: "microstrip" or "stripline". Defaults to "microstrip".
        tolerance_percent: Acceptable error as percentage of target.
            Defaults to 1.0%.
        min_width: Minimum manufacturable trace width in mm.
            Defaults to 0.1mm.
        max_width: Maximum trace width in mm. Defaults to 2.0mm.

    Returns:
        ImpedanceResult with computed width and validity flag.

    Raises:
        ValueError: If any parameter is out of valid range.
    """
    # Input validation (per threat model T-36-04).
    if target_z0 <= 0:
        raise ValueError(f"target_z0 must be > 0, got {target_z0}")
    if h <= 0:
        raise ValueError(f"h must be > 0, got {h}")
    if t <= 0:
        raise ValueError(f"t must be > 0, got {t}")
    if er <= 0:
        raise ValueError(f"er must be > 0, got {er}")
    if model not in ("microstrip", "stripline"):
        raise ValueError(
            f"model must be 'microstrip' or 'stripline', got '{model}'"
        )
    if tolerance_percent <= 0:
        raise ValueError(
            f"tolerance_percent must be > 0, got {tolerance_percent}"
        )
    if min_width <= 0:
        raise ValueError(f"min_width must be > 0, got {min_width}")
    if max_width <= min_width:
        raise ValueError(
            f"max_width must be > min_width, "
            f"got max_width={max_width}, min_width={min_width}"
        )

    z0_fn = microstrip_z0 if model == "microstrip" else stripline_z0

    lo = min_width
    hi = max_width

    # Bisection: impedance decreases with width, so z0(lo) > z0(hi).
    # We want z0(w) = target_z0.
    for _ in range(50):  # Hard iteration limit (per threat model T-36-05).
        mid = (lo + hi) / 2.0
        z0_mid = z0_fn(mid, h, t, er)

        if abs(z0_mid - target_z0) / target_z0 * 100 <= tolerance_percent * 0.1:
            # Converged well within tolerance; exit early.
            break

        if z0_mid > target_z0:
            # Impedance too high -> need wider trace.
            lo = mid
        else:
            # Impedance too low -> need narrower trace.
            hi = mid

        if hi - lo < 1e-6:
            break

    best_w = (lo + hi) / 2.0
    # Clamp to min_width if bisection pushed below.
    best_w = max(min_width, best_w)

    achieved = z0_fn(best_w, h, t, er)
    error_pct = abs(achieved - target_z0) / target_z0 * 100

    return ImpedanceResult(
        trace_width_mm=round(best_w, 6),
        target_z0=target_z0,
        achieved_z0=round(achieved, 4),
        impedance_error_percent=round(error_pct, 4),
        model=model,
        valid=error_pct <= tolerance_percent,
    )
