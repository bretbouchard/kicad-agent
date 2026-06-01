---
phase: 44-adversarial-test-generation
plan: 01
subsystem: benchmarks
tags: [adversarial, mutation-testing, fuzz-testing, property-based, parser-robustness, seeded-rng]
dependency_graph:
  requires: [41-01, 42-01]
  provides: [MutationEngine, SchematicMutation, AdversarialTestSuite, CircuitProperty, FuzzResult, adversarial-v1.json]
  affects: [44, training-pipeline, benchmark-evaluation]
tech_stack:
  added: [pydantic mutation schemas, fuzz engine with 5 strategies, property-based test verification]
  patterns: [seeded RNG reproducibility, TDD red-green, S-expression fuzz mutations, kiutils round-trip verification]
key_files:
  created:
    - src/kicad_agent/benchmarks/mutation_engine.py
    - src/kicad_agent/benchmarks/adversarial.py
    - benchmarks/adversarial-v1.json
    - tests/test_adversarial.py
decisions:
  - MutationEngine operates on .kicad_sch files via SchematicGraph for target discovery
  - 5 primary mutation operations (swap_values, break_wire, remove_label, short_pins, floating_pin) plus 2 declarative types (duplicate_net, wrong_polarity)
  - Fuzz engine uses 5 strategies: flip_bit, delete_char, insert_char, swap_chars, duplicate_line
  - Property-based tests verify 5 invariants with deterministic seeded checks
  - kiutils used for parser fuzz round-trip verification
metrics:
  duration: 5min
  completed: 2026-06-01
  total_tests: 750
  mutations: 200
  properties: 50
  fuzz: 500
  unit_tests: 27
---

# Phase 44 Plan 01: Adversarial Test Generation Summary

Mutation engine, property-based tests, and fuzz testing generating 750 adversarial test cases with seeded reproducibility for parser robustness and ERC detection verification.

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-01T00:18:47Z
- **Completed:** 2026-06-01T00:23:44Z
- **Tasks:** 2 (TDD: RED + GREEN for each)
- **Files created:** 4

## Accomplishments

- SchematicMutation Pydantic schema supporting 7 mutation types with target, original, mutated, expected_detection fields
- MutationEngine with seeded RNG applying 5 primary mutation operations to KiCad schematics via SchematicGraph target discovery
- CircuitProperty and FuzzResult schemas for property-based and fuzz test specifications
- AdversarialTestSuite orchestrator combining mutation (200), property (50), and fuzz (500) testing for 750+ total adversarial cases
- Fuzz engine with 5 mutation strategies testing parser robustness on random S-expression mutations (no crashes)
- 5 default property-based tests verifying round-trip, schema validation, add-remove, ERC fix, and audit trail invariants
- Canonical benchmarks/adversarial-v1.json dataset with exactly 750 test cases

## Task Commits

Each task was committed atomically with TDD gates:

1. **Task 1 RED:** test(44-01): add failing tests - `f5c1c1d`
2. **Task 1 GREEN:** feat(44-01): implement MutationEngine - `0cd5784`
3. **Task 2 GREEN:** feat(44-01): implement AdversarialTestSuite - `ffd5ab1`

## Files Created/Modified

- `src/kicad_agent/benchmarks/mutation_engine.py` - SchematicMutation schema + MutationEngine class (5 mutation operations, seeded RNG, target discovery)
- `src/kicad_agent/benchmarks/adversarial.py` - CircuitProperty, FuzzResult, AdversarialTestSuite orchestrator, fuzz engine
- `benchmarks/adversarial-v1.json` - Canonical adversarial dataset (750 test cases)
- `tests/test_adversarial.py` - 27 tests covering schemas, engine, properties, fuzz, and suite generation

## Decisions Made

- MutationEngine uses SchematicGraph for target discovery (reuse existing parser)
- 5 primary operations produce actual mutations; 2 additional types (duplicate_net, wrong_polarity) reserved for declarative use
- Fuzz engine tests kiutils parser directly (not SchematicGraph) to validate the lowest parsing layer
- Property-based tests use deterministic seeded verification rather than Hypothesis for simplicity and reproducibility
- All random state flows from a single seed for complete reproducibility

## TDD Gate Compliance

| Gate | Commit | Description |
|------|--------|-------------|
| RED | f5c1c1d | test(44-01): add failing tests for adversarial test generation |
| GREEN | 0cd5784 | feat(44-01): implement MutationEngine with 7 mutation types |
| GREEN | ffd5ab1 | feat(44-01): implement AdversarialTestSuite with property and fuzz testing |

All gates present. RED commit has 27 failing tests. GREEN commits have all 27 passing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test break_wire assertion for mutated field corrected**
- **Found during:** Task 1 GREEN phase
- **Issue:** Test asserted `mutation.mutated != ""` but break_wire removes the wire entirely, making mutated an empty string by design.
- **Fix:** Updated test to assert `mutation.mutated == ""` and added `assert mutation.expected_detection == "pin_not_connected"` for additional coverage.
- **Files modified:** `tests/test_adversarial.py`
- **Commit:** 0cd5784

## Verification Results

```
27 tests PASSED
AdversarialTestSuite import: OK
Dataset: 750 total (200 mutations + 50 properties + 500 fuzz)
```

Dataset breakdown:
| Category | Count |
|----------|-------|
| Mutations | 200 |
| Properties | 50 |
| Fuzz | 500 |
| **Total** | **750** |

## Self-Check: PASSED

All 4 created files verified present. All 3 commit hashes verified in git log.
