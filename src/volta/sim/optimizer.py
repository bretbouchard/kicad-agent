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
from pathlib import Path

import optuna

from volta.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist
from volta.spice import (
    AnalysisType,
    generate_ac_testbench,
    get_model,
    run_simulation,
)

# E12 series — 12 values per decade (resistor + cap industry standard).
E12_BASE: tuple[float, ...] = (
    1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2,
)

# Resistors — narrowed per RESEARCH.md L829-836 to fit demo time budget
# (kicad-agent-e2b). Each resistor now has its own per-role range based on
# the CE preamp bias equations rather than a single 100Ω-820kΩ mega-space:
#   R1 (collector load):    1.0k  .. 82k    (2 decades, Vc ~mid-rail)
#   R2 (base bias upper):   10k   .. 820k   (2 decades, ~10x R3)
#   R3 (base bias lower):   1.0k  .. 82k    (2 decades, Vb divider)
#   R4 (emitter degen):     100   .. 8.2k   (2 decades, Ie stability)
# Total search space: ~21k combinations (was 5.3M with the wide range),
# letting GPSampler converge in 15-20 trials instead of 50.
def _e12_range(low_exp: int, high_exp: int) -> tuple[float, ...]:
    """E12 values spanning [10^low_exp, 10^high_exp] inclusive."""
    return tuple(v * 10 ** e for e in range(low_exp, high_exp + 1) for v in E12_BASE)

E12_R1: tuple[float, ...] = _e12_range(3, 4)   # 1.0k .. 82k
E12_R2: tuple[float, ...] = _e12_range(4, 5)   # 10k  .. 820k
E12_R3: tuple[float, ...] = _e12_range(3, 4)   # 1.0k .. 82k
E12_R4: tuple[float, ...] = _e12_range(2, 3)   # 100  .. 8.2k

# E12_RESISTORS retained for backward compat (test_e12_resistors_are_discrete
# asserts on it). Union of all per-role ranges.
E12_RESISTORS: tuple[float, ...] = tuple(sorted(set(
    E12_R1 + E12_R2 + E12_R3 + E12_R4
)))

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
    r1 = trial.suggest_categorical("r1", E12_R1)
    r2 = trial.suggest_categorical("r2", E12_R2)
    r3 = trial.suggest_categorical("r3", E12_R3)
    r4 = trial.suggest_categorical("r4", E12_R4)
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

    # kicad-agent-8vv: prefer measured Ic from .OP analysis (op:i(vcc)_ma
    # trace, populated when generate_ac_testbench has include_op=True which
    # is the default). Falls back to the (Vcc-Vce_sat)/R1 heuristic if the
    # OP trace isn't present (e.g., pure-AC testbench or older ngspice).
    op_vcc_trace = next(
        (t for t in ac.traces if t.name == "op:i(vcc)_ma"), None
    )
    if op_vcc_trace is not None and op_vcc_trace.values:
        ic_ma = float(op_vcc_trace.values[0])
    else:
        # Heuristic fallback: (Vcc - Vce_sat) / R1 * 1000.
        # Vcc=12, Vce_sat=0.2 — overestimates Ic, conservative for saturation guard.
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
    # kicad-agent-233: Optuna sqlite storage now lives in a stable user-data
    # dir, not cwd. Default:
    #   macOS:   ~/Library/Application Support/kicad-agent/sweeps/eurorack_preamp.db
    #   Linux:   ${XDG_DATA_HOME:-~/.local/share}/kicad-agent/sweeps/eurorack_preamp.db
    # Override with OPTUNA_STORAGE env var (must be a full sqlite:///<abs_path>
    # URL — relative paths still go to cwd to support tests via tmp_path).
    import sys
    storage = os.environ.get("OPTUNA_STORAGE")
    if storage is None:
        if sys.platform == "darwin":
            data_base = Path.home() / "Library" / "Application Support"
        else:
            data_base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        sweeps_dir = data_base / "kicad-agent" / "sweeps"
        sweeps_dir.mkdir(parents=True, exist_ok=True)
        storage = f"sqlite:///{sweeps_dir / 'eurorack_preamp.db'}"
    if storage.startswith("sqlite:///"):
        db_path = storage.removeprefix("sqlite:///")
        if not db_path.startswith(":memory:"):
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    # Quiet Optuna logs (default INFO is chatty for 50 trials)
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # GPSampler is marked ExperimentalWarning by Optuna. Phase 199's pytest.ini
    # uses --strict-markers + filterwarnings=error which turns warnings into
    # test failures. Suppress the experimental warning here (we accept the API
    # stability risk per RESEARCH.md).
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
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
