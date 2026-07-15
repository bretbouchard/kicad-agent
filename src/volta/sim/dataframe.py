"""Phase 204: pandas DataFrame adapter for SPICE SimulationResult.

Phase 158's SimulationResult (frozen dataclass) is the canonical type.
This module returns a *view* — never mutates the source.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from volta.spice import AnalysisType, SimulationResult


def to_dataframe(result: SimulationResult) -> pd.DataFrame:
    """Convert a SimulationResult's AC analysis to a pandas DataFrame.

    Two cases:
      1. AC has traces: one row per frequency point, one column per trace name.
         Index = trace.scale (frequency for AC).
      2. AC has empty traces (Phase 158 v1 default): one row with scalar metrics
         (gain_db, bandwidth_hz, passed).

    Args:
        result: Phase 158 SimulationResult (frozen).

    Returns:
        pandas.DataFrame view. Does NOT mutate `result`.
    """
    ac = result.get_analysis(AnalysisType.AC)
    if ac is None or not ac.traces:
        return pd.DataFrame([{
            "gain_db": ac.gain_db if ac else None,
            "bandwidth_hz": ac.bandwidth_hz if ac else None,
            "passed": ac.passed if ac else False,
        }])

    data = {t.name: list(t.values) for t in ac.traces}
    index = list(ac.traces[0].scale)
    return pd.DataFrame(data, index=index)


def study_to_dataframe(study: Any) -> pd.DataFrame:
    """Flatten an Optuna Study's completed trials into a tidy DataFrame.

    One row per completed trial: number, value (objective), and every param.
    Used by the demo script to summarize the sweep.

    Args:
        study: optuna.Study (typed as Any to avoid hard optuna dep at import).

    Returns:
        DataFrame with columns ["number", "value", ...params].
    """
    import optuna  # local import — keeps module importable without optuna

    rows: list[dict[str, object]] = []
    for trial in study.trials:
        if trial.state == optuna.trial.TrialState.COMPLETE:
            rows.append({
                "number": trial.number,
                "value": trial.value,
                **trial.params,
            })
    return pd.DataFrame(rows)
