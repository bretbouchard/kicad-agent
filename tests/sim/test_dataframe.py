"""Phase 204: pandas adapter for SimulationResult."""
from __future__ import annotations

import pandas as pd

from kicad_agent.spice import AnalysisResult, AnalysisType, SimulationResult, Trace
from kicad_agent.sim.dataframe import to_dataframe


def _result_with_traces() -> SimulationResult:
    trace = Trace(name="vdb(out)", values=(1.0, 2.0, 3.0), scale=(10.0, 100.0, 1000.0))
    ac = AnalysisResult(
        analysis_type=AnalysisType.AC,
        traces=(trace,),
        gain_db=20.0,
        bandwidth_hz=100e3,
    )
    return SimulationResult(circuit_name="test", analyses=(ac,))


def _result_without_traces() -> SimulationResult:
    ac = AnalysisResult(
        analysis_type=AnalysisType.AC,
        traces=(),
        gain_db=20.0,
        bandwidth_hz=100e3,
    )
    return SimulationResult(circuit_name="test", analyses=(ac,))


def test_to_dataframe_with_empty_traces_returns_scalar_row() -> None:
    df = to_dataframe(_result_without_traces())
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert set(df.columns) >= {"gain_db", "bandwidth_hz", "passed"}
    assert df.loc[0, "gain_db"] == 20.0


def test_to_dataframe_with_traces_returns_per_frequency_rows() -> None:
    df = to_dataframe(_result_with_traces())
    assert len(df) == 3
    assert "vdb(out)" in df.columns


def test_to_dataframe_preserves_index_from_scale() -> None:
    df = to_dataframe(_result_with_traces())
    assert list(df.index) == [10.0, 100.0, 1000.0]


def test_to_dataframe_does_not_mutate_source() -> None:
    result = _result_with_traces()
    df1 = to_dataframe(result)
    df2 = to_dataframe(result)
    pd.testing.assert_frame_equal(df1, df2)
