"""Tests for LTspice .raw simulation result reading via read_raw()."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.ltspice.raw_reader import read_raw
from kicad_agent.ltspice.types import SimulationResult, LTspiceTrace


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "ltspice"
BASIC_RC_RAW = FIXTURES_DIR / "basic_rc.raw"


class TestRawReader:
    """Tests for read_raw() parsing LTspice .raw files."""

    def test_read_raw_returns_simulation_result_with_traces(self) -> None:
        """Test 1: read_raw returns SimulationResult with traces tuple."""
        result = read_raw(BASIC_RC_RAW)
        assert isinstance(result, SimulationResult)
        assert isinstance(result.traces, tuple)
        assert len(result.traces) > 0
        for trace in result.traces:
            assert isinstance(trace, LTspiceTrace)

    def test_read_raw_has_points_and_variables(self) -> None:
        """Test 2: result has n_points > 0 and n_variables > 0."""
        result = read_raw(BASIC_RC_RAW)
        assert result.n_points > 0
        assert result.n_variables > 0

    def test_read_raw_get_trace_by_name(self) -> None:
        """Test 3: result.get_trace('V(n001)') returns LTspiceTrace with values."""
        result = read_raw(BASIC_RC_RAW)
        trace = result.get_trace("V(n001)")
        assert trace is not None
        assert trace.name == "V(n001)"
        assert isinstance(trace.values, tuple)
        assert len(trace.values) > 0
        assert all(isinstance(v, float) for v in trace.values)

    def test_read_raw_trace_names_includes_voltage(self) -> None:
        """Test 4: result.trace_names returns tuple including at least one voltage trace."""
        result = read_raw(BASIC_RC_RAW)
        assert isinstance(result.trace_names, tuple)
        voltage_traces = [n for n in result.trace_names if n.startswith("V(")]
        assert len(voltage_traces) >= 1

    def test_read_raw_time_axis(self) -> None:
        """Test 5: result.time_axis returns tuple of floats (transient analysis)."""
        result = read_raw(BASIC_RC_RAW)
        time = result.time_axis
        assert isinstance(time, tuple)
        assert len(time) > 0
        assert all(isinstance(v, float) for v in time)

    def test_read_raw_missing_file_raises_file_not_found(self) -> None:
        """Test 6: read_raw with non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            read_raw("/nonexistent/path/simulation.raw")

    def test_read_raw_path_traversal_raises_value_error(self) -> None:
        """Test 7: read_raw with malformed path raises ValueError (path traversal)."""
        with pytest.raises(ValueError, match="[Tt]raversal|invalid path"):
            read_raw("../../etc/passwd")
