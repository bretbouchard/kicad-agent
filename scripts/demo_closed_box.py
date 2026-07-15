#!/usr/bin/env python3
"""Phase 204: Closed-box demo -- "give me a 20 dB Eurorack preamp".

Pipeline:
    1. Check ngspice on PATH (user-stupid guardrail, fails clear).
    2. Optuna GPSampler sweeps E12 R/C values (default 50 trials).
    3. Rebuild the best-trial circuit, verify with ngspice.
    4. BLK-1 assert: gain_db >= 17 (target 20, tolerance 3).
    5. Emit bode.png (matplotlib) and bom.md (markdown table).
    6. Print summary + input-Z scope note + exit 0.

Usage:
    python3 scripts/demo_closed_box.py
    python3 scripts/demo_closed_box.py --n-trials 30 --target-gain-db 20

Time budget: ~200 s on Apple Silicon with 50 trials (~4 s per ngspice trial).
Pass --n-trials 10 for a ~45 s smoke run.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

GAIN_FLOOR_DB = 17.0  # BLK-1 strict: target 20 dB - 3 dB tolerance

# Approximate input Z for CE topology (RESEARCH.md A6 -- r_pi of 2N3904 at Ic~1mA).
# Used for the scope-gap note only; not asserted.
APPROX_INPUT_Z_KOHM = 8.7


def check_ngspice() -> None:
    """Exit with clear error if ngspice not on PATH. No traceback."""
    if shutil.which("ngspice") is not None:
        return
    sys.stderr.write(
        "ERROR: ngspice CLI not found on PATH.\n"
        "Install with:\n"
        "  macOS:  brew install ngspice\n"
        "  Linux:  apt install ngspice  (or dnf install ngspice)\n"
        "Then re-run: python3 scripts/demo_closed_box.py\n"
    )
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Closed-box Eurorack preamp demo")
    parser.add_argument("--n-trials", type=int, default=20,
                        help="Optuna trials (default 20, ~5s/trial = ~100s total; "
                             "volta-e2b fix — narrowed E12 ranges let GPSampler "
                             "converge in 15-20 trials instead of 50)")
    parser.add_argument("--target-gain-db", type=float, default=20.0,
                        help="Target gain in dB (default 20)")
    parser.add_argument("--seed", type=int, default=42,
                        help="GPSampler seed (default 42 for determinism)")
    parser.add_argument("--bode", default="bode.png",
                        help="Output Bode PNG path (default ./bode.png)")
    parser.add_argument("--bom", default="bom.md",
                        help="Output BOM markdown path (default ./bom.md)")
    args = parser.parse_args()

    check_ngspice()

    # Late imports -- only after ngspice check passes (faster failure)
    from volta.sim import (
        build_preamp_circuit, circuit_to_spice_netlist,
        circuit_to_bom_markdown, optimize_preamp, plot_bode,
    )
    from volta.spice import (
        AnalysisType, generate_ac_testbench, get_model, run_simulation,
    )

    print("=== Closed-Box Eurorack Preamp Demo ===")
    print(f"n_trials={args.n_trials}  target={args.target_gain_db} dB  seed={args.seed}")
    t0 = time.time()

    # --- 1. Optuna sweep ---
    study = optimize_preamp(n_trials=args.n_trials, seed=args.seed)
    sweep_s = time.time() - t0
    best = study.best_trial
    print(f"Sweep: {sweep_s:.1f}s, best objective={best.value:.4g}")
    print(f"Best params: r1={best.params['r1']}  r2={best.params['r2']}  "
          f"r3={best.params['r3']}  r4={best.params['r4']}")
    print(f"            c_in={best.params['c_in']}  c_out={best.params['c_out']}  "
          f"c_emit={best.params['c_emit']}")

    # --- 2. Rebuild + verify best trial ---
    circuit = build_preamp_circuit(
        best.params["r1"], best.params["r2"], best.params["r3"], best.params["r4"],
        best.params["c_in"], best.params["c_out"], best.params["c_emit"],
    )
    model = get_model("2N3904")
    assert model is not None, "2N3904 missing from registry"
    netlist = model + "\n" + circuit_to_spice_netlist(circuit)
    cir = generate_ac_testbench(
        netlist=netlist, input_node="in", output_node="out",
        freq_start=10.0, freq_stop=1e9, points_per_decade=50,
    )
    result = run_simulation(cir, "eurorack_demo_final", analyses=["ac"])
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None and ac.passed, f"verify sim failed: {result.log[-500:]}"
    assert ac.gain_db is not None, "verify sim: gain_db is None"
    assert ac.bandwidth_hz is not None, "verify sim: bandwidth_hz is None"
    print(f"Verified: gain_db={ac.gain_db:.2f}  bandwidth_hz={ac.bandwidth_hz:.0f}")

    # --- 3. BLK-1 strict assertion ---
    assert ac.gain_db >= GAIN_FLOOR_DB, (
        f"BLK-1 FAIL: gain {ac.gain_db:.2f} < floor {GAIN_FLOOR_DB} dB"
    )

    # --- 4. Emit artifacts ---
    plot_bode(result, save_path=args.bode,
              title=f"Eurorack Preamp (target {args.target_gain_db} dB)")
    bom_md = circuit_to_bom_markdown(circuit)
    Path(args.bom).write_text(bom_md, encoding="utf-8")
    print(f"Emitted: {args.bode} ({Path(args.bode).stat().st_size} B), "
          f"{args.bom} ({Path(args.bom).stat().st_size} B)")

    # --- 5. Summary (with input-Z scope note per Stupid-Proof Principle) ---
    total_s = time.time() - t0
    print(f"\n=== COMPLETE: {total_s:.1f}s ===")
    print(f"Gain:    {ac.gain_db:.2f} dB (target {args.target_gain_db}, floor {GAIN_FLOOR_DB})")
    print(f"BW:      {ac.bandwidth_hz:.0f} Hz")
    n_complete = sum(1 for t in study.trials if t.state.name == "COMPLETE")
    print(f"Trials:  {len(study.trials)} ({n_complete} complete)")
    # HONEST scope-gap disclosure: CE topology can't hit 1 MOhm input Z (CONTEXT.md target).
    # Real 1 MOhm needs JFET input stage -- deferred to v2 per RESEARCH.md A6.
    print(f"NOTE: input Z ≈ {APPROX_INPUT_Z_KOHM:.1f} kΩ (target 1 MΩ -- real 1 MΩ "
          f"needs JFET input, deferred to v2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
