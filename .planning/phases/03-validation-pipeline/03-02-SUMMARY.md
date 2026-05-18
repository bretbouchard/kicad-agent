---
phase: 03-validation-pipeline
plan: 02
subsystem: validation
tags: [structural-validation, uuid-uniqueness, pre-mutation, pydantic, frozen-dataclass]

# Dependency graph
requires:
  - phase: 02-operation-schema-and-ir-layer
    provides: Operation schema (ops/schema.py), IR layer (ir/base.py, ir/schematic_ir.py, ir/pcb_ir.py)
  - phase: 01-foundation
    provides: UUID extractor (parser/uuid_extractor.py), ParseResult (parser/types.py)
provides:
  - Pre-mutation structural validator (validate_structural)
  - UUID uniqueness checker (validate_uuid_uniqueness)
  - StructuralResult, StructuralViolation, ViolationKind types
affects: [03-validation-pipeline, mutation-engine, erc-drc-gates]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-result-dataclass, duck-typed-component-lookup, dispatch-table-validator]

key-files:
  created:
    - src/kicad_agent/validation/structural.py
    - tests/test_structural_validator.py
  modified: []

key-decisions:
  - "Duck-typed _component_exists() works with both SchematicIR and PcbIR via hasattr checks"
  - "StructuralResult uses operation_type and target_file fields for traceability"
  - "Library ref validated with regex LIBRARY:SYMBOL pattern in structural validator"

patterns-established:
  - "Frozen dataclass result types with tuple violations for immutability"
  - "Dispatch table pattern for type-specific validators keyed by op_type"

requirements-completed: [VAL-05]

# Metrics
duration: 5min
completed: 2026-05-18
---

# Phase 3 Plan 2: Structural Validator Summary

**Pre-mutation structural validator with file-type checks, component existence, library ref format validation, and UUID uniqueness detection across 4 operation types**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-18T07:10:41Z
- **Completed:** 2026-05-18T07:15:39Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Pre-mutation structural validator catches invalid operations before execution (missing components, file type mismatches, invalid library refs, negative positions)
- UUID uniqueness checker detects duplicate UUIDs in file content using the existing extract_uuids() infrastructure
- All 4 operation types (add/remove/move/modify) have dedicated type-specific validation logic
- 19 new tests against real KiCad fixtures with zero regressions (165 total tests pass)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create structural validator and UUID uniqueness checker** - `45c6d6c` (feat)
2. **Task 2: Create structural validator test suite** - `6f017e2` (test)

## Files Created/Modified
- `src/kicad_agent/validation/structural.py` - Pre-mutation structural validator with validate_structural() and validate_uuid_uniqueness()
- `tests/test_structural_validator.py` - 19 tests across 6 test classes covering all operation types and UUID uniqueness

## Decisions Made
- Duck-typed `_component_exists()` uses `hasattr` checks for SchematicIR (get_component_by_ref) and PcbIR (footprints with properties dict) compatibility instead of isinstance checks
- StructuralResult includes `operation_type` and `target_file` fields for audit traceability
- Library reference format validated with regex `^[^:]+:[^:]+$` pattern (LIBRARY:SYMBOL format)
- `validate_uuid_uniqueness()` reuses existing `extract_uuids()` from parser/uuid_extractor.py rather than re-implementing UUID extraction

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Structural validator is the first gate in the validation pipeline, ready for integration with the mutation engine
- UUID uniqueness checker can be used post-mutation to verify file integrity
- Future plans can add more violation kinds (e.g., sheet existence, net validity) by extending ViolationKind enum and adding validators

## Self-Check: PASSED

All files exist: structural.py, test_structural_validator.py, SUMMARY.md
All commits found: 45c6d6c, 6f017e2

---
*Phase: 03-validation-pipeline*
*Completed: 2026-05-18*
