"""ConstraintTable: deterministic lookup from signal integrity to constraint parameters.

CP-04: Maps (SignalIntegrity, NetImportance) to ConstraintParams via
ordered rule list. First match wins. Follows _LIBID_TYPE_MAP pattern
from topology_graph.py.

Usage:
    from volta.constraints.table import lookup_params, ConstraintParams
    from volta.analysis.net_classifier import SignalIntegrity, NetImportance

    params = lookup_params(SignalIntegrity.HIGH_SPEED, NetImportance.CRITICAL)
    print(params.clearance_mm)  # 0.15
"""
from __future__ import annotations

from dataclasses import dataclass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from volta.analysis.net_classifier import NetImportance, SignalIntegrity


@dataclass(frozen=True)
class ConstraintParams:
    """Design constraint parameters derived from signal integrity classification.

    All dimensions in millimeters. Frozen dataclass -- immutable after
    construction.

    Attributes:
        clearance_mm: Minimum copper-to-copper clearance.
        trace_width_mm: Default trace width.
        diff_pair_gap_mm: Differential pair gap.
        via_diameter_mm: Via pad diameter.
    """

    clearance_mm: float = 0.2
    trace_width_mm: float = 0.25
    diff_pair_gap_mm: float = 0.1
    via_diameter_mm: float = 0.8


# ---------------------------------------------------------------------------
# Constraint lookup rules -- ordered list, first match wins.
# Pattern follows _LIBID_TYPE_MAP from topology_graph.py.
# Each entry: (match_fn, ConstraintParams)
# ---------------------------------------------------------------------------

_CONSTRAINT_RULES: list[tuple[
    "callable[[SignalIntegrity, NetImportance], bool]",
    ConstraintParams,
]] = []


def _build_rules() -> None:
    """Populate _CONSTRAINT_RULES with late-bound enums.

    Called at module init to avoid circular imports at definition time.
    """
    from volta.analysis.net_classifier import NetImportance, SignalIntegrity

    _CONSTRAINT_RULES.extend([
        # HIGH_SPEED + CRITICAL: tightest clearance, narrowest diff pair gap
        (
            lambda si, imp: si == SignalIntegrity.HIGH_SPEED and imp == NetImportance.CRITICAL,
            ConstraintParams(clearance_mm=0.15, trace_width_mm=0.15, diff_pair_gap_mm=0.08, via_diameter_mm=0.6),
        ),
        # HIGH_SPEED + HIGH: tight clearance
        (
            lambda si, imp: si == SignalIntegrity.HIGH_SPEED and imp == NetImportance.HIGH,
            ConstraintParams(clearance_mm=0.15, trace_width_mm=0.15, diff_pair_gap_mm=0.1),
        ),
        # HIGH_SPEED + MEDIUM/LOW: moderate clearance
        (
            lambda si, imp: si == SignalIntegrity.HIGH_SPEED,
            ConstraintParams(clearance_mm=0.2, trace_width_mm=0.2, diff_pair_gap_mm=0.1),
        ),
        # CLOCK patterns classified as HIGH_SPEED already, but add explicit
        # rule for any CLOCK signal_integrity that may exist
        # POWER_INTEGRITY + CRITICAL: wide traces for power
        (
            lambda si, imp: si == SignalIntegrity.POWER_INTEGRITY and imp == NetImportance.CRITICAL,
            ConstraintParams(clearance_mm=0.3, trace_width_mm=0.5, via_diameter_mm=1.0),
        ),
        # POWER_INTEGRITY + other: moderate power traces
        (
            lambda si, imp: si == SignalIntegrity.POWER_INTEGRITY,
            ConstraintParams(clearance_mm=0.25, trace_width_mm=0.4),
        ),
        # LOW_FREQUENCY + CRITICAL/HIGH: standard clearance
        (
            lambda si, imp: si == SignalIntegrity.LOW_FREQUENCY and imp in (NetImportance.CRITICAL, NetImportance.HIGH),
            ConstraintParams(clearance_mm=0.2, trace_width_mm=0.25),
        ),
        # DC + CRITICAL: standard clearance
        (
            lambda si, imp: si == SignalIntegrity.DC and imp == NetImportance.CRITICAL,
            ConstraintParams(clearance_mm=0.2, trace_width_mm=0.25),
        ),
    ])


# Initialize rules at module load time
_build_rules()


def lookup_params(si: "SignalIntegrity", importance: "NetImportance") -> ConstraintParams:
    """Look up constraint parameters for a signal integrity / importance pair.

    Iterates the ordered rule list. Returns the first matching
    ConstraintParams. Falls back to default ConstraintParams() if no
    rule matches.

    Args:
        si: Signal integrity classification.
        importance: Net importance ranking.

    Returns:
        ConstraintParams with appropriate dimensions.
    """
    for match_fn, params in _CONSTRAINT_RULES:
        if match_fn(si, importance):
            return params
    return ConstraintParams()
