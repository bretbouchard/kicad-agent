# Phase 160 — NL Circuit Generation

**Goal:** The capstone end-to-end pipeline. A fine-tuned LLM (the Qwen text adapter from Phase 159) takes a natural-language circuit request and generates SKIDL Python, which then flows unattended through ERC → SPICE → floor plan → PCB → Quilter routing. This is the **full pipeline advantage** over SchGen/pcbGPT (which stop at schematic): natural language all the way to a manufacturable board. The canonical test — *"I need a preamp with +18dB gain and -128dBu EIN"* — must generate a working circuit that clears every gate.

**Depends on:** Phase 159 (trained Qwen text adapter + Gemma vision adapter + the training data pipeline)
**Requirements:** NLGEN-01, NLGEN-02, NLGEN-03, NLGEN-04, NLGEN-05
**Research basis:** `.planning/research/STACK-SKIDL.md` (SchGen stops at schematic; full-pipeline is the differentiator), `.planning/research/STACK-SPICE.md` (SPICE as a spec-verification gate, not just reward)
**Integration target:** `src/kicad_agent/circuit_ir/` (Phase 156), `src/kicad_agent/spice/` (Phase 158), `src/kicad_agent/floorplan/` (Phase 157), `src/kicad_agent/training/` (Phase 159 adapter)

---

## Design Principles

1. **The pipeline is a chain of validation gates, not a single generation call.** NLGEN-01 is the LLM call; NLGEN-02/03 are hard gates that reject bad output; NLGEN-04 is the orchestration of the full chain. Each gate is independently testable and independently fail-closed. A generated circuit that fails ERC never reaches SPICE; one that fails SPICE never reaches the floor planner. This is the opposite of "generate and hope" — it is "generate, verify, advance or repair."
2. **Best-of-N with gate feedback, not single-shot.** The Qwen adapter generates K candidate SKIDL programs per NL request. Each is run through the gate chain. The first to clear all gates wins. If none clear, an LLM-driven repair loop (extending the Phase 15 `ErrorFixer` pattern) feeds the gate failure back to the model for a corrected attempt (bounded retries). This mirrors SchGen's finding that representation quality matters more than single-call accuracy.
3. **SPICE is a spec-verification gate, not just a reward.** In Phase 159, SPICE degradation is a *reward signal* (TRAIN-04). In Phase 160, SPICE is a *pass/fail gate against the spec extracted from the NL request* (NLGEN-03). "+18dB gain" parsed from the prompt becomes a hard target; the generated circuit's AC analysis must meet it. This is stronger than ERC (which only checks connectivity) and is the differentiator vs SchGen (which explicitly skips SPICE).
4. **Reuse the entire v5.0 stack as pipeline stages.** Every stage of NLGEN-04 already exists as a Phase 156-159 artifact: SKIDL→schematic (`circuit_ir/skidl_to_kicad.py`), ERC (`pre_pcb_schematic_gate`), SPICE (`spice/`), floor plan (`floorplan/`), PCB populate (`skidl_to_pcb.py`), Quilter (`pcb_auto_route`). Phase 160 is an **orchestrator** — it sequences these existing capabilities behind a single NL entry point. No new EDA capability is built here; the work is orchestration + the eval harness.
5. **The eval harness is the deliverable, not just the pipeline.** NLGEN-05 is one canonical test, but a single passing test proves little. Phase 160 ships a **spec-grounded eval suite** — a curated set of NL prompts with parseable spec targets (gain, BW, noise, EIN, voltage) — that measures the end-to-end success rate across circuit families. The eval strategy (below) is the core of this phase.
6. **Degradation gracefully.** The full pipeline (NL→...→Quilter) is the happy path. Each stage can fail independently: SKIDL won't parse, ERC errors, no SPICE model, Quilter timeout, floor plan over-constrained. The orchestrator reports *which gate failed and why*, producing a structured failure report. This makes the pipeline debuggable and gives the repair loop actionable feedback.

---

## Reference: Requirements → Tasks

| Req | Description | Wave | Primary Task |
|-----|-------------|------|--------------|
| NLGEN-01 | Fine-tuned LLM generates SKIDL Python from NL | 1 | Task 1 |
| NLGEN-02 | Execute SKIDL → ERC validation gate (0 errors) | 1 | Task 2 |
| NLGEN-03 | SPICE validation gate (meets spec targets) | 2 | Task 3 |
| NLGEN-04 | Full pipeline: NL → SKIDL → ERC → SPICE → floor plan → PCB → Quilter | 3 | Task 5 |
| NLGEN-05 | Test: preamp +18dB / -128dBu EIN → working circuit | 3 | Task 6 |

---

## Key Design Decisions

- **D-160-1: Best-of-N generation with early-exit on gate pass.** K=4 candidate SKIDL programs per NL request (configurable). Evaluate in gate order (parse → ERC → SPICE → spec). First to pass all gates is returned. This trades compute for success rate — the single most effective lever per SchGen's representation-quality thesis. The Phase 22 `best_of_n` pattern (existing) is the template.
- **D-160-2: Spec extraction is rule-based, not LLM-based.** The NL prompt contains numeric spec targets ("+18dB gain", "-128dBu EIN", "100kHz bandwidth"). A deterministic regex/quantity extractor (`spec_extractor.py`) parses these into a `SpecTargets` dataclass. This is deliberately *not* an LLM call — spec targets must be exact (18.0 dB), and LLM extraction introduces unquantifiable error into the very gate that validates the LLM. Rule-based extraction is auditable and fails closed (no target found → SPICE gate skipped, ERC-only).
- **D-160-3: The repair loop is LLM-driven, bounded, and gate-aware.** When all K candidates fail a gate, the failure (ERC error list, or SPICE gain=12dB vs target=18dB) is formatted into a correction prompt for the Qwen adapter (extending Phase 15 `ErrorFixer`). Max 3 repair rounds. Each round re-runs best-of-N. If still failing, the pipeline reports the best partial result + the gate that blocked it. This is the SchGen "generate → verify → fix → repeat" loop (Phase 15-03 pattern), applied to circuits.
- **D-160-4: SPICE gate targets spec, not parasitic tolerance.** Phase 159's `sim_score` measures *degradation* (pre vs post-route delta). Phase 160's SPICE gate measures *absolute spec compliance* (does gain meet +18dB on the ideal schematic?). These are different: NLGEN-03 runs on the pre-route (ideal) circuit; parasitic degradation is a Phase 159 training signal, not a Phase 160 gate. The full pipeline (NLGEN-04) can optionally re-simulate post-route as a *report*, but it is not a gate — manufacturability is the floor-plan + Quilter + DRC stage's job.
- **D-160-5: The canonical preamp test (NLGEN-05) uses the analog-ecosystem mono blade as ground truth.** The mono blade preamp (116 parts, NE5532, known +18dB gain) is the reference circuit. The eval doesn't require the LLM to reproduce it exactly — it requires the LLM to produce *a* circuit meeting the spec (+18dB gain, -128dBu EIN). The mono blade's SPICE baseline (Phase 158 SPICE-10) is the comparison anchor. This tests *functional generation*, not *memorization*.

---

## Target Package Layout

```
src/kicad_agent/generation/
├── __init__.py            # ~40 lines — public exports
├── spec_extractor.py      # ~180 lines — NL → SpecTargets (rule-based, D-160-2)
├── skidl_generator.py     # ~220 lines — NL → K candidate SKIDL programs (best-of-N, D-160-1)
├── gate_chain.py          # ~250 lines — SKIDL → parse → ERC → SPICE → spec gates (NLGEN-02, NLGEN-03)
├── repair_loop.py         # ~200 lines — gate-failure → LLM correction prompt (bounded, D-160-3)
├── pipeline.py            # ~300 lines — full NL → ... → Quilter orchestrator (NLGEN-04)
└── eval_harness.py        # ~250 lines — spec-grounded eval suite runner (NLGEN-05 + beyond)

tests/
├── test_spec_extractor.py
├── test_skidl_generator.py
├── test_gate_chain.py
├── test_repair_loop.py
├── test_pipeline.py
└── test_eval_harness.py

eval/
└── nl_circuit_prompts/    # curated eval prompts with spec targets
    ├── preamp_gain.jsonl          # the canonical NLGEN-05 test + variants
    ├── filter.jsonl
    ├── power_supply.jsonl
    └── ...

scripts/
└── run_nl_pipeline.py     # ~100 lines — CLI: NL string → full pipeline → report
```

**Why a top-level `generation/` subpackage?** This is the user-facing capstone — NL in, manufacturable board out. It sits above `circuit_ir/`, `spice/`, `floorplan/`, and `training/` (the adapter), orchestrating them. A dedicated package keeps the orchestration logic, the eval harness, and the spec-extraction rules in one cohesive unit. It does not duplicate any stage's internals — it calls them in sequence.

### Reused primitives (no duplication)

| Phase 160 concept | Existing primitive | Location |
|---|---|---|
| Qwen adapter inference | Phase 159 trained adapter + `best_of_n` pattern | Phase 22 inference wrapper, Phase 159 adapter |
| SKIDL parse + exec | `skidl.Circuit` + `exec()` | Phase 156 (`circuit_ir/`) |
| ERC validation | `pre_pcb_schematic_gate`, `erc_check` | Phase 3, Phase 31 |
| SPICE simulation | `run_testbench()` (AC, noise, THD) | Phase 158 (`spice/`) |
| Spec comparison | `metrics.gain_db`, `noise_floor`, `baselines.compare` | Phase 158 (`spice/metrics.py`, `baselines.py`) |
| SKIDL → schematic | `circuit_to_kicad_sch()` | Phase 156 (`circuit_ir/skidl_to_kicad.py`) |
| SKIDL → PCB | `circuit_to_pcb()` | Phase 156 (`circuit_ir/skidl_to_pcb.py`) |
| Floor plan | `apply_floor_plan()` | Phase 157 (`floorplan/`) |
| Quilter routing | `pcb_auto_route` ops | Phase 99/100 |
| LLM error repair | `ErrorFixer` pattern | Phase 15 (`ai/error_fixer.py`) |
| LLM provider | `LLMProvider` protocol, `get_provider()` | Phase 34 (`llm/`) |
| Best-of-N selection | best-of-N scoring | Phase 22 |
| Pipeline result reporting | structured JSON results | Phase 10/15 generation pipeline |

---

## Wave 1 — NL → SKIDL → ERC Gate (NLGEN-01, NLGEN-02)

**Goal:** The LLM generates SKIDL from NL, and a hard ERC gate rejects anything with connectivity errors.

**Files:** `generation/spec_extractor.py`, `generation/skidl_generator.py`, `generation/gate_chain.py` (ERC portion), `tests/test_spec_extractor.py`, `tests/test_skidl_generator.py`

### Task 1: NL → SKIDL generation (NLGEN-01)

`skidl_generator.py` invokes the Phase 159 Qwen adapter to produce K candidate SKIDL programs:

```python
@dataclass(frozen=True)
class GenerationResult:
    nl_prompt: str
    spec_targets: "SpecTargets"
    candidates: tuple["SkidlCandidate", ...]
    best: "SkidlCandidate | None"   # first to pass all gates, or highest-scoring

@dataclass(frozen=True)
class SkidlCandidate:
    skidl_code: str
    parse_ok: bool
    circuit: "CircuitIR | None"
    generation_logprobs: float | None

def generate_skidl(
    nl_prompt: str,
    adapter_path: Path,           # Phase 159 Qwen adapter
    n_candidates: int = 4,
    provider: "LLMProvider | None" = None,  # Phase 34 provider (None = local adapter)
    temperature: float = 0.7,
) -> GenerationResult:
    """Best-of-N SKIDL generation from NL (D-160-1)."""
```

**Generation flow:**
1. Load the Phase 159 Qwen adapter (LoRA on Qwen2.5, via the Phase 22 inference wrapper).
2. Construct the prompt: system prompt (`SYSTEM_PROMPT_CIRCUIT_GEN` from Phase 159) + the NL user request.
3. Sample K=4 candidates at temperature 0.7 (diversity for the best-of-N to exploit).
4. For each candidate: attempt `exec()` into a `skidl.Circuit`. Set `parse_ok`. Candidates that don't parse are retained (scored 0) for the repair loop's context.

### Task 1a: Spec extraction (D-160-2)

`spec_extractor.py` — deterministic NL → `SpecTargets`:

```python
@dataclass(frozen=True)
class SpecTargets:
    gain_db: float | None         # e.g. 18.0 from "+18dB gain"
    bandwidth_hz: float | None    # e.g. 100_000 from "100kHz bandwidth"
    noise_einu_dbu: float | None  # e.g. -128.0 from "-128dBu EIN"
    thd_percent: float | None     # e.g. 0.1 from "<0.1% THD"
    supply_v: float | None        # e.g. 48.0 from "48V phantom power"
    raw_extracts: dict            # all matched quantities for traceability

def extract_spec(nl_prompt: str) -> SpecTargets:
    """Rule-based spec extraction. Fails closed (None = target not found)."""
```

Regex patterns for common audio/analog spec idioms: `([+-]?\d+(?:\.\d+)?)\s*dB\s*(gain|attenuation)`, `(\d+(?:\.\d+)?)\s*(kHz|MHz|Hz)\s*(bandwidth|BW)`, `(-?\d+(?:\.\d+)?)\s*dBu\s*(EIN|noise)`, `(\d+(?:\.\d+)?)\s*V`, `THD.*?<\s*(\d+(?:\.\d+)?)\s*%`. Each match populates the corresponding field; `raw_extracts` keeps the full match text for the eval report. **No target found → field is None → that gate is skipped** (fail-closed).

### Task 2: ERC validation gate (NLGEN-02)

The first hard gate in `gate_chain.py`:

```python
@dataclass(frozen=True)
class GateResult:
    gate_name: str          # "parse" | "erc" | "spice_spec" | "floorplan" | "route"
    passed: bool
    details: dict           # errors, metrics, score
    blocking_error: str | None

def run_parse_gate(skidl_code: str) -> GateResult: ...   # exec() + CircuitIR construction
def run_erc_gate(circuit: "CircuitIR") -> GateResult: ...  # 0 errors required
def run_gate_chain(
    candidate: "SkidlCandidate",
    spec: "SpecTargets",
    gates: tuple[str, ...] = ("parse", "erc", "spice_spec"),
) -> tuple[GateResult, ...]:
    """Run gates in order; stop at first failure. Return all results."""
```

`run_erc_gate` reuses the existing `erc_check` (Phase 31 MCP tool / Phase 3 `pre_pcb_schematic_gate`). The gate **passes only with 0 errors** (warnings are allowed and reported). This is NLGEN-02.

---

## Wave 2 — SPICE Spec Gate (NLGEN-03)

**Goal:** The generated circuit must meet the spec targets extracted from the NL prompt, verified by simulation — not just pass ERC.

**Files:** `generation/gate_chain.py` (SPICE portion), `tests/test_gate_chain.py`

### Task 3: SPICE validation gate (NLGEN-03)

```python
def run_spice_spec_gate(
    circuit: "CircuitIR",
    spec: "SpecTargets",
) -> GateResult:
    """Simulate the circuit; verify each spec target (D-160-4).

    Runs the relevant Phase 158 analysis per target:
      gain_db  → AC analysis, measure midband gain
      bandwidth_hz → AC analysis, -3dB point
      noise_einu_dbu → Noise analysis, input-referred
      thd_percent → THD analysis at 1kHz
    A target is 'met' if within tolerance (e.g. gain within ±1dB, noise within ±3dBu).
    Gate passes only if ALL present targets are met.
    """
```

**Gate logic:**
1. Export the ERC-passing circuit to SPICE (Phase 158 `netlist_exporter.py`).
2. For each non-None `SpecTargets` field, run the corresponding Phase 158 analysis:
   - `gain_db` → AC analysis, `metrics.gain_db()` at midband
   - `bandwidth_hz` → AC analysis, `metrics.bandwidth_3db()`
   - `noise_einu_dbu` → Noise analysis, `metrics.noise_floor()` input-referred
   - `thd_percent` → THD analysis, `metrics.thd_from_harmonics()`
3. Compare each measured value against the target within tolerance (gain ±1dB, BW ±10%, noise ±3dBu, THD < target).
4. **Gate passes iff all present targets are met.** If `SpecTargets` is entirely empty (no quantities found in NL), this gate is skipped (NLGEN-03 vacuously satisfied — ERC is the only gate). This is the fail-closed behavior: we never *invent* a spec target.

**Tolerance rationale:** generated circuits have component-value variance; demanding exact spec match (18.000 dB) would make the gate unusable. The tolerances reflect engineering judgment (±1dB gain is inaudible; ±10% BW is within component tolerance). These are configurable in `generation/config.yaml`.

**SchGen boundary honored:** if the circuit contains `UNSIMULATABLE` parts (Phase 158 `models/registry.py` — AK4619VN, MCUs), the SPICE gate runs only on the analog sub-circuit (Phase 158 `parasitics.py` analog-subcircuit extraction). If *no* analog sub-circuit exists, the gate is skipped with a report flag.

---

## Wave 3 — Full Pipeline + Canonical Test (NLGEN-04, NLGEN-05)

**Goal:** Orchestrate the complete NL → manufacturable board pipeline, and prove it on the canonical preamp test.

**Files:** `generation/repair_loop.py`, `generation/pipeline.py`, `generation/eval_harness.py`, `eval/nl_circuit_prompts/`, `scripts/run_nl_pipeline.py`, `tests/test_pipeline.py`, `tests/test_eval_harness.py`

### Task 5: Full pipeline orchestrator (NLGEN-04)

`pipeline.py` is the capstone — NL in, full result out:

```python
@dataclass(frozen=True)
class PipelineResult:
    nl_prompt: str
    spec_targets: "SpecTargets"
    success: bool                    # cleared all gates to routing
    stage_reached: str               # "parse" | "erc" | "spice_spec" | "floorplan" | "route" | "complete"
    best_candidate: "SkidlCandidate | None"
    gate_results: tuple[GateResult, ...]
    artifacts: dict                  # paths to .kicad_sch, .kicad_pcb, .raw, renders
    repair_rounds: int
    failure_report: str | None       # human-readable, if success=False

def generate_circuit_pipeline(
    nl_prompt: str,
    adapter_path: Path,
    run_floorplan: bool = True,
    run_quilter: bool = True,
    n_candidates: int = 4,
    max_repair_rounds: int = 3,
    output_dir: Path = Path("./nl_output"),
) -> PipelineResult:
    """Full NL → SKIDL → ERC → SPICE → floor plan → PCB → Quilter pipeline (NLGEN-04)."""
```

**Pipeline stages (each calls an existing Phase 156-159 artifact):**

| Stage | Action | Gate | Existing primitive |
|---|---|---|---|
| 1. Generate | NL → K SKIDL candidates | parse gate | Phase 159 adapter + `skidl_generator.py` |
| 2. ERC | SKIDL → schematic → ERC | `run_erc_gate` (0 errors) | Phase 156 `skidl_to_kicad.py` + Phase 3 ERC |
| 3. SPICE spec | circuit → sim → compare targets | `run_spice_spec_gate` | Phase 158 `spice/` |
| 4. Floor plan | SKIDL → PCB → apply floor plan | (soft — report quality) | Phase 157 `floorplan/` |
| 5. Quilter route | placed PCB → routed PCB | (soft — report completion) | Phase 99/100 Quilter |

**Stage-gate semantics:** Stages 1-3 are *hard gates* (NLGEN-01/02/03). Stages 4-5 are *soft* — a floor plan that over-constrains or a Quilter timeout does not fail the pipeline; it produces a placed-but-unrouted or partially-routed board with a report flag. Manufacturability (NLGEN-04's end state) is "a board that cleared ERC + SPICE spec and has a floor plan + best-effort routing." The hard gates guarantee the circuit is electrically correct and meets spec; the soft stages deliver the physical artifact.

**Early-exit on best-of-N:** the orchestrator runs candidate 1 through the full gate chain; if it passes, done. If it fails at gate G, candidate 2 is tried, etc. Only if all K candidates fail does the repair loop engage.

### Task 4: Repair loop (D-160-3)

`repair_loop.py` — when all K candidates fail a gate, feed the failure back to the LLM:

```python
def repair_attempt(
    nl_prompt: str,
    failed_candidate: "SkidlCandidate",
    gate_result: GateResult,
    adapter_path: Path,
    provider: "LLMProvider | None" = None,
) -> "SkidlCandidate":
    """Format gate failure → correction prompt → regenerated candidate.

    ERC failure: include the error list ("U1 pin 4 unconnected", "net VCC has no driver").
    SPICE failure: include the measured vs target ("gain=12dB, target=18dB — insufficient").
    Bounded by max_repair_rounds in the pipeline caller.
    """
```

The correction prompt extends Phase 15's `ErrorFixer` pattern: it appends the failing SKIDL + the specific gate errors and asks the model to fix *only* the error. The repaired candidate re-enters the best-of-N gate chain. Max 3 rounds (configurable). Each round's failure is accumulated in the final `PipelineResult.failure_report`.

### Task 6: Canonical preamp test (NLGEN-05) + eval harness

The NLGEN-05 test and the broader eval suite live in `eval_harness.py` + `eval/nl_circuit_prompts/`.

**The canonical test (NLGEN-05):**
```python
CANONICAL_PREAMP_PROMPT = (
    "I need a preamp with +18dB gain and -128dBu EIN"
)

def test_canonical_preamp():
    """NLGEN-05: the canonical preamp generates a working circuit."""
    result = generate_circuit_pipeline(
        CANONICAL_PREAMP_PROMPT,
        adapter_path=Path("adapters/qwen_circuit_v1"),
    )
    assert result.spec_targets.gain_db == 18.0       # extracted
    assert result.spec_targets.noise_einu_dbu == -128.0
    assert result.success is True
    assert result.stage_reached == "complete"
    # The generated circuit meets spec:
    spice_gate = [g for g in result.gate_results if g.gate_name == "spice_spec"][0]
    assert spice_gate.passed
    assert 17.0 <= spice_gate.details["measured_gain_db"] <= 19.0
    assert spice_gate.details["measured_einu_dbu"] <= -125.0  # within tolerance
```

**Ground-truth anchor:** the mono blade preamp (Phase 158 SPICE-10 baseline: +18dB, BW > 100kHz). The test does *not* require the LLM to reproduce the mono blade — it requires a circuit meeting the same spec. The mono blade's SPICE baseline is the sanity-check anchor in the eval report.

---

## Eval Strategy (the core of Phase 160)

A single passing test (NLGEN-05) proves the pipeline *can* work, not how *often* it works. Phase 160 ships a **spec-grounded eval harness** that measures end-to-end success rate across circuit families. This is the primary deliverable for judging phase success beyond the canonical test.

### Eval harness design (`eval_harness.py`)

```python
@dataclass(frozen=True)
class EvalCase:
    prompt: str
    spec_targets: SpecTargets        # ground-truth parsed targets
    circuit_family: str             # "preamp", "filter", "regulator", "mcu_breakout", "mixed"
    difficulty: str                 # "easy" | "medium" | "hard"
    min_components: int             # expected complexity hint
    source: str                     # "canonical" | "curated" | "corpus"

@dataclass(frozen=True)
class EvalResult:
    case: EvalCase
    success: bool
    stage_reached: str
    gate_results: tuple[GateResult, ...]
    measured_spec: dict             # actual sim values
    repair_rounds: int
    latency_s: float

def run_eval_suite(
    cases: list[EvalCase],
    adapter_path: Path,
    output_report: Path,
) -> "EvalReport":
    """Run all cases; produce a markdown + JSON report."""
```

### Eval prompt suite (`eval/nl_circuit_prompts/`)

Curated JSONL of NL prompts with ground-truth spec targets, organized by circuit family. Each line: `{"prompt": "...", "spec": {...}, "family": "...", "difficulty": "..."}`.

**Suite composition (target ~100 cases):**

| Family | Count | Example prompt | Spec target | Difficulty |
|---|---|---|---|---|
| **preamp** | 20 | "I need a preamp with +18dB gain and -128dBu EIN" | gain=18dB, EIN=-128dBu | easy-hard |
| preamp | | "Design a mic preamp, 60dB gain, phantom powered" | gain=60dB, supply=48V | hard |
| **filter** | 20 | "Low-pass filter, 2kHz cutoff, 2nd order" | BW=2000Hz | easy |
| filter | | "Anti-alias filter, 48kHz, 4th order Butterworth" | BW=48000Hz | medium |
| **regulator** | 15 | "5V linear regulator from 12V input, 1A" | supply=5V | easy |
| regulator | | "Buck converter, 24V to 3.3V, 5A, 500kHz" | supply=3.3V, BW=500kHz | hard |
| **oscillator** | 10 | "1kHz Wien bridge oscillator" | BW=1000Hz | medium |
| **mcu_breakout** | 10 | "RP2040 minimal breakout with USB-C and 12MHz crystal" | (none — ERC only) | medium |
| **mixed** | 25 | corpus-sourced real-world prompts (from Phase 159 NL describer) | varied | varied |

**Difficulty rubric:**
- **easy:** single sub-circuit, common topology, spec in standard range.
- **medium:** 2-3 sub-circuits, standard ICs, multiple spec targets.
- **hard:** multi-stage, exotic components (THAT340, DG413), tight specs (low EIN), or no-clean-README corpus prompts.

**Source diversity:** canonical (the NLGEN-05 test + obvious variants), curated (hand-written to cover families), corpus (real NL descriptions from Phase 159's `nl_describer.py`, ground-truth-validated by spot-check).

### Eval report (the success metric)

The harness emits `eval_report.md` + `eval_report.json`:

```
## NL Circuit Generation Eval Report

Overall success rate: 47/100 (47%)
By stage reached:
  parse:      91/100 (91%)   ← SKIDL parses
  erc:        68/100 (68%)   ← clears ERC
  spice_spec: 47/100 (47%)   ← meets spec targets
  floorplan:  47/100 (47%)
  route:      39/100 (39%)   ← Quilter completed

By family:
  preamp:       12/20 (60%)
  filter:       14/20 (70%)
  regulator:     8/15 (53%)
  oscillator:    4/10 (40%)
  mcu_breakout:  8/10 (80%)  ← ERC-only gate (no SPICE spec)
  mixed:         1/25  (4%)  ← hardest (real corpus prompts)

By difficulty:
  easy:   22/30 (73%)
  medium: 19/45 (42%)
  hard:    6/25 (24%)

Canonical preamp (NLGEN-05): PASS — gain=18.2dB, EIN=-129.1dBu
```

**Success criterion for the phase:** the canonical test passes (NLGEN-05), AND the eval suite shows a non-trivial success rate on easy/medium families (target: ≥40% on easy+medium combined). The hard/corpus rates are expected to be low and are tracked for improvement across model versions — they are *not* phase-gate blockers. This mirrors SchGen's own reported 60.5% functional correctness on their (easier, schematic-only) benchmark: full-pipeline-to-manufacturing is strictly harder, so lower absolute rates are expected and acceptable.

---

## End-to-End Pipeline Flow (NLGEN-04)

```
NL prompt: "I need a preamp with +18dB gain and -128dBu EIN"
        │
        ▼  [spec_extractor.py — D-160-2]
SpecTargets(gain_db=18.0, noise_einu_dbu=-128.0)
        │
        ▼  [skidl_generator.py — NLGEN-01, best-of-N=4]
K candidate SKIDL programs
        │
        ├──► parse gate (exec → CircuitIR)          ✗ candidate 1: SyntaxError → repair context
        ├──► parse gate                              ✓ candidate 2
        │       ▼
        │     ERC gate (0 errors) — NLGEN-02         ✗ candidate 2: "U1 pin 4 unconnected" → repair
        ├──► parse gate                              ✓ candidate 3
        │       ▼
        │     ERC gate                               ✓ candidate 3
        │       ▼
        │     SPICE spec gate — NLGEN-03             ✗ candidate 3: gain=12dB (target 18dB) → repair
        ├──► (all K failed) ──► repair_loop.py (D-160-3, round 1)
        │       │   feeds ERC error + SPICE gap back to Qwen
        │       ▼
        │     K repaired candidates → gate chain
        │       ├──► ... ERC ✓, SPICE spec ✓ (gain=18.4dB, EIN=-128.7dBu)
        │              ▼
        │            BEST CANDIDATE SELECTED
        │
        ▼  [pipeline.py — NLGEN-04, soft stages]
SKIDL → schematic (circuit_ir/skidl_to_kicad.py)
        ▼
PCB populate (circuit_ir/skidl_to_pcb.py)
        ▼
Floor plan (floorplan/apply_floor_plan)  [soft — report quality]
        ▼
Quilter route (pcb_auto_route)           [soft — report completion]
        ▼
PipelineResult(success=True, stage_reached="complete",
               artifacts={.kicad_sch, .kicad_pcb, .raw, renders},
               measured_spec={gain_db: 18.4, einu_dbu: -128.7})
```

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Qwen adapter success rate too low (most candidates fail parse) | Medium | Best-of-N=4 + repair loop (3 rounds) = up to 16 generation attempts. ERC gate is lenient (warnings ok). The Phase 159 L2 SKIDL training data is specifically the representation Qwen learns. |
| SPICE models missing for generated circuits (exotic ICs) | High | SPICE gate skips gracefully for `UNSIMULATABLE` parts; analog sub-circuit extraction (Phase 158). mcu_breakout family is ERC-only by design. |
| Spec extraction misses targets (NL phrasing varies) | Medium | Rule-based extractor covers common idioms; misses → gate skipped (fail-closed, not false-fail). Eval report tracks extraction rate; expand patterns iteratively. |
| Quilter timeouts on generated boards | Medium | Quilter stage is *soft* (NLGEN-04 success does not require routing completion). `max_components` cap. Report partial routing. |
| Repair loop doesn't converge (model repeats errors) | Medium | Max 3 rounds; failure_report accumulates all attempts. The loop is a quality multiplier, not a guarantee — the base success rate (without repair) is the floor. |
| Eval suite over-fits to the adapter (curated prompts leak into training) | Low | Eval prompts are held out from the Phase 159 training corpus (separate from `sft_pair_builder` output). Corpus-sourced eval prompts (25%) are real-world NL not seen in training. |
| Hallucinated SKIDL (valid Python, wrong circuit) | Medium | ERC catches connectivity errors; SPICE spec gate catches functional errors (right components, wrong values). This two-gate design is precisely why NLGEN-03 exists — ERC alone is insufficient. |

---

## Success Criteria Traceability (ROADMAP §160)

| ROADMAP criterion | Where satisfied |
|---|---|
| 1. Fine-tuned LLM generates valid SKIDL from NL | Wave 1 Task 1 — `skidl_generator.py` (best-of-N) |
| 2. Generated SKIDL passes ERC gate (0 errors) | Wave 1 Task 2 — `run_erc_gate` |
| 3. Generated SKIDL passes SPICE gate (meets spec) | Wave 2 Task 3 — `run_spice_spec_gate` |
| 4. Full pipeline runs unattended (NL → Quilter) | Wave 3 Task 5 — `generate_circuit_pipeline` |
| 5. Canonical preamp test (+18dB, -128dBu EIN) → working circuit | Wave 3 Task 6 — `test_canonical_preamp` + eval harness |
