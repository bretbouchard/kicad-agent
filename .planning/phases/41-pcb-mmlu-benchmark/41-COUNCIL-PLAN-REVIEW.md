# The Council of Ricks Plan Review Report

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent)
- **Domain**: EDA / KiCad automation / AI tooling
- **Build System**: CMake (firmware) + pip install -e . (Python)
- **Testing**: pytest (135+ test files, 1392+ tests)
- **CI/CD**: GitHub Actions (build.yml, ci.yml, publish.yml)
- **Key Dependencies**: Pydantic v2, kiutils, networkx, transformers/PEFT (training)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (PCB/EDA specialist), Component Rick (supply chain/dataset quality)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency domain perspective on circuit analysis), Go Bubble Tea Rick (terminal UI patterns for CLI design)
- **Total reviewers this session:** 10/84

---

## Executive Summary
- **Total Issues**: 22
- **Critical (SLC)**: 3
- **High (Architecture/Security)**: 7
- **Medium (Functional)**: 8
- **Low (Style/Completeness)**: 4

---

## Historical Context and Pattern Wisdom (Rickfucius)
**Status**: PATTERNS FOUND

### Relevant Patterns Found

#### Template-Based Generation (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Plans use deterministic template-based question generation, not LLM-based. This mirrors the existing `training/dataset.py` pattern where maze data is generated programmatically. Consistent with the project's philosophy of reproducibility.
- **Recommendation**: Follow pattern -- templates are the correct approach here.

#### Regression Detection (extends existing pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phase 43's `RegressionDetector` mirrors the existing `training/regression.py` pattern with `BaselineStore` and `detect_regression()`. This is a proven pattern in this codebase.
- **Recommendation**: Follow pattern -- reuse the same threshold/config approach.

#### Model Abstraction (follows existing pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: The `BenchmarkModel` ABC with `predict()` method follows the same interface pattern as `inference/evaluator.py`'s evaluation approach. Clean abstraction.
- **Recommendation**: Follow pattern.

### Anti-Patterns Detected

#### NotImplementedError Stubs (violation of SLC principle)
- **Category**: code
- **Problem**: Phase 24 Council audit explicitly removed `NotImplementedError` stubs as SLC violations. Plans 41-02 re-introduces this pattern with `LocalLoRAModel` and `APIModel` raising `NotImplementedError`.
- **Historical Evidence**: Phase 24 remediation removed bus operations entirely rather than keeping stubs. Council review in phase 25 specifically flagged "no NotImplementedError in production code."
- **Current Violations**: 41-02-PLAN.md lines 205 and 214.
- **Recommendation**: Either implement these models in Phase 41-02 or do not create them until Phase 42. Stubs that crash at runtime violate the project's own hard-won standards.

#### Incomplete Dependency Specification
- **Category**: architecture
- **Problem**: Phase 42-01 says `depends_on: [41-01]` but does not depend on 41-02 (the runner). However, the QA dataset's purpose is "fine-tuning" -- which requires the runner to evaluate. The dependency chain is incomplete.
- **Recommendation**: Add explicit dependency on 41-02 for Phase 42, or clarify that QA dataset generation is independent of evaluation.

**Rickfucius Decision**: DOCUMENT DEVIATION -- NotImplementedError pattern must be resolved before execution. Historical precedent from Phase 24 is clear.

---

## SLC Validation (Slick Rick)
**Status**: FAIL

### SLC Anti-Patterns Detected
- **Workarounds**: 0 found
- **Stub Methods**: 2 found (NotImplementedError in 41-02-PLAN.md)
- **TODO/FIXME without tickets**: 0 found
- **Incomplete Implementations**: 3 found (see below)

### SLC Criteria Assessment

- [x] **Simple**: Obvious purpose, minimal learning
  - [Intuitive interface? yes] Schema-first design with Pydantic is clean and well-understood in this codebase.
  - [Self-explanatory features? yes] Category names, QA types, and model names are all descriptive.
  - [Minimal docs needed? yes] CLI usage is documented inline.

- [ ] **Lovable**: Delightful to use, builds trust
  - [Polished design? partial] The `--regression-check` CLI flag is mentioned in Phase 43 overview but not wired into the `__main__.py` from Phase 41-02. CLI design is fragmented across phases.
  - [Graceful errors? no] No error handling for missing dataset file, invalid JSON, or unreachable model API.
  - [Celebrated successes? no] No summary reporting or visualization of benchmark results.

- [ ] **Complete**: Full user journey, no gaps
  - [All APIs implemented? no] LocalLoRAModel and APIModel raise NotImplementedError.
  - [Edge cases handled? no] Missing: empty dataset handling in runner (noted in tests but not in implementation code), missing schematic file handling in dataset builder, timeout handling for API calls.
  - [No broken flows? no] The Phase 43 regression check CLI command (`--regression-check`) is specified in the overview but not in the `__main__.py` implementation plan.

### Critical SLC Violations

#### SLC-1: NotImplementedError in production model classes (41-02-PLAN.md:205, 41-02-PLAN.md:214)
- **Severity**: CRITICAL
- **Description**: `LocalLoRAModel.predict()` and `APIModel.predict()` raise `NotImplementedError`. These classes are registered in `MODEL_REGISTRY` (commented out, but the classes exist and are importable). If someone imports and calls them, they crash.
- **Fix**: Either (a) implement them fully in Phase 41-02, (b) omit them entirely from Phase 41-02 and create them in Phase 42, or (c) use a factory pattern that only registers models that have working implementations. Option (b) is recommended -- the runner is useful with just the random and heuristic baselines.

#### SLC-2: CLI does not support --regression-check flag (43-PLAN.md:42 vs 41-02-PLAN.md)
- **Severity**: HIGH
- **Description**: Phase 43 overview specifies `python -m kicad_agent.benchmarks --regression-check` but the `__main__.py` from Phase 41-02 does not have this flag. Phase 43 does not show updating `__main__.py` to add it. The regression check is done inline in the CI YAML with a Python one-liner instead.
- **Fix**: Phase 43 Plan 43-01 must include modifying `__main__.py` to add `--regression-check`, `--baseline`, and `--current` flags, or the overview must be updated to reflect the actual CLI design.

#### SLC-3: QA dataset generation lacks concrete answer templates (42-01-PLAN.md)
- **Severity**: HIGH
- **Description**: Plan 42-01 specifies 6 QA types with question templates but does not provide answer templates for any type except brief inline examples. The `_generate_violation_qa`, `_generate_signal_flow_qa`, etc. methods have docstrings showing example output but no template structure. For 2000+ QA pairs, the answer generation needs the same template rigor as the question generation.
- **Fix**: Add explicit answer templates for each QA type, parallel to the question templates in Phase 41-01.

**SLC Decision**: REJECT -- NotImplementedError stubs must be removed or resolved before execution.

---

## Security Review (Rick C-137)
**Status**: PASS (with recommendations)

### Threat Assessment

All four plans include STRIDE threat models. This is good practice. Key observations:

#### Template Injection in Question Generation (41-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: injection
- **Description**: Template strings like `"What type of circuit is formed by {components}?"` are filled with context data from schematics. If component reference names or net names contain special characters (unlikely in KiCad but possible), this could produce malformed output. More importantly, the template system uses Python `.format()` or f-string semantics, but the exact mechanism is not specified.
- **Location**: `question_generator.py` (to be created)
- **Exploit Scenario**: A maliciously crafted component name `__class__` or similar Python dunder attribute in a schematic could potentially interact with template rendering. Low probability but should be explicitly mitigated.
- **Fix Recommendation**: Use `string.Template` (safe substitution with `$var` syntax) instead of `.format()` or f-strings. Explicitly validate that all template values are alphanumeric + standard schematic characters.
- **Confidence**: 0.6 (below 0.8 threshold -- informational)

#### Dataset JSON Integrity (41-01, 42-01, 43-01, 44-01)
- **Severity**: LOW
- **Category**: tampering
- **Description**: All threat models accept tampering risk because datasets are version-controlled. This is correct. Git diff provides tamper detection.
- **Confidence**: 0.9

#### Fuzz Test Resource Consumption (44-01-PLAN.md)
- **Severity**: LOW
- **Category**: denial_of_service
- **Description**: 500 fuzz tests on S-expression mutations. Each test parses potentially malformed content. The plan correctly bounds the count and uses seeded RNG. No network or external resource access.
- **Confidence**: 0.9

**Security Summary**:
- High Severity: 0
- Medium Severity: 1 (template injection -- informational, below confidence threshold)
- Low Severity: 2

**Security Decision**: APPROVE -- no exploitable vulnerabilities at 0.8+ confidence. Template safety recommendation is informational.

---

## Code Quality Review (Rick Sanchez)
**Status**: FAIL

### Issues Found

#### ARCH-1: NotImplementedError re-introduced after Phase 24 remediation (41-02-PLAN.md:205, 41-02-PLAN.md:214)
- **Severity**: CRITICAL
- **Category**: anti-pattern
- **Description**: The project spent Phase 24 specifically removing `NotImplementedError` stubs. The Council audit at that time said: "No `NotImplementedError` raised in source." Re-introducing this pattern in new code violates established code quality standards.
- **Engineering Principle**: Code should do what it advertises, or not exist.
- **Fix Recommendation**: Remove `LocalLoRAModel` and `APIModel` from Phase 41-02 entirely. Create them in Phase 42 when they can be implemented. The runner is fully functional with just `BaselineRandom` and `BaselineHeuristic`.

#### ARCH-2: BenchmarkResult schema duplication between runner.py and plan overview (41-PLAN.md vs 41-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: consistency
- **Description**: The `BenchmarkResult` schema is defined in both `41-PLAN.md` (phase overview) and `41-02-PLAN.md` (detailed plan). The definitions match, but having two sources of truth for the same schema creates maintenance risk.
- **Engineering Principle**: Single source of truth.
- **Fix Recommendation**: Define the schema once in 41-02-PLAN.md and reference it from 41-PLAN.md.

#### ARCH-3: No error handling for file I/O in dataset builder (41-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: robustness
- **Description**: `DatasetBuilder._extract_subcircuits()` calls `SchematicGraph.from_file()` but the plan does not specify handling for: (a) file not found, (b) invalid KiCad format, (c) empty schematic, (d) schematics without ICs (only passives).
- **Engineering Principle**: Handle all failure modes at system boundaries.
- **Fix Recommendation**: Add explicit error handling for each source schematic, with warnings for unprocessable files and graceful degradation.

#### ARCH-4: Distractor quality undefined for several categories (41-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: completeness
- **Description**: The `_DISTRACTOR_POOLS` dict shows detailed distractors for `topology_recognition` but the plan says `# ... 6 more categories` without specifying them. For 500+ questions across 8 categories, each category needs explicit distractor pools. This is the core quality mechanism -- plausible wrong answers are what make MMLU-style benchmarks meaningful.
- **Engineering Principle**: Complete specifications for all code paths.
- **Fix Recommendation**: Specify distractor pools for all 8 categories before execution.

#### ARCH-5: Difficulty assignment algorithm unspecified (41-01-PLAN.md)
- **Severity**: LOW
- **Category**: completeness
- **Description**: The plan says "Assign difficulty based on component count / violation complexity" but does not specify the algorithm. What component count = easy vs medium vs hard? What violation complexity score?
- **Engineering Principle**: Deterministic behavior.
- **Fix Recommendation**: Define explicit thresholds. Example: easy = 1-3 components, medium = 4-8 components, hard = 9+ components. Or: easy = single-pin violation, medium = multi-component violation, hard = cross-sheet violation.

#### ARCH-6: Phase 42 QA generator depends on Phase 41 question_generator (42-01-PLAN.md key_links)
- **Severity**: MEDIUM
- **Category**: architecture
- **Description**: The key_links section of 42-01-PLAN shows `qa_generator.py` imports from `question_generator.py` for "shared source extraction patterns and subcircuit identification." This creates tight coupling between MMLU question generation and QA pair generation. If the template structure in 41-01 changes, 42-01 breaks.
- **Engineering Principle**: Loose coupling between modules.
- **Fix Recommendation**: Extract shared subcircuit identification into a separate module (e.g., `benchmarks/subcircuit_extractor.py`) that both generators depend on, rather than having the QA generator depend on the MMLU question generator.

#### ARCH-7: RegressionDetector does not handle statistical significance (43-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: correctness
- **Description**: The 2% threshold is absolute, not statistical. A category with 50 questions and a 2% drop (1 question difference) triggers regression. With small sample sizes, this could be noise. The plan does not address statistical confidence.
- **Engineering Principle**: Measurements should distinguish signal from noise.
- **Fix Recommendation**: Either (a) increase minimum questions per category to make 2% meaningful (200+ per category), or (b) use a confidence interval approach, or (c) explicitly document that the threshold is intentionally conservative and may produce false positives. Option (c) is simplest and acceptable for a CI gate.

#### ARCH-8: MutationEngine operates on .kicad_sch files but test fixtures are limited (44-01-PLAN.md)
- **Severity**: LOW
- **Category**: testing
- **Description**: The plan references `tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch` as the single source for mutation testing. A single schematic provides limited mutation surface diversity. The Arduino Mega is a large board but represents only one circuit topology.
- **Engineering Principle**: Test diversity matters.
- **Fix Recommendation**: Add at least 2-3 more fixture schematics with different topologies (e.g., a simple filter circuit, a power supply, a mixed-signal board). The existing fixtures directory only has Arduino_Mega, RaspberryPi-uHAT, and Regulator_Current symbol lib.

**Code Summary**:
- Critical: 1
- High: 0
- Medium: 5
- Low: 2

**Code Decision**: REJECT -- CRITICAL issue (NotImplementedError) must be resolved.

---

## Design Review (Rick Prime)
**Status**: FAIL (minor)

### Issues Found

#### DESIGN-1: CLI design fragmented across phases
- **Severity**: HIGH
- **Category**: consistency
- **Description**: Phase 41-02 creates `__main__.py` with `--dataset`, `--model`, `--output` flags. Phase 43 overview adds `--regression-check`. Phase 44 overview adds `--adversarial --count`. These are all additions to the same CLI entry point, but Phase 43 and 44 plans don't show updating `__main__.py`. The CLI will have a fragmented evolution.
- **Design Principle**: CLI should be designed as a cohesive interface from the start.
- **Fix Recommendation**: Design the full CLI surface in Phase 41-02 (even if some flags are stubs that print "not yet implemented"), then implement each flag's behavior in subsequent phases. This prevents a piecemeal CLI experience.

#### DESIGN-2: No human-readable results output
- **Severity**: MEDIUM
- **Category**: UX
- **Description**: The CLI outputs JSON results and a brief summary. There is no rich formatting (table, color-coded categories, trend arrows). For a tool that will be run frequently in CI, a clear visual summary is important.
- **Design Principle**: Tooling should be delightful, not just functional.
- **Fix Recommendation**: Add a `--format table` option that outputs a formatted table of per-category accuracy with delta indicators. Consider using `rich` library for terminal formatting (already common in Python CLI tools).

#### DESIGN-3: No benchmark dataset versioning strategy
- **Severity**: MEDIUM
- **Category**: maintainability
- **Description**: The dataset is `benchmarks/pcb-mmlu-v1.json`. When questions are added or corrected, there is no version migration strategy. The `version` field is `"1.0.0"` but no plan for how it increments or how results are compared across versions.
- **Fix Recommendation**: Define versioning rules in 41-CONTEXT.md: patch = typo fixes, minor = new questions, major = category schema changes. Include version in BenchmarkResult for cross-version tracking.

**Design Summary**:
- High: 1
- Medium: 2
- Low: 0

**Design Decision**: REJECT -- CLI fragmentation must be resolved architecturally before execution.

---

## KiCad/EDA Domain Review (KiCad Rick)
**Status**: PASS (with recommendations)

### Domain Assessment

#### Circuit Intelligence Coverage
The 8 PCB MMLU categories are well-chosen for measuring circuit understanding:
- Component Identification, Topology Recognition, Signal Flow, Power Design, Pin Function, Net Purpose, Design Rules, Troubleshooting
- These cover the core competencies an EDA AI tool should demonstrate.

#### Source Material Assessment
The plans reference real analog-ecosystem schematics:
- compressor (THAT4301 VCA) -- good, complex mixed-signal
- LFO (CD4060 oscillator) -- good, timing circuit
- ADSR (envelope) -- good, analog control
- VCA, VCF, delay, moog-ladder -- good, audio signal chain
- mic-pre, class-a-gain -- good, analog amplification
- control-center (RP2040) -- good, digital/mixed

This is a solid source corpus covering analog, digital, and mixed-signal domains.

### Issues Found

#### DOMAIN-1: Subcircuit extraction from schematics is underspecified (41-01-PLAN.md)
- **Severity**: HIGH
- **Category**: algorithm
- **Description**: `_extract_subcircuits()` says "Group components by proximity and connectivity. Identify ICs and their surrounding passives. Classify subcircuit function from IC type." This is the core algorithm that makes the entire benchmark possible, and it is described in 3 sentences. KiCad schematics have hierarchical sheets, power symbols, no-connect flags, and bus entries that complicate connectivity analysis. The existing `SchematicGraph` provides wire tracing and pin positions, but does not have a built-in subcircuit grouping feature.
- **KiCad-Specific Concern**: Components in KiCad are connected by wires, labels, and hierarchical pins. A "subcircuit" is not a formal concept in KiCad -- it must be inferred. The plan needs to define how to handle: (a) power distribution networks (shared across all subcircuits), (b) hierarchical sheet boundaries, (c) global labels that span sheets, (d) passive-only subcircuits (RC filters, voltage dividers with no IC).
- **Fix Recommendation**: Define the subcircuit extraction algorithm explicitly:
  1. Start from each IC (lib_id contains "NE5532", "THAT4301", "CD4066", etc.)
  2. Trace all nets connected to IC pins via `SchematicGraph.trace_endpoint_to_net()`
  3. Collect all components connected to those nets (1 hop from IC)
  4. Classify based on IC type + passive count + net names
  5. Handle shared power nets by excluding VCC/GND from subcircuit grouping

#### DOMAIN-2: Signal flow QA type requires graph traversal not specified (42-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: algorithm
- **Description**: "What is the signal path from COMP_IN to EQ_OUT?" requires tracing a path through the schematic graph from input label to output label, passing through intermediate components. The plan does not specify how to perform this trace. The existing `SchematicGraph` has `trace_endpoint_to_net()` but not a full input-to-output path tracer.
- **Fix Recommendation**: Either (a) implement a `trace_signal_path(start_label, end_label)` method in `SchematicGraph` or a helper, or (b) pre-author signal paths for each source schematic and store them in the source data.

#### DOMAIN-3: ERC troubleshooting questions may be brittle (41-01-PLAN.md)
- **Severity**: LOW
- **Category**: quality
- **Description**: ERC violation types change between KiCad versions. Questions based on specific violation descriptions may become outdated. The plan references `erc_parser.py` which parses ERC output, but the question templates use specific violation text.
- **Fix Recommendation**: Use violation type codes (e.g., `power_pin_not_driven`) rather than human-readable descriptions in templates. Map codes to descriptions at runtime.

**Domain Summary**:
- High: 1
- Medium: 1
- Low: 1

**Domain Decision**: CONDITIONAL APPROVE -- subcircuit extraction algorithm must be specified before execution.

---

## Requirement Coverage Assessment

| Requirement | Phase | Plan | Coverage |
|------------|-------|------|----------|
| BENCH-01: PCB MMLU Benchmark Dataset | 41 | 41-01 | COVERED -- 500+ questions, 8 categories, schema, generation, validation |
| BENCH-02: Benchmark Runner + Baseline | 41 | 41-02 | PARTIAL -- Runner works for random/heuristic. LocalLoRA and API models are stubs |
| BENCH-03: Circuit QA Dataset | 42 | 42-01 | COVERED -- 2000+ QA pairs, 6 types, schema, generation |
| BENCH-04: Regression Benchmark Suite | 43 | 43-01 | COVERED -- regression detection, CI, historical tracking |
| BENCH-05: Adversarial Test Generation | 44 | 44-01 | COVERED -- mutation, property-based, fuzz testing, 750+ tests |

**Coverage Gap**: BENCH-02 is partially covered. The requirement says "evaluate any model" but two of four model types are NotImplementedError stubs. The requirement should clarify whether "any model" means the interface exists (even if not all implementations are ready) or whether all declared model types must be functional.

**Missing Requirements Note**: REQUIREMENTS.md does not contain BENCH-01 through BENCH-05. These requirements exist only in the phase plans. They should be added to REQUIREMENTS.md for traceability.

---

## Missing Edge Cases

### What the Plans Do Not Address

1. **Deterministic generation**: Question generation uses `random` module for difficulty selection and distractor choice. Plans do not specify a global seed for reproducibility. Two runs of dataset generation could produce different question IDs/ordering. Phase 44 correctly uses seeded RNG for adversarial tests, but Phases 41 and 42 do not.

2. **Dataset splitting**: No mention of train/validation/test splits for the QA dataset. If the same QA pairs are used for both fine-tuning and evaluation, results are meaningless. The PCB MMLU (multi-choice) is evaluation-only, but the QA dataset (Phase 42) needs a split strategy.

3. **Component value units**: Value calculation QA type (42-01) mentions "What value should C47 be for a 10ms time constant?" but does not specify how component values are extracted from schematics. KiCad stores values as strings ("10k", "100nF", "10u"). Parsing these requires unit handling.

4. **Multi-sheet schematics**: Several analog-ecosystem modules have hierarchical sheets (compressor has left-channel, cv-interface, digital-control sub-sheets). The dataset builder needs to handle sub-sheet references when tracing connectivity. The existing `SchematicGraph.from_file()` parses a single sheet.

5. **Benchmark JSON size**: 500+ questions with full explanations could be 2-5MB. Plan does not discuss size or loading performance. For CI, this matters -- large JSON files slow down checkout and parsing.

6. **Adversarial mutation side effects**: `MutationEngine` writes mutated schematics to temp files but does not specify cleanup. 200 mutations across test runs could leave temp files accumulating.

7. **Property-based test template circuits**: Phase 44 mentions "Generate random valid circuits from templates" but does not specify what these templates are or how they produce valid KiCad S-expressions. This is a significant implementation gap.

8. **CI job timeout**: The GitHub Actions workflow in Phase 43 runs the full benchmark suite. No timeout is specified. For a 500-question benchmark with a heuristic model, this should be fast, but no explicit bound is set.

---

## Disagreement Resolution

No disagreements between Council members on this review. All specialists converge on the same core finding: the NotImplementedError stubs are the critical blocker. The subcircuit extraction algorithm underspecification is the second-tier concern.

---

## Final Council Decision

**Evil Morty's Ruling**: **REJECT**

### Decision Summary
- **SLC Validation**: FAIL (3 violations)
- **Security Review**: PASS
- **Code Quality**: FAIL (1 CRITICAL, 5 MEDIUM)
- **Design Review**: FAIL (1 HIGH, 2 MEDIUM)
- **KiCad Domain**: CONDITIONAL APPROVE (1 HIGH)
- **Historical Context**: DOCUMENT DEVIATION

### All Issues to Fix Before Approval (sorted by severity)

#### CRITICAL (blocks approval)

1. **[CRITICAL] Remove NotImplementedError stubs from 41-02-PLAN.md** (41-02-PLAN.md:205, 41-02-PLAN.md:214)
   - Remove `LocalLoRAModel` and `APIModel` classes from Phase 41-02, or implement them fully.
   - Recommended: Remove them. Phase 41-02 only needs `BaselineRandom` and `BaselineHeuristic`.
   - Create a separate plan for model integrations (can be Phase 42-02 or deferred to training phases).

2. **[CRITICAL] Specify subcircuit extraction algorithm in 41-01-PLAN.md** (41-01-PLAN.md)
   - Define the algorithm for grouping connected components into subcircuits.
   - Handle: power net exclusion, hierarchical sheets, passive-only groups, multi-IC groups.
   - Provide pseudo-code, not just prose description.

3. **[CRITICAL] Add BENCH-01 through BENCH-05 to REQUIREMENTS.md** (REQUIREMENTS.md)
   - Requirements must be traceable from plans to the formal requirements document.

#### HIGH (strongly recommended)

4. **[HIGH] Design complete CLI surface in Phase 41-02** (41-02-PLAN.md, 43-PLAN.md, 44-PLAN.md)
   - Add `--regression-check`, `--baseline`, `--current`, `--adversarial`, `--count` flags to the CLI design in 41-02.
   - Flags not yet implemented should print "Not available until Phase N" rather than being absent.

5. **[HIGH] Specify distractor pools for all 8 categories in 41-01-PLAN.md** (41-01-PLAN.md)
   - Currently only `topology_recognition` has detailed distractors.
   - All 8 categories need explicit plausible wrong answer pools.

6. **[HIGH] Specify answer templates for all 6 QA types in 42-01-PLAN.md** (42-01-PLAN.md)
   - Currently only question templates are specified.
   - Answer templates must be deterministic and sourced from verified circuit analysis.

7. **[HIGH] Extract shared subcircuit logic to avoid tight coupling** (42-01-PLAN.md key_links)
   - Create `benchmarks/subcircuit_extractor.py` shared by both generators.
   - Remove direct dependency of `qa_generator.py` on `question_generator.py`.

8. **[HIGH] Add global seed for reproducible dataset generation** (41-01-PLAN.md, 42-01-PLAN.md)
   - Phase 44 correctly uses seeded RNG. Phases 41 and 42 should too.
   - Add `seed` parameter to `DatasetBuilder` and `QAGenerator`.

9. **[HIGH] Define dataset splitting strategy for QA dataset** (42-01-PLAN.md)
   - Specify train/validation/test split ratios.
   - Ensure fine-tuning data and evaluation data are disjoint.

10. **[HIGH] Resolve CLI --regression-check implementation gap** (43-01-PLAN.md)
    - Phase 43 must include updating `__main__.py` to add the regression check subcommand.
    - The CI YAML should call the CLI, not an inline Python script.

#### MEDIUM (should be addressed)

11. **[MEDIUM] Add error handling for schematic file I/O** (41-01-PLAN.md)
    - Handle missing files, invalid format, empty schematics, no-IC schematics.

12. **[MEDIUM] Define difficulty assignment thresholds** (41-01-PLAN.md)
    - Explicit mapping: component count ranges to difficulty levels.

13. **[MEDIUM] Define dataset versioning strategy** (41-CONTEXT.md)
    - Patch/minor/major rules for `pcb-mmlu-v1.json` version field.

14. **[MEDIUM] Address statistical significance of 2% regression threshold** (43-01-PLAN.md)
    - Document that 2% is intentionally conservative and may produce false positives on small categories.

15. **[MEDIUM] Specify signal flow path tracing algorithm** (42-01-PLAN.md)
    - Either implement `trace_signal_path()` or pre-author paths for source schematics.

16. **[MEDIUM] Add rich terminal output for benchmark results** (41-02-PLAN.md)
    - Consider `--format table` option with per-category breakdown.

17. **[MEDIUM] Handle multi-sheet schematics in dataset builder** (41-01-PLAN.md)
    - Several analog-ecosystem modules have hierarchical sheets.
    - `SchematicGraph.from_file()` only parses a single file.

18. **[MEDIUM] Specify component value unit parsing** (42-01-PLAN.md)
    - KiCad stores values as strings. Define how to parse "10k", "100nF", "10u" for calculations.

#### LOW (should be tracked)

19. **[LOW] Deduplicate BenchmarkResult schema between overview and detailed plan** (41-PLAN.md, 41-02-PLAN.md)

20. **[LOW] Add test fixture diversity for mutation engine** (44-01-PLAN.md)
    - Arduino_Mega is the only fixture schematic. Add 2-3 more topologies.

21. **[LOW] Specify property-based test circuit templates** (44-01-PLAN.md)
    - "Generate random valid circuits from templates" -- what templates?

22. **[LOW] Add CI timeout and temp file cleanup** (43-01-PLAN.md, 44-01-PLAN.md)

### Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): REJECT
- Rick C-137 (Security): APPROVE
- Slick Rick (SLC): REJECT

**Wave Beta (Wisdom):**
- Rick Prime (Design): REJECT
- Rickfucius (Historian): DOCUMENT DEVIATION

**Wave Gamma (Domain):**
- KiCad Rick (PCB/EDA): CONDITIONAL APPROVE
- Component Rick (Dataset Quality): CONDITIONAL APPROVE

**Wave Delta (Pipeline):**
- GSD Plan Checker: REJECT (missing requirements in REQUIREMENTS.md)

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick: APPROVE (with signal flow concern)
- Go Bubble Tea Rick: CONDITIONAL APPROVE (CLI fragmentation concern)

**Final:**
- **Evil Morty**: REJECT

---

## Recommended Path Forward

### Option A: Revise and Resubmit (Recommended)
1. Fix the 3 CRITICAL issues (NotImplementedError, subcircuit algorithm, REQUIREMENTS.md)
2. Fix the 7 HIGH issues (CLI design, distractor pools, answer templates, coupling, seed, splitting, regression CLI)
3. Address MEDIUM issues as time permits (they can be tracked as beads and fixed during execution)
4. Resubmit to Council for re-review

### Option B: Conditional Approval
1. Fix CRITICAL issues only
2. Track HIGH issues as beads with explicit acceptance that they will be resolved during execution
3. Proceed with execution under the condition that HIGH issues are addressed before the relevant phase starts

### Estimated Revision Effort
- CRITICAL fixes: 2-3 hours
- HIGH fixes: 4-6 hours
- MEDIUM fixes: 3-4 hours (can be deferred)

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Fresh eyes catch blind spots. Domain experts catch details. Evil Morty makes the final call. No appeals."

**Review Completed**: 2026-05-31
**Review Duration**: Council review session
**Review Type**: Plan Review (Council Gate 1)
**Next Step**: Revise plans addressing CRITICAL and HIGH findings, then resubmit for re-review.
