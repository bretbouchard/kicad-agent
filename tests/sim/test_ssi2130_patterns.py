"""Tests for SSI2130 VCO design patterns (kicad-agent-30/31/32/33).

4 builder functions, each emitting SPICE netlist for a Bart Instruments
inspired circuit pattern. Tests verify:
- Netlist structure (key components present)
- Boundary validation (NaN/negative rejected)
- Default + custom values
"""
from __future__ import annotations

import pytest

from kicad_agent.sim.ssi2130_patterns import (
    build_measurement_tap_spice_netlist,
    build_hf_trim_spice_netlist,
    build_local_refs_spice_netlist,
    build_passive_cv_sum_spice_netlist,
)


class TestMeasurementTap:
    """kicad-agent-30: Per-VCO measurement tap for digital autotune."""

    def test_default_has_pullup_and_buffer(self) -> None:
        nl = build_measurement_tap_spice_netlist()
        assert "R_PULLUP +5V SQUARE_OUT" in nl
        assert "X_BUF" in nl and "TL072" in nl
        assert "X_COMP" in nl and "LM311" in nl
        assert "MCU_TIMER_CAP" in nl or "COMP_OUT" in nl

    def test_custom_pullup_value(self) -> None:
        nl = build_measurement_tap_spice_netlist(r_pullup=4.7e3)
        assert "4700" in nl  # 4.7kΩ formatted as 4700 in scientific

    def test_rejects_negative_cap(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_measurement_tap_spice_netlist(c_filter=-1e-12)

    def test_rejects_nan_resistor(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_measurement_tap_spice_netlist(r_in=float("nan"))


class TestHFTrimNetwork:
    """kicad-agent-31: HF tracking trim network for discrete VCO cores."""

    def test_default_has_rc_lag_network(self) -> None:
        nl = build_hf_trim_spice_netlist()
        assert "R_HFT" in nl and "C_HFT" in nl
        assert "R_FEEDBACK" in nl
        assert "HF_TRACK_OUT" in nl and "HFT_BASE" in nl and "EXPO_OUT" in nl

    def test_custom_cap(self) -> None:
        nl = build_hf_trim_spice_netlist(c_hft=220e-12)
        assert "2.2e-10" in nl  # 220pF formatted

    def test_rejects_zero_resistor(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_hf_trim_spice_netlist(r_hft=0)


class TestLocalReferences:
    """kicad-agent-32: Local ±2.5V references per voice submodule."""

    def test_default_has_dual_dividers(self) -> None:
        nl = build_local_refs_spice_netlist()
        assert "R_TOP_P" in nl and "R_BOT_P" in nl
        assert "R_TOP_N" in nl and "R_BOT_N" in nl
        assert "VREF_POS" in nl and "VREF_NEG" in nl
        assert "R_BAL" in nl  # balance trim
        assert "X_BUF_P" in nl and "X_BUF_N" in nl  # dual TL072 buffers

    def test_custom_r_top(self) -> None:
        nl = build_local_refs_spice_netlist(r_top=22e3)
        assert "22000" in nl

    def test_rejects_negative_balance(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_local_refs_spice_netlist(r_balance=-100)


class TestPassiveCVSum:
    """kicad-agent-33: Passive-summed multiple V/oct inputs."""

    def test_default_has_4_cv_resistors_into_scale_trim(self) -> None:
        nl = build_passive_cv_sum_spice_netlist()
        assert "R_CV1 CV1 SCALE_TRIM" in nl
        assert "R_CV2 CV2 SCALE_TRIM" in nl
        assert "R_CV3 CV3 SCALE_TRIM" in nl
        assert "R_CV4 CV4 SCALE_TRIM" in nl
        assert "SCALE_TRIM" in nl  # SSI2130 pin 3 destination

    def test_all_4_cv_values_appear(self) -> None:
        nl = build_passive_cv_sum_spice_netlist(
            r_cv1=82e3, r_cv2=100e3, r_cv3=120e3, r_cv4=150e3,
        )
        assert "82000" in nl  # 82k
        assert "100000" in nl  # 100k
        assert "120000" in nl  # 120k
        assert "150000" in nl  # 150k

    def test_rejects_zero_r_cv(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_passive_cv_sum_spice_netlist(r_cv1=0)

    def test_rejects_nan_r_cv(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            build_passive_cv_sum_spice_netlist(r_cv2=float("inf"))
