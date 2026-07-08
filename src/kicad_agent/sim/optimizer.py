"""Phase 204: Optuna GPSampler objective for Eurorack CE preamp.

Sweeps E12-series resistor and capacitor values, scoring each trial by:
    objective = (gain_db - TARGET_GAIN_DB)^2 + CURRENT_PENALTY * icollector_ma

    - Squared term: drives gain toward target (20 dB).
    - Current penalty: discourages power-hungry bias points.

Uses GPSampler (Bayesian optimization, Optuna 4.5+) and sqlite storage for
resumable sweeps. Serial execution (n_jobs=1) for reproducibility.
"""
from __future__ import annotations

import os
import threading

import optuna

from kicad_agent.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist
from kicad_agent.spice import (
    AnalysisType,
    generate_ac_testbench,
    get_model,
    run_simulation,
)

# E12 series — 12 values per decade (resistor + cap industry standard).
E12_BASE: tuple[float, ...] = (
    1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2,
)

# Resistors: 100 Ω .. 820 kΩ (4 decades — covers CE bias network).
E12_RESISTORS: tuple[float, ...] = tuple(
    v * 10 ** e for e in range(2, 6) for v in E12_BASE
)

# Capacitors: 1 nF .. 820 μF (8 decades — covers audio coupling + bypass).
# WR-02 (Council R2 P2): range(-9, -2) covers exponents [-9..-2] inclusive,
# producing 100µF (1.0×10^-4) and 820µF (8.2×10^-4) naturally as E12 values.
# The previous `+ (100e-6,)` special-case created a duplicate — removed.
E12_CAPS: tuple[float, ...] = tuple(
    v * 10 ** e for e in range(-9, -2) for v in E12_BASE
)

TARGET_GAIN_DB: float = 20.0
CURRENT_PENALTY: float = 0.001  # λ — 1 mA costs ~1 dB equivalent

# CR-02 (Council R2 P1): per-trial wall-time budget. Phase 158's
# _NGSPICE_TIMEOUT=120s would allow 50×120s=100min worst case — blowing the
# 60s demo budget. ThreadPoolExecutor.result(timeout=TRIAL_TIMEOUT_S) caps
# each trial at 10s; objective returns inf on TimeoutError. Budget math:
# 50 trials × 10s = 500s worst case (still bounded; real CE sims take <2s).
TRIAL_TIMEOUT_S: float = float(os.environ.get("KICAD_AGENT_TRIAL_TIMEOUT_S", "10"))

# CR-03 (Council R2 P1): Ic saturation guard. 2N3904 Ic_max is 200mA
# continuous; 50mA safety. Without this the optimizer would accept trials
# that push R1 to the E12 floor (100Ω) where Ic explodes.
IC_SATURATION_LIMIT_MA: float = 50.0


def objective(trial: optuna.Trial) -> float:
    """Per-trial objective: build circuit, run sim, score.

    Returns float('inf') on simulation failure — Optuna treats this as infeasible.
    """
    r1 = trial.suggest_categorical("r1", E12_RESISTORS)
    r2 = trial.suggest_categorical("r2", E12_RESISTORS)
    r3 = trial.suggest_categorical("r3", E12_RESISTORS)
    r4 = trial.suggest_categorical("r4", E12_RESISTORS)
    c_in = trial.suggest_categorical("c_in", E12_CAPS)
    c_out = trial.suggest_categorical("c_out", E12_CAPS)
    c_emit = trial.suggest_categorical("c_emit", E12_CAPS)

    circuit = build_preamp_circuit(r1, r2, r3, r4, c_in, c_out, c_emit)
    model = get_model("2N3904")
    if model is None:
        return float("inf")
    netlist = model + "\n" + circuit_to_spice_netlist(circuit)
    cir = generate_ac_testbench(
        netlist=netlist, input_node="in", output_node="out",
        freq_start=10.0, freq_stop=1e9, points_per_decade=50,
    )

    # CR-02 (Council R2 P1): per-trial wall-time budget.
    # Daemon thread + queue lets us abandon hung trials without blocking on
    # __exit__ join. ThreadPoolExecutor's context-manager __exit__ joins the
    # worker thread, which defeats the purpose of result(timeout=...) when
    # ngspice hangs. Direct threading.Thread(daemon=True) sidesteps that.
    result_box: list = []  # mutable container so worker thread can write back
    exc_box: list = []

    def _worker() -> None:
        try:
            result_box.append(run_simulation(cir, "ce_preamp_trial", ["ac"]))
        except BaseException as exc:  # noqa: BLE001 — re-raised in caller
            exc_box.append(exc)

    worker = threading.Thread(target=_worker, daemon=True, name="ngspice-trial")
    worker.start()
    worker.join(timeout=TRIAL_TIMEOUT_S)
    if worker.is_alive():
        # Trial exceeded wall-time budget — mark infeasible. The daemon
        # worker continues until its subprocess finishes (or process exit),
        # but we don't wait for it.
        return float("inf")
    if exc_box:
        raise exc_box[0]
    if not result_box:
        return float("inf")
    result = result_box[0]

    ac = result.get_analysis(AnalysisType.AC)
    if ac is None or not ac.passed or ac.gain_db is None:
        return float("inf")

    # Heuristic Ic (mA): (Vcc - Vce_sat) / R1 * 1000
    # Vcc=12, Vce_sat=0.2 — approximation; full .OP analysis deferred to v2.
    ic_ma = (12.0 - 0.2) / r1 * 1000.0

    # CR-03 (Council R2 P1): current-saturation guard.
    # Without this, the (gain_db - 20)^2 term pulls R1 toward the E12 floor
    # (100Ω) where Ic explodes past 2N3904's Ic_max. Reject infeasible.
    if ic_ma > IC_SATURATION_LIMIT_MA:
        return float("inf")

    return (ac.gain_db - TARGET_GAIN_DB) ** 2 + CURRENT_PENALTY * ic_ma


def optimize_preamp(
    n_trials: int = 50,
    seed: int = 42,
    study_name: str = "eurorack_preamp_v1",
) -> optuna.Study:
    """Run Bayesian optimization over E12 values.

    Args:
        n_trials: Number of Optuna trials (GPSampler recommended budget 100-1000).
            Default 50 fits the < 60 s demo budget on Apple Silicon.
        seed: GPSampler seed for deterministic sweeps.
        study_name: Optuna study name (sqlite key).

    Returns:
        Completed optuna.Study. Use study.best_trial for the optimum.
    """
    storage = os.environ.get(
        "OPTUNA_STORAGE",
        "sqlite:///sweeps/eurorack_preamp.db",
    )
    if storage.startswith("sqlite:///"):
        # Ensure the parent directory exists for the default sweeps/ path
        db_path = storage.removeprefix("sqlite:///")
        if not db_path.startswith(":memory:"):
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    # Quiet Optuna logs (default INFO is chatty for 50 trials)
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    sampler = optuna.samplers.GPSampler(seed=seed)
    study = optuna.create_study(
        sampler=sampler,
        storage=storage,
        study_name=study_name,
        direction="minimize",
        load_if_exists=True,
    )
    study.optimize(objective, n_trials=n_trials, n_jobs=1)
    return study
