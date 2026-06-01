---
phase: 52-synthetic-circuit-generation
plan: 01-02
subsystem: training
tags: [synthetic-generation, circuit-templates, mass-generation, training-data, parallel-execution]
dependency_graph:
  requires: [45-01]
  provides: [circuit-templates, synthetic-generator, mass-generate]
  affects: [training]
tech_stack:
  added: [pydantic-templates, process-pool-executor, jsonl-datasets]
  patterns: [parameterized-templates, deterministic-seed-generation, sha256-dedup]
key_files:
  created:
    - src/kicad_agent/training/circuit_templates.py
    - src/kicad_agent/training/synthetic_generator.py
    - src/kicad_agent/training/mass_generate.py
    - tests/test_synthetic_generation.py
  modified: []
decisions:
  - "eval() for predicates restricted with empty __builtins__, safe for developer-defined strings only"
  - "run_validation field renamed from validate to avoid Pydantic BaseModel parent shadowing"
  - "Templates serialized as dicts for ProcessPoolExecutor to avoid pickling CircuitTemplate"
  - "Log-uniform sampling default for component ranges (resistors, capacitors span decades)"
metrics:
  duration: 9m
  completed: 2026-06-01
  tasks: 4
  files: 4
  tests: 45
  commits: 3
---

# Phase 52 Synthetic Circuit Generation Summary

Template-based synthetic circuit generation: 10 parameterized analog building blocks, deterministic seed-based generation, parallel mass pipeline producing 10,000+ unique circuits as JSONL datasets with train/val/test splits.

## Plans Completed

### Plan 52-01: Circuit Template Schema and SyntheticGenerator

**Commit:** 589eae4 (test), 5682843 (feat)

- `CircuitTemplate` Pydantic schema with `ComponentTemplate`, `NetTemplate`, `ComponentRange`
- 10 parameterized templates: common-emitter amplifier, op-amp inverting amplifier, Sallen-Key LPF, voltage follower, RC LPF, RC HPF, voltage divider, LED driver, MOSFET switch, Schmitt trigger
- 7 circuit categories: amplifier, filter, buffer, passive, driver, switch, digital
- `instantiate_template()` with deterministic seed-based log-uniform sampling
- `valid_range_predicates` using restricted `eval()` reject impossible parameter combinations (e.g., C1/C2 ratio bounds for Sallen-Key realizability)
- `SyntheticGenerator.create_intent()` converts template + seed to `GenerationIntent`
- `generate_batch()` with SHA256 hash-based deduplication and failure limits
- Serialization helpers `attempt_to_dict()`/`dict_to_attempt()` for JSON round-trip

### Plan 52-02: Mass Generation Pipeline

**Commit:** 3df6674

- `MassGenerationConfig` with validated parameters (target_count, n_workers, seed, output_dir)
- `run_mass_generation()` using `ProcessPoolExecutor` for parallel generation across all templates
- SHA256 deduplication by circuit hash across workers
- JSONL output files: synthetic-train.jsonl, synthetic-val.jsonl, synthetic-test.jsonl, synthetic-all.jsonl
- Deterministic 80/10/10 train/val/test split with seed-based shuffling
- `QualityMetrics`: template coverage, component diversity, ERC pass rate
- CLI entry point with `--dry-run` support: `python -m kicad_agent.training.mass_generate`

## Key Technical Decisions

1. **eval() for predicates** -- Restricted with `{"__builtins__": {}}`, only developer-defined comparison expressions. Safe because predicates are code constants, never user input.

2. **Field rename** -- `validate` renamed to `run_validation` in `MassGenerationConfig` to avoid Pydantic `BaseModel` parent attribute shadowing warning.

3. **Template serialization for subprocess** -- Templates serialized as dicts via `model_dump()` to avoid pickling `CircuitTemplate` across `ProcessPoolExecutor` boundaries. Reconstructed in worker via `model_validate()`.

4. **Log-uniform sampling** -- Default for component ranges since resistors (10 - 10M) and capacitors (1pF - 1mF) span many decades. Linear sampling would cluster at high values.

## Deviations from Plan

None -- plan executed exactly as written.

## Test Coverage

- **45 tests** in `tests/test_synthetic_generation.py`
- TestCircuitTemplateSchema (3): schema validation
- TestComponentRange (3): range validation, defaults
- TestTemplateLibrary (5): 10 templates, unique names, valid categories
- TestTemplateInstantiation (3): determinism, diversity, range bounds
- TestValidityPredicates (3): predicate acceptance/rejection
- TestSyntheticGenerator (10): intent creation, component/net counts, formatting, determinism, batch, dedup
- TestAttemptSerialization (4): dict round-trip, null intent
- TestMassGenerationConfig (4): defaults, rejection of invalid inputs
- TestMassGenerationPipeline (5): all templates, dedup, JSONL, split proportions, determinism
- TestQualityMetrics (4): expected keys, coverage, diversity, empty input
- TestCLI (1): dry-run output

## Verification

```
$ python -c "from kicad_agent.training.circuit_templates import get_all_templates; print(f'{len(get_all_templates())} templates')"
10 templates

$ python -m kicad_agent.training.mass_generate --dry-run
Templates: 10
Per template: 1000
Workers: 4
Output: training_data/synthetic-circuits
```
