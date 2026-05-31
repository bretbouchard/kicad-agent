---
phase: 40-erc-root-cause
plan: 01
subsystem: erc-intelligence
tags: [erc, classification, violation-triage, rule-engine, pydantic]

# Dependency graph
requires:
  - phase: 35-gen-ops
    provides: erc_parser.py (parse_erc, ErcViolation), erc_auto_fix.py (VIOLATION_REPAIR_MAP)
provides:
  - ClassifyViolationsOp schema for executor dispatch
  - classify_violations() function with rule-based triage
  - ViolationCategory enum (FIXABLE, PRE_EXISTING, BENIGN, CONFIG_ISSUE)
  - _CLASSIFICATION_RULES extensible rule list
affects: [40-02-diagnosis, 40-03-enhanced-fix]

# Tech tracking
tech-stack:
  added: []
  patterns: [rule-based-classification, extensible-rule-list, ir-position-context]

key-files:
  created:
    - src/kicad_agent/ops/_schema_erc_smart.py
    - src/kicad_agent/ops/violation_classifier.py
    - tests/test_violation_classifier.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py

key-decisions:
  - "Classification rules in _CLASSIFICATION_RULES list of (match_fn, category, root_cause, confidence) tuples for extensibility"
  - "First-match-wins rule ordering: pre-existing checks before benign before fixable"
  - "IR position data (pin/wire/label positions) used to distinguish #PWR symbols from regular components"
  - "ClassifyViolationsOp in _schema_erc_smart.py (separate from _schema_repair.py per D-01)"

patterns-established:
  - "Rule-based classification: ordered list of (predicate, category, root_cause, confidence) tuples"
  - "ERC smart ops in _schema_erc_smart.py (separate from repair schema)"

requirements-completed: [ERC-SMART-01]

# Metrics
duration: 5min
completed: 2026-05-31
---

# Phase 40 Plan 01: ERC Violation Classification Summary

**Rule-based ERC violation classifier triaging into fixable/pre-existing/benign/config_issue categories with IR-aware position context**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-31T23:24:40Z
- **Completed:** 2026-05-31T23:29:34Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- ClassifyViolationsOp Pydantic schema with target_file and optional erc_report_path
- Rule-based classifier with 10 classification rules covering all major violation types
- Each classified violation has category, confidence (high/medium/low), root_cause, and details
- Executor dispatch and Operation union wiring complete -- callable from LLM/MCP
- 19 new tests, 49 total pass with no regression

## Task Commits

Each task was committed atomically:

1. **Task 1: ClassifyViolationsOp schema and violation_classifier module with tests** - `1afb1b4` (test -- TDD RED+GREEN)
2. **Task 2: Executor registration and Operation union wiring** - `6b8ca2b` (feat)

## Files Created/Modified
- `src/kicad_agent/ops/_schema_erc_smart.py` - ClassifyViolationsOp Pydantic schema
- `src/kicad_agent/ops/violation_classifier.py` - classify_violations() with 10 rule-based classification rules
- `tests/test_violation_classifier.py` - 19 tests covering schema, classification, counts, and registration
- `src/kicad_agent/ops/schema.py` - Added ClassifyViolationsOp import and Operation union member
- `src/kicad_agent/ops/executor.py` - Registered @register_schematic("classify_violations") handler

## Decisions Made
- Classification rules stored in `_CLASSIFICATION_RULES` list for clean extensibility (new rules = new tuple)
- First-match-wins ordering: pre-existing rules checked before benign before fixable defaults
- IR position data distinguishes #PWR power symbols from regular components for pin_not_connected classification
- Schema in `_schema_erc_smart.py` (not `_schema_repair.py`) per CONTEXT.md D-01 decision

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed _is_pin_not_connected_default parameter name mismatch**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Parameter named `_ir_data` but body referenced `ir_data` -- NameError at runtime
- **Fix:** Changed parameter name from `_ir_data` to `ir_data` to match usage
- **Files modified:** src/kicad_agent/ops/violation_classifier.py
- **Verification:** Test pin_not_connected_non_power_is_fixable passed after fix
- **Committed in:** 1afb1b4 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial typo fix. No scope creep.

## Issues Encountered
None beyond the single typo auto-fix above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 40-02 (diagnose_violations) can consume the fixable violations from classify_violations output
- Plan 40-03 (enhanced erc_auto_fix) will use classification to skip pre-existing/benign violations
- The _CLASSIFICATION_RULES list is ready for extension with new violation types as needed

---
*Phase: 40-erc-root-cause*
*Completed: 2026-05-31*

## Self-Check: PASSED

- All 5 created/modified files verified on disk
- Both task commits (1afb1b4, 6b8ca2b) verified in git log
- 49/49 tests passing (19 new + 30 existing)
