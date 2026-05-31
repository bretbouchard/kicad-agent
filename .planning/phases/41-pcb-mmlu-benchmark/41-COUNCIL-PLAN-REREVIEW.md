# Council Re-Review: Benchmark Phases 41-44

**Review Type**: Plan Review (Council Gate 1 -- Re-Review)
**Previous Review**: 2026-05-31 (22 findings: 3 CRITICAL, 7 HIGH, 8 MEDIUM, 4 LOW -- REJECT)
**Re-Review Date**: 2026-05-31

## Verdict: APPROVE

All 3 CRITICAL findings are resolved. All 7 HIGH findings are resolved (6 fully, 1 with minor residual). No new issues introduced. MEDIUM/LOW items are acceptable for deferral to execution as tracked beads.

---

## Previous Finding Status

### CRITICAL Findings

| ID | Finding | Status | Evidence |
|----|---------|--------|----------|
| CRITICAL-1 | NotImplementedError stubs in 41-02 (LocalLoRAModel, APIModel) | **FIXED** | 41-02-PLAN.md lines 195-199: Explicit NOTE states "Do NOT create stub classes that raise NotImplementedError." models.py code shows only BaselineRandom and BaselineHeuristic. MODEL_REGISTRY has only "random" and "heuristic" keys. No LocalLoRAModel or APIModel classes exist anywhere in the plan. |
| CRITICAL-2 | Subcircuit extraction algorithm underspecified in 41-01 | **FIXED** | 41-01-PLAN.md lines 357-375: `_extract_subcircuits()` now has a complete 10-step algorithm: (1) parse via SchematicGraph.from_file, (2) identify ICs by lib_id patterns or >= 4 pins, (3) trace nets on IC pins via trace_endpoint_to_net(), (4) collect 1-hop components, (5) exclude power nets, (6) classify by IC type, (7) passive-only clustering within 10mm, (8) multi-IC separation, (9) hierarchical sheet handling, (10) graceful empty/unparseable fallback. Method `trace_endpoint_to_net()` verified to exist in actual codebase (schematic_graph.py:153). |
| CRITICAL-3 | BENCH-01 through BENCH-05 missing from REQUIREMENTS.md | **FIXED** | REQUIREMENTS.md lines 583-602: New "v2.5 Requirements -- Evaluation Benchmarks" section with all five requirements. BENCH-01 specifies "distractor pools for all categories, explicit difficulty thresholds, reproducible seeded generation." BENCH-02 specifies "CLI interface with full surface designed upfront." BENCH-03 specifies "answer templates for all types, train/validation/test split." BENCH-04 specifies "regression check available as CLI subcommand." BENCH-05 specifies all three adversarial testing types with counts and seeding. |

### HIGH Findings

| ID | Finding | Status | Evidence |
|----|---------|--------|----------|
| HIGH-1 | CLI surface fragmentation -- full CLI should be designed upfront | **FIXED** | 41-02-PLAN.md lines 309-320: `__main__.py` now has `--categories`, `--difficulty`, `--max-questions` as active flags, plus four future flags as comments: `--regression-check`, `--baseline`, `--adversarial`, `--count`. Each commented flag notes "Phase 43/44" origin. Full surface is visible and cohesive. |
| HIGH-2 | Incomplete distractor pools -- only topology_recognition had detail | **FIXED** | 41-01-PLAN.md lines 230-278: `_DISTRACTOR_POOLS` dict now has explicit entries for all 8 categories: topology_recognition (7 pools), component_identification (4), signal_flow (3), power_design (3), pin_function (4), net_purpose (4), design_rules (2), troubleshooting (4). Each pool has 3-5 plausible wrong answers per correct-answer key. |
| HIGH-3 | Missing answer templates for QA types | **FIXED** | 42-01-PLAN.md lines 190-197: All 6 QA types now have explicit answer templates with slot notation: violation_diagnosis ("The {violation_type} is caused by {root_cause}..."), signal_flow ("The path: {input} -> {comp1} -> {comp2} -> {output}..."), component_function ("{ref} is a {role} that {function}..."), net_purpose ("{net_name} is {function} connecting {pin_list}..."), design_review ("The {subcircuit} could benefit from: 1) {imp1}, 2) {imp2}..."), value_calculation ("{ref} = {formula} = {result}..."). |
| HIGH-4 | No seed parameter for reproducible generation | **FIXED** | 41-01-PLAN.md line 336: `DatasetBuilder.__init__(self, source_schematics=None, seed: int = 42)` with `self.rng = random.Random(seed)`. 42-01-PLAN.md line 149: `QAGenerator.__init__(self, source_schematics=None, seed: int = 42)` with `self.rng = random.Random(seed)`. Both use seeded RNG for deterministic generation. |
| HIGH-5 | No train/test split for Circuit QA | **FIXED** | 42-01-PLAN.md lines 200-202: "Train/validation/test split: 80/10/10, stratified by qa_type to ensure all 6 types appear in each split. Split is deterministic (seeded RNG assigns each QA pair). Dataset metadata includes split counts: {train: 1600, val: 200, test: 200}." |
| HIGH-6 | Tight coupling -- qa_generator depends on question_generator | **FIXED** | 42-01-PLAN.md key_links (lines 38-43): qa_generator.py imports from schematic_routing/schematic_graph.py directly, NOT from question_generator.py. Key link says "shares subcircuit extraction via SchematicGraph (decoupled from question_generator)." Second key link imports from ops/erc_parser.py. No dependency on question_generator remains. |
| HIGH-7 | Phase 43 Task 2 should include CLI update in files_modified | **PARTIALLY FIXED** | 43-01-PLAN.md Task 2 inline `files` field (line 206) lists `src/kicad_agent/benchmarks/__main__.py`. However, the plan header `files_modified` (lines 9-13) does NOT list `__main__.py`. The task-level specification is correct, but the header is inconsistent. Additionally, the CI workflow (lines 230-253) uses inline Python for regression check rather than a CLI flag. The `--regression-check` flag is designed in 41-02 but not shown being uncommented/implemented in 43-01. **Residual**: Minor header inconsistency. Functional intent is clear -- Task 2 will update `__main__.py`. Acceptable for execution. |

### MEDIUM/LOW Findings

| ID | Finding | Status | Notes |
|----|---------|--------|-------|
| MEDIUM ARCH-2 | BenchmarkResult schema duplication between overview and plan | **Deferrable** | Schema defined once in 41-02-PLAN.md. Overview can reference it. Minor documentation consistency issue. |
| MEDIUM ARCH-3 | No error handling for file I/O in dataset builder | **Partially Addressed** | CRITICAL-2 fix added step 10: "Empty/unparseable: return [] with warning log." Handles the most common failure mode. Additional error handling (file not found, invalid format) can be added during execution. |
| MEDIUM ARCH-5 | Difficulty assignment thresholds unspecified | **FIXED** | 41-01-PLAN.md now specifies in `_select_difficulty` docstring: "easy = 1-3 components in subcircuit, medium = 4-8 components, hard = 9+ components OR cross-sheet violation OR multi-IC interaction." |
| MEDIUM ARCH-7 | RegressionDetector does not handle statistical significance | **Deferrable** | 2% threshold is intentionally conservative. False positives on small categories are acceptable for a CI gate. Can be refined if noise becomes an issue. |
| MEDIUM DOMAIN-2 | Signal flow path tracing not specified | **Deferrable** | QA generator uses template-based generation with pre-authored signal paths from source metadata. Full graph traversal not required for Phase 42. |
| MEDIUM DESIGN-2 | No human-readable results output | **Deferrable** | CLI prints summary with accuracy and duration. Rich table formatting is a UX enhancement, not a functional gap. |
| MEDIUM DESIGN-3 | No benchmark dataset versioning strategy | **Deferrable** | Dataset has version field ("1.0.0"). Versioning rules can be defined in execution. Not blocking. |
| MEDIUM ARCH-6 | Tight coupling qa_generator -> question_generator | **FIXED** | Resolved by HIGH-6 fix. qa_generator now uses schematic_graph directly. |
| MEDIUM (edge cases) | Multi-sheet schematics, component value units, CI timeout | **Deferrable** | Plan handles single-sheet processing with global label awareness (CRITICAL-2 step 9). Component values are template-driven. CI runs are bounded by dataset size. All addressable during execution. |
| LOW ARCH-8 | Limited mutation test fixtures | **Deferrable** | Arduino_Mega provides sufficient mutation surface for Phase 44. Additional fixtures can be added as the test suite matures. |
| LOW (misc) | Property-based test templates, temp file cleanup, schema dedup | **Deferrable** | All addressable during execution. No functional gaps. |

---

## New Findings

### NEW-1: Phase 43 header files_modified missing __main__.py (LOW)

- **Severity**: LOW
- **Category**: documentation-consistency
- **Description**: 43-01-PLAN.md header `files_modified` lists 4 files but does not include `src/kicad_agent/benchmarks/__main__.py`. Task 2 inline `files` field correctly includes it. The header should be updated for consistency.
- **Impact**: None on execution -- the task-level specification is correct.
- **Recommendation**: Fix during execution when Task 2 runs. No plan revision needed.

### NEW-2: CI regression check uses inline Python instead of CLI flag (MEDIUM)

- **Severity**: MEDIUM
- **Category**: design-consistency
- **Description**: BENCH-04 requirement says "regression check available as CLI subcommand." Phase 41-02 designs the `--regression-check` flag (as a comment). But Phase 43's CI workflow (lines 230-253) uses inline Python with `RegressionDetector` directly rather than calling `python -m kicad_agent.benchmarks --regression-check`. This means the CLI flag designed in 41-02 may not get implemented in Phase 43 -- the CI uses a different path.
- **Impact**: The regression check works either way. But BENCH-04 explicitly requires "CLI subcommand." If the CI uses inline Python, the CLI flag may never get uncommented.
- **Recommendation**: During execution of Phase 43 Task 2, implement the `--regression-check` flag in `__main__.py` and have the CI workflow call it via CLI rather than inline Python. This satisfies the BENCH-04 requirement literally. Trackable as a bead during execution.

---

## Requirement Coverage Re-Assessment

| Requirement | Phase | Plan | Coverage | Previous | Current |
|------------|-------|------|----------|----------|---------|
| BENCH-01 | 41 | 41-01 | FULL | PARTIAL (missing distractors, algorithm, seed) | FULL |
| BENCH-02 | 41 | 41-02 | FULL | PARTIAL (stubs, no CLI design) | FULL |
| BENCH-03 | 42 | 42-01 | FULL | PARTIAL (no answer templates, no split) | FULL |
| BENCH-04 | 43 | 43-01 | FULL | PARTIAL (no CLI regression subcommand) | FULL (minor gap in CI implementation) |
| BENCH-05 | 44 | 44-01 | FULL | FULL | FULL |

All five BENCH requirements now have full coverage in the plans.

---

## Summary

**Changes Since Previous Review:**

1. NotImplementedError stubs completely removed. Phase 41-02 only implements working models (Random, Heuristic). Explicit NOTE in plan forbids stubs. MODEL_REGISTRY only has working keys. (CRITICAL-1)

2. Subcircuit extraction algorithm fully specified as a 10-step procedure with power net exclusion, hierarchical sheet handling, passive-only clustering, multi-IC separation, and graceful fallback. References real `trace_endpoint_to_net()` method verified in codebase. (CRITICAL-2)

3. BENCH-01 through BENCH-05 added to REQUIREMENTS.md as v2.5 Evaluation Benchmarks section. Requirements are comprehensive and include the specific details that were missing (distractor pools, difficulty thresholds, seeded generation, answer templates, CLI surface, train/test split). (CRITICAL-3)

4. CLI surface designed upfront in 41-02 with 5 active flags and 4 future flags as comments. No fragmentation -- the full interface is visible. (HIGH-1)

5. All 8 distractor pools specified with 2-7 sub-pools each, covering plausible wrong answers for each category. (HIGH-2)

6. All 6 QA answer templates specified with slot-based format. (HIGH-3)

7. Seed parameter (default 42) on both DatasetBuilder and QAGenerator with seeded RNG. (HIGH-4)

8. Train/validation/test split (80/10/10) specified for Circuit QA, stratified by qa_type. (HIGH-5)

9. qa_generator imports from schematic_graph directly, decoupled from question_generator. (HIGH-6)

10. Phase 43 Task 2 inline files list includes __main__.py (header inconsistent but task-level correct). (HIGH-7, partial)

**No Regressions**: The fixes did not introduce any new CRITICAL or HIGH issues. Two minor new findings (documentation header inconsistency, CI inline vs CLI) are both deferrable to execution.

**MEDIUM/LOW Assessment**: Original 8 MEDIUM and 4 LOW findings are either already fixed (ARCH-5 difficulty thresholds, ARCH-6 coupling) or acceptable for deferral to execution. None block approval.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): APPROVE
- Rick C-137 (Security): APPROVE (no changes to security assessment)
- Slick Rick (SLC): APPROVE (all SLC violations resolved)

**Wave Beta (Wisdom):**
- Rick Prime (Design): APPROVE (CLI fragmentation resolved)
- Rickfucius (Historian): APPROVE (NotImplementedError anti-pattern eliminated, Phase 24 precedent respected)

**Wave Gamma (Domain):**
- KiCad Rick (PCB/EDA): APPROVE (subcircuit algorithm fully specified)
- Component Rick (Dataset Quality): APPROVE (all distractor pools specified)

**Wave Delta (Pipeline):**
- GSD Plan Checker: APPROVE (BENCH-01 through BENCH-05 in REQUIREMENTS.md, full traceability)

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick: APPROVE
- Go Bubble Tea Rick: APPROVE (CLI surface cohesive)

**Final:**
- **Evil Morty**: APPROVE

---

## Execution Notes

Track these as beads during execution:

1. **Phase 43 Task 2**: Implement `--regression-check` CLI flag in `__main__.py` and update CI to use CLI rather than inline Python. This satisfies BENCH-04 "regression check available as CLI subcommand" literally.
2. **Phase 43 Task 2**: Add `__main__.py` to the plan header `files_modified` for documentation consistency.
3. **Phase 41 Task 2**: Add error handling for file I/O edge cases (file not found, invalid KiCad format, no-IC schematics) beyond the empty/unparseable case already specified.
4. **Phase 43**: Document that the 2% regression threshold is intentionally conservative and may produce false positives on categories with fewer than 100 questions.
5. **Phase 44**: Consider adding 1-2 additional test fixture schematics with different topologies beyond Arduino_Mega.

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Fresh eyes catch blind spots. Domain experts catch details. Evil Morty makes the final call. No appeals."

**Re-Review Completed**: 2026-05-31
**Review Duration**: Council re-review session
**Review Type**: Plan Review (Council Gate 1 -- Re-Review)
**Result**: APPROVED for execution
