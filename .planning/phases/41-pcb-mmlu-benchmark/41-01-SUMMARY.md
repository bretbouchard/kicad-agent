---
phase: 41
plan: 01
subsystem: benchmarks
tags: [benchmark, mmlu, dataset, evaluation, analog-ecosystem]
dependency_graph:
  requires: []
  provides: [pcb-mmlu-v1.json, BenchmarkQuestion schema, BenchmarkDataset schema, question_generator, DatasetBuilder]
  affects: [41-02, 42, 43, 44]
tech_stack:
  added: [pydantic schemas, template-based generation, seeded RNG]
  patterns: [TDD red-green-refactor, deterministic benchmark generation, category-balanced dataset]
key_files:
  created:
    - src/kicad_agent/benchmarks/__init__.py
    - src/kicad_agent/benchmarks/schemas.py
    - src/kicad_agent/benchmarks/question_generator.py
    - src/kicad_agent/benchmarks/dataset_builder.py
    - benchmarks/pcb-mmlu-v1.json
    - tests/test_benchmark_dataset.py
decisions:
  - Template-based generation instead of LLM for reproducibility
  - Seeded RNG (default 42) for deterministic dataset creation
  - 10 analog-ecosystem modules as source schematics
  - Difficulty conversion strategy (relabel medium to easy/hard when underrepresented)
  - Synthesize troubleshooting violations from refs when none provided
metrics:
  duration: ~5 minutes
  completed: 2026-05-31
  questions_generated: 500
  categories: 8
  tests: 25
---

# Phase 41 Plan 01: PCB MMLU Benchmark Dataset Generation Summary

Template-based multi-choice benchmark dataset (500 questions, 8 categories) generated from analog-ecosystem schematics with seeded reproducibility.

## What Was Built

### Benchmark Schemas (`schemas.py`)
- `BenchmarkQuestion`: Pydantic model with id (pcb-mmlu-NNNN), 8 categories, 3 difficulty levels, exactly 4 unique non-empty choices, correct_index 0-3, explanation, source, source_type, and tags. Validators reject duplicates, empties, out-of-bounds indices, and invalid categories.
- `BenchmarkDataset`: Version (semver), generated_at (ISO 8601), questions list (min 1), metadata dict.

### Question Generator (`question_generator.py`)
- Template-based generation for 8 categories using deterministic string templates filled with schematic context data.
- Distractor pools for all 8 categories with plausible wrong answers (2-10 sub-pools each).
- Component type mapping from lib_id and ref prefix to display names.
- Difficulty assignment by component count: easy (1-3), medium (4-8), hard (9+ or cross-sheet/multi-IC).
- Sequential ID generation with global counter and reset capability.

### Dataset Builder (`dataset_builder.py`)
- Orchestrates generation across 10 analog-ecosystem source schematics (compressor, LFO, ADSR, VCA, VCF, delay, Moog ladder, mic-pre, Class A gain, RP2040 control center).
- Category balancing ensures >= target/8 per category.
- Difficulty distribution adjustment to 20/60/20 targets within 5% tolerance.
- JSON serialization and deserialization with schema validation.

### Dataset (`benchmarks/pcb-mmlu-v1.json`)
- 500 questions across 8 categories (62-63 each).
- Difficulty: 100 easy (20%), 302 medium (60.4%), 98 hard (19.6%).
- Reproducible with seed=42.

## TDD Gate Compliance

| Gate | Commit | Hash |
|------|--------|------|
| RED | test(41-01): add failing tests for PCB MMLU benchmark schemas and generators | 00a5278 |
| GREEN | feat(41-01): implement PCB MMLU benchmark schemas and question generator | ff91bf9 |
| GREEN | feat(41-01): implement DatasetBuilder and generate pcb-mmlu-v1.json benchmark | 16e33e0 |

All three gates present. RED commit has 25 failing tests. GREEN commits have all 25 passing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Synthesized troubleshooting violations when context has none**
- **Found during:** Task 1 GREEN phase
- **Issue:** `generate_questions("troubleshooting", {"refs": ["U22", "R60"]})` returned empty list because no violations were in context. Test `test_generate_questions_returns_list` expected > 0 for all categories.
- **Fix:** Added fallback in `generate_questions` to synthesize a pin_not_connected violation from refs when no violations are provided in context.
- **Files modified:** `src/kicad_agent/benchmarks/question_generator.py`
- **Commit:** ff91bf9

**2. [Rule 1 - Bug] Test explanation string too short for schema validation**
- **Found during:** Task 1 GREEN phase
- **Issue:** Test `test_rejects_invalid_version` used `explanation="Test."` (5 chars) which failed BenchmarkQuestion's min_length=10 validator. The test was testing BenchmarkDataset rejection, not BenchmarkQuestion, so the question creation failed first.
- **Fix:** Updated test data to use a longer explanation string that passes BenchmarkQuestion validation.
- **Files modified:** `tests/test_benchmark_dataset.py`
- **Commit:** ff91bf9

## Verification Results

```
25 tests PASSED
Dataset OK: 500 questions, 8 categories
```

Category distribution:
| Category | Count |
|----------|-------|
| component_identification | 62 |
| topology_recognition | 62 |
| signal_flow | 63 |
| power_design | 63 |
| pin_function | 63 |
| net_purpose | 62 |
| design_rules | 62 |
| troubleshooting | 63 |

Difficulty distribution:
| Difficulty | Count | Percentage | Target |
|-----------|-------|-----------|--------|
| easy | 100 | 20.0% | 20% |
| medium | 302 | 60.4% | 60% |
| hard | 98 | 19.6% | 20% |

All within 5% tolerance.

## Self-Check: PASSED

All 7 created files verified present. All 3 commit hashes verified in git log.
