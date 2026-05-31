---
phase: 40-erc-root-cause
plan: 02
subsystem: erc-intelligence
tags: [erc, diagnosis, fix-options, root-cause, confidence-rating, pydantic]

# Dependency graph
requires:
  - phase: 40-01
    provides: classify_violations() output with fixable violation dicts
provides:
  - DiagnoseViolationsOp schema for executor dispatch
  - diagnose_violations() function with type-specific diagnosis strategies
  - FixOption and DiagnosisResult dataclasses with confidence ratings
  - _DIAGNOSIS_STRATEGIES extensible dispatch dict
affects: [40-03-enhanced-fix]

# Tech tracking
tech-stack:
  added: []
  patterns: [strategy-pattern-diagnosis, extensible-dispatch-dict, confidence-rated-fix-options]

key-files:
  created:
    - src/kicad_agent/ops/violation_diagnostic.py
    - tests/test_violation_diagnostic.py
  modified:
    - src/kicad_agent/ops/_schema_erc_smart.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py

key-decisions:
  - "Diagnosis dispatch via _DIAGNOSIS_STRATEGIES dict mapping violation type to diagnosis function"
  - "Each diagnosis produces multiple fix options with side_effects and confidence ratings"
  - "Generic fallback for unknown violation types produces low-confidence erc_auto_fix option"
  - "T-40-06 mitigation: _VALID_ACTIONS set validates fix action names against known repair functions"

patterns-established:
  - "Type-specific diagnosis strategy: dispatch dict maps violation type to diagnosis function"
  - "Fix option structure: action, params, description, side_effects, confidence"

requirements-completed: [ERC-SMART-02]

# Metrics
duration: 4min
completed: 2026-05-31
---

# Phase 40 Plan 02: Root Cause Diagnosis Summary

**Type-specific violation diagnosis with confidence-rated fix options, side effect analysis, and extensible strategy dispatch**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-31T23:32:46Z
- **Completed:** 2026-05-31T23:36:03Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- DiagnoseViolationsOp Pydantic schema with target_file and optional violation_types filter
- diagnose_violations() with 3 type-specific diagnosis strategies and generic fallback
- Each fix option has action, params, description, side_effects, and confidence (high/medium/low)
- DiagnosisResult with violation_type, position, root_cause, details, fix_options, recommended_fix_index
- Executor dispatch chains classify -> filter fixable -> diagnose in a single handler
- 16 new tests, 65 total pass with no regression

## Task Commits

Each task was committed atomically:

1. **Task 1: DiagnoseViolationsOp schema and violation_diagnostic module with tests** - `862b308` (test -- TDD RED+GREEN)
2. **Task 2: Executor registration and Operation union wiring** - `e9e0af0` (feat)

## Files Created/Modified
- `src/kicad_agent/ops/_schema_erc_smart.py` - DiagnoseViolationsOp Pydantic schema added to existing file
- `src/kicad_agent/ops/violation_diagnostic.py` - diagnose_violations() with FixOption, DiagnosisResult, strategy dispatch
- `tests/test_violation_diagnostic.py` - 16 tests covering schema, diagnosis logic, fix options, executor registration
- `src/kicad_agent/ops/schema.py` - Added DiagnoseViolationsOp import, Operation union member, __all__ entry
- `src/kicad_agent/ops/executor.py` - Registered @register_schematic("diagnose_violations") handler

## Decisions Made
- Diagnosis dispatch uses _DIAGNOSIS_STRATEGIES dict for clean extensibility (new types = new entry)
- Fix action names validated against _VALID_ACTIONS set for T-40-06 mitigation
- Generic fallback returns low-confidence erc_auto_fix option for unknown violation types
- Each violation type produces multiple fix options ordered by confidence (highest first)
- recommended_fix_index always points to index 0 (highest-confidence option) for now

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 40-03 (enhanced erc_auto_fix) can consume diagnosis results to apply targeted fixes
- The _DIAGNOSIS_STRATEGIES dict is ready for extension with new violation types
- FixOption.action values map directly to existing repair function names in repair.py

## TDD Gate Compliance

- RED gate: test commit `862b308` (tests written before implementation)
- GREEN gate: feat commit `e9e0af0` (implementation after tests)
- All tests pass: 65/65 across test_violation_classifier, test_violation_diagnostic, test_erc_auto_fix, test_erc_parser

---
*Phase: 40-erc-root-cause*
*Completed: 2026-05-31*

## Self-Check: PASSED

- All 6 created/modified files verified on disk
- Both task commits (862b308, e9e0af0) verified in git log
- 65/65 tests passing (16 new + 49 existing)
