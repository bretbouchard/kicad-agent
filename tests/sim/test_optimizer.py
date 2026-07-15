"""Phase 204: Optuna GPSampler objective + sweep runner."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from volta.spice import (
    AnalysisResult, AnalysisType, SimulationResult,
)
from volta.sim.optimizer import (
    E12_BASE, E12_RESISTORS, E12_CAPS, TARGET_GAIN_DB, CURRENT_PENALTY,
    objective, optimize_preamp,
)


def test_e12_base_has_12_values() -> None:
    assert len(E12_BASE) == 12
    assert 1.0 in E12_BASE
    assert 4.7 in E12_BASE
    assert 8.2 in E12_BASE


def test_e12_resistors_are_discrete() -> None:
    """E12 series values must be exact — no 4723, no 4.71k."""
    for v in (470.0, 1e3, 4.7e3, 10e3, 68e3):
        assert v in E12_RESISTORS, f"E12 missing {v}"


def test_e12_caps_include_audio_band_values() -> None:
    for v in (10e-6, 100e-6):
        assert v in E12_CAPS, f"E12 missing {v}"


def test_objective_returns_inf_on_failed_sim(monkeypatch: MonkeyPatch) -> None:
    """If ngspice fails, objective returns float('inf') — Optuna marks infeasible."""
    from volta.sim import optimizer as opt_mod

    def fake_run(cir, name, analyses):
        ac = AnalysisResult(
            analysis_type=AnalysisType.AC, traces=(),
            passed=False, error_message="stub failure",
        )
        return SimulationResult(circuit_name=name, analyses=(ac,))

    monkeypatch.setattr(opt_mod, "run_simulation", fake_run)

    class FakeTrial:
        def suggest_categorical(self, name, choices):
            return choices[0]

    assert objective(FakeTrial()) == float("inf")


def test_objective_zero_squared_when_gain_hits_target(monkeypatch: MonkeyPatch) -> None:
    """When gain_db == TARGET_GAIN_DB, squared error is 0; objective = lambda*ic."""
    from volta.sim import optimizer as opt_mod

    def fake_run(cir, name, analyses):
        ac = AnalysisResult(
            analysis_type=AnalysisType.AC, traces=(),
            passed=True, gain_db=TARGET_GAIN_DB,
        )
        return SimulationResult(circuit_name=name, analyses=(ac,))

    monkeypatch.setattr(opt_mod, "run_simulation", fake_run)

    class FakeTrial:
        def suggest_categorical(self, name, choices):
            # Return a value that makes ic computable: r1 = 4.7k → ic ≈ 2.5 mA
            return 4.7e3 if name == "r1" else choices[0]

    val = objective(FakeTrial())
    # squared term is 0; only the current penalty remains
    expected_ic_ma = (12.0 - 0.2) / 4.7e3 * 1000.0
    assert val == pytest.approx(CURRENT_PENALTY * expected_ic_ma, rel=1e-6)


# ----- Council R2 fixes (CR-02 P1, CR-03 P1, WR-03 P2, WR-02 P2) -----


def test_objective_times_out_on_slow_sim(monkeypatch: MonkeyPatch) -> None:
    """CR-02 (P1 R2): per-trial wall-time budget caps slow ngspice at TRIAL_TIMEOUT_S.

    Without the budget, 50 trials x 120s _NGSPICE_TIMEOUT = 100 min worst case,
    blowing the 60s demo budget. With the budget, each trial is capped at
    TRIAL_TIMEOUT_S (default 10s) and returns float('inf') on timeout.
    """
    import time as _time
    from volta.sim import optimizer as opt_mod

    def slow_run(cir, name, analyses):
        # Simulate a convergence hang — ngspice retries internally.
        _time.sleep(15)  # longer than TRIAL_TIMEOUT_S (10s)
        ac = AnalysisResult(
            analysis_type=AnalysisType.AC, traces=(),
            passed=True, gain_db=20.0,
        )
        return SimulationResult(circuit_name=name, analyses=(ac,))

    monkeypatch.setattr(opt_mod, "run_simulation", slow_run)

    class FakeTrial:
        def suggest_categorical(self, name, choices):
            return 4.7e3 if name == "r1" else choices[0]

    t0 = _time.time()
    val = objective(FakeTrial())
    elapsed = _time.time() - t0
    assert val == float("inf"), f"timeout must return inf, got {val}"
    # Budget: ~10s TRIAL_TIMEOUT_S + ~3-6s skidl symbol-lookup overhead in
    # build_preamp_circuit (skidl first-import is slow, varies by system cache).
    # 40s gives slack for cold-cache build_preamp_circuit (Part lookups
    # re-parse Device.kicad_sym on first call per process — ~4-6s overhead
    # tracked as kicad-agent-pzz follow-up). The assertion's purpose is
    # "shorter than the 120s ngspice default", not a tight timing guarantee.
    assert elapsed < 40.0, (
        f"objective should short-circuit at ~10s TRIAL_TIMEOUT_S + ~3-6s skidl setup, "
        f"plus cold-cache build_preamp_circuit overhead. "
        f"took {elapsed:.1f}s — TRIAL_TIMEOUT_S budget not enforced (CR-02 P1)"
    )


def test_objective_rejects_current_saturation(monkeypatch: MonkeyPatch) -> None:
    """CR-03 (P1 R2): trials that push Ic past 50mA return float('inf').

    2N3904 Ic_max is 200mA continuous; 50mA safety. With R1=100Ω (E12 floor),
    Ic ≈ (12-0.2)/100 = 118mA — past the limit. Even if ngspice reports a
    'passing' high-gain result (which it might, since the bias point is
    technically valid), the objective rejects it.
    """
    from volta.sim import optimizer as opt_mod

    def fake_run(cir, name, analyses):
        # ngspice reports a passing sim — but the bias point is destructive.
        ac = AnalysisResult(
            analysis_type=AnalysisType.AC, traces=(),
            passed=True, gain_db=30.0,
        )
        return SimulationResult(circuit_name=name, analyses=(ac,))

    monkeypatch.setattr(opt_mod, "run_simulation", fake_run)

    class FakeTrial:
        def suggest_categorical(self, name, choices):
            if name == "r1":
                return 100.0  # E12 floor → ic_ma ≈ 118 mA, past 50mA guard
            return choices[0]

    val = objective(FakeTrial())
    assert val == float("inf"), (
        f"saturating trial (r1=100Ω, ic≈118mA) must return inf, got {val} "
        "(CR-03 P1 current-saturation penalty missing)"
    )


def test_objective_penalizes_gain_below_target(monkeypatch: MonkeyPatch) -> None:
    """WR-03 (P2 R2): nonzero-squared branch coverage.

    When gain_db=15 (5 dB below TARGET_GAIN_DB=20), squared error = (15-20)^2 = 25.
    Combined with the current penalty: objective = 25 + 0.001 * ic_ma.
    """
    from volta.sim import optimizer as opt_mod

    def fake_run(cir, name, analyses):
        ac = AnalysisResult(
            analysis_type=AnalysisType.AC, traces=(),
            passed=True, gain_db=15.0,
        )
        return SimulationResult(circuit_name=name, analyses=(ac,))

    monkeypatch.setattr(opt_mod, "run_simulation", fake_run)

    class FakeTrial:
        def suggest_categorical(self, name, choices):
            return 4.7e3 if name == "r1" else choices[0]

    val = objective(FakeTrial())
    expected_ic_ma = (12.0 - 0.2) / 4.7e3 * 1000.0
    expected = (15.0 - TARGET_GAIN_DB) ** 2 + CURRENT_PENALTY * expected_ic_ma
    assert val == pytest.approx(expected, rel=1e-6), (
        f"gain_below_target objective wrong: expected {expected}, got {val} "
        "(WR-03 P2 nonzero-squared branch)"
    )


def test_e12_caps_no_special_case_100uf() -> None:
    """WR-02 (P2 R2): 100µF is generated naturally by range(-9,-2).

    The comprehension covers exponents [-9..-2] inclusive, producing
    1.0 × 10^-4 = 100µF as a legitimate E12 value. No special-case
    `+ (100e-6,)` append — that would create a duplicate.
    """
    assert 100e-6 in E12_CAPS, "100µF missing from E12_CAPS"
    # Count occurrences — must be exactly 1, no duplicates.
    count = sum(1 for v in E12_CAPS if v == 100e-6)
    assert count == 1, (
        f"100µF appears {count} times in E12_CAPS — should be exactly 1 "
        "(WR-02 P2: remove asymmetric + (100e-6,) special-case)"
    )
    # Sanity: range should cover larger values too (820µF = 8.2e-4).
    assert 820e-6 in E12_CAPS, "820µF should be present when range goes to -2"


@pytest.mark.slow
def test_optimize_smoke_completes_5_trials(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """End-to-end: 5 real trials via GPSampler + ngspice + sqlite. <30s."""
    # Redirect sqlite to tmp_path so the test doesn't pollute the repo
    db = tmp_path / "test_sweep.db"
    monkeypatch.setenv("OPTUNA_STORAGE", f"sqlite:///{db}")

    study = optimize_preamp(n_trials=5, seed=42)
    completed = [t for t in study.trials if t.state.name == "COMPLETE"]
    assert len(completed) >= 4, (
        f"Expected >= 4 complete trials, got {len(completed)}; "
        f"states={[t.state.name for t in study.trials]}"
    )
    assert db.exists(), f"sqlite DB not created at {db}"


@pytest.mark.slow
def test_study_uses_sqlite_storage(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """sqlite DB is created at the configured path."""
    db = tmp_path / "storage_test.db"
    monkeypatch.setenv("OPTUNA_STORAGE", f"sqlite:///{db}")
    optimize_preamp(n_trials=3, seed=42, study_name="storage_check")
    assert db.exists(), f"sqlite DB not created at {db}"


@pytest.mark.slow
def test_gpsampler_deterministic(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """GPSampler(seed=42) produces identical trial params across runs.

    Critical for reproducibility — the demo (Plan 04) must produce the same
    best-trial every time on the same seed. If this fails, the sampler is
    reading external entropy (NG, threading, etc.) and the demo cannot be
    trusted to be reproducible.
    """
    db1 = tmp_path / "determ_1.db"
    db2 = tmp_path / "determ_2.db"
    monkeypatch.setenv("OPTUNA_STORAGE", f"sqlite:///{db1}")
    study1 = optimize_preamp(n_trials=3, seed=42, study_name="determ_run_a")
    monkeypatch.setenv("OPTUNA_STORAGE", f"sqlite:///{db2}")
    study2 = optimize_preamp(n_trials=3, seed=42, study_name="determ_run_b")

    params1 = [t.params for t in study1.trials if t.state.name == "COMPLETE"]
    params2 = [t.params for t in study2.trials if t.state.name == "COMPLETE"]

    assert len(params1) == len(params2), (
        f"Trial count diverged: {len(params1)} vs {len(params2)}"
    )
    for i, (p1, p2) in enumerate(zip(params1, params2)):
        assert p1 == p2, (
            f"Trial {i} params diverged with same seed:\n"
            f"  run1: {p1}\n  run2: {p2}"
        )


@pytest.mark.slow
def test_optimize_best_trial_meets_floor_gain(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The best trial from a 10-trial sweep should achieve gain >= 14 dB (loose floor
    for 10-trial budget; the 50-trial demo in Plan 04 hits 17 dB).
    """
    db = tmp_path / "test_sweep10.db"
    monkeypatch.setenv("OPTUNA_STORAGE", f"sqlite:///{db}")

    study = optimize_preamp(n_trials=10, seed=42)
    # Re-evaluate best trial to extract gain_db
    from volta.sim import optimizer as opt_mod
    from volta.spice import AnalysisType

    best = study.best_trial
    circuit = opt_mod.build_preamp_circuit(
        best.params["r1"], best.params["r2"], best.params["r3"], best.params["r4"],
        best.params["c_in"], best.params["c_out"], best.params["c_emit"],
    )
    model = opt_mod.get_model("2N3904")
    netlist = model + "\n" + opt_mod.circuit_to_spice_netlist(circuit)
    cir = opt_mod.generate_ac_testbench(
        netlist=netlist, input_node="in", output_node="out",
        freq_start=10.0, freq_stop=1e9, points_per_decade=50,
    )
    result = opt_mod.run_simulation(cir, "best_trial_verify", analyses=["ac"])
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None and ac.gain_db is not None
    assert ac.gain_db >= 14.0, f"Best 10-trial gain too low: {ac.gain_db:.2f} dB"
