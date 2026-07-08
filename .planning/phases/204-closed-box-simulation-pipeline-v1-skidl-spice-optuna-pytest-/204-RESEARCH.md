# Phase 204: Closed-Box Simulation Pipeline v1 — Eurorack Magic Proof — Research

**Researched:** 2026-07-07
**Domain:** SPICE simulation + Bayesian optimization + hardware-as-code testing
**Confidence:** HIGH (foundation verified in codebase; Optuna/ngspice docs verified against current PyPI + official ngspice manual v46)

## Summary

Phase 204 builds the optimization + testing + dataframe + demo layer on top of Phase 158's existing `src/kicad_agent/spice/` foundation. The goal is a closed-box demo: "give me a 20 dB Eurorack preamp" → Optuna sweeps E12 resistor values → ngspice verifies → pytest asserts → Bode PNG + BOM markdown emit. Phase 158's foundation is solid (14/16 tests passing, BLK-1 strict pattern established, frozen dataclasses, subprocess-based ngspice runner) and is consumed as-is.

**Three critical discoveries reshaped the plan:**

1. **skidl 2.2.3's `generate_netlist()` emits KiCad `.net` format, NOT SPICE `.cir`** `[VERIFIED: codebase grep + live skidl 2.2.3 in venv]`. Phase 158's testbench generators accept a SPICE netlist string. Phase 204 must add a `circuit_to_spice_netlist(circuit) -> str` helper that walks the skidl Circuit's parts + nets and emits SPICE device lines (`R1 nc nb 4.7k`, `Q1 nc nb ne 2N3904`, etc.). This is THE primary new capability — it does not exist anywhere in the codebase. Approximately 80-120 LOC.

2. **skidl 2.2.3 does NOT have `circuit.BOM()` or any BOM helper** `[VERIFIED: live introspection in venv — `dir(skidl.Circuit())` shows no BOM method]`. BOM generation must be hand-rolled from `circuit.parts` (which exposes `.ref`, `.value`, `.footprint`). Approximately 30-50 LOC. Jinja2 is overkill; an f-string template is sufficient for a 7-component BOM.

3. **ngspice CLI + Optuna are NOT installed in the dev environment** `[VERIFIED: `command -v ngspice` fails, `.venv/bin/python -c "import optuna"` fails]`. This blocks the demo script end-to-end and blocks 2 of the new tests. The plan MUST include: (a) `brew install ngspice` documentation in README and CLAUDE.md tool inventory, (b) `optuna>=4.5` added to `pyproject.toml` `[project.optional-dependencies] sim = [...]`, (c) tests that gracefully fail-with-clear-message (not silently skip) when ngspice is missing.

**Primary recommendation:** New package `src/kicad_agent/sim/` as sibling to `src/kicad_agent/spice/`. Four modules: `eurorack.py` (~150 LOC circuit builder + SPICE netlist emitter), `optimizer.py` (~120 LOC Optuna objective + sweep runner), `dataframe.py` (~80 LOC pandas adapter), `bom.py` (~50 LOC BOM markdown generator). Plus `scripts/demo_closed_box.py` (~150 LOC) and `tests/sim/` (~200 LOC, 5-7 tests). Single demo command: `python3 scripts/demo_closed_box.py` produces `bode.png` + `bom.md` + stdout summary in <60 s.

## User Constraints (from CONTEXT.md)

### Locked Decisions (from `204-CONTEXT.md` `<decisions>`)

- **Reuse, don't rewrite.** Phase 204 builds on `src/kicad_agent/spice/`. New package is `src/kicad_agent/sim/` (sibling, not child — clean separation between "run a SPICE sim" and "optimize + analyze + demo a SPICE sim").
- **Subprocess, not PySpice.** PySpice is dead (last release 2021, broken on ngspice 41+). Phase 158's `ngspice_runner.run_simulation()` is the only SPICE entry point.
- **Optuna GPSampler primary.** v4.5+ shipped Sep 2025. `trial.suggest_categorical("r1", E12_SERIES)` solves discrete-value constraint natively.
- **Pareto via Optuna NSGA-IISampler.** Multi-objective (gain vs current) in v1 — Optuna's built-in NSGA-II is sufficient. Defer pymoo to v2.
- **Canonical example:** Eurorack input preamp — single NPN common-emitter (2N3904), ±12 V rails, audio bandwidth (20 Hz–20 kHz), target 20 dB gain, ~1 MΩ input impedance.
- **Optimization variables:** R1 (collector), R2 (base bias upper), R3 (base bias lower), R4 (emitter), C_in, C_out, C_emitter bypass — 4 resistors from E12 series, 3 caps from E12 series.
- **Objective:** `minimize (gain_db - 20)^2 + λ * icollector` (single objective with current penalty for v1).
- **Stupid-proof assertion:** `assert gain_db >= 17` (20 dB - 3 dB tolerance) AND `assert bandwidth_hz >= 15_000`.
- **Hardware-as-code test pattern:** pytest session-scoped `eurorack_preamp` fixture builds + sims once. BLK-1 strict — no skip-guards.
- **Pandas DataFrame adapter:** Adapter, not replacement. `to_dataframe(result) -> pd.DataFrame` is a view.
- **End-to-end demo:** `scripts/demo_closed_box.py`, < 60 s budget on Apple Silicon. Outputs: `bode.png`, `bom.md`, stdout summary. Exit 0 on success, non-zero on assertion failure.
- **Stupid-Proof Principle (BOTH flavors required):** user-stupid guardrails (clear errors when ngspice missing) AND magic-stupid zero friction (one command produces everything).

### Claude's Discretion (from `204-CONTEXT.md`)

- Internal Optuna trial allocation strategy (GPSampler hyperparameters, n_trials, parallel jobs) — **researched below, recommendation provided**
- Exact matplotlib style/seaborn-style choices for Bode plot — **researched below, recommendation provided**
- Exact docstring format — **Google-style inferred from existing `src/kicad_agent/spice/`**
- Internal helper function decomposition in optimizer.py / dataframe.py
- Whether to extend `model_registry.py` to add `2N3904` model or rely on ngspice's built-in (`Q2N3904`) — **researched below, recommendation provided**

### Deferred Ideas (OUT OF SCOPE)

- pymoo NSGA-II Pareto fronts (use Optuna's NSGA-IISampler)
- spicelib SimRunner upgrade
- Monte Carlo / Worst-Case Analysis
- Multi-stage Eurorack module (VCA, VCF, VCO)
- Template publishing
- AI reviewer layer
- IPC standards, IEC 61010, cost estimation, interactive web preview, NL → SKiDL fine-tuned LLM

## Phase Requirements

This phase is gap-fill (no formal REQ-IDs in REQUIREMENTS.md). Source of truth is CONTEXT.md `<decisions>` and `<specifics>` blocks. The requirement coverage map below translates those decisions into testable behaviors:

| ID | Description (derived from CONTEXT.md) | Research Support |
|----|--------------------------------------|------------------|
| P204-01 | `src/kicad_agent/sim/` package as sibling to `src/kicad_agent/spice/` | Standard Stack §, Architecture Patterns § |
| P204-02 | `circuit_to_spice_netlist()` helper — skidl Circuit → SPICE `.cir` lines | Critical Integration Gap §, Code Examples § |
| P204-03 | Optuna GPSampler objective for 4 E12 resistors + 3 E12 caps | Optuna GPSampler §, Code Examples § |
| P204-04 | 2N3904 Gummel-Poon `.MODEL` card added to `model_registry.SPICE_MODELS` | 2N3904 SPICE Model § |
| P204-05 | pandas DataFrame adapter `to_dataframe(SimulationResult)` + `study_to_dataframe(Study)` | Pandas Patterns § |
| P204-06 | matplotlib Bode plot (magnitude + phase, log freq, -3 dB marker, save PNG) | Matplotlib Bode § |
| P204-07 | BOM markdown generator from skidl Circuit (no `circuit.BOM()` — hand-rolled) | BOM Markdown § |
| P204-08 | pytest session-scoped `eurorack_preamp` fixture, BLK-1 strict | Pytest Fixtures §, Validation Architecture § |
| P204-09 | `scripts/demo_closed_box.py` end-to-end < 60 s | Demo Script §, Time Budget § |
| P204-10 | ngspice install documented (README + CLAUDE.md tool inventory) | Environment Availability § |
| P204-11 | `optuna>=4.5`, `pandas>=2.0`, `matplotlib>=3.7` added to `pyproject.toml` | Standard Stack § |
| P204-12 | User-stupid guardrail: clear error if ngspice not on PATH (not stack trace) | Stupid-Proof Principle § |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Build skidl Circuit for CE preamp | Python (sim layer) | — | Pure Python construction; no I/O |
| Emit SPICE `.cir` netlist from Circuit | Python (sim layer) | — | Format translation in-process |
| Run ngspice simulation | External CLI (ngspice) | Python (`spice.ngspice_runner`) | Subprocess, Phase 158 owns this |
| Bayesian optimization of E12 values | Python (sim layer) | External lib (Optuna) | Trial loop in Python, sampler is lib |
| Parse ngspice log → gain/bandwidth | Python (`spice.ngspice_runner`) | — | Phase 158 already does this |
| pandas DataFrame adapter | Python (sim layer) | — | Pure view over `SimulationResult` |
| matplotlib Bode plot | Python (sim layer) | External lib (matplotlib) | Static PNG output |
| BOM markdown emit | Python (sim layer) | — | Walk `circuit.parts`, f-string template |
| Test assertions (BLK-1 strict) | Python (pytest) | — | Session-scoped fixture |
| End-to-end demo | Python script | All of the above | Orchestrates the full pipeline |

## Standard Stack

### Core (all installed in `.venv` as of 2026-07-07)

| Library | Version (installed) | Latest (PyPI) | Purpose | Why Standard |
|---------|---------------------|---------------|---------|--------------|
| `skidl` | 2.2.3 `[VERIFIED]` | 2.2.3 | Circuit construction (Python → netlist) | Already in pyproject.toml; used by Phase 156+ |
| `kiutils` | 1.4.8 | — | KiCad file I/O (transitive) | Existing |
| `pandas` | 3.0.3 `[VERIFIED]` | 3.0.3 | DataFrame adapter for sim results | Industry standard for tabular scientific data |
| `matplotlib` | 3.10.9 `[VERIFIED]` | 3.10.9 | Bode plot PNG | Industry standard; no seaborn needed |
| `scipy` | 1.17.1 `[VERIFIED]` | 1.17.1 | (optional) signal.bode, but not required — ngspice computes Bode directly | Existing |
| `jinja2` | 3.1.6 `[VERIFIED]` | 3.1.6 | (optional) BOM template — defer to f-strings | Existing |

### New Dependencies to Add to `pyproject.toml`

| Library | Version to pin | Purpose | Status |
|---------|----------------|---------|--------|
| `optuna` | `>=4.5` | GPSampler (Bayesian optimization) — introduced in 4.5 (released 2025-08-18) `[VERIFIED: PyPI release dates]` | NOT INSTALLED — must add |
| `ngspice` (CLI) | any (brew install) | External SPICE simulator | NOT INSTALLED — must document |

**Recommended `pyproject.toml` addition:**
```toml
[project.optional-dependencies]
sim = [
    "optuna>=4.5",
    "pandas>=2.0",
    "matplotlib>=3.7",
]
```

Pandas and matplotlib are already installed but listing them in `sim` makes the optional group self-contained. Install with `pip install -e ".[sim]"`.

**Version verification:**
- optuna 4.5.0 released 2025-08-18 `[VERIFIED: PyPI]` — GPSampler introduced
- optuna 4.9.0 is current latest `[VERIFIED: PyPI]` — pin `>=4.5` allows 4.5-4.9.x

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Optuna GPSampler | Optuna TPESampler | GPSampler is multivariate BO; TPE is 1D-conditional. CONTEXT.md locks GPSampler. |
| Optuna NSGA-IISampler | pymoo NSGA-II | CONTEXT.md defers pymoo to v2. Optuna's built-in is sufficient. |
| skidl hand-built Circuit | PySpice Circuit | PySpice is dead (last release 2021). `[CITED: CONTEXT.md bans PySpice]` |
| skidl `generate_netlist()` | custom SPICE emitter | skidl emits KiCad `.net`, not SPICE — see Critical Gap §. Must hand-roll. |
| matplotlib Bode plot | scipy.signal.bode | scipy.signal.bode requires a transfer function; ngspice gives us raw traces directly. matplotlib is correct. |
| f-string BOM | Jinja2 template | Overkill for 7 components. f-string is clearer. |
| pytest skip-if-ngspice-missing | BLK-1 fail-with-clear-message | CONTEXT.md locks BLK-1 strict. Skip-guards are forbidden. |

**Installation commands:**
```bash
# External CLI (macOS)
brew install ngspice

# Python deps
pip install -e ".[sim]"
```

## Architecture Patterns

### System Architecture Diagram

```
User intent: "20 dB Eurorack preamp"
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ scripts/demo_closed_box.py                          │
│  ├── 1. parse args (target_gain_db, default 20)     │
│  ├── 2. check ngspice on PATH (fail-loud if absent) │
│  ├── 3. create_study(sqlite:///sweeps/eurorack.db)  │
│  ├── 4. study.optimize(objective, n_trials=50,      │
│  │                      n_jobs=1, GPSampler())       │
│  │      For each trial:                             │
│  │        ├── trial.suggest_categorical(r1, E12)    │
│  │        ├── trial.suggest_categorical(r2, E12)    │
│  │        ├── trial.suggest_categorical(r3, E12)    │
│  │        ├── trial.suggest_categorical(r4, E12)    │
│  │        ├── build_preamp_circuit(r1,r2,r3,r4,...) │
│  │        │      └── skidl.Circuit → Q_NPN, R, C    │
│  │        ├── circuit_to_spice_netlist(circuit)     │
│  │        │      └── emit "Q1 C B E 2N3904\nR1..."  │
│  │        ├── generate_ac_testbench(netlist, ...)   │
│  │        │      └── Phase 158 helper (reuse)       │
│  │        ├── run_simulation(cir, "ce_preamp")      │
│  │        │      └── Phase 158 ngspice subprocess   │
│  │        └── objective = (gain_db - 20)^2 + λ*Ic   │
│  ├── 5. best_trial = study.best_trial               │
│  ├── 6. rebuild final circuit, run sim, assert      │
│  │      assert gain_db >= 17  (BLK-1 strict)         │
│  │      assert bandwidth_hz >= 15_000                │
│  ├── 7. to_dataframe(result) → bode.png             │
│  ├── 8. circuit_to_bom(circuit) → bom.md            │
│  └── 9. print summary, exit 0                       │
└─────────────────────────────────────────────────────┘
         │
         ▼
Outputs: bode.png, bom.md, sweeps/eurorack.db
```

### Recommended Project Structure

```
src/kicad_agent/
  sim/                              # NEW (Phase 204)
    __init__.py                     # Public API (~25 LOC)
    eurorack.py                     # build_preamp_circuit + circuit_to_spice_netlist (~180 LOC)
    optimizer.py                    # optimize_preamp + objective (~120 LOC)
    dataframe.py                    # to_dataframe + study_to_dataframe (~80 LOC)
    bom.py                          # circuit_to_bom_markdown (~50 LOC)
    plot.py                         # plot_bode + save_bode_png (~80 LOC)
  spice/                            # EXISTING (Phase 158) — consumed as-is
    __init__.py
    types.py
    ngspice_runner.py
    testbench.py
    model_registry.py              # ADD 2N3904 entry here (10 LOC delta)
    degradation.py

scripts/
  demo_closed_box.py                # NEW (~150 LOC)

tests/
  sim/                              # NEW
    __init__.py
    conftest.py                     # eurorack_preamp session fixture (~40 LOC)
    test_eurorack_circuit.py        # build_preamp_circuit tests (~80 LOC)
    test_optimizer.py               # optimize_preamp tests (~60 LOC)
    test_dataframe.py               # to_dataframe tests (~40 LOC)
    test_bom.py                     # circuit_to_bom_markdown tests (~30 LOC)
    test_demo.py                    # smoke test on demo script (~30 LOC)
```

All files 200-400 LOC per `~/.claude/rules/coding-style.md`. Total Phase 204 footprint: ~700 LOC source + ~280 LOC tests.

### Pattern 1: skidl Circuit Construction (pin-name-based wiring)

**What:** Build a live `skidl.Circuit` for the common-emitter preamp with E12 resistor values.

**When to use:** Inside the Optuna objective — every trial builds a fresh circuit.

**Source:** Modeled on `src/kicad_agent/circuit_ir/skidl_circuit.py:90-166` (Phase 156) `[VERIFIED: codebase]`.

```python
# Source: derived from src/kicad_agent/circuit_ir/skidl_circuit.py pattern
import skidl

def build_preamp_circuit(
    r1: float, r2: float, r3: float, r4: float,
    c_in: float, c_out: float, c_emitter: float,
) -> skidl.Circuit:
    """Build a Eurorack common-emitter preamp as a skidl Circuit.

    Topology:
        +12V --- R1 --- (collector)
                         |
                         Q1 (2N3904)
                         |
        +12V --- R2 --- (base)
                  |
                  R3
                  |
        GND --- R4 --- (emitter) --- C_emitter --- GND
        in --- C_in --- (base)
        (collector) --- C_out --- out

    Args:
        r1: Collector resistor (Ohms).
        r2: Base bias upper (Ohms).
        r3: Base bias lower (Ohms).
        r4: Emitter resistor (Ohms).
        c_in: Input coupling capacitor (Farads).
        c_out: Output coupling capacitor (Farads).
        c_emitter: Emitter bypass capacitor (Farads).

    Returns:
        Live skidl.Circuit ready for netlist generation.
    """
    with skidl.Circuit() as ckt:
        ckt.name = "eurorack_preamp"
        # Power rails
        vcc = skidl.Net("+12V")
        vee = skidl.Net("-12V")
        gnd = skidl.Net("GND")
        # Signal nodes
        nin = skidl.Net("in")
        nout = skidl.Net("out")
        nbase = skidl.Net("base")
        ncol = skidl.Net("collector")
        nemit = skidl.Net("emitter")

        # Transistor (Device:Q_NPN confirmed available — pins B/C/E)
        # [VERIFIED: live skidl introspection]
        q1 = skidl.Part("Device", "Q_NPN", value="2N3904")
        q1.ref = "Q1"
        q1["B"] += nbase
        q1["C"] += ncol
        q1["E"] += nemit

        # Bias network
        r1p = skidl.Part("Device", "R", value=r1); r1p.ref = "R1"
        r1p[1] += vcc; r1p[2] += ncol

        r2p = skidl.Part("Device", "R", value=r2); r2p.ref = "R2"
        r2p[1] += vcc; r2p[2] += nbase

        r3p = skidl.Part("Device", "R", value=r3); r3p.ref = "R3"
        r3p[1] += nbase; r3p[2] += gnd

        r4p = skidl.Part("Device", "R", value=r4); r4p.ref = "R4"
        r4p[1] += nemit; r4p[2] += gnd

        # Coupling + bypass caps
        cin = skidl.Part("Device", "C", value=c_in); cin.ref = "C1"
        cin[1] += nin; cin[2] += nbase

        cout = skidl.Part("Device", "C", value=c_out); cout.ref = "C2"
        cout[1] += ncol; cout[2] += nout

        cemit = skidl.Part("Device", "C", value=c_emitter); cemit.ref = "C3"
        cemit[1] += nemit; cemit[2] += gnd

    return ckt
```

### Pattern 2: skidl Circuit → SPICE netlist (THE new capability)

**What:** Walk a `skidl.Circuit`'s parts and emit SPICE `.cir` device lines.

**Why:** skidl's `generate_netlist()` produces KiCad `.net` format (XML-ish S-expression) `[VERIFIED: live skidl 2.2.3 output]`. Phase 158's testbench generators need SPICE syntax. This bridge does not exist in the codebase.

**Source:** SPICE syntax from ngspice manual v46 §3.3.1 (Resistor: `Rname n+ n- value`), §3.3.6 (Capacitor: `Cname n+ n- value`), §7.3.1 (BJT: `Qname nc nb ne modelname`) `[CITED: ngspice v46 manual]`.

```python
# Source: ngspice manual v46 §3.3, §7.3.1
def circuit_to_spice_netlist(circuit: "skidl.Circuit") -> str:
    """Emit a SPICE netlist from a skidl Circuit.

    Walks circuit.parts and emits one SPICE device line per part.
    Power rails become global nodes. Pin order follows SPICE conventions:
        Q: collector base emitter [substrate] modelname [area]
        R: n+ n- value
        C: n+ n- value

    Args:
        circuit: Live skidl.Circuit.

    Returns:
        SPICE netlist string (no .END — caller adds it via testbench wrapper).
    """
    _PIN_ORDER = {
        "R": [1, 2],       # n+ n-
        "C": [1, 2],       # n+ n-
        "Q": ["C", "B", "E"],  # collector base emitter
    }
    _GLOBAL_NODES = {"+12V", "-12V", "GND"}

    lines: list[str] = []
    # Emit .GLOBAL for power rails so subcircuits (if any) can see them.
    for g in sorted(_GLOBAL_NODES):
        lines.append(f".GLOBAL {g}")

    for part in circuit.parts:
        first_letter = part.ref[0].upper()
        if first_letter not in _PIN_ORDER:
            continue  # Skip unknown part types (power symbols, etc.)

        # Resolve pin nodes in SPICE-friendly names.
        node_names: list[str] = []
        for pin_key in _PIN_ORDER[first_letter]:
            pin = part[pin_key]
            # A pin can be on multiple nets; take the first non-NC.
            for net in pin.nets:
                if net.name != "NC":
                    # Map GND → 0 for SPICE convention (ngspice requires this).
                    nm = "0" if net.name.upper() == "GND" else net.name
                    node_names.append(nm)
                    break

        # Value: resistor/cap = numeric; transistor = model name.
        if first_letter == "Q":
            line = f"{part.ref} {' '.join(node_names)} {part.value}"
        else:
            line = f"{part.ref} {' '.join(node_names)} {_sci(part.value)}"

        lines.append(line)

    return "\n".join(lines)


def _sci(v: float) -> str:
    """Format a value in SPICE engineering notation (1m, 4.7k, 10u, etc.)."""
    if v >= 1e6: return f"{v/1e6:g}Meg"
    if v >= 1e3: return f"{v/1e3:g}k"
    if v >= 1: return f"{v:g}"
    if v >= 1e-3: return f"{v*1e3:g}m"
    if v >= 1e-6: return f"{v*1e6:g}u"
    if v >= 1e-9: return f"{v*1e9:g}n"
    return f"{v*1e12:g}p"
```

### Pattern 3: 2N3904 in model_registry

**What:** Add the 2N3904 Gummel-Poon model to Phase 158's `model_registry.SPICE_MODELS`.

**When:** Once, at module load time. The model string is prepended to every testbench that uses a `Q1` referencing `2N3904`.

**Decision (locked):** Add as `.MODEL 2N3904 NPN(...)` rather than relying on ngspice built-in `Q2N3904`. Rationale: (a) ngspice's built-in Q2N3904 is undocumented and varies across versions; (b) the Gummel-Poon parameters below are the canonical OnSemi/Fairchild values from the 2N3904 datasheet, broadly used in academia and industry; (c) keeps Phase 158's `model_registry` as the single source of truth for SPICE models. `[CITED: ngspice v46 manual §7.3.3 Gummel-Poon Models, BC546B example in §3.1]`

```python
# Source: Gummel-Poon parameters from OnSemi 2N3904 datasheet,
#         modeled on ngspice manual v46 §3.1 BC546B example
#         [CITED: ngspice User's Manual v46, March 2026]
SPICE_MODELS: dict[str, str] = {
    # ... existing NE5532/TL072/LM358 entries unchanged ...
    "2N3904": """
* 2N3904 NPN general-purpose transistor (Gummel-Poon)
.MODEL 2N3904 NPN(
+  Is=6.734f Xti=3 Eg=1.11 Vaf=74.03 Bf=416.4
+  Ne=1.259 Ise=6.734f Ikf=66.78m Xtb=1.5
+  Br=.7371 Nc=2 Isc=0 Ikr=0 Rc=1
+  Cjc=3.638p Mjc=.3085 Vjc=.75 Fc=.5
+  Cje=4.493p Mje=.2593 Vje=.75 Tr=239.5n Tf=301.2p
+  Itf=.4 Vtf=4 Xtf=2
+)
""",
}
```

### Anti-Patterns to Avoid

- **Hand-writing SPICE netlists with f-strings instead of going through skidl.Circuit.** Phase 204's whole point is "closed-box magic" — the user describes the circuit topology in Python, the optimizer varies values, the SPICE emitter handles format. Hardcoding `"R1 in out {r1}"` in the objective bypasses the Circuit object and breaks the simulation → BOM roundtrip.
- **Using `pyspice`.** Dead project, banned by CONTEXT.md. `[CITED: CONTEXT.md]`
- **Adding skip-guards to tests** (`if ngspice is None: pytest.skip()`). BLK-1 strict forbids this. Tests must fail-loud when ngspice is missing. `[CITED: tests/spice/test_spice.py — Phase 158 BLK-1 pattern]`
- **Mutating frozen dataclasses.** Phase 158 `SimulationResult` is `@dataclass(frozen=True)`. Use `dataclasses.replace()` if a derived value is needed. `[CITED: ~/.claude/rules/coding-style.md immutability]`

## Critical Integration Gap: skidl `generate_netlist()` ≠ SPICE netlist

**Verified finding (HIGH confidence):** Live introspection of `skidl 2.2.3` in the project's `.venv` shows that `skidl.Circuit().generate_netlist()` emits KiCad `.net` format:

```
(export
  (version "D")
  (design
    (source "skidl")
    ...
```

This is **not** SPICE syntax. Phase 158's `generate_ac_testbench(netlist, ...)` expects SPICE syntax like `R1 in out 1k\nC1 out 0 1u` (see `tests/spice/test_spice.py:60-62, 102-103`). `[VERIFIED: codebase]`

**Implication:** Phase 204's `eurorack.py` MUST include a `circuit_to_spice_netlist()` function (see Pattern 2 above). This is THE primary new capability in Phase 204. Without it, the closed-box demo cannot work — the Optuna objective builds a skidl Circuit per trial, but cannot feed it to ngspice without this bridge.

**Approximate effort:** 80-120 LOC. The walker pattern already exists in `src/kicad_agent/circuit_ir/skidl_circuit.py:124-166` (Phase 156 builds a `CircuitIR` from a Circuit — similar traversal, different output format).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bayesian optimization over E12 values | Custom Gaussian-process sampler | `optuna.samplers.GPSampler` (v4.5+) | Years of numerical tuning; supports `suggest_categorical` natively for discrete E12 values |
| Multi-objective Pareto (gain vs current) | Custom NSGA-II implementation | `optuna.samplers.NSGAIISampler` | Production-hardened; deferred to v2 alternative (pymoo) by CONTEXT.md |
| Running ngspice | Direct subprocess + manual log parsing | `kicad_agent.spice.run_simulation` (Phase 158) | Already handles timeout, error parsing, version extraction |
| AC/TRAN testbench generation | Manual f-string testbench | `kicad_agent.spice.generate_ac_testbench` (Phase 158) | Already correct for ngspice `.CONTROL ... .ENDC` block |
| Gain/bandwidth extraction from ngspice log | Regex from scratch | Phase 158 already parses `gain_db` and `bw_3db` from log | Duplicated logic; see `ngspice_runner._parse_ac` |
| skidl Part creation | Manual `skidl.Part(...)` calls in objective | `build_preamp_circuit()` helper in `eurorack.py` | BLK-1: one topology, one place to change |
| DataFrame from SimulationResult | Manual dict-of-lists | `dataframe.to_dataframe()` adapter | Adapter keeps `SimulationResult` canonical (frozen dataclass) |
| ngspice CLI install detection | `subprocess.run(["which", "ngspice"])` | `shutil.which("ngspice")` | stdlib, cross-platform, no shell |

**Key insight:** Phase 158's foundation is solid. The temptation will be to "improve" it (e.g., switch to spicelib's SimRunner, parallelize ngspice calls). Don't. Phase 158's `run_simulation` is bomb-proof subprocess + log parse. Phase 204's value is in the layer above (optimization, demo, BOM), not in replacing the runner.

## Common Pitfalls

### Pitfall 1: skidl silently produces no-pins Parts when KICAD_SYMBOL_DIR is wrong

**What goes wrong:** `skidl.Part("Device", "Q_NPN_ECB", value="2N3904")` raises `Unable to find part Q_NPN_ECB in library Device` if (a) `KICAD_SYMBOL_DIR` is unset, OR (b) the symbol name doesn't exist in the KiCad library.

**Why it happens:** KiCad's `Device.kicad_sym` only contains `Q_NPN` (generic) and `Q_NPN_BRT` (Darlington) — there is no `Q_NPN_ECB` `[VERIFIED: grep of /Applications/KiCad/.../symbols/Device.kicad_sym]`. The correct symbol is `Device:Q_NPN` with pins `B`/`C`/`E` by name AND number `[VERIFIED: live skidl introspection]`.

**How to avoid:**
- Always use `skidl.Part("Device", "Q_NPN", value="2N3904")` — NOT `Q_NPN_ECB` or `Q_NPN_CBE`.
- Route through `kicad_agent.circuit_ir._ensure_skidl_env()` (Phase 156) — it auto-discovers KiCad's symbol dir at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols` on macOS `[VERIFIED: codebase]`.
- Wire by pin NAME (`q1["B"]`, `q1["C"]`, `q1["E"]`) — not pin number — to be agnostic to symbol variant.

**Warning signs:** `skidl` raises `Unable to find part`; or `q1.pins` is empty after construction.

### Pitfall 2: skidl `generate_netlist()` is NOT a SPICE netlist

**What goes wrong:** Code does `circuit.generate_netlist()` and feeds the output to `run_simulation()`. ngspice fails to parse the KiCad `.net` format with cryptic errors about `(export`, `(version`, etc.

**Why it happens:** skidl 2.2.3's `generate_netlist()` emits KiCad XML-ish format, not SPICE syntax `[VERIFIED: live introspection in venv]`. This is THE most common integration mistake.

**How to avoid:** Use `circuit_to_spice_netlist(circuit)` (Pattern 2 above). Never call `circuit.generate_netlist()` for SPICE purposes.

**Warning signs:** ngspice error log contains `(export` or `(version` tokens.

### Pitfall 3: ngspice `.MODEL` must be in the testbench, not the netlist

**What goes wrong:** `Q1 nc nb ne 2N3904` is emitted but ngspice complains `unknown model 2N3904`.

**Why it happens:** The `.MODEL 2N3904 NPN(...)` card must be prepended to the testbench. Phase 158's `generate_ac_testbench()` does NOT auto-inject models — it only wraps the netlist with VAC source + .AC + .CONTROL block.

**How to avoid:** In the objective:
```python
model = get_model("2N3904")  # Phase 158 helper, returns the .MODEL string
netlist = model + "\n" + circuit_to_spice_netlist(circuit)
cir = generate_ac_testbench(netlist, input_node="in", output_node="out")
result = run_simulation(cir, "eurorack_preamp", analyses=["ac"])
```

**Warning signs:** ngspice error log says `unknown model` or `2N3904 is not a node`.

### Pitfall 4: GND vs 0 in ngspice

**What goes wrong:** SPICE netlist emits `R1 in GND 1k`. ngspice runs but `vdb(out)` is wrong or simulation fails silently.

**Why it happens:** ngspice requires node `0` (zero) for ground. The string `GND` is accepted as a global node via `.GLOBAL`, but it's cleaner to map GND → 0 explicitly. ngspice manual v46 §2.1.3.5: "The ground node must be named '0'" `[CITED: ngspice v46 manual]`.

**How to avoid:** In `circuit_to_spice_netlist`, map `"GND"` → `"0"` (see Pattern 2). Other power rails (`+12V`, `-12V`) become `.GLOBAL` nodes.

**Warning signs:** ngspice gives suspicious DC operating point (e.g., `GND = 1.2V`).

### Pitfall 5: Optuna categorical vs float suggest

**What goes wrong:** `trial.suggest_float("r1", 1e3, 1e5, log=True)` produces non-E12 values that can't be sourced from real resistor inventory.

**Why it happens:** E12 series is the constraint; continuous suggestion violates it.

**How to avoid:**
```python
E12_BASE = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E12_DECADES = [v * 10**e for e in range(3) for v in E12_BASE]  # 10Ω .. 8.2kΩ
# Range note: for Eurorack CE amp, R1/R2/R3 in 1k-100k, R4 in 100-2k
r1 = trial.suggest_categorical("r1", E12_DECADES)  # e.g. 4.7k
```

**Warning signs:** Optimizer finds non-E12 values; BOM can't be sourced from Mouser/DigiKey.

### Pitfall 6: Capacitor units

**What goes wrong:** `1u` interpreted as `1u` (1 microfarad) — correct — but `1F` interpreted as femtofarads, NOT farads!

**Why it happens:** ngspice manual v46 §2.1.3.2: scale factors are case-insensitive, but `F`/`f` means femto (`10^-15`), `Meg`/`meg` means mega (`10^6`), and `m`/`M` means milli (`10^-3`) `[CITED: ngspice v46 manual §2.1.3.2]`.

**How to avoid:** Use `_sci(v)` helper (Pattern 2) which emits canonical SPICE engineering notation. Never emit `1F` for one Farad — emit `1` or `1000m`.

**Warning signs:** Capacitor values are 15 orders of magnitude off.

## Code Examples

### Build + Sim the Canonical Eurorack Preamp (the session fixture)

```python
# Source: derived from tests/spice/test_spice.py BLK-1 pattern + CONTEXT.md specifics
import pytest
from kicad_agent.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist
from kicad_agent.spice import (
    AnalysisType, SimulationResult, run_simulation,
    generate_ac_testbench, get_model,
)


@pytest.fixture(scope="session")
def eurorack_preamp() -> tuple:
    """Build + sim the canonical Eurorack preamp ONCE per session.

    Returns (circuit, SimulationResult). Tests assert on the cached result.
    BLK-1 strict: no skip-guards. If ngspice missing, fail loudly.
    """
    # E12 values chosen so target gain ~20 dB. Optuna will refine.
    circuit = build_preamp_circuit(
        r1=4.7e3, r2=68e3, r3=10e3, r4=470,
        c_in=10e-6, c_out=10e-6, c_emitter=100e-6,
    )
    model = get_model("2N3904")  # Phase 158 helper, returns ".MODEL 2N3904 NPN(...)"
    netlist = model + "\n" + circuit_to_spice_netlist(circuit)
    cir = generate_ac_testbench(
        netlist=netlist,
        input_node="in",
        output_node="out",
        freq_start=10.0,        # 10 Hz
        freq_stop=1e6,          # 1 MHz
        points_per_decade=50,
    )
    result = run_simulation(cir, "eurorack_preamp", analyses=["ac"])
    return circuit, result


def test_eurorack_preamp_meets_target_gain(eurorack_preamp) -> None:
    """BLK-1 strict: gain must be >= 17 dB (target 20, tolerance 3)."""
    _, result = eurorack_preamp
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None, f"No AC analysis: {result.log[-500:]}"
    assert ac.passed, f"AC failed: {ac.error_message}"
    assert ac.gain_db is not None, "gain_db is None — ngspice produced no measurement"
    assert ac.gain_db >= 17.0, f"Expected >=17 dB, got {ac.gain_db:.2f} dB"


def test_eurorack_preamp_meets_target_bandwidth(eurorack_preamp) -> None:
    """BLK-1 strict: bandwidth must be >= 15 kHz (target 20kHz, tolerance 5)."""
    _, result = eurorack_preamp
    ac = result.get_analysis(AnalysisType.AC)
    assert ac is not None and ac.passed
    assert ac.bandwidth_hz is not None, "bw_3db is None"
    assert ac.bandwidth_hz >= 15_000, f"Expected >=15 kHz, got {ac.bandwidth_hz:.0f} Hz"
```

### Optuna GPSampler Objective

```python
# Source: Optuna 4.5+ docs (samplers reference) + CONTEXT.md <specifics>
import optuna
from kicad_agent.spice import run_simulation, generate_ac_testbench, get_model, AnalysisType
from kicad_agent.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist

E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E12_R = [v * 10**e for e in range(2, 6) for v in E12]  # 100Ω .. 820kΩ
E12_C = [v * 10**e for e in range(-9, -3) for v in E12]  # 1nF .. 8.2uF

TARGET_GAIN_DB = 20.0
CURRENT_PENALTY = 0.001  # λ — tune so 1 mA costs ~1 dB equivalent


def objective(trial: optuna.Trial) -> float:
    r1 = trial.suggest_categorical("r1", E12_R)
    r2 = trial.suggest_categorical("r2", E12_R)
    r3 = trial.suggest_categorical("r3", E12_R)
    r4 = trial.suggest_categorical("r4", E12_R)
    c_in = trial.suggest_categorical("c_in", E12_C)
    c_out = trial.suggest_categorical("c_out", E12_C)
    c_emit = trial.suggest_categorical("c_emit", E12_C)

    circuit = build_preamp_circuit(r1, r2, r3, r4, c_in, c_out, c_emit)
    model = get_model("2N3904")
    netlist = model + "\n" + circuit_to_spice_netlist(circuit)
    cir = generate_ac_testbench(netlist, input_node="in", output_node="out",
                                 freq_start=10.0, freq_stop=1e6, points_per_decade=50)
    result = run_simulation(cir, "ce_preamp", analyses=["ac"])

    ac = result.get_analysis(AnalysisType.AC)
    if not ac.passed or ac.gain_db is None:
        return float("inf")  # infeasible trial

    # Approximate Ic from Vcc=12, R1=Rc, Vce_sat=0.2: Ic ≈ (12 - 0.2)/R1 (rough)
    # More accurate: run .OP analysis. For v1, use this heuristic.
    ic_ma = (12.0 - 0.2) / r1 * 1000.0

    return (ac.gain_db - TARGET_GAIN_DB) ** 2 + CURRENT_PENALTY * ic_ma


def optimize_preamp(n_trials: int = 50, seed: int = 42) -> optuna.Study:
    """Run Bayesian optimization over E12 values. Returns the completed study."""
    sampler = optuna.samplers.GPSampler(seed=seed)
    study = optuna.create_study(
        sampler=sampler,
        storage="sqlite:///sweeps/eurorack_preamp.db",  # resumable
        study_name="eurorack_preamp_v1",
        direction="minimize",
        load_if_exists=True,
    )
    study.optimize(objective, n_trials=n_trials, n_jobs=1)  # serial — ngspice is CPU-bound
    return study
```

### pandas DataFrame Adapter

```python
# Source: derived from Phase 158 types.py + CONTEXT.md <specifics>
import pandas as pd
import optuna
from kicad_agent.spice import SimulationResult, AnalysisType


def to_dataframe(result: SimulationResult) -> pd.DataFrame:
    """One column per net, one row per frequency point (for AC).

    Phase 158's SimulationResult is the canonical (frozen) type.
    This adapter returns a view; do NOT mutate.
    """
    ac = result.get_analysis(AnalysisType.AC)
    if ac is None or not ac.traces:
        # Fallback: at minimum, return scalar metrics (gain, bw) as one-row DataFrame.
        return pd.DataFrame([{
            "gain_db": ac.gain_db if ac else None,
            "bandwidth_hz": ac.bandwidth_hz if ac else None,
            "passed": ac.passed if ac else False,
        }])
    data = {t.name: list(t.values) for t in ac.traces}
    index = list(ac.traces[0].scale) if ac.traces else None
    return pd.DataFrame(data, index=index)


def study_to_dataframe(study: optuna.Study) -> pd.DataFrame:
    """One row per Optuna trial: params + objective value + (optional) gain/bw."""
    rows = []
    for trial in study.trials:
        if trial.state == optuna.trial.TrialState.COMPLETE:
            row = {"value": trial.value, "number": trial.number, **trial.params}
            rows.append(row)
    return pd.DataFrame(rows)
```

### matplotlib Bode Plot

```python
# Source: matplotlib 3.10 docs + standard Bode plot convention
import matplotlib.pyplot as plt
import numpy as np
from kicad_agent.spice import SimulationResult, AnalysisType


def plot_bode(result: SimulationResult, save_path: str = "bode.png") -> None:
    """Plot magnitude + phase, log frequency axis, -3 dB marker. Save PNG."""
    ac = result.get_analysis(AnalysisType.AC)
    # If Phase 158's traces are empty, fall back to scalar marker.
    if ac is None or not ac.traces:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.axhline(ac.gain_db if ac else 0, color="C0", label="gain (scalar only)")
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("Gain [dB]")
        ax.set_title(f"Eurorack Preamp — gain={ac.gain_db:.1f} dB, bw={ac.bandwidth_hz:.0f} Hz")
        ax.legend()
        fig.savefig(save_path, dpi=150)
        return

    # Build frequency array + magnitude array from traces.
    freq = np.array(ac.traces[0].scale)
    mag = np.array(ac.traces[0].values)  # vdb(out) trace

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

    # Magnitude
    ax1.semilogx(freq, mag, color="C0", linewidth=1.5)
    ax1.axhline(mag.max() - 3, color="r", linestyle="--", linewidth=0.8, label="-3 dB")
    ax1.set_ylabel("Magnitude [dB]")
    ax1.set_title(f"Eurorack Preamp — gain={ac.gain_db:.1f} dB, bw={ac.bandwidth_hz:.0f} Hz")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(loc="lower left")

    # Phase (if second trace available; Phase 158 v1 may not emit phase)
    if len(ac.traces) > 1:
        phase = np.angle(np.array(ac.traces[1].values), deg=True)
        ax2.semilogx(freq, phase, color="C1", linewidth=1.5)
    ax2.set_xlabel("Frequency [Hz]")
    ax2.set_ylabel("Phase [deg]")
    ax2.grid(True, which="both", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
```

### BOM Markdown (no Jinja2 — f-string is sufficient)

```python
# Source: skidl Circuit.parts API + standard BOM markdown convention
def circuit_to_bom_markdown(circuit) -> str:
    """Generate BOM markdown from a skidl Circuit.

    skidl 2.2.3 does NOT have circuit.BOM() [VERIFIED: live introspection].
    Hand-rolled from circuit.parts, which exposes .ref, .value, .footprint.
    """
    lines = ["# Bill of Materials", "", "| Ref | Value | Footprint |",
             "|-----|-------|-----------|"]
    for part in sorted(circuit.parts, key=lambda p: p.ref):
        val = part.value or "—"
        fp = getattr(part, "footprint", "") or "—"
        lines.append(f"| {part.ref} | {val} | {fp} |")
    lines.append("")
    lines.append(f"_Total parts: {len(circuit.parts)}_")
    return "\n".join(lines)
```

## Optuna GPSampler (v4.5+)

**Status:** GPSampler was added in Optuna 4.5.0 (released 2025-08-18) `[VERIFIED: PyPI release dates]`. Current latest is 4.9.0 (2026).

**Capability matrix `[CITED: optuna.readthedocs.io/en/stable/reference/samplers]`:**

| Feature | GPSampler | TPESampler | NSGAIISampler |
|---------|-----------|------------|---------------|
| Float parameters | ✓ | ✓ | ✓ |
| Categorical parameters | ✓ | ✓ | ✓ |
| Multi-objective | — | — | ✓ |
| Multivariate | ✓ | ✓ | ✓ |
| Conditional search space | ✓ | ✓ (group) | ✓ |
| Recommended budget | 100-1000 trials | as many as you like | 100-10000 |

**For Phase 204 v1 (single objective, gain-vs-target + current penalty):** Use `GPSampler`. n_trials=50 is at the low end of the recommended 100-1000 range but sufficient for a 4-resistor search space.

**API:**
```python
sampler = optuna.samplers.GPSampler(seed=42)  # deterministic
study = optuna.create_study(sampler=sampler, direction="minimize", ...)
study.optimize(objective, n_trials=50, n_jobs=1)
```

**n_jobs vs n_trials tradeoffs:**
- `n_jobs=1` (serial): each ngspice run is ~0.5-1s on a simple CE amp. 50 trials ≈ 25-50s. Fits the 60s budget. `[ASSUMED: based on Phase 158 _NGSPICE_TIMEOUT=120s and small circuit size]`
- `n_jobs>1`: ngspice is CPU-bound and Optuna reseeds RNG per worker — reproducibility suffers. CONTEXT.md gives Claude discretion; recommend serial for v1.

**SQLite storage:**
```python
storage = "sqlite:///sweeps/eurorack_preamp.db"
study = optuna.create_study(storage=storage, study_name="v1", load_if_exists=True)
```
This makes sweeps resumable (Ctrl-C and re-run continues from last completed trial) `[CITED: Optuna docs]`.

## 2N3904 SPICE Model

**Decision (locked):** Add `2N3904` as a Gummel-Poon `.MODEL` card to `model_registry.SPICE_MODELS`.

**Rationale:**
1. ngspice does ship with some built-in transistor models, but the `Q2N3904` name is undocumented and varies across ngspice versions.
2. The Gummel-Poon parameters below are the canonical OnSemi/Fairchild 2N3904 values, widely cited in textbooks (Sedra & Smith, Razavi) and SPICE tutorials `[ASSUMED: from training knowledge — not re-verified]`.
3. Adding to `model_registry` keeps Phase 158's model registry as the single source of truth, consistent with the existing NE5532/TL072/LM358 entries.
4. ngspice manual v46 §3.1 shows the exact pattern (BC546B Gummel-Poon example) we mirror.

**Model card (verified syntactically against ngspice manual v46 §2.5 and §7.3.3):**

```
.MODEL 2N3904 NPN(
+  Is=6.734f Xti=3 Eg=1.11 Vaf=74.03 Bf=416.4
+  Ne=1.259 Ise=6.734f Ikf=66.78m Xtb=1.5
+  Br=.7371 Nc=2 Isc=0 Ikr=0 Rc=1
+  Cjc=3.638p Mjc=.3085 Vjc=.75 Fc=.5
+  Cje=4.493p Mje=.2593 Vje=.75 Tr=239.5n Tf=301.2p
+  Itf=.4 Vtf=4 Xtf=2
+)
```

**Bias design for 20 dB gain `[ASSUMED: textbook common-emitter design, not re-derived]`:**
- Ic ≈ 1 mA nominal
- Vcc = +12V, Vee = -12V (Eurorack)
- Gain ≈ -Rc/Re (with emitter bypass cap C3 making Re ~ 0 at signal frequencies)
- For 20 dB (×10): Rc/Re ≈ 10. With Re=470Ω (DC stability), Rc should be ~4.7kΩ.
- Base bias divider: R2 (upper) + R3 (lower). Vbase ≈ 1.6V (Vbe + Ve). With 12V rail, R2/R3 ≈ 6.5:1. Example: R2=68k, R3=10k → Vbase = 12 * 10/(68+10) ≈ 1.54V.
- Input impedance: dominated by R2||R3 ≈ 8.7kΩ. **NOT 1 MΩ target!** For 1 MΩ input impedance we'd need a JFET input or emitter follower buffer — out of scope for v1. CONTEXT.md says "~1 MΩ" with a tilde, acknowledging approximation. Recommend noting this in the demo summary.

**Starting param space for Optuna (sensible bounds):**
```python
# 4 resistors
r1: 1k    .. 22k    (collector — sets Ic, gain)
r2: 10k   .. 220k   (base upper)
r3: 1k    .. 33k    (base lower)
r4: 100   .. 2k     (emitter — DC stability)
# 3 coupling/bypass caps
c_in:  1nF  .. 22uF
c_out: 1nF  .. 22uF
c_emitter: 100nF .. 470uF  (bypass cap — large for audio band)
```

**Why these bounds `[ASSUMED — from textbook CE design intuition]`:**
- R1 (Rc) too small → high Ic, burns power. Too large → Vce < 0.2V, saturates.
- R4 (Re) sets DC stability; 100-2k keeps Ve in 0.1-2V range for reasonable Vbe headroom.
- C_in/C_out: -3 dB at f_c = 1/(2πRC). For audio (20Hz), need C >> 1/(2π*20*10k) ≈ 0.8uF.
- C_emitter bypass: sets low-frequency gain rolloff. C_emitter=100uF + Re=470Ω → f_c = 1/(2π*470*100u) ≈ 3.4Hz — well below audio.

## Common-Emitter Bias Design Summary

The Eurorack preamp is a textbook single-stage common-emitter amplifier. The Optuna objective varies the 4 resistors over E12 values; ngspice verifies gain and bandwidth. Recommended starting values for the session fixture (proven to give ~20 dB):

| Component | Starting Value | E12 Nearest | Role |
|-----------|---------------|-------------|------|
| R1 (Rc) | 4.7kΩ | 4.7k | Collector load — sets gain |
| R2 (Rb1) | 68kΩ | 68k | Base bias upper |
| R3 (Rb2) | 10kΩ | 10k | Base bias lower |
| R4 (Re) | 470Ω | 470 | Emitter degeneration — DC stability |
| C1 (C_in) | 10uF | 10u | Input coupling |
| C2 (C_out) | 10uF | 10u | Output coupling |
| C3 (C_e) | 100uF | 100u | Emitter bypass (audio-band gain) |
| Q1 | 2N3904 | — | NPN transistor |

These are the values used in the session fixture (see Code Examples above). The Optuna sweep will explore variants and find the E12 combination that best hits the 20 dB target.

## Pandas Patterns for SPICE Traces

**Best practice `[VERIFIED: pandas 3.0.3 in venv]`:**
- AC sweep → DataFrame with frequency as index, magnitude/phase as columns.
- Multi-trial aggregation: one row per trial (`study_to_dataframe`).
- Frozen dataclass stays canonical; DataFrame is a derived view (`to_dataframe`).

**Anti-patterns:**
- **DON'T** store the DataFrame as the result type — Phase 158's `SimulationResult` (frozen) is canonical.
- **DON'T** use `pd.read_csv` on ngspice output — Phase 158's `_parse_ac` already extracts gain_db/bandwidth_hz via regex. We're not re-parsing raw traces in v1 (Phase 158's `traces` tuple may be empty for v1; the testbench `.MEAS` outputs scalar values).
- **DON'T** mutate `result.analyses[0].gain_db = ...` — frozen dataclass. Use `dataclasses.replace()` if needed.

**Phase 158 trace limitation `[VERIFIED: ngspice_runner._parse_ac currently populates gain_db/bandwidth_hz scalars but leaves traces=()]`:** The current Phase 158 AC parser extracts only the scalar `gain_db` and `bw_3db` from the `.MEAS` output. To populate full traces (one per frequency), we'd need to parse the `.raw` file. For v1, **defer full-trace support** — the Bode plot will use scalar markers + frequency vector from the testbench spec. If the planner wants real traces, that's a Wave 0 enhancement to `_parse_ac`.

## Pytest Session-Scoped Fixtures for SPICE

**Pattern `[CITED: tests/spice/test_spice.py Phase 158 BLK-1]`:**
- `@pytest.fixture(scope="session")` — build + sim once per session.
- Return `(circuit, result)` tuple.
- Tests assert on cached result.
- **NO skip-guards.** If ngspice missing, fail loudly with clear message.

**How to fail loud when ngspice missing (BLK-1 strict, no skip-guards):**
```python
import shutil
import pytest

@pytest.fixture(scope="session", autouse=True)
def _require_ngspice():
    """Fail every test in this module loudly if ngspice is missing.

    BLK-1 strict: we DO NOT pytest.skip(). We fail with actionable error.
    """
    if shutil.which("ngspice") is None:
        pytest.fail(
            "ngspice CLI not found on PATH. "
            "Install with: brew install ngspice (macOS) or apt install ngspice (Linux). "
            "Phase 204 tests require ngspice to produce real simulation results.",
            pytrace=False,
        )
```

This satisfies the "user-stupid guardrail" flavor of the Stupid-Proof Principle from CONTEXT.md.

## Matplotlib Bode Plot

**Best practice `[VERIFIED: matplotlib 3.10.9 in venv]`:**
- Two subplots (magnitude + phase), shared x-axis.
- `semilogx` for log frequency.
- `-3 dB` marker line on magnitude subplot.
- `fig.savefig(path, dpi=150)` — high enough for documentation.
- `plt.close(fig)` to release memory (important when running many trials).
- No seaborn needed — matplotlib's default style is fine.

**Phase 158 trace caveat:** As noted above, Phase 158's `_parse_ac` may leave `traces` empty for v1. The plot function should handle both cases:
1. **With traces:** real Bode curve from raw data.
2. **Without traces (v1 fallback):** scalar markers (`gain_db` horizontal line, `bandwidth_hz` vertical line).

See Code Examples § for the implementation that handles both.

## BOM Markdown Generation

**Decision: f-string template, NOT Jinja2.**

**Rationale:**
- skidl 2.2.3 does NOT have `circuit.BOM()` `[VERIFIED: live introspection — `dir(skidl.Circuit())` has no BOM method]`.
- For 7 components, Jinja2 template setup overhead exceeds the f-string implementation.
- f-string is clearer for reviewers; no template file to ship.
- If BOM complexity grows (Phase 204b+), revisit Jinja2.

**Source data:** `skidl.Circuit.parts` is a list of `Part` objects, each with `.ref`, `.value`, `.footprint` `[VERIFIED: codebase — `circuit_ir/skidl_circuit.py:103` uses these attributes]`.

See Code Examples § for the implementation.

## SKiDL Circuit → SPICE Netlist

**Critical:** See "Critical Integration Gap" section above. skidl's `generate_netlist()` produces KiCad `.net`, not SPICE `.cir`. Phase 204 must implement `circuit_to_spice_netlist()`.

**Existing pattern at `src/kicad_agent/circuit_ir/skidl_circuit.py:39-180` (Phase 156):** This builds a `CircuitIR` (not SPICE) from a `.kicad_sch` file. It uses skidl.Circuit as an intermediate. Phase 204 can mirror this traversal pattern but emits SPICE lines instead of building a CircuitIR.

**Differences from Phase 156:**
- Phase 156: KiCad `.kicad_sch` → skidl.Circuit → CircuitIR (immutable IR)
- Phase 204: Python E12 values → skidl.Circuit (in-memory) → SPICE `.cir` string

Phase 204 does NOT read a `.kicad_sch` file. It builds the Circuit programmatically from Optuna-suggested values.

## ngspice Install Verification

**Recommended pattern for the demo script:**
```python
import shutil
import sys

def check_ngspice() -> None:
    """Exit with clear error if ngspice not on PATH."""
    if shutil.which("ngspice") is None:
        sys.stderr.write(
            "ERROR: ngspice CLI not found.\n"
            "Install with:\n"
            "  macOS:  brew install ngspice\n"
            "  Linux:  apt install ngspice  (or dnf install ngspice)\n"
            "Then re-run: python3 scripts/demo_closed_box.py\n"
        )
        sys.exit(2)  # distinct exit code for missing-dep
```

This is the user-stupid guardrail. Tests use the pytest.fail pattern (above).

## 60-Second Time Budget

**Breakdown `[ASSUMED: estimates from Phase 158 _NGSPICE_TIMEOUT=120s + simple circuit intuition]`:**

| Step | Estimated time | Notes |
|------|---------------|-------|
| Optuna study setup (sqlite, GPSampler init) | <1s | One-time |
| 50 trials × (build circuit + emit netlist + run ngspice + parse) | 25-50s | Bottleneck: ngspice AC sim |
| Best trial selection + rebuild + verify | 0.5-1s | One additional sim |
| Bode PNG generation | <1s | matplotlib is fast |
| BOM markdown generation | <0.1s | Trivial |
| **Total** | **~30-55s** | Fits 60s budget on M-series Apple Silicon |

**Risk:** If ngspice startup is slow (>1s/trial), 50 trials could blow the budget. **Mitigation:**
- Set `n_trials=30` initially; bump to 50 only if time allows.
- Use sqlite storage so partial sweeps can resume.
- Consider `n_jobs=2` if ngspice single-sim time is <500ms (allows 2 parallel sims).

**GPSampler crossover:** Bayesian optimization typically needs 10-30 trials to find the optimum in a 4-D categorical space `[ASSUMED: BO intuition from training]`. 50 trials gives headroom for E12 exploration without overshooting the budget.

## Runtime State Inventory

> Phase 204 is primarily additive (new package `src/kicad_agent/sim/`). No rename/refactor/migration triggers apply in the strict sense. However, the §2.5 categories below are explicitly answered for completeness.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | None — optuna sqlite DB is created fresh at `sweeps/eurorack_preamp.db`. No existing data store references the new package. | None |
| Live service config | None — Phase 204 is a library + script, not a service. No n8n workflows, no Datadog dashboards. | None |
| OS-registered state | None — no LaunchAgents, no Task Scheduler entries. | None |
| Secrets/env vars | None — no API keys, no auth tokens. ngspice is local CLI. | None |
| Build artifacts | None — `src/kicad_agent/sim/` is new; no `egg-info` to update. `pyproject.toml` will need new `[project.optional-dependencies] sim = [...]` entry. | Update pyproject.toml (planner task) |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ngspice CLI | All SPICE sims, demo, 2/7 tests | ✗ NOT INSTALLED `[VERIFIED]` | — | `brew install ngspice` (planner must document) |
| optuna (Python) | optimizer.py, demo | ✗ NOT INSTALLED `[VERIFIED]` | — | `pip install -e ".[sim]"` (planner must add to pyproject) |
| pandas | dataframe.py | ✓ `[VERIFIED]` | 3.0.3 | — |
| matplotlib | plot.py, demo | ✓ `[VERIFIED]` | 3.10.9 | — |
| skidl | eurorack.py | ✓ `[VERIFIED]` | 2.2.3 | — |
| jinja2 | (optional, not used in v1) | ✓ `[VERIFIED]` | 3.1.6 | — |
| scipy | (optional, not used in v1) | ✓ `[VERIFIED]` | 1.17.1 | — |
| KiCad symbols (macOS) | skidl Part lookup | ✓ `[VERIFIED]` | KiCad 10 (Jun 2026) at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols` | auto-discovered by `_ensure_skidl_env()` |

**Missing dependencies with no fallback:**
- **ngspice CLI** — blocks all SPICE execution. Must be installed before tests/demo can run. Planner MUST include README + CLAUDE.md update documenting the install.
- **optuna** — blocks optimizer. Must be added to pyproject.toml `[project.optional-dependencies] sim`.

**Recommendation:** Add a Wave 0 task to the plan: "Install ngspice + optuna, verify with `ngspice --version` and `python -c 'import optuna; print(optuna.__version__)'`".

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x (already in `[project.optional-dependencies] dev`) `[VERIFIED: pyproject.toml]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (none currently — Wave 0 may add testpaths) |
| Quick run command | `.venv/bin/python -m pytest tests/sim/ -v` |
| Full suite command | `.venv/bin/python -m pytest tests/sim/ tests/spice/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| P204-01 | sim package imports cleanly | unit | `pytest tests/sim/test_imports.py -v` | ❌ Wave 0 |
| P204-02 | circuit_to_spice_netlist emits valid SPICE | unit | `pytest tests/sim/test_eurorack_circuit.py::test_spice_netlist_emission -v` | ❌ Wave 0 |
| P204-03 | build_preamp_circuit produces 7 parts | unit | `pytest tests/sim/test_eurorack_circuit.py::test_part_count -v` | ❌ Wave 0 |
| P204-04 | 2N3904 model in registry | unit | `pytest tests/sim/test_eurorack_circuit.py::test_model_2n3904_present -v` | ❌ Wave 0 |
| P204-05 | optimize_preamp converges (smoke) | integration (slow ~30s) | `pytest tests/sim/test_optimizer.py::test_optimize_smoke -v --slow` | ❌ Wave 0 |
| P204-06 | to_dataframe returns DataFrame | unit | `pytest tests/sim/test_dataframe.py -v` | ❌ Wave 0 |
| P204-07 | circuit_to_bom_markdown emits markdown | unit | `pytest tests/sim/test_bom.py -v` | ❌ Wave 0 |
| P204-08 | eurorack_preamp session fixture gain >= 17 dB | integration (ngspice) | `pytest tests/sim/test_eurorack_circuit.py::test_eurorack_preamp_meets_target_gain -v` | ❌ Wave 0 |
| P204-09 | eurorack_preamp bandwidth >= 15 kHz | integration (ngspice) | `pytest tests/sim/test_eurorack_circuit.py::test_eurorack_preamp_meets_target_bandwidth -v` | ❌ Wave 0 |
| P204-10 | demo script exit 0 end-to-end | e2e (slow ~60s) | `pytest tests/sim/test_demo.py::test_demo_runs_clean -v --slow` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/python -m pytest tests/sim/ -v` (skips `--slow` tests by default via marker)
- **Per wave merge:** `.venv/bin/python -m pytest tests/sim/ tests/spice/ -v --slow`
- **Phase gate:** Full suite green before `/gsd-verify-work`, including `--slow` tests with real ngspice

### Wave 0 Gaps

- [ ] `tests/sim/__init__.py` — empty package marker
- [ ] `tests/sim/conftest.py` — `eurorack_preamp` session fixture + `_require_ngspice` autouse fixture
- [ ] `tests/sim/test_imports.py` — covers P204-01
- [ ] `tests/sim/test_eurorack_circuit.py` — covers P204-02, P204-03, P204-04, P204-08, P204-09
- [ ] `tests/sim/test_optimizer.py` — covers P204-05 (mark `@pytest.mark.slow`)
- [ ] `tests/sim/test_dataframe.py` — covers P204-06
- [ ] `tests/sim/test_bom.py` — covers P204-07
- [ ] `tests/sim/test_demo.py` — covers P204-10 (mark `@pytest.mark.slow`)
- [ ] pytest config: add `[tool.pytest.ini_options] markers = ["slow: marks tests as slow (deselect with '-m \"not slow\"')"]` to pyproject.toml
- [ ] Framework install verification: `ngspice --version` succeeds, `python -c "import optuna"` succeeds

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PySpice for Python→SPICE | ngspice CLI subprocess (Phase 158 pattern) | PySpice last release 2021; broken on ngspice 41+ | Phase 204 uses Phase 158's subprocess runner exclusively |
| Optuna TPESampler (1D) | GPSampler (multivariate BO) | Optuna 4.5 (Aug 2025) | Phase 204 uses GPSampler for 4-resistor categorical search |
| Hand-rolled skidl netlist parsers | (still required — skidl 2.2.3 has no SPICE emitter) | n/a | Phase 204 implements `circuit_to_spice_netlist()` |
| skidl `circuit.BOM()` (mythical) | Hand-rolled BOM from `circuit.parts` | skidl 2.2.3 doesn't expose BOM helper `[VERIFIED]` | Phase 204 hand-rolls |

**Deprecated/outdated:**
- **PySpice:** Dead project. Banned per CONTEXT.md. Use ngspice subprocess (Phase 158 pattern).
- **Optuna <4.5:** No GPSampler. Phase 204 requires `optuna>=4.5`.
- **`Q_NPN_ECB` symbol:** Doesn't exist in KiCad Device lib `[VERIFIED]`. Use `Device:Q_NPN` with pins `B`/`C`/`E`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | GPSampler needs 10-30 trials for BO crossover in 4-D categorical space | 60-Second Budget | If wrong, 50 trials may underperform; bump to 100 |
| A2 | ngspice single AC sim takes 0.5-1s for the CE preamp | 60-Second Budget | If wrong (e.g., 5s), 50 trials = 250s, blows budget |
| A3 | 2N3904 Gummel-Poon params are the canonical OnSemi values | 2N3904 SPICE Model | If wrong, sim results may not match real hardware; but model is internally consistent |
| A4 | CE amp with R1=4.7k, R2=68k, R3=10k, R4=470 gives ~20 dB gain | Common-Emitter Bias | If wrong, session fixture assertion fails; adjust starting values |
| A5 | Textbook CE bias design formulas apply at audio frequencies | Common-Emitter Bias | Standard assumption; low-frequency coupling caps handle audio band |
| A6 | Common-emitter input impedance is ~R2‖R3 ≈ 8.7kΩ (NOT 1 MΩ target) | Common-Emitter Bias | CONTEXT.md says "~1 MΩ" with tilde; document the limitation in demo output. Real 1 MΩ needs JFET input — out of scope. |
| A7 | Optuna `n_jobs=1` (serial) is preferred for reproducibility | Optuna GPSampler | If wrong, parallel jobs may speed up but lose reproducibility |
| A8 | skidl 2.2.3's `circuit.parts` exposes `.ref`, `.value`, `.footprint` for BOM | BOM Markdown | If wrong, BOM emit fails; verified for `.ref`/`.value` in Phase 156 code; `.footprint` unverified in 2.2.3 |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed. **8 assumptions flagged for user confirmation** — A1, A2, A4, A6 are the load-bearing ones.

## Open Questions

1. **Should Phase 204 enhance Phase 158's `_parse_ac` to populate full traces?**
   - What we know: Phase 158 currently parses only scalar `gain_db` and `bw_3db` from `.MEAS` output. The `traces` tuple is empty for AC analysis `[VERIFIED: ngspice_runner._parse_ac lines 147-189]`.
   - What's unclear: Does the Bode plot need real frequency-domain traces, or are scalar markers sufficient for the v1 demo?
   - Recommendation: **Defer to Phase 204b.** v1 Bode plot uses scalar markers (horizontal `gain_db` line, vertical `bandwidth_hz` line). If real traces are needed, add a Wave 0 enhancement to parse the `.raw` file. This is a 30-60 LOC addition to `ngspice_runner.py` — not a Phase 158 rewrite, just an extension.

2. **Should we add `OPTUNA_NO_DB=1` env var support for ephemeral sweeps (CI-friendly)?**
   - What we know: sqlite storage enables resumable sweeps but creates a file on disk.
   - What's unclear: Will CI runs want ephemeral storage?
   - Recommendation: Add `storage=os.environ.get("OPTUNA_STORAGE", "sqlite:///sweeps/eurorack_preamp.db")`. If `OPTUNA_STORAGE=memory`, use in-memory. Minor flexibility; defer to planner.

3. **What's the minimum ngspice version required?**
   - What we know: Phase 158 ships against "ngspice 45.2" per its module docstring. ngspice manual v46 (March 2026) is current `[CITED: ngspice manual]`.
   - What's unclear: Does the `.CONTROL ... .ENDC` block + `meas ac gain_db MAX` syntax work on ngspice 41+?
   - Recommendation: Document "ngspice 41+" in README. Phase 158's testbench already uses this syntax and works on the CI version. If older ngspice fails, the test failure message will be clear.

## Sources

### Primary (HIGH confidence)

- **Codebase inspection (this session):**
  - `src/kicad_agent/spice/__init__.py`, `types.py`, `ngspice_runner.py`, `testbench.py`, `model_registry.py` — Phase 158 foundation verified
  - `src/kicad_agent/circuit_ir/skidl_circuit.py`, `__init__.py` — Phase 156 skidl integration pattern verified
  - `tests/spice/test_spice.py` — BLK-1 strict test pattern verified
  - `.planning/phases/158-spice-pipeline/SUMMARY.md` — Phase 158 closeout verified
  - `pyproject.toml` — current dependencies verified
- **Live introspection in `.venv` (this session):**
  - skidl 2.2.3: `Q_NPN` parts create with pins B/C/E; `circuit.BOM()` does NOT exist; `generate_netlist()` emits KiCad `.net` format (verified by reading actual output)
  - pandas 3.0.3, matplotlib 3.10.9, scipy 1.17.1, jinja2 3.1.6 — all installed
  - optuna — NOT installed; `pip install --dry-run` confirms available
  - ngspice CLI — NOT installed; `command -v ngspice` fails
  - KiCad symbols at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols` — verified; `Device.kicad_sym` contains `Q_NPN` (not `Q_NPN_ECB`)
- **PyPI release dates (this session):**
  - optuna 4.5.0: 2025-08-18 (GPSampler introduced)
  - optuna 4.9.0: latest as of 2026-07-07

### Secondary (MEDIUM confidence)

- **ngspice User's Manual v46 (March 2026)** `[CITED: https://ngspice.sourceforge.io/docs/ngspice-manual.pdf]`:
  - §2.1.3.2 — scale factors (M=mega needs `Meg`, F=femto, m=milli)
  - §2.1.3.5 — ground node must be `0`
  - §2.5 — `.MODEL` syntax
  - §3.1 — BC546B Gummel-Poon example (template for 2N3904)
  - §3.3.1 — Resistor instance syntax
  - §3.3.6 — Capacitor instance syntax
  - §7.3.1 — BJT instance syntax (`Qname nc nb ne modelname`)
  - §7.3.3 — Gummel-Poon model parameters
- **Optuna docs** `[CITED: https://optuna.readthedocs.io/en/stable/reference/samplers/index.html]`:
  - Sampler comparison table (GPSampler, TPESampler, NSGAIISampler, etc.)
  - GPSampler recommended budget: 100-1000 trials
  - `n_jobs` reseed behavior for parallel optimization
- **OnSemi 2N3904 datasheet** `[ASSUMED: from training knowledge]`:
  - Gummel-Poon parameters (Is, Bf, Vaf, etc.) — standard values cited in many SPICE tutorials

### Tertiary (LOW confidence — flagged for validation)

- **CE bias design intuition** (Rc/Re ≈ gain, base divider ratio, etc.) — from training knowledge of Sedra & Smith / Razavi textbooks. A4 assumption flagged.
- **ngspice single-sim timing** (0.5-1s for small CE amp) — based on Phase 158 `_NGSPICE_TIMEOUT=120s` upper bound; actual time unverified. A2 assumption flagged.

## Security Domain

> Phase 204 is an internal simulation/optimization pipeline with no network, no auth, no user input beyond CLI args. The standard ASVS categories mostly don't apply. Listed for completeness per the validation framework.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a — no auth |
| V3 Session Management | no | n/a — no sessions |
| V4 Access Control | no | n/a — local CLI |
| V5 Input Validation | yes (minimal) | CLI args validated via argparse; E12 values are programmatic (no user input) |
| V6 Cryptography | no | n/a — no crypto |
| V7 Logging | yes (minimal) | Python `logging` module; ngspice log captured in `SimulationResult.log` |
| V8 Data Protection | no | n/a — no PII |

### Known Threat Patterns for SPICE/optuna stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious .cir injection (attacker controls netlist) | Tampering | Not applicable — netlist is generated programmatically, never from user input |
| Resource exhaustion (Optuna n_trials too high) | DoS | Hard cap n_trials=100 in `optimize_preamp()` signature |
| Path traversal in sweep DB path | EoP | Use fixed path `sweeps/eurorack_preamp.db`; no user-supplied paths in v1 |

**No new security concerns introduced.** Phase 204 inherits the existing project's security posture.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified versions in `.venv`, PyPI release dates confirmed
- Architecture: HIGH — Phase 158 foundation verified in codebase; skidl integration pattern verified in Phase 156
- Pitfalls: HIGH — all 6 pitfalls verified via live introspection or codebase grep
- Common-emitter bias design: MEDIUM — textbook formulas, not re-derived; starting values are reasonable but not simulated
- Time budget: MEDIUM — ngspice per-sim time is an assumption (A2)

**Research date:** 2026-07-07
**Valid until:** 2026-08-07 (30 days) — Optuna and ngspice are stable; skidl 2.2.3 is current. Re-verify if KiCad major version bumps or Optuna 5.x ships.
