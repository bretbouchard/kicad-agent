---
phase: 04-component-operations
plan: 02
subsystem: ops
tags: [kicad, operations, duplicate, array, replicate, linear, circular, matrix]

# Dependency graph
requires:
  - phase: 04-component-operations
    provides: "OperationExecutor, add_component handler, SchematicSymbol creation pattern"
provides:
  - "duplicate_component handler with reference incrementing, deep copy, and multi-copy support"
  - "array_replicate handler with linear, circular, and matrix array patterns"
  - "DuplicateComponentOp and ArrayReplicateOp schemas added to discriminated union"
affects: [04-component-operations, 05-net-operations, 06-advanced-operations]

# Tech tracking
tech-stack:
  added: []
patterns:
  - "Reference incrementing: parse prefix+number, scan all existing refs, find next available"
  - "Deep copy pattern: fresh UUID for symbol + pins, copy all properties, update Reference"
  - "Array position generators: _linear_positions, _circular_positions, _matrix_positions"
  - "Pattern-specific parameter validation in handler (center/angle_step/rows/cols)"

key-files:
  created:
    - src/kicad_agent/ops/duplicate_component.py
    - src/kicad_agent/ops/array_replicate.py
    - tests/test_duplicate_component.py
    - tests/test_array_replicate.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py

key-decisions:
  - "SymbolProjectPath uses sheetInstancePath (not path); SymbolProjectInstance uses name (not project)"
  - "Matrix array skips (0,0) position since source occupies it; creates rows*cols-1 replicas"
  - "Circular array rotates (dx, dy) vector around center using standard rotation matrix"
  - "Reference incrementing scans all existing references to find next unused number per prefix"
  - "count constrained to 1-100 via Pydantic Field for DoS mitigation (T-04-07)"

requirements-completed: [COMP-03, COMP-04]

# Metrics
duration: 7min
completed: 2026-05-18
---

# Phase 4 Plan 2: Duplicate and Array Replicate Operations Summary

**Duplicate and array replicate handlers with fresh UUID generation, automatic reference incrementing, and linear/circular/matrix array patterns**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-18T07:59:06Z
- **Completed:** 2026-05-18T08:06:49Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- DuplicateComponentOp schema added with source_reference, optional offset, and count (1-100)
- ArrayReplicateOp schema added with linear/circular/matrix pattern types and pattern-specific fields
- duplicate_component handler creates deep copies with fresh UUIDs, incremented references, position offsets
- array_replicate handler supports three array patterns: linear (even spacing), circular (trigonometric rotation), matrix (row/col grid)
- Both handlers registered in OperationExecutor dispatch map
- 34 new tests passing (16 duplicate + 18 array), 235 total tests passing

## Task Commits

Each task was committed atomically (TDD: RED then GREEN):

1. **Task 1 RED: duplicate_component tests** - `e24119e` (test)
2. **Task 1 GREEN: duplicate_component handler** - `40e04f8` (feat)
3. **Task 2 RED: array_replicate tests** - `4255db7` (test)
4. **Task 2 GREEN: array_replicate handler** - `51b26db` (feat)

## Files Created/Modified

- `src/kicad_agent/ops/schema.py` - Added DuplicateComponentOp and ArrayReplicateOp models, updated Operation union
- `src/kicad_agent/ops/duplicate_component.py` - Duplicate handler with _increment_reference, _deep_copy_symbol, multi-copy support
- `src/kicad_agent/ops/array_replicate.py` - Array replicate handler with _linear_positions, _circular_positions, _matrix_positions
- `src/kicad_agent/ops/executor.py` - Added duplicate_component and array_replicate dispatch cases
- `tests/test_duplicate_component.py` - 16 tests: reference incrementing, offset, properties, UUIDs, schema, executor, pipeline
- `tests/test_array_replicate.py` - 18 tests: linear/circular/matrix patterns, positions, uniqueness, errors, executor, pipeline

## Decisions Made

- **SymbolProjectPath.sheetInstancePath (not path):** kiutils uses `sheetInstancePath` not `path` for the instance path field; discovered during initial test run
- **SymbolProjectInstance.name (not project):** kiutils uses `name` not `project` for the instance name field
- **Matrix skips (0,0):** Source occupies the (0,0) grid position, so matrix creates rows*cols - 1 replicas
- **Circular rotation matrix:** Uses standard 2D rotation (cos/sin) around center point for each step
- **Reference increment scans all refs:** Prevents collisions by collecting all existing references and finding next unused number per prefix

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed kiutils SymbolProjectPath field name**
- **Found during:** Task 1 GREEN phase
- **Issue:** Used `path.path` and `inst.project` but kiutils fields are `sheetInstancePath` and `name`
- **Fix:** Updated to correct field names `path.sheetInstancePath` and `inst.name`
- **Files modified:** src/kicad_agent/ops/duplicate_component.py
- **Commit:** 40e04f8

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Executor has 4 dispatch paths: add_component, remove_component, duplicate_component, array_replicate
- move_component and modify_property dispatch stubs present (raise NotImplementedError)
- 235 total tests passing (34 new + 201 existing)
- Plan 04-03 ready: move_component and modify_property handlers

---
*Phase: 04-component-operations*
*Completed: 2026-05-18*

## Self-Check: PASSED

All files verified:
- FOUND: src/kicad_agent/ops/duplicate_component.py
- FOUND: src/kicad_agent/ops/array_replicate.py
- FOUND: src/kicad_agent/ops/schema.py
- FOUND: src/kicad_agent/ops/executor.py
- FOUND: tests/test_duplicate_component.py
- FOUND: tests/test_array_replicate.py

All commits verified:
- e24119e: test(04-02): add failing tests for duplicate_component operation
- 40e04f8: feat(04-02): implement duplicate_component handler with schema and executor dispatch
- 4255db7: test(04-02): add failing tests for array_replicate operation
- 51b26db: feat(04-02): implement array_replicate handler with linear, circular, and matrix patterns
