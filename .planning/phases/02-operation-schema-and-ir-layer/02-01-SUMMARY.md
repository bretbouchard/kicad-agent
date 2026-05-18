---
phase: 02-operation-schema-and-ir-layer
plan: 01
subsystem: schema
tags: [pydantic, json-schema, discriminated-union, validation, llm-contract]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: parser module patterns (barrel exports, frozen dataclasses)
provides:
  - Pydantic v2 discriminated union Operation schema (add_component, remove_component, move_component, modify_property)
  - TargetFile type with path traversal defense (H-01)
  - String field length constraints (M-04)
  - get_operation_schema() for LLM JSON Schema export (D-04)
  - PositionSpec and PropertySpec shared types
affects: [02-02, 02-03, 04-mutation-operations]

# Tech tracking
tech-stack:
  added: [pydantic-2.12.5-already-installed]
  patterns: [discriminated-union-via-Literal, BeforeValidator-for-path-safety, Field-constraints-for-abuse-prevention]

key-files:
  created:
    - src/kicad_agent/ops/__init__.py
    - src/kicad_agent/ops/schema.py
    - tests/test_ops_schema.py

key-decisions:
  - "Used Operation.root field with Field(discriminator='op_type') for Pydantic v2 discriminated union"
  - "TargetFile uses BeforeValidator (not root_validator) for early rejection of path traversal"
  - "Added PropertySpec model alongside PositionSpec for future use"

patterns-established:
  - "Discriminated union: each op type has Literal op_type field, Operation wraps union via discriminator"
  - "TargetFile annotated type: reusable path-safe string with BeforeValidator chain"
  - "Barrel export: ops/__init__.py mirrors parser/__init__.py pattern"

requirements-completed: [OPS-01, OPS-02]

# Metrics
duration: 2min
completed: 2026-05-18
---

# Phase 2 Plan 01: Operation Schema Summary

**Pydantic v2 discriminated union schema with 4 operation types, TargetFile path traversal defense, and JSON Schema export for LLM consumption**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-18T05:34:30Z
- **Completed:** 2026-05-18T05:37:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created ops package with discriminated union schema (AddComponentOp, RemoveComponentOp, MoveComponentOp, ModifyPropertyOp)
- Implemented TargetFile type with BeforeValidator rejecting path traversal, absolute paths, null bytes, and non-KiCad extensions (Council H-01)
- Enforced min_length/max_length on all string fields to prevent oversized payloads (Council M-04)
- Exported full JSON Schema via get_operation_schema() for LLM tool contract (D-04)
- Created comprehensive test suite with 20 tests covering valid ops, invalid ops, path security, length constraints, schema export, and position defaults

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Pydantic operation schema with discriminated union** - `de95d40` (feat)
2. **Task 2: Create operation schema test suite** - `bc8e8ef` (test)

## Files Created/Modified
- `src/kicad_agent/ops/__init__.py` - Barrel exports for ops package
- `src/kicad_agent/ops/schema.py` - Pydantic discriminated union of all operation types with security mitigations
- `tests/test_ops_schema.py` - 20 tests: valid ops (5), invalid ops (10), schema export (3), position spec (2)

## Decisions Made
- Used `Operation.root` field with `Field(discriminator="op_type")` for Pydantic v2 discriminated union pattern
- TargetFile uses `BeforeValidator` for early rejection before Pydantic's own field validation runs
- Added `PropertySpec` model alongside `PositionSpec` for future property mutation operations
- Placed tests in `tests/test_ops_schema.py` (flat) rather than a subdirectory to match the plan specification

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Operation schema ready for Plan 02 (IR layer) and Plan 03 (transaction engine)
- Phase 1 tests (48) continue to pass alongside new Phase 2 tests (20) for a total of 68 tests
- TargetFile and PositionSpec types available for reuse in IR mutation methods

## Self-Check: PASSED

All files exist:
- src/kicad_agent/ops/__init__.py
- src/kicad_agent/ops/schema.py
- tests/test_ops_schema.py
- .planning/phases/02-operation-schema-and-ir-layer/02-01-SUMMARY.md

All commits found:
- de95d40 (feat: Pydantic operation schema)
- bc8e8ef (test: operation schema test suite)

---
*Phase: 02-operation-schema-and-ir-layer*
*Completed: 2026-05-18*
