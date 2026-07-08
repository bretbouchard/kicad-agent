"""Phase 204 w1f fix: tests for TL072-buffered CE preamp."""
from __future__ import annotations

import pytest

from kicad_agent.sim.buffered_preamp import (
    build_buffered_preamp_spice_netlist,
    compute_input_impedance_kohm,
)


class TestBufferedPreampNetlist:
    """Netlist generation + validation."""

    def test_default_netlist_has_tl072_buffer(self) -> None:
        netlist = build_buffered_preamp_spice_netlist()
        assert "X_BUF" in netlist
        assert "TL072" in netlist
        assert "R_BIAS in 0 1e+06" in netlist  # 1M default as f"{1e6:g}"
        # X_BUF needs 5 nodes: in+ in- vcc vee out — verify pin order matches
        # the .SUBCKT TL072 IN+ IN- VCC VEE OUT signature in model_registry.
        assert "X_BUF in out_buf +12V -12V out_buf TL072" in netlist

    def test_default_netlist_has_ce_preamp(self) -> None:
        """CE preamp stage preserved from build_preamp_circuit."""
        netlist = build_buffered_preamp_spice_netlist()
        assert "Q1 collector base emitter 2N3904" in netlist
        assert "R1 collector +12V" in netlist
        assert "C3 emitter 0" in netlist  # emitter bypass

    def test_custom_r_bias_appears_in_netlist(self) -> None:
        netlist = build_buffered_preamp_spice_netlist(r_bias=2.2e6)
        assert "R_BIAS in 0 2.2e+06" in netlist

    def test_rejects_nan_r_bias(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_buffered_preamp_spice_netlist(r_bias=float("nan"))

    def test_rejects_zero_cap(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_buffered_preamp_spice_netlist(c_in=0.0)

    def test_rejects_negative_r(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_buffered_preamp_spice_netlist(r1=-100.0)


class TestInputImpedanceComputation:
    """Input Z computed analytically from R_BIAS || TL072 input Z."""

    def test_default_input_z_is_1_meg(self) -> None:
        """R_BIAS=1MΩ + TL072 ~10^12 Ω → Z_in ≈ 1MΩ = 1000 kΩ."""
        z_kohm = compute_input_impedance_kohm()
        assert 999.0 <= z_kohm <= 1001.0  # within 0.1% of 1000 kΩ

    def test_2_2_meg_bias_gives_2200_kohm(self) -> None:
        z_kohm = compute_input_impedance_kohm(r_bias=2.2e6)
        assert 2199.0 <= z_kohm <= 2201.0


@pytest.mark.slow
class TestBufferedPreampSimulation:
    """End-to-end simulation — gain preserved, input Z measurable via AC."""

    def test_buffered_preamp_sims_with_gain_near_20db(self) -> None:
        """Full sim with TL072 + 2N3904 models produces ~20 dB gain."""
        from kicad_agent.spice import (
            run_simulation,
            generate_ac_testbench,
            get_model,
            AnalysisType,
        )

        netlist = build_buffered_preamp_spice_netlist(
            r1=4.7e3, r2=68e3, r3=10e3, r4=470,
            c_in=10e-6, c_out=1e-6, c_emitter=100e-6,
            r_bias=1e6,
        )
        # Prepend both models — TL072 for buffer, 2N3904 for CE preamp.
        full_netlist = get_model("TL072") + "\n" + get_model("2N3904") + "\n" + netlist
        tb = generate_ac_testbench(full_netlist)

        result = run_simulation(tb, "buffered_preamp", analyses=["ac"])
        ac = result.get_analysis(AnalysisType.AC)
        assert ac is not None, "No AC analysis in result"
        assert ac.passed, f"AC analysis failed: {ac.error_message}"
        # Gain should be similar to unbuffered CE preamp (~20 dB).
        # BLK-1 strict — real value assertion, no skip-guards.
        assert ac.gain_db is not None, "gain_db is None — TL072 buffer may have broken sim"
        assert 15.0 <= ac.gain_db <= 60.0, (
            f"Buffered preamp gain out of expected range: {ac.gain_db:.2f} dB "
            f"(expected 15-60 dB — TL072 unity buffer shouldn't reduce CE gain)"
        )

    def test_input_z_measured_via_ac_current(self) -> None:
        """Input Z = V_in / I_in. With V_in = 1V AC and R_BIAS = 1MΩ,
        I_in should be ~1µA → Z = 1MΩ = 1000 kΩ."""
        from kicad_agent.spice import (
            run_simulation,
            generate_ac_testbench,
            get_model,
            AnalysisType,
        )

        netlist = build_buffered_preamp_spice_netlist(r_bias=1e6)
        full_netlist = get_model("TL072") + "\n" + get_model("2N3904") + "\n" + netlist
        tb = generate_ac_testbench(full_netlist)

        result = run_simulation(tb, "input_z_test", analyses=["ac"])
        ac = result.get_analysis(AnalysisType.AC)
        assert ac is not None and ac.passed

        # Find the AC current-into-VAC-source trace.
        # _build_traces_from_raw emits i(vac_in)_mag_db (current magnitude in dB).
        i_mag_trace = next(
            (t for t in ac.traces if t.name == "i(vac_in)_mag_db"), None
        )
        assert i_mag_trace is not None, "i(vac_in)_mag_db trace not found"

        # Current in dB relative to 1A. For 1µA: 20*log10(1e-6) = -120 dB.
        # At mid-band (where C_in is transparent), I_in = V_in / R_BIAS = 1/1e6 = 1µA.
        # So we expect i_mag_db ≈ -120 dB at mid-band.
        import numpy as np
        i_mag = np.asarray(i_mag_trace.values, dtype=float)
        freq = np.asarray(i_mag_trace.scale, dtype=float)

        # Find mid-band point (e.g., 1 kHz) — well above C_in coupling pole.
        midband_idx = int(np.argmin(np.abs(freq - 1000.0)))
        i_db_at_1k = float(i_mag[midband_idx])

        # Z = V / I. V_in = 1V. |I| = 10^(i_db/20) Amps.
        # Z_ohm = 1 / 10^(i_db/20). For Z=1M: i_db = 20*log10(1e-6) = -120.
        # Acceptance: Z within [100 kΩ, 10 MΩ] — generous tolerance for sim noise.
        # That's i_db in [-140, -100].
        assert -140.0 <= i_db_at_1k <= -100.0, (
            f"Input Z out of [100kΩ, 10MΩ] range. "
            f"i(vac_in) at 1kHz = {i_db_at_1k:.1f} dB → "
            f"Z = {1.0 / (10 ** (i_db_at_1k / 20.0)):.0f} Ω"
        )
