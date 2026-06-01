---
phase: 42-circuit-qa-dataset
plan: 01
subsystem: benchmarks
tags: [qa-dataset, fine-tuning, circuit-understanding, pydantic, template-generation, stratified-split]

# Dependency graph
requires:
  - phase: 41-01
    provides: BenchmarkQuestion schema and question_generator patterns
provides:
  - CircuitQAPair and CircuitQADataset schemas
  - QAGenerator with 6 QA type template-based generation
  - benchmarks/circuit-qa-v1.json with 2000 QA pairs
  - Train/val/test stratified splits (80/10/10)
affects: [42, 43, 44, training-pipeline]

# Tech tracking
tech-stack:
  added: [pydantic QA schemas, template-based QA generation]
  patterns: [deterministic seeded RNG, stratified train/val/test split, explicit answer templates per QA type, decoupled imports from question_generator]

key-files:
  created:
    - src/kicad_agent/benchmarks/qa_schemas.py
    - src/kicad_agent/benchmarks/qa_generator.py
    - benchmarks/circuit-qa-v1.json
    - tests/test_circuit_qa.py

key-decisions:
  - "Template-based QA generation (no LLM) for reproducibility"
  - "Seeded RNG (default 42) for deterministic dataset creation"
  - "10 analog-ecosystem modules as source context"
  - "80/10/10 train/val/test split stratified by qa_type"
  - "Decoupled from question_generator.py per Council HIGH-6"
  - "Explicit answer templates per QA type per Council HIGH-3"

patterns-established:
  - "Deterministic template-based QA: question + answer templates with slot notation, filled from circuit context data"
  - "Stratified splitting: per-qa-type seeded RNG ensures all 6 types appear in every split"

requirements-completed: [BENCH-03]

# Metrics
duration: 3min
completed: 2026-06-01
---

# Phase 42 Plan 01: Circuit QA Dataset Summary

Template-based open-ended QA dataset (2000 pairs, 6 types) generated from analog-ecosystem schematics with seeded reproducibility and stratified train/val/test splits.

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-31T20:15:00Z
- **Completed:** 2026-05-31T20:18:00Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- CircuitQAPair and CircuitQADataset schemas with Pydantic validation for 6 QA types, 3 difficulty levels, source references, and split assignment
- QAGenerator producing 2000 QA pairs across 6 types (violation_diagnosis, signal_flow, component_function, net_purpose, design_review, value_calculation) using template-based generation with no LLM dependency
- Canonical benchmarks/circuit-qa-v1.json dataset with 80/10/10 stratified train/val/test splits
- 29 tests covering schema validation, generation for all types, determinism, split stratification, and unique IDs

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): QA schemas and generator failing tests** - `ae0cdf3` (test)
2. **Task 1 (GREEN): QA schemas, generator, and dataset implementation** - `d2c102e` (feat)

_Note: TDD task with RED/GREEN gate commits._

## Files Created/Modified
- `src/kicad_agent/benchmarks/qa_schemas.py` - CircuitQAPair and CircuitQADataset Pydantic schemas
- `src/kicad_agent/benchmarks/qa_generator.py` - QAGenerator class with 6 QA type template-based generation
- `tests/test_circuit_qa.py` - 29 tests covering schemas, generation, and dataset validation
- `benchmarks/circuit-qa-v1.json` - Canonical QA dataset (2000 pairs, 1.4MB)

## Decisions Made
- Template-based QA generation (no LLM) for reproducibility and determinism
- Seeded RNG (default 42) ensures identical dataset across runs
- 10 analog-ecosystem modules (compressor, lfo, adsr, vca, vcf, delay, moog_ladder, mic_pre, class_a_gain, mcu_control) as source context
- 80/10/10 train/val/test split stratified by qa_type to ensure all 6 types in every split
- Decoupled from question_generator.py per Council HIGH-6; imports from erc_parser.py directly
- Explicit answer templates per QA type per Council HIGH-3

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

| Gate | Commit | Description |
|------|--------|-------------|
| RED | ae0cdf3 | test(42-01): add failing tests for Circuit QA dataset schemas and generator |
| GREEN | d2c102e | feat(42-01): implement Circuit QA schemas, generator, and dataset |

All gates present. RED commit has 29 failing tests. GREEN commit has all 29 passing. No REFACTOR gate needed.

## Verification Results

```
29 tests PASSED
QA Dataset OK: 2000 pairs, types: {violation_diagnosis, signal_flow, component_function, net_purpose, design_review, value_calculation}
```

QA type distribution:
| QA Type | Count |
|---------|-------|
| violation_diagnosis | 345 |
| signal_flow | 130 |
| component_function | 490 |
| net_purpose | 460 |
| design_review | 230 |
| value_calculation | 345 |

Split distribution: train=1600 (80%), val=199 (10%), test=201 (10.1%). All splits contain all 6 QA types.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Circuit QA dataset ready for fine-tuning circuit understanding models
- Schema compatible with training pipeline (train/val/test split fields on each pair)
- Dataset separate from PCB MMLU (open-ended QA vs multi-choice)

---
*Phase: 42-circuit-qa-dataset*
*Completed: 2026-06-01*
