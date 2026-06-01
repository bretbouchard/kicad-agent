---
phase: 42
plan: 01
subsystem: benchmarks
tags: [qa-dataset, fine-tuning, circuit-understanding, templates, stratified-split]
dependency_graph:
  requires: [41-01]
  provides: [circuit-qa-v1.json, CircuitQAPair schema, CircuitQADataset schema, QAGenerator]
  affects: [42, 43, 44]
tech_stack:
  added: [pydantic QA schemas, template-based QA generation, stratified train/val/test split]
  patterns: [TDD red-green, deterministic seeded generation, explicit answer templates, decoupled imports]
key_files:
  created:
    - src/kicad_agent/benchmarks/qa_schemas.py
    - src/kicad_agent/benchmarks/qa_generator.py
    - benchmarks/circuit-qa-v1.json
    - tests/test_circuit_qa.py
decisions:
  - Template-based QA generation (no LLM) for reproducibility
  - Seeded RNG (default 42) for deterministic dataset creation
  - 10 analog-ecosystem modules as source context
  - 80/10/10 train/val/test split stratified by qa_type
  - Decoupled from question_generator.py per Council HIGH-6
  - Explicit answer templates per QA type per Council HIGH-3
metrics:
  duration: ~3 minutes
  completed: 2026-06-01
  qa_pairs_generated: 2000
  qa_types: 6
  tests: 29
---

# Phase 42 Plan 01: Circuit QA Dataset Summary

Template-based open-ended QA dataset (2000 pairs, 6 types) generated from analog-ecosystem schematics with seeded reproducibility and stratified train/val/test splits.

## What Was Built

### QA Schemas (`qa_schemas.py`)
- `CircuitQAPair`: Pydantic model with id (qa-NNNN), 6 QA types, 3 difficulty levels, open-ended question/answer (no multi-choice), source reference, source_type, tags, and train/val/test split field. Validators enforce min_length on question (10) and answer (20), id pattern, and enum constraints.
- `CircuitQADataset`: Version (semver), generated_at (ISO 8601), qa_pairs list (min 1), metadata dict with split counts and type distributions.

### QA Generator (`qa_generator.py`)
- `QAGenerator` class with template-based generation for 6 QA types using deterministic string templates filled with circuit context data.
- Question and answer templates for all 6 types with explicit slot notation (Council HIGH-3).
- Root cause mappings for violation_diagnosis with structured fix suggestions.
- Component role mappings for component_function from lib_id.
- Difficulty assignment: passive=easy, IC=medium, complex IC=hard (per type).
- Replication mechanism to reach target count with question variations.
- Stratified train/val/test split using per-type seeded RNG (80/10/10) (Council HIGH-5).
- Imports from `schematic_graph.py` and `erc_parser.py` directly -- decoupled from `question_generator.py` (Council HIGH-6).

### Dataset (`benchmarks/circuit-qa-v1.json`)
- 2000 QA pairs across 6 types.
- Stratified 80/10/10 split: train=1600, val=199, test=201.
- All 6 types represented in every split.
- Reproducible with seed=42.

## TDD Gate Compliance

| Gate | Commit | Hash |
|------|--------|------|
| RED | test(42-01): add failing tests for Circuit QA dataset schemas and generators | ae0cdf3 |
| GREEN | feat(42-01): implement Circuit QA schemas, generator, and dataset | d2c102e |

All gates present. RED commit has 29 failing tests. GREEN commit has all 29 passing.

## Deviations from Plan

None -- plan executed exactly as written.

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

Difficulty distribution:
| Difficulty | Count | Percentage |
|-----------|-------|-----------|
| easy | 655 | 32.8% |
| medium | 870 | 43.5% |
| hard | 475 | 23.8% |

Split distribution:
| Split | Count | Percentage |
|-------|-------|-----------|
| train | 1600 | 80.0% |
| val | 199 | 10.0% |
| test | 201 | 10.1% |

All splits contain all 6 QA types (stratified).

## Self-Check: PASSED

All 4 created files verified present. All 2 commit hashes verified in git log.
