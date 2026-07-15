"""Phase 204: Eurorack CE preamp — circuit construction + SPICE netlist emission."""
from __future__ import annotations

import pytest

from volta.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist, _sci
from volta.sim import eurorack as eurorack_mod  # for internal helper test


def test_build_preamp_circuit_has_8_parts() -> None:
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    refs = {p.ref for p in ckt.parts}
    assert refs == {"Q1", "R1", "R2", "R3", "R4", "C1", "C2", "C3"}, refs
    assert len(list(ckt.parts)) == 8


def test_q1_value_is_2n3904() -> None:
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    q1 = next(p for p in ckt.parts if p.ref == "Q1")
    assert q1.value == "2N3904"


def test_spice_netlist_contains_q1_line() -> None:
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    netlist = circuit_to_spice_netlist(ckt)
    lines = netlist.splitlines()
    q1_lines = [ln for ln in lines if ln.startswith("Q1 ")]
    assert len(q1_lines) == 1
    assert q1_lines[0].endswith("2N3904"), q1_lines[0]


def test_spice_netlist_contains_all_resistors() -> None:
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    netlist = circuit_to_spice_netlist(ckt)
    for ref in ("R1 ", "R2 ", "R3 ", "R4 "):
        assert any(ln.startswith(ref) for ln in netlist.splitlines()), f"missing {ref!r}"


def test_spice_netlist_contains_all_caps() -> None:
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    netlist = circuit_to_spice_netlist(ckt)
    for ref in ("C1 ", "C2 ", "C3 "):
        assert any(ln.startswith(ref) for ln in netlist.splitlines()), f"missing {ref!r}"


def test_spice_netlist_maps_gnd_to_zero() -> None:
    """ngspice manual v46 §2.1.3.5: ground node must be '0' (not 'GND')."""
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    netlist = circuit_to_spice_netlist(ckt)
    # Every device line — GND must appear as " 0" not "GND"
    device_lines = [ln for ln in netlist.splitlines() if ln and ln[0] in "RCQV"]
    assert device_lines, "no device lines emitted"
    for ln in device_lines:
        assert " GND" not in ln, f"GND leaked into SPICE line: {ln!r}"
    # At least one line should reference node 0
    assert any(" 0" in ln for ln in device_lines), "no node 0 in netlist"


def test_spice_netlist_emits_global_for_power_rails() -> None:
    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    netlist = circuit_to_spice_netlist(ckt)
    assert ".GLOBAL +12V" in netlist
    assert ".GLOBAL -12V" in netlist


def test_sci_formats_engineering_notation() -> None:
    assert _sci(4.7e3) == "4.7k"
    assert _sci(10e-6) == "10u"
    assert _sci(1e6) == "1Meg"
    assert _sci(100e-6) == "100u"
    assert _sci(470.0) == "470"
    assert _sci(1e-9) == "1n"


# ----- BLK-1 strict integration tests (require ngspice — fail loud if missing) -----


def test_emitted_netlist_is_valid_spice() -> None:
    """Localize emitter failures from topology failures.

    Runs the emitted SPICE netlist through ngspice with just .OP analysis
    (no AC sweep). If this fails, the emitter is producing invalid SPICE.
    If this passes but the full AC test fails, the topology or testbench
    is the problem.

    The testbench wraps the emitted netlist with: a DC input source (so the
    input node has a reference), a 100k load from out to ground (DC path for
    AC-coupled outputs), and a .OP+.PRINT statement (ngspice batch mode
    requires an analysis statement).
    """
    from volta.spice import get_model, run_simulation

    ckt = build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
    model = get_model("2N3904")
    assert model is not None, "2N3904 missing from registry"
    netlist = model + "\n" + circuit_to_spice_netlist(ckt)
    # Minimal .OP testbench — DC input + output load + .OP+.PRINT so ngspice
    # batch mode has an analysis statement (without .PRINT/.PLOT/.FOURIER ngspice
    # exits with "no simulations run").
    op_cir = (
        "* emitter_op_check\n"
        f"{netlist}\n\n"
        "VDC_IN in 0 DC 0\n"
        "RLOAD out 0 100k\n"
        ".OP\n"
        ".PRINT OP v(collector) v(base) v(emitter)\n"
        ".END\n"
    )
    result = run_simulation(op_cir, "emitter_op_check", analyses=["op"])
    assert result.passed, (
        f"Emitted netlist failed ngspice .OP parse: log tail = {result.log[-500:]!r}"
    )


def test_eurorack_preamp_meets_target_gain(eurorack_preamp) -> None:
    """BLK-1: gain >= 17 dB (target 20, tolerance 3)."""
    _, result = eurorack_preamp
    from volta.spice import AnalysisType
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None, f"no AC analysis: tail of log = {result.log[-500:]!r}"
    assert ac.passed, f"AC failed: {ac.error_message}"
    assert ac.gain_db is not None, "gain_db is None — ngspice produced no measurement"
    assert ac.gain_db >= 17.0, f"Expected >=17 dB, got {ac.gain_db:.2f} dB"


def test_eurorack_preamp_meets_target_bandwidth(eurorack_preamp) -> None:
    """BLK-1: bandwidth >= 15 kHz (target 20 kHz, tolerance 5 kHz)."""
    _, result = eurorack_preamp
    from volta.spice import AnalysisType
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None and ac.passed
    assert ac.bandwidth_hz is not None, "bw_3db is None — no -3 dB point found"
    assert ac.bandwidth_hz >= 15_000, (
        f"Expected >=15 kHz bandwidth, got {ac.bandwidth_hz:.0f} Hz"
    )


# ----- Council R2 fixes (CR-01 P0, CR-03 P1, CR-04 P1) -----


def test_build_preamp_circuit_sets_skidl_env() -> None:
    """CR-01 (P0 R2 fix): build_preamp_circuit must call _ensure_skidl_env() so
    KICAD_SYMBOL_DIR is set before skidl.Part() lookup. Phase 156 pitfall #6 —
    without this, skidl silently produces no-pin Parts when the env var is unset.
    """
    import os
    # Ensure the env var is unset going in (proves the function sets it).
    saved = os.environ.pop("KICAD_SYMBOL_DIR", None)
    try:
        build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
        val = os.environ.get("KICAD_SYMBOL_DIR")
        assert val, (
            "KICAD_SYMBOL_DIR not set after build_preamp_circuit — Phase 156 "
            "pitfall #6 guard missing (council CR-01 P0)"
        )
    finally:
        if saved is not None:
            os.environ["KICAD_SYMBOL_DIR"] = saved


def test_fixture_gain_matches_hand_calc(eurorack_preamp) -> None:
    """CR-03 (P1 R2 fix): CE preamp with C_emitter=100uF bypass yields gain
    near 47 dB at audio band (R1/re ≈ 4700/20 ≈ 47 dB when bypassed). The
    optimizer's squared-error term will pull R1 down to hit 20 dB. Bound the
    upper end so a shorted-base-to-Vcc bug doesn't silently pass the floor.
    """
    _, result = eurorack_preamp
    from volta.spice import AnalysisType
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None and ac.gain_db is not None
    assert 17.0 <= ac.gain_db <= 55.0, (
        f"Fixture gain out of expected range: {ac.gain_db:.2f} dB "
        f"(expected 17..55 — CE with bypass)"
    )


def test_build_preamp_circuit_rejects_nan() -> None:
    """CR-04 (P1 R2 fix): NaN R/C values must raise ValueError at function
    entry — defense-in-depth so _sci(nan) -> 'nan' never reaches the netlist.
    """
    import math
    with pytest.raises(ValueError, match="positive finite"):
        build_preamp_circuit(math.nan, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)


def test_build_preamp_circuit_rejects_negative() -> None:
    """CR-04 (P1 R2 fix): negative R/C values must raise ValueError."""
    with pytest.raises(ValueError, match="positive finite"):
        build_preamp_circuit(-1.0, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)
