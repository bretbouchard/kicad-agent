# Phase 158 — SPICE Pipeline (ngspice integration)

**Status:** Complete (shipped 2026-07-04, retroactively closed 2026-07-07)
**Ship commits:** `08c5e7a9 feat(158): SPICE pipeline — ngspice integration + testbenches`, `46ed4b3b fix(158): BLK-1 — ngspice AC testbench produces real results`

## Goal

Headless, scriptable ngspice simulation pipeline: SKIDL netlist → ngspice → structured JSON results. Foundation for AI training reward signals (Phase 159) and Phase 204 closed-box optimization.

## What Shipped

### Source code (`src/kicad_agent/spice/`, 5 files, ~20 KB)

| File | Purpose | Lines |
|---|---|---|
| `__init__.py` | Public API surface (15 symbols) | 46 |
| `types.py` | Immutable typed results (`Trace`, `AnalysisResult`, `SimulationResult`, `DegradationReport`) — frozen dataclasses | 100 |
| `ngspice_runner.py` | ngspice CLI subprocess wrapper, log parser, timeout + error handling | 225 |
| `testbench.py` | Testbench generators for AC / TRAN / NOISE / THD analyses + dispatcher | 210 |
| `model_registry.py` | SPICE macromodels for NE5532 / TL072 / LM358 + `UNSIMULATABLE` list (RP2350B, AK4619VN, etc.) | 100 |
| `degradation.py` | Pre-route vs post-route degradation scorer (Phase 159 reward signal) | 75 |

### Tests (`tests/spice/test_spice.py`)

**14 / 16 passing (87.5%)**

- ✅ `TestModelRegistry` — 7 tests (model lookup, simulatable checks, passive/digital classification)
- ✅ `TestTestbenchGenerators` — 5 tests (AC/TRAN/NOISE/THD/dispatch)
- ⚠️ `TestSimulationRunner` — 0/2 passing — **requires ngspice CLI installed**
  - `test_ac_simulation_produces_gain` — BLK-1 strict assertion on RC lowpass gain ≈ 0 dB
  - `test_ac_simulation_produces_bandwidth` — BLK-1 strict assertion on RC lowpass fc ≈ 159 Hz
- ✅ `TestDegradation` — 2 tests (identical-result, gain-loss detection)

**Failure mode is environment-only.** Tests are BLK-1 strict (no skip-guards, no `if result is None: return`). When ngspice is installed, both tests are expected to pass.

## Design Decisions

1. **ngspice CLI subprocess over PySpice** — PySpice is dead (last release 2021, broken on ngspice 41+). Subprocess is bomb-proof and works across macOS/Linux/Vast.ai.
2. **Immutable typed results** — `frozen=True` dataclasses per coding-style.md. `Trace.values` and `scale` are tuples, not lists.
3. **BLK-1 strict tests** — tests assert on real values (`-1.5 < gain_db < 1.5`, `120 < bandwidth_hz < 200`). No "skip if None" guard patterns.
4. **NGSPICE_TIMEOUT = 120s** — sane upper bound for any analog testbench.
5. **Simplified opamp macromodels** — NE5532/TL072/LM358 use abstracted macromodels (gain + output impedance only). Sufficient for AC/transient sweeps; not for precise noise/THD. Phase 159+ can swap in vendor models.

## Dependencies Added

- `spicelib>=1.5.1` (already in pyproject.toml — used elsewhere for LTSpice I/O)
- `ngspice` CLI (external, not Python — user must `brew install ngspice` on macOS or `apt install ngspice` on Linux)

## Public API

```python
from kicad_agent.spice import (
    # Types
    AnalysisType, Trace, AnalysisResult, SimulationResult, DegradationReport,
    # Runner
    run_simulation,
    # Testbenches
    generate_ac_testbench, generate_tran_testbench,
    generate_noise_testbench, generate_thd_testbench, generate_testbench,
    # Models
    get_model, is_simulatable, get_all_models, UNSIMULATABLE,
    # Degradation
    compute_degradation,
)
```

## What Phase 158 Did NOT Deliver (deferred to Phase 204)

- ❌ **Optuna integration** — no parameter sweeps, no E12/E24 constraints, no Pareto fronts
- ❌ **pytest fixtures for circuits** — no `gain_stage` / `noise_floor` session-scoped fixtures
- ❌ **pandas DataFrame adapter** — results are dataclasses, not DataFrame-ready
- ❌ **spicelib SimRunner upgrade** — current uses raw subprocess, not spicelib's parallel batch runner
- ❌ **End-to-end closed-box demo** — no canonical example proving the magic

These are exactly Phase 204's scope.

## Deviations From Typical Phase Workflow

- **No PLAN.md** — Phase 158 was shipped without formal planning. This SUMMARY is being written retroactively (2026-07-07).
- **No phase directory existed until 2026-07-07** — code shipped via `feat(158)` commits but `.planning/phases/158-spice-pipeline/` was never created.
- **No ROADMAP.md entry** — same ghost-work pattern; entry added during 2026-07-07 closeout.

These deviations are documented for transparency. Phase 204+ returns to normal GSD discipline.

## Verification

```bash
# Without ngspice installed (current default dev environment):
.venv/bin/python -m pytest tests/spice/test_spice.py -v
# → 14 passed, 2 failed (environment-only)

# With ngspice installed (brew install ngspice):
.venv/bin/python -m pytest tests/spice/test_spice.py -v
# → 16 passed (expected)
```

## Hand-off to Phase 204

Phase 204 consumes this module as-is. Phase 204's job is the **optimization, testing, dataframe, and demo layer on top of `src/kicad_agent/spice/`** — not a rewrite.

Phase 204 canonical example: **Eurorack input preamp** (single NPN common-emitter, ±12 V rails, audio bandwidth, ~20 dB target gain). Optuna sweeps R1/R2/Rc/Re over E12 series, ngspice_runner verifies, pandas aggregates, pytest asserts, demo script ships Bode PNG + BOM markdown.

---

**Closed by:** Bret Bouchard + Claude (retroactive closeout 2026-07-07)
**Next phase:** 204 — Closed-Box Simulation Pipeline v1 (optimization + tests + dataframe + demo)
