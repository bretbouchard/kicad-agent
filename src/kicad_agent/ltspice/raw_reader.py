"""Read LTspice .raw simulation result files into structured Python dataclasses.

Wraps SpiceLib's RawRead to parse .raw files containing voltage and current
traces from transient, AC, DC, and other LTspice simulation types. Returns
immutable :class:`SimulationResult` objects with typed trace data.

Threat mitigations:
    - T-11-05: Path traversal protection via resolve() + traversal check.
    - T-11-06: Malformed .raw files wrapped in try/except with clear error.
"""

from __future__ import annotations

from pathlib import Path

from spicelib import RawRead

from kicad_agent.ltspice.types import LTspiceTrace, SimulationResult


def _infer_unit(trace_name: str) -> str:
    """Infer engineering unit from a trace name prefix.

    Args:
        trace_name: LTspice trace name (e.g. ``"V(n001)"``, ``"I(R1)"``, ``"time"``).

    Returns:
        ``"voltage"`` for ``V(...)`` traces, ``"current"`` for ``I(...)`` traces,
        ``"time"`` for the time axis, or ``""`` for unknown prefixes.
    """
    if trace_name == "time":
        return "time"
    if trace_name.startswith("V("):
        return "voltage"
    if trace_name.startswith("I("):
        return "current"
    return ""


def read_raw(raw_path: str | Path) -> SimulationResult:
    """Parse an LTspice .raw simulation result file.

    Args:
        raw_path: Path to the ``.raw`` file. Must exist and must not contain
            directory traversal sequences.

    Returns:
        A frozen :class:`SimulationResult` containing all voltage and current
        traces as immutable tuples of floats.

    Raises:
        FileNotFoundError: If *raw_path* does not point to an existing file.
        ValueError: If *raw_path* contains directory traversal (``..``).
        RuntimeError: If the .raw file cannot be parsed by SpiceLib.
    """
    resolved = Path(raw_path).resolve()

    # T-11-05: Reject path traversal
    if ".." in Path(raw_path).parts:
        raise ValueError(
            f"Path traversal rejected: '{raw_path}' contains '..'"
        )

    if not resolved.is_file():
        raise FileNotFoundError(f"Raw file not found: {resolved}")

    # T-11-06: Wrap SpiceLib parse in try/except for malformed files
    try:
        raw = RawRead(str(resolved), dialect="ltspice", verbose=False)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse .raw file '{resolved}': {exc}"
        ) from exc

    # Extract trace data
    trace_names = tuple(raw.get_trace_names())

    traces: list[LTspiceTrace] = []
    for name in trace_names:
        wave = raw.get_wave(name)
        values = tuple(float(v) for v in wave)
        unit = _infer_unit(name)
        traces.append(LTspiceTrace(name=name, values=values, unit=unit))

    # Determine analysis type -- raw_type can be empty or non-informative
    raw_type = getattr(raw, "raw_type", "") or ""
    if not raw_type or raw_type.startswith("values"):
        # Fallback: infer from Plotname header
        plotname = ""
        if hasattr(raw, "plots") and raw.plots:
            plotname = str(getattr(raw.plots[0], "name", "")).lower()
        if "transient" in plotname:
            raw_type = "transient"
        elif "ac analysis" in plotname:
            raw_type = "ac"
        elif "dc transfer" in plotname:
            raw_type = "dc"
        elif "operating point" in plotname:
            raw_type = "op"
        else:
            raw_type = "unknown"

    return SimulationResult(
        traces=tuple(traces),
        trace_names=trace_names,
        raw_type=raw_type,
        n_points=raw.nPoints,
        n_variables=raw.nVariables,
        source_path=str(resolved),
    )
