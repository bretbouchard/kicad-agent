---
phase: 40-erc-root-cause
plan: 03
subsystem: erc-intelligence
tags: [erc, auto-fix, root-cause-mode, classify-diagnose-fix, schema-migration, pydantic]

# Dependency graph
requires:
  - phase: 40-01
    provides: classify_violations() output with fixable violation dicts
  - phase: 40-02
    provides: diagnose_violations() output with fix options and confidence ratings
provides:
  - ErcAutoFixOp with mode field (symptom/root_cause) and fix_classes field
  - erc_auto_fix_root_cause() function: classify -> diagnose -> targeted repair
  - _action_to_repair_name() helper mapping diagnosis actions to repair functions
  - _empty_root_cause_result() helper for empty result structure
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [mode-dispatch, classify-diagnose-fix-pipeline, atomic-schema-migration]

key-files:
  created:
    - tests/test_erc_auto_fix_root_cause.py
  modified:
    - src/kicad_agent/ops/_schema_erc_smart.py
    - src/kicad_agent/ops/_schema_repair.py
    - src/kicad_agent/ops/erc_auto_fix.py
    - src/kicad_agent/ops/executor.py
    - src/kicad_agent/ops/schema.py
    - tests/test_violation_classifier.py

key-decisions:
  - "ErcAutoFixOp migrated from _schema_repair.py to _schema_erc_smart.py (Council H-02: two classes with same op_type discriminator cannot coexist in Operation union)"
  - "mode field defaults to 'symptom' for backward compatibility -- existing callers get existing behavior"
  - "Root cause mode is single-pass (iterations=1) because diagnosis replaces iteration"
  - "Pre-existing violations documented with root cause explanations, not silently ignored"
  - "Benign violations suppressed from detailed report (count only) to reduce noise"
  - "_action_to_repair_name maps diagnosis actions to repair functions; unmappable actions (add_wire, erc_auto_fix) return None and are skipped"

patterns-established:
  - "Mode dispatch pattern: erc_auto_fix() accepts mode param, dispatches to specialized function"
  - "Atomic schema migration: remove from old module, add to new, update import -- all in one commit"

requirements-completed: [ERC-SMART-03]

# Metrics
duration: 4min
completed: 2026-05-31
---

# Phase 40 Plan 03: Enhanced erc_auto_fix with Root Cause Mode Summary

**Root cause mode for erc_auto_fix: classify-diagnose-fix pipeline with atomic ErcAutoFixOp schema migration from _schema_repair to _schema_erc_smart**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-31T23:38:17Z
- **Completed:** 2026-05-31T23:42:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- ErcAutoFixOp migrated from _schema_repair.py to _schema_erc_smart.py (Council H-02 atomic migration)
- New mode field: Literal["symptom", "root_cause"] defaulting to "symptom" (backward compatible)
- New fix_classes field: Optional[list[str]] for filtering violation classes in root_cause mode
- erc_auto_fix_root_cause() function: classify -> diagnose -> targeted repair, single-pass
- Pre-existing violations documented with root_cause, details, confidence (not silently ignored)
- Benign violations suppressed from detailed report (benign_suppressed count only)
- Config issues listed with type and details for user action
- Symptom mode (default) preserves existing iteration-based repair exactly
- Executor handler uses getattr(op, "mode", "symptom") for backward compatibility
- _action_to_repair_name helper maps 6 diagnosis actions to repair function names
- 31 new tests, 96 total pass across all Phase 40 test suites with zero regressions

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2: Schema migration + root cause mode + executor handler + tests** - `8196dd7` (feat -- TDD RED+GREEN)

## Files Created/Modified
- `src/kicad_agent/ops/_schema_erc_smart.py` - Added ErcAutoFixOp with mode and fix_classes fields
- `src/kicad_agent/ops/_schema_repair.py` - Removed ErcAutoFixOp (replaced with migration comment)
- `src/kicad_agent/ops/erc_auto_fix.py` - Added erc_auto_fix_root_cause(), _action_to_repair_name(), _empty_root_cause_result(), updated erc_auto_fix() with mode dispatch
- `src/kicad_agent/ops/executor.py` - Updated _handle_erc_auto_fix to pass mode and fix_classes via getattr
- `src/kicad_agent/ops/schema.py` - Updated import: ErcAutoFixOp from _schema_erc_smart instead of _schema_repair
- `tests/test_erc_auto_fix_root_cause.py` - 31 tests covering schema, root cause mode, symptom mode, mode dispatch, executor handler, action mapping
- `tests/test_violation_classifier.py` - Fixed ErcAutoFixOp import to new location

## Decisions Made
- ErcAutoFixOp moved to _schema_erc_smart.py to avoid duplicate op_type in Operation union (Council H-02)
- mode defaults to "symptom" so existing callers get existing behavior without changes
- Root cause mode is single-pass (iterations=1) because diagnosis eliminates the need for iterative repair
- Pre-existing violations are documented, not silently ignored -- LLM agents and MCP callers get full context
- Benign violations suppressed from detail to reduce noise -- only count exposed
- Unmappable diagnosis actions (add_wire, erc_auto_fix) return None from _action_to_repair_name and are skipped gracefully
- Executor handler uses getattr defaults for backward compat with old schema objects

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed test patching paths for lazy imports**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** classify_violations and diagnose_violations are imported lazily inside erc_auto_fix_root_cause(), so @patch on kicad_agent.ops.erc_auto_fix.classify_violations fails with AttributeError
- **Fix:** Changed patch targets to source modules: kicad_agent.ops.violation_classifier.classify_violations and kicad_agent.ops.violation_diagnostic.diagnose_violations
- **Files modified:** tests/test_erc_auto_fix_root_cause.py
- **Verification:** All 96 tests pass after fix

**2. [Rule 3 - Blocking] Updated stale import in test_violation_classifier.py**
- **Found during:** Full Phase 40 regression
- **Issue:** test_existing_erc_auto_fix_tests_still_pass imported ErcAutoFixOp from old location (_schema_repair)
- **Fix:** Updated import to kicad_agent.ops._schema_erc_smart
- **Files modified:** tests/test_violation_classifier.py
- **Verification:** All 96 tests pass

---

**Total deviations:** 2 auto-fixed (2 blocking issues)
**Impact on plan:** Both were import path fixes caused by the schema migration. No scope creep.

## Issues Encountered
None beyond the two import fixes auto-resolved above.

## User Setup Required
None - no external service configuration required.

## TDD Gate Compliance

- RED gate: Tests written first, failed with ImportError before implementation
- GREEN gate: Implementation commit 8196dd7 makes all 96 tests pass
- REFACTOR: _action_to_repair_name covers all 6 mappable actions from violation_diagnostic.py

## Next Phase Readiness
- Phase 40 is complete (all 3 plans executed)
- The full classify -> diagnose -> fix pipeline is operational
- LLM agents can use mode="root_cause" for intelligent auto-fix
- mode="symptom" preserves existing behavior for backward compatibility

---
*Phase: 40-erc-root-cause*
*Completed: 2026-05-31*

## Self-Check: PASSED

- All 7 created/modified files verified on disk
- Commit 8196dd7 verified in git log
- 96/96 tests passing (31 new + 65 existing)
