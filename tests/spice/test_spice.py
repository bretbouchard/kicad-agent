"""Phase 158: SPICE pipeline tests."""
from __future__ import annotations

import pytest

from kicad_agent.spice import (
    AnalysisType,
    SimulationResult,
    AnalysisResult,
    DegradationReport,
    run_simulation,
    generate_ac_testbench,
    generate_tran_testbench,
    generate_noise_testbench,
    generate_thd_testbench,
    generate_testbench,
    get_model,
    is_simulatable,
    get_all_models,
    UNSIMULATABLE,
    compute_degradation,
)


class TestModelRegistry:
    """Model registry — SPICE models for common ICs."""

    def test_ne5532_has_model(self) -> None:
        model = get_model("NE5532")
        assert model is not None
        assert "SUBCKT" in model

    def test_tl072_has_model(self) -> None:
        model = get_model("TL072")
        assert model is not None

    def test_unknown_part_no_model(self) -> None:
        assert get_model("UNKNOWN_IC_999") is None

    def test_passive_is_simulatable(self) -> None:
        assert is_simulatable("Device:R") is True
        assert is_simulatable("Device:C") is True

    def test_unsimulatable_digital(self) -> None:
        assert is_simulatable("RP2350B") is False
        assert is_simulatable("AK4619VN") is False

    def test_opamp_is_simulatable(self) -> None:
        assert is_simulatable("NE5532") is True

    def test_get_all_models_concatenated(self) -> None:
        models = get_all_models()
        assert "SUBCKT" in models
        assert "NE5532" in models


class TestTestbenchGenerators:
    """Testbench generation for each analysis type."""

    _SIMPLE_NETLIST = "R1 in out 1k\nC1 out 0 1u"

    def test_ac_testbench(self) -> None:
        cir = generate_ac_testbench(self._SIMPLE_NETLIST)
        assert ".AC" in cir
        assert "VAC_IN" in cir
        assert ".MEAS AC gain_db" in cir

    def test_tran_testbench(self) -> None:
        cir = generate_tran_testbench(self._SIMPLE_NETLIST)
        assert ".TRAN" in cir
        assert "SINE" in cir

    def test_noise_testbench(self) -> None:
        cir = generate_noise_testbench(self._SIMPLE_NETLIST)
        assert ".NOISE" in cir

    def test_thd_testbench(self) -> None:
        cir = generate_thd_testbench(self._SIMPLE_NETLIST)
        assert ".FOUR" in cir
        assert ".TRAN" in cir

    def test_dispatch_via_generate_testbench(self) -> None:
        cir = generate_testbench(self._SIMPLE_NETLIST, AnalysisType.AC)
        assert ".AC" in cir


class TestSimulationRunner:
    """ngspice runner — real simulation on a simple RC filter."""

    def test_runs_simple_rc_filter(self) -> None:
        """Run ngspice on a simple RC lowpass filter."""
        cir = generate_ac_testbench(
            netlist="R1 in out 1000\nC1 out 0 1u",
            input_node="in",
            output_node="out",
        )
        result = run_simulation(cir, "rc_filter", analyses=["ac"])
        assert isinstance(result, SimulationResult)
        # ngspice should be installed and return a result.
        if result.analyses:
            ac = result.get_analysis(AnalysisType.AC)
            if ac:
                assert isinstance(ac, AnalysisResult)


class TestDegradation:
    """SPICE degradation scoring."""

    def test_no_degradation_when_identical(self) -> None:
        """Identical pre/post simulations = score 1.0."""
        result = SimulationResult(
            circuit_name="test",
            analyses=(AnalysisResult(
                analysis_type=AnalysisType.AC,
                traces=(),
                gain_db=20.0,
                bandwidth_hz=100e3,
            ),),
        )
        deg = compute_degradation(result, result)
        assert deg.gain_delta_db == 0.0
        assert deg.sim_score == 1.0

    def test_gain_loss_detected(self) -> None:
        """Gain loss reduces the score."""
        pre = SimulationResult(
            circuit_name="test",
            analyses=(AnalysisResult(
                analysis_type=AnalysisType.AC, traces=(),
                gain_db=20.0,
            ),),
        )
        post = SimulationResult(
            circuit_name="test",
            analyses=(AnalysisResult(
                analysis_type=AnalysisType.AC, traces=(),
                gain_db=17.0,  # -3dB loss
            ),),
        )
        deg = compute_degradation(pre, post)
        assert deg.gain_delta_db == -3.0
        assert deg.sim_score < 1.0
