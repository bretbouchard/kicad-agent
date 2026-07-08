# Phase 204: Closed-Box Simulation Pipeline v1 — Eurorack Magic Proof — Context

**Gathered:** 2026-07-07
**Status:** Ready for planning
**Source:** Inline from conversational design session (4 research rounds + Eurorack pivot + Phase 158 closeout)

<domain>
## Phase Boundary

Build the **optimization + testing + dataframe + demo layer** ON TOP of Phase 158's existing `src/kicad_agent/spice/` foundation. Prove the closed-box magic end-to-end on a **Eurorack input preamp** canonical example: "give me a 20 dB preamp" → Optuna sweeps E12 resistor values → ngspice verifies → pytest asserts → Bode PNG + BOM markdown emit.

**Phase 204 does NOT:**
- Rewrite or replace `src/kicad_agent/spice/` (Phase 158 foundation is consumed as-is)
- Switch to PySpice (dead project — banned per design decision)
- Build a new ngspice subprocess wrapper (Phase 158's `ngspice_runner.py` is the runner)
- Replace `SimulationResult` types (Phase 158's `types.py` is the canonical result type)
- Add IPC standards / DRC compliance (deferred — separate phase)
- Add UI/chat layer (Track D work, separate phases)
- Train AI models (Phase 159+ territory)

</domain>

<decisions>
## Implementation Decisions (LOCKED from conversation)

### Architecture
- **Reuse, don't rewrite.** Phase 204 builds on `src/kicad_agent/spice/`. New package is `src/kicad_agent/sim/` (sibling, not child — clean separation between "run a SPICE sim" and "optimize + analyze + demo a SPICE sim").
- **Subprocess, not PySpice.** PySpice is dead (last release 2021, broken on ngspice 41+). Phase 158's `ngspice_runner.run_simulation()` is the only SPICE entry point.
- **Optuna GPSampler primary.** v4.5+ shipped Sep 2025. Bayesian optimization built-in. `sqlite:///` storage for resumable sweeps. `trial.suggest_categorical("r1", E12_SERIES)` solves discrete-value constraint natively.
- **Pareto via Optuna NSGA-IISampler.** Multi-objective (gain vs current) in v1 — Optuna's built-in NSGA-II is sufficient. Defer pymoo to v2.

### Canonical Example (Eurorack Input Preamp)
- **Topology:** Single NPN common-emitter — `2N3904` (universal, ngspice has built-in model)
- **Power rails:** ±12 V (Eurorack standard)
- **Target gain:** 20 dB (×10) at audio frequencies
- **Target bandwidth:** 20 Hz – 20 kHz (±3 dB)
- **Input impedance:** ~1 MΩ (high-Z for guitar/synth pickup)
- **Optimization variables:** R1 (collector), R2 (base bias upper), R3 (base bias lower), R4 (emitter), C_in, C_out, C_emitter bypass — 4 resistors from E12 series, 3 caps from E12 series
- **Objective:** `minimize (gain_db - 20)^2 + λ * icollector` (single objective with current penalty for v1)
- **Stupid-proof assertion:** `assert gain_db >= 17` (20 dB - 3 dB tolerance) AND `assert bandwidth_hz >= 15_000`

### Hardware-as-Code Test Pattern
- **pytest fixtures:** session-scoped `eurorack_preamp` builds SKiDL Circuit + runs baseline sim ONCE, returns `(circuit, SimulationResult)`. Tests assert on the cached result.
- **BLK-1 strict:** No skip-guards (`if result is None: return`). Tests MUST assert on real numbers, like Phase 158's existing `test_ac_simulation_produces_gain`.
- **First test:** `test_eurorack_preamp_meets_target_gain` — `assert gain_db >= 17`

### Pandas DataFrame Adapter
- **Adapter, not replacement.** Phase 158's `SimulationResult` (frozen dataclass) stays canonical. The pandas adapter is a **view**: `to_dataframe(result) -> pd.DataFrame` where columns are nets and rows are sweep points.
- **Sweep-aware:** `to_dataframe(study_results: list[SimulationResult]) -> pd.DataFrame` flattens Optuna trial outcomes into a tidy DataFrame with one row per trial.

### End-to-End Demo
- **Script:** `scripts/demo_closed_box.py`
- **Time budget:** < 60 s on Apple Silicon (M-series)
- **Outputs:** `bode.png` (matplotlib Bode plot of chosen circuit), `bom.md` (Markdown BOM with values + part numbers), stdout summary (chosen R values, gain, bandwidth)
- **Exit code:** 0 on success, non-zero if assertion fails

### Infrastructure
- **ngspice install:** `brew install ngspice` (macOS) / `apt install ngspice` (Linux). External CLI dependency, not bundled. README + CLAUDE.md document this.
- **Python deps added to pyproject.toml:** `pandas>=2.0`, `matplotlib>=3.7`, `optuna>=4.5`
- **CLAUDE.md tool inventory:** add ngspice + Optuna patterns

### Stupid-Proof Principle (BOTH flavors required)
- **User-stupid guardrails:** Demo script fails with clear error if ngspice not on PATH. Convergence failures produce actionable error messages, not stack traces.
- **Magic-stupid zero friction:** One command (`python3 scripts/demo_closed_box.py`) produces everything. No manual netlist writing. No manual resistor picking. No manual SPICE setup.

### Claude's Discretion
- Internal Optuna trial allocation strategy (GPSampler hyperparameters, n_trials, parallel jobs)
- Exact matplotlib style/seaborn-style choices for Bode plot
- Exact docstring format (Google-style inferred from existing src/kicad_agent/spice/)
- Internal helper function decomposition in optimizer.py / dataframe.py
- Whether to extend `model_registry.py` to add `2N3904` model or rely on ngspice's built-in (`Q2N3904`)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 158 Foundation (BUILD ON TOP — DO NOT REWRITE)
- `src/kicad_agent/spice/__init__.py` — Public API (15 symbols: run_simulation, generate_*_testbench, compute_degradation, is_simulatable, get_model, UNSIMULATABLE, types)
- `src/kicad_agent/spice/types.py` — Canonical result types (`SimulationResult`, `AnalysisResult`, `Trace`, `DegradationReport` — frozen dataclasses)
- `src/kicad_agent/spice/ngspice_runner.py` — ngspice CLI subprocess wrapper (THE entry point for sims)
- `src/kicad_agent/spice/testbench.py` — AC/TRAN/NOISE/THD testbench generators (USE `generate_ac_testbench`)
- `src/kicad_agent/spice/model_registry.py` — SPICE model lookup (add `2N3904` here or rely on ngspice built-in)
- `tests/spice/test_spice.py` — BLK-1 strict test pattern (model for new tests)

### Existing SKiDL Integration
- `src/kicad_agent/circuit_ir/skidl_circuit.py` — Build skidl.Circuit from KiCad schematic (lines 39-89)
- `src/kicad_agent/circuit_ir/skidl_emitter.py` — Emit SKiDL Python source (lines 69, 150 reference KiCad symbol paths)
- `src/kicad_agent/circuit_ir/topology_from_skidl.py` — skidl.Circuit → CircuitTopology (lines 38, 196)

### GSD Phase Tracking
- `.planning/phases/158-spice-pipeline/SUMMARY.md` — Phase 158 closeout (what shipped, what's deferred to 204)
- `.planning/ROADMAP.md` — Phase 204 entry with full deliverables list

### Coding Standards (MANDATORY)
- `CLAUDE.md` (project root) — tool inventory, conventions, agent rules
- `~/.claude/rules/coding-style.md` — immutability (frozen dataclasses), file size (200-400 lines), no mutation

### Strategic Context
- `docs/GAP_ANALYSIS.md` — Eurorack identified as highest-leverage untapped market (50K+ users)
- `docs/PRODUCT_DESCRIPTION.md` — Closed-box vision: "intent → verified hardware"

</canonical_refs>

<specifics>
## Specific Ideas

### Optimization Loop Sketch
```python
import optuna

E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E12_DECADES = [v * 10**e for e in range(3) for v in E12]  # 10Ω .. 8.2kΩ

def objective(trial: optuna.Trial) -> float:
    r1 = trial.suggest_categorical("r1", E12_DECADES)
    r2 = trial.suggest_categorical("r2", E12_DECADES)
    # ... build SKiDL Circuit, emit netlist, run ngspice via Phase 158 runner
    sim = run_simulation(testbench, "ce_preamp", analyses=["ac"])
    ac = sim.get_analysis(AnalysisType.AC)
    if not ac.passed or ac.gain_db is None:
        return float("inf")
    return (ac.gain_db - 20.0) ** 2 + 0.001 * icollector_ma

study = optuna.create_study(
    sampler=optuna.samplers.GPSampler(),
    storage="sqlite:///sweeps/eurorack_preamp.db",
    direction="minimize",
)
study.optimize(objective, n_trials=50, n_jobs=4)
```

### DataFrame Adapter Sketch
```python
import pandas as pd
from kicad_agent.spice import SimulationResult, AnalysisType

def to_dataframe(result: SimulationResult) -> pd.DataFrame:
    """One column per net, one row per frequency point (for AC)."""
    ac = result.get_analysis(AnalysisType.AC)
    if ac is None or not ac.traces:
        return pd.DataFrame()
    data = {t.name: t.values for t in ac.traces}
    index = ac.traces[0].scale if ac.traces else None
    return pd.DataFrame(data, index=index)

def study_to_dataframe(study: optuna.Study) -> pd.DataFrame:
    """One row per Optuna trial: params + objective value + gain/bw."""
    rows = []
    for trial in study.trials:
        if trial.state == optuna.trial.TrialState.COMPLETE:
            row = {"value": trial.value, **trial.params}
            rows.append(row)
    return pd.DataFrame(rows)
```

### Pytest Fixture Pattern
```python
# tests/sim/conftest.py
import pytest
from kicad_agent.sim.eurorack import build_preamp_circuit, build_testbench
from kicad_agent.spice import run_simulation, SimulationResult

@pytest.fixture(scope="session")
def eurorack_preamp() -> tuple:
    """Build + sim the canonical Eurorack preamp once per session."""
    circuit = build_preamp_circuit(r1=4.7e3, r2=22e3, r3=2.2e3, r4=470, ...)
    testbench = build_testbench(circuit)
    result = run_simulation(testbench, "eurorack_preamp", analyses=["ac", "noise"])
    return circuit, result
```

### Demo Script Structure
```
scripts/demo_closed_box.py
├── 1. Parse args (target_gain_db default 20)
├── 2. Run Optuna sweep (50 trials, GPSampler, sqlite storage)
├── 3. Pick best trial → build final SKiDL Circuit
├── 4. Verify with ngspice → SimulationResult
├── 5. Assert gain_db >= target - 3 (BLK-1 strict)
├── 6. Generate bode.png (matplotlib)
├── 7. Generate bom.md (Jinja2 template or f-string)
└── 8. Print summary + exit
```

### 2N3904 ngspice Model
- ngspice ships with `Q2N3904` built-in model (NPN general purpose)
- Or use standard Gummel-Poon: `.MODEL 2N3904 NPN(Is=6.734f Xti=3 Eg=1.11 Vaf=74.03 Bf=416.4 Ne=1.259 Ise=6.734f Ikf=66.78m Xtb=1.5 Br=.7371 Nc=2 Isc=0 Ikr=0 Rc=1 Cjc=3.638p Mjc=.3085 Vjc=.75 Fc=.5 Cje=4.493p Mje=.2593 Vje=.75 Tr=239.5n Tf=301.2p Itf=.4 Vtf=4 Xtf=2)`
- Decision: add `2N3904` to `model_registry.SPICE_MODELS` as a `.MODEL` (not `.SUBCKT` — transistor, not IC)

</specifics>

<deferred>
## Deferred Ideas

### Deferred to Phase 204b (or v2)
- **pymoo NSGA-II Pareto fronts** — Optuna's NSGA-IISampler is sufficient for v1; pymoo produces cleaner Pareto fronts for "show tradeoffs" UI later
- **spicelib SimRunner upgrade** — Phase 158 uses raw subprocess; spicelib's SimRunner offers better parallel batch + recovery. Defer until needed for >4 parallel sims
- **Monte Carlo / Worst-Case Analysis** — spicelib has built-in `Montecarlo` and `WorstCaseAnalysis` classes. Defer until tolerance analysis matters
- **Multi-stage Eurorack module** (VCA, VCF, VCO) — Phase 204 proves the magic on single-stage CE preamp; complex topologies come later
- **Template publishing** — Eurorack preamp becomes a reusable White Room template once Phase 204 ships. Track in backlog
- **AI reviewer layer** — "AI critiques the optimized circuit" — out of scope, separate phase

### Deferred to Other Phases (NOT Phase 204)
- **IPC standards (trace width vs current, annular rings, clearance)** — DRC layer work, Phase 99+ hardening territory
- **IEC 61010 safety compliance** — compliance-rick territory, separate milestone
- **Cost estimation ("this board costs $X at JLC")** — separate BOM/pricing phase
- **Interactive web preview** — Track D (UI shell) work
- **NL → SKiDL fine-tuned LLM** — Phase 160+ territory

</deferred>

---

*Phase: 204-closed-box-simulation-pipeline-v1-skidl-spice-optuna-pytest*
*Context gathered: 2026-07-07 via inline conversational design session (4 research rounds + Eurorack pivot + Phase 158 closeout)*
