# Cicada Team Phase Handoff

**Date:** 2026-05-31
**From:** Bret (with strategic context from external consultation)
**To:** Cicada team
**Project:** kicad-agent v2.5 Benchmark Suite

---

## Where We Are

**Shipped:** 40 phases, 8 milestones (v1.0 through v2.4)
**In Progress:** Phases 41-44 (v2.5 Benchmark Suite) — Council reviewed, plans approved, execution underway (41-02, 42-01, 43-01, 44-01 already committed)
**Planned:** Phases 45-58 — Council reviewed, plans approved, ready to execute
**Total:** 85 operations, 2174+ tests, 62,000+ source lines

### v2.4 COMPLETE (Phases 38-40)

**225 new tests, 11 new operations, 30 commits, 0 regressions.**

| Phase | Plans | Operations | Tests |
|-------|-------|------------|-------|
| 38: Schematic Routing Engine | 4 | resolve_pin_positions, detect_routing_collisions, detect_pin_overlaps, connect_pins, batch_connect, regenerate_wiring | 85 |
| 39: Schematic Intelligence | 3 | extract_nets, detect_net_conflicts, suggest_net_names | 44 |
| 40: ERC Root Cause Analysis | 3 | classify_violations, diagnose_violations, erc_auto_fix(root_cause) | 96 |

All plans TDD-executed. Council Gate 1 (Plan Review) and Gate 2 (Execution Review) passed for all phases. Phase 40 Council Gate 2: APPROVED with 3 non-blocking findings.

---

## Strategic Context

The external consultation confirmed our direction and identified two critical gaps:

### 1. Benchmarks (Currently 2/10)

We have no standardized way to measure kicad-agent's intelligence. This is the #1 blocker for professional credibility.

**What we need:** A "PCB MMLU" — multi-choice circuit analysis questions that test understanding of:
- Component selection and function
- Topology recognition (is this a compressor? a filter? a preamp?)
- Signal flow tracing
- Power design correctness
- DFM/SI/PI/EMC domain knowledge

**Why it matters:** No professional takes an AI tool seriously without published benchmarks. This is how we prove we're not vaporware.

### 2. Domain Intelligence (Currently 2/10)

kicad-agent edits schematics without understanding what the circuit DOES. It can place a resistor, but doesn't know if it's a pull-up, feedback, or bias resistor.

**What comes after benchmarks:** Phases 45-48 in STRATEGIC-EXPANSION-PLAN.md

### 3. Positioning

**"Engineering review system for KiCad" > "AI PCB designer"**

Every failed AI EDA startup tried to design circuits. We review, fix, and validate them. This is our moat:
- Binary success criteria (valid file or not)
- Measurable value (ERC violations reduced by X%)
- No scaling problem (local model, no cloud)
- Already 40 phases of foundation work

---

## v2.5 Benchmark Suite — Phases 41-44

**Milestone goal:** Create a standardized circuit intelligence benchmark suite that measures kicad-agent's understanding of electronics design. Publish baseline scores. Integrate regression detection into CI.

**Execution order:** 41 -> 42 -> 43 -> 44 (dependency chain)

**Total plans:** 5 (41 has 2 plans, 42-44 have 1 each)
**Estimated new files:** ~15 source + ~5 test + ~4 data files
**Estimated new tests:** ~80

### Phase 41: PCB MMLU Benchmark (2 plans)

**Goal:** Create the "PCB MMLU" — 500+ multi-choice circuit analysis questions across 8 categories that measure circuit understanding.

**Why this matters:** This is the foundation artifact. Everything else (runner, QA dataset, regression, adversarial) depends on this dataset existing.

**Plan 41-01: Benchmark Dataset (BENCH-01)**
| Item | Detail |
|------|--------|
| Wave | 1 |
| Depends on | Nothing (uses existing schematics) |
| Files created | `benchmarks/__init__.py`, `benchmarks/schemas.py`, `benchmarks/question_generator.py`, `benchmarks/dataset_builder.py`, `benchmarks/pcb-mmlu-v1.json`, `tests/test_benchmark_dataset.py` |
| Key schemas | `BenchmarkQuestion(id, category, difficulty, question, choices[4], correct_index, explanation, source, tags)`, `BenchmarkDataset(version, generated_at, questions, metadata)` |
| Test assertions | 500+ questions, >=50 per category, difficulty within 5% of 20/60/20 split, no duplicate IDs, all distractors differ from correct |

**8 question categories:**
1. component_identification — What does this component do?
2. topology_recognition — What type of circuit is this subcircuit?
3. signal_flow — Trace signal from input to output
4. power_design — Power rails, decoupling, regulator selection
5. pin_function — What is pin N doing in this circuit?
6. net_purpose — What is this net's function?
7. design_rules — Is this design rule satisfied?
8. troubleshooting — What is the root cause of this ERC violation?

**Question sources:** 55 analog-ecosystem schematics, real ERC reports, datasheets (THAT4301, CD4066BE, NE5532, RP2040), netlists, BOMs. Template-based generation (no LLM needed).

**Plan 41-02: Benchmark Runner + Baseline Models (BENCH-02)**
| Item | Detail |
|------|--------|
| Wave | 2 (depends on 41-01) |
| Files created | `benchmarks/runner.py`, `benchmarks/models.py`, `benchmarks/__main__.py`, `tests/test_benchmark_runner.py` |
| Key classes | `BenchmarkRunner`, `BaselineRandomModel`, `BaselineHeuristicModel`, `LocalLoRAModel`, `APIModel` |
| CLI | `python -m kicad_agent.benchmarks --dataset benchmarks/pcb-mmlu-v1.json --model random --output results.json` |
| Test assertions | Random ~25% ±10%, heuristic >25%, BenchmarkResult validates, category accuracy for all categories |

**Expected baselines:**
- Random: ~25% (4 choices)
- Heuristic: 30-40% (keyword matching)
- LoRA fine-tuned: target >70%

**Council Gate 1 status:** Phase 41 plans reviewed by 10 specialists. 22 findings (3 critical, 7 high) — all addressed in plan revisions. Re-review passed clean.

---

### Phase 42: Circuit QA Dataset (1 plan)

**Goal:** Generate 2000+ open-ended QA pairs for fine-tuning. This is the training data that makes benchmark scores go up.

**Why this matters:** PCB MMLU measures understanding. This dataset *teaches* understanding. Fine-tuning on QA pairs improves the model's ability to generate explanations, not just pick correct answers.

**Plan 42-01: Circuit QA Dataset (BENCH-03)**
| Item | Detail |
|------|--------|
| Wave | 1 (depends on 41-01 only) |
| Files created | `benchmarks/qa_schemas.py`, `benchmarks/qa_generator.py`, `benchmarks/circuit-qa-v1.json`, `tests/test_circuit_qa.py` |
| Key schemas | `CircuitQAPair(question, answer, qa_type, source, verification)`, `CircuitQADataset` |
| Test assertions | 2000+ QA pairs, all 6 types covered, verifiable answers with source references |

**6 QA types:**
1. violation_diagnosis — "Why does this schematic have X violation?"
2. signal_flow — "What is the signal path from A to B?"
3. component_function — "What is the purpose of R60?"
4. net_purpose — "What is the SC_FILTER net for?"
5. design_review — "What improvements could be made to X?"
6. value_calculation — "What value should C47 be for X time constant?"

**Key integration points:**
- `qa_generator.py` -> `schematic_graph.py` (subcircuit extraction)
- `qa_generator.py` -> `erc_parser.py` (violation diagnosis QA)
- Decoupled from `question_generator.py` (separate module, shared patterns)

---

### Phase 43: Regression Benchmark Suite (1 plan)

**Goal:** Automated regression detection + CI integration. Every PR runs benchmarks; if scores drop, the PR is flagged.

**Why this matters:** Benchmarks are useless without regression tracking. This prevents silent model degradation and gives confidence that code changes improve (not hurt) circuit understanding.

**Plan 43-01: Regression Detection + CI (BENCH-04)**
| Item | Detail |
|------|--------|
| Wave | 1 (depends on 41-02 and 42-01) |
| Files created | `benchmarks/regression.py`, `.github/workflows/benchmark.yml`, `benchmarks/results/baseline.json`, `tests/test_benchmark_regression.py` |
| Key classes | `RegressionDetector(compare, check_regression)`, `RegressionReport(current, baseline, delta, is_regression, regression_categories)` |
| Test assertions | >2% drop in any category flagged, equal/improved scores pass, historical tracking works, CI YAML valid |

**Regression detection logic:**
- Compare current `BenchmarkResult` against baseline
- Flag if any category accuracy drops >2% (configurable threshold)
- Store results in `benchmarks/results/` with timestamps
- Baseline = best-known result, not just first result

**CI workflow:**
```yaml
name: Benchmark
on: [pull_request]
jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .
      - run: python -m kicad_agent.benchmarks --dataset benchmarks/pcb-mmlu-v1.json --model heuristic --output /tmp/results.json
      - run: python -m kicad_agent.benchmarks --regression-check --baseline benchmarks/results/baseline.json --current /tmp/results.json
```

---

### Phase 44: Adversarial Test Generation (1 plan)

**Goal:** Three types of adversarial testing — mutation, property-based, fuzzing. Proves kicad-agent handles edge cases and broken inputs correctly.

**Why this matters:** Benchmarks measure understanding. Adversarial tests prove robustness. The combination gives confidence that kicad-agent doesn't just pass happy-path tests.

**Plan 44-01: Adversarial Test Suite (BENCH-05)**
| Item | Detail |
|------|--------|
| Wave | 1 (depends on 41-01 and 42-01) |
| Files created | `benchmarks/mutation_engine.py`, `benchmarks/adversarial.py`, `benchmarks/adversarial-v1.json`, `tests/test_adversarial.py` |
| Key classes | `SchematicMutation(mutation_type, target, original, mutated, description, expected_detection)`, `MutationEngine`, `AdversarialTestSuite` |
| Test assertions | 750+ adversarial tests total, all seeded for reproducibility, parser never crashes on fuzz |

**Three test types:**

| Type | Count | Method | What it tests |
|------|-------|--------|---------------|
| Mutation testing | 200 | Apply 7 mutation types to valid schematics | Detection of deliberately broken circuits |
| Property-based testing | 50 | Verify invariants on generated circuits | Operations preserve validity, ERC never increases |
| Fuzz testing | 500 | Random S-expression mutations | Parser robustness (no crashes) |

**7 mutation types:** swap_values, break_wire, remove_label, duplicate_net, short_pins, floating_pin, wrong_polarity

**Key integration points:**
- `mutation_engine.py` -> `schematic_graph.py` (target identification)
- `adversarial.py` -> `erc_parser.py` (verify mutations produce expected violations)
- `adversarial.py` -> `mutation_engine.py` (orchestration)

---

## Execution Wave Plan

```
Wave 1: 41-01 (dataset) + 42-01 (QA) — parallel (41-01 is dataset only, 42-01 depends on schemas but can build independently)
Wave 2: 41-02 (runner) — depends on 41-01
Wave 3: 43-01 (regression) + 44-01 (adversarial) — parallel (both depend on 41-01/41-02 + 42-01)
```

**Note:** 42-01 only lists `41-01` as a dependency (it needs the schemas and source patterns). 43-01 and 44-01 depend on both the runner (41-02) and QA (42-01).

---

## New Package Structure (Phases 41-44 create this)

```
src/kicad_agent/benchmarks/
├── __init__.py               # Package init
├── __main__.py               # CLI: python -m kicad_agent.benchmarks
├── schemas.py                # BenchmarkQuestion, BenchmarkDataset
├── question_generator.py     # Template-based question generation (8 categories)
├── dataset_builder.py        # Orchestrates generation from real schematics
├── runner.py                 # BenchmarkRunner + BenchmarkResult
├── models.py                 # BaselineRandom, BaselineHeuristic, LocalLoRA, APIModel
├── qa_schemas.py             # CircuitQAPair, CircuitQADataset
├── qa_generator.py           # Open-ended QA pair generation (6 types)
├── regression.py             # RegressionDetector + CI integration
├── mutation_engine.py        # SchematicMutation (7 mutation types)
└── adversarial.py            # AdversarialTestSuite (mutation + property + fuzz)

benchmarks/
├── pcb-mmlu-v1.json          # 500+ multi-choice questions
├── circuit-qa-v1.json        # 2000+ open-ended QA pairs
├── adversarial-v1.json       # 750+ adversarial test cases
└── results/
    ├── baseline.json         # Best-known baseline result
    └── *.json                # Historical run results
```

---

## Architecture Reference

### Existing modules that benchmarks integrate with

```
src/kicad_agent/
├── schematic_routing/
│   └── schematic_graph.py    # SchematicGraph.from_file() for subcircuit extraction
├── ops/
│   ├── erc_parser.py         # parse_erc(), ErcViolation for violation diagnosis QA
│   ├── violation_classifier.py  # Phase 40: classify_violations for troubleshooting questions
│   └── violation_diagnostic.py  # Phase 40: diagnose_violations for root cause QA
├── inference/
│   └── evaluator.py          # EvalResult pattern for benchmark results
└── training/
    └── evaluation.py         # EvalResult pattern reuse
```

### Schema files (existing pattern)

```
src/kicad_agent/ops/
├── _schema_erc_smart.py      # Phase 40: ClassifyViolationsOp, DiagnoseViolationsOp, ErcAutoFixOp
├── _schema_schematic_routing.py  # Phase 38: Routing op schemas
├── _schema_schematic_intel.py    # Phase 39: Intelligence op schemas
└── schema.py                 # Re-exports all 17 schema sub-modules
```

### Test pattern

Tests in `tests/` follow `test_<module>.py`. Benchmark tests will be:
- `test_benchmark_dataset.py` (41-01)
- `test_benchmark_runner.py` (41-02)
- `test_circuit_qa.py` (42-01)
- `test_benchmark_regression.py` (43-01)
- `test_adversarial.py` (44-01)

---

## Key Decisions Already Made

1. **Template-based generation, no LLM** — Question generation uses templates + real schematic data, not LLM calls. Deterministic, reproducible, no API costs.
2. **8 PCB MMLU categories** — component_identification, topology_recognition, signal_flow, power_design, pin_function, net_purpose, design_rules, troubleshooting.
3. **6 QA types** — violation_diagnosis, signal_flow, component_function, net_purpose, design_review, value_calculation.
4. **4-choice multi-choice** — 25% random baseline, established ML benchmark convention.
5. **2% regression threshold** — Any category dropping >2% flags a regression. Configurable.
6. **7 mutation types** — swap_values, break_wire, remove_label, duplicate_net, short_pins, floating_pin, wrong_polarity.
7. **Seeded RNG for all adversarial tests** — Every adversarial test is reproducible.
8. **Separate QA dataset from MMLU** — QA is open-ended for fine-tuning; MMLU is multi-choice for evaluation. Different purposes.
9. **CI runs heuristic baseline, not LoRA** — Heuristic is fast and deterministic. LoRA baseline runs locally or on schedule.

---

## What Success Looks Like

**v2.5 (this work):**
- [ ] PCB MMLU benchmark published with 500+ questions
- [ ] Benchmark runner produces comparable scores for any model
- [ ] Random baseline ~25%, heuristic >25%, LoRA target >70%
- [ ] Circuit QA dataset with 2000+ question-answer pairs
- [ ] CI pipeline that flags PRs on benchmark regression (>2% drop)
- [ ] 750+ adversarial test cases proving parser robustness
- [ ] All plans pass Council Gate 1 (Plan Review) and Gate 2 (Execution Review)

**v3.0 (after benchmarks):**
- Domain intelligence: circuit topology graph, subcircuit recognition
- Design rule intelligence: beyond KiCad DRC
- Multi-format support (at least EasyEDA)
- Professional positioning: "The ESLint of KiCad"

---

## Phases 45-58: Strategic Expansion (Council Approved)

**All 14 phases have execution-ready plans with Council approval.**
- 39 plan files, 19,923 lines total
- Council reviewed in 4 waves, all CRITICAL/HIGH findings fixed
- 2 APPROVED, 2 CONDITIONAL APPROVE (remaining items deferred to execution)

### Phase Summary

| Phase | Category | Score Target | Plans | Council Status |
|-------|----------|-------------|-------|----------------|
| 45 | Circuit Topology Graph | Domain 2→4 | 2 | CONDITIONAL |
| 46 | Component Function Recognition | Domain 4→6 | 2 | CONDITIONAL |
| 47 | Circuit Intent Inference | Domain 6→8 | 2 | CONDITIONAL APPROVE |
| 48 | Design Rule Intelligence | Domain 8→10 | 2 | CONDITIONAL APPROVE |
| 49 | One-Command Demo | Demo 6→8 | 2 | APPROVED |
| 50 | Visual Output Showcase | Demo 8→9 | 2 | APPROVED |
| 51 | Interactive Playground | Demo 9→10 | 1 | APPROVED |
| 52 | Synthetic Circuit Generation | Training 8→9 | 2 | APPROVED |
| 53 | Real-World Corpus Expansion | Training 9→10 | 1 | APPROVED |
| 54 | VS Code Extension | Workflow 9→10 | 1 | APPROVED |
| 55 | Abstract AST | Multi-Format foundation | 2 | APPROVED |
| 56 | EasyEDA Support | Multi-Format | 2 | APPROVED |
| 57 | Altium Support | Multi-Format enterprise | 2 | APPROVED |
| 58 | Eagle + OpenWater | Multi-Format | 2 | APPROVED |

### Execution Priority Order

```
Priority 1: Finish v2.4 (38-40)                      ✅ DONE
Priority 2: Benchmarks (41-44)                        🔄 IN PROGRESS
Priority 3: Domain Intelligence (45-48)               📋 READY
Priority 4: Demo Quality (49-51)                      📋 READY
Priority 5: Training Corpus (52-53)                   📋 READY
Priority 6: VS Code Extension (54)                    📋 READY
Priority 7: Multi-Format Foundation (55-56)           📋 READY
Priority 8: Multi-Format Enterprise (57-58)           📋 READY
```

### Timeline

| Quarter | Phases | Milestone |
|---------|--------|-----------|
| Q3 2026 | 38-40 | v2.4 — Schematic Intelligence ✅ |
| Q4 2026 | 41-44 | v2.5 — Benchmark Suite 🔄 |
| Q1 2027 | 45-46 | v2.6 — Circuit Semantics |
| Q2 2027 | 47-48, 49-50 | v2.7 — Intelligence + Demo |
| Q3 2027 | 51-54 | v3.0 — Professional Release |
| Q4 2027 | 55-58 | v3.1 — Multi-Format |

### Key Architecture Decisions (Phases 45-58)

1. **No LLM in domain intelligence** — Phases 45-48 are deterministic, rule-based systems. Circuit classification uses ordered rules (like violation_classifier.py), not AI.
2. **Abstract AST is the keystone** — Phase 55 creates a format-neutral circuit representation. All multi-format phases (56-58) depend on it.
3. **EasyEDA first, Altium last** — EasyEDA is JSON (easy). Altium is binary OLE (hard). Prove the architecture with the easy one.
4. **Altium write is infeasible** — Read-only support + migration to KiCad tool instead of writing .SchDoc.
5. **Playground is vanilla JS** — No React, no build step. FastAPI backend, plain HTML/JS frontend.
6. **10,000+ synthetic circuits** — Phase 52 generates valid circuits from parameterized templates for training diversity.
7. **LABEL_OFFSET fixed** — NetConnector now places labels 2.54mm outward from IC body (commit 1d96620).

### Requirements Tracking

All requirements in `REQUIREMENTS.md`:
- **DOMAIN-01..04** — Phases 45-48 (topology, classification, intent, design rules)
- **DEMO-01..03** — Phases 49-51 (demo pipeline, SVG annotation, playground)
- **CORPUS-01..02** — Phases 52-53 (synthetic generation, real-world corpus)
- **WORKFLOW-01** — Phase 54 (VS Code extension)
- **FORMAT-01..04** — Phases 55-58 (abstract AST, EasyEDA, Altium, Eagle)

---

## References

- `.planning/STRATEGIC-EXPANSION-PLAN.md` — Full 17-phase expansion plan (41-58)
- `.planning/ROADMAP.md` — Complete project roadmap (40 phases, 8 milestones)
- `.planning/REQUIREMENTS.md` — Requirements tracked with phase mapping
- `.planning/phases/40-*/40-COUNCIL-EXEC-REVIEW.md` — Phase 40 Council Gate 2 (APPROVED)
- `.planning/phases/41-pcb-mmlu-benchmark/` — PCB MMLU dataset + runner (2 plans, Council reviewed)
- `.planning/phases/42-circuit-qa-dataset/` — Circuit QA fine-tuning dataset (1 plan)
- `.planning/phases/43-regression-benchmark-suite/` — CI regression detection (1 plan)
- `.planning/phases/44-adversarial-test-generation/` — Mutation/fuzz adversarial tests (1 plan)
- `.planning/phases/45-circuit-topology-graph/` — Topology graph + net classification (2 plans, Council reviewed)
- `.planning/phases/46-component-function-recognition/` — Subcircuit detection + classification (2 plans, Council reviewed)
- `.planning/phases/47-circuit-intent-inference/` — Design intent + improvement suggestions (2 plans, Council reviewed)
- `.planning/phases/48-design-rule-intelligence/` — Domain-specific design rules engine (2 plans, Council reviewed)
- `.planning/phases/49-one-command-demo/` — One-command demo pipeline (2 plans, Council APPROVED)
- `.planning/phases/50-visual-output-showcase/` — SVG annotation + visual diff (2 plans, Council APPROVED)
- `.planning/phases/51-interactive-playground/` — FastAPI playground (1 plan, Council APPROVED)
- `.planning/phases/52-synthetic-circuit-generation/` — Synthetic circuit templates (2 plans, Council APPROVED)
- `.planning/phases/53-real-world-corpus/` — Open-source project curation (1 plan, Council APPROVED)
- `.planning/phases/54-vscode-extension/` — VS Code extension with MCP (1 plan, Council APPROVED)
- `.planning/phases/55-abstract-ast/` — Format-neutral circuit model (2 plans, Council APPROVED)
- `.planning/phases/56-easyeda-support/` — EasyEDA JSON support (2 plans, Council APPROVED)
- `.planning/phases/57-altium-support/` — Altium SchDoc parsing (2 plans, Council APPROVED)
- `.planning/phases/58-eagle-openwater/` — Eagle XML + FormatRegistry (2 plans, Council APPROVED)
