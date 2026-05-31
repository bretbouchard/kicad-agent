---
phase: 35-remaining-ops-gaps
plan: 02
subsystem: ops
tags: [erc, repair, meta-operation, iteration-control, violation-dispatch]

# Dependency graph
requires:
  - phase: 34-llm-provider-abstraction
    provides: "Existing operation schema pattern and executor dispatch infrastructure"
provides:
  - "erc_auto_fix meta-operation chaining parse_erc to violation-type repair dispatch with iteration control"
  - "ErcAutoFixOp schema with max_iterations field (default=3, ge=1, le=10)"
  - "VIOLATION_REPAIR_MAP mapping violation type strings to repair function names"
  - "REPAIR_PRIORITY list controlling repair execution order (shorts > types > power > cosmetic)"
  - "Early stop when violation count does not decrease between iterations"
  - "Unhandled violation type reporting in return value"
affects: [mcp-server, documentation, slc-compliance]

# Tech tracking
tech-stack:
  added: []
patterns: ["Meta-operation pattern: parse_erc + dispatch repairs + iterate", "Priority-ordered repair dispatch via REPAIR_PRIORITY list", "Violation type mapping via VIOLATION_REPAIR_MAP dict"]

key-files:
  created:
    - src/kicad_agent/ops/erc_auto_fix.py
  modified:
    - src/kicad_agent/ops/_schema_repair.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
    - tests/test_schematic_repair.py
    - tests/test_slc_compliance.py
    - tests/test_mcp/test_edit_server.py
    - README.md
    - skills/SKILL.md

key-decisions:
  - "parse_erc imported at module level (not lazily) in erc_auto_fix.py to enable test mocking"
  - "Repair functions imported lazily via _get_repair_function dispatcher for consistency with executor pattern"
  - "Iteration count = 0 when first parse_erc returns no violations (never entered a repair iteration)"
  - "Early stop after 2 iterations when count stays the same (first iteration runs repairs, second detects no improvement)"

patterns-established:
  - "Meta-operation pattern: single op that chains parse + dispatch + iterate with early stopping"
  - "Violation-to-repair mapping via configurable VIOLATION_REPAIR_MAP dict"
  - "Priority-ordered dispatch: shorts > pin type conflicts > missing units > power flags > cosmetic"

requirements-completed: [GEN-03]

# Metrics
duration: 8min
completed: 2026-05-31
---

# Phase 35 Plan 02: ERC Auto-Fix Meta-Operation Summary

**erc_auto_fix meta-operation with violation-type dispatch map, priority-ordered repairs, iteration limits (max 10), early stop on no improvement, and unhandled violation reporting**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-31T16:08:57Z
- **Completed:** 2026-05-31T16:17:47Z
- **Tasks:** 1
- **Files modified:** 9

## Accomplishments
- ErcAutoFixOp schema registered in schema.py union (72 operation types total)
- erc_auto_fix.py module with VIOLATION_REPAIR_MAP (4 direct mappings + 2 pattern-based), REPAIR_PRIORITY list, and erc_auto_fix function
- Handler registered as @register_schematic("erc_auto_fix") in executor.py
- 8 tests covering: no violations, pin_not_connected dispatch, power_pin_not_driven dispatch, max_iterations limit, early stop, unhandled violations, schema validation, priority order
- Updated operation counts (71->72) across SLC compliance, MCP tests, README, SKILL.md

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement erc_auto_fix meta-operation with violation dispatch and iteration control** - `d96b546` (feat) [TDD: test + feat combined]

## Files Created/Modified
- `src/kicad_agent/ops/erc_auto_fix.py` - New module: erc_auto_fix function, VIOLATION_REPAIR_MAP, REPAIR_PRIORITY, _get_repair_function dispatcher
- `src/kicad_agent/ops/_schema_repair.py` - Added ErcAutoFixOp schema class with max_iterations field
- `src/kicad_agent/ops/schema.py` - Added ErcAutoFixOp to import, union (72 types), and __all__
- `src/kicad_agent/ops/executor.py` - Added @register_schematic("erc_auto_fix") handler
- `tests/test_schematic_repair.py` - Added TestErcAutoFix class with 8 tests
- `tests/test_slc_compliance.py` - Updated operation count assertion (71->72)
- `tests/test_mcp/test_edit_server.py` - Updated tool count assertions (65->66 ops, 71->72 total)
- `README.md` - Updated operation count (71->72)
- `skills/SKILL.md` - Updated operation count (71->72)

## Decisions Made
- parse_erc imported at module level in erc_auto_fix.py (not lazily) to enable unittest.mock.patch targeting
- Repair functions imported lazily via _get_repair_function dispatcher, matching executor's lazy-import pattern
- Iteration count is 0 when first parse_erc returns empty (never entered repair loop)
- Early stop logic: first iteration runs repairs and records count, second iteration checks if count decreased and stops if not
- Unhandled violations collected across all iterations and deduplicated by type in final return value

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated stale operation counts (71->72) in SLC, MCP tests, README, SKILL.md**
- **Found during:** Task 1 (verification -- full test suite run)
- **Issue:** Adding ErcAutoFixOp bumped operation count from 71 to 72, breaking hardcoded assertions in test_slc_compliance.py and test_mcp/test_edit_server.py
- **Fix:** Updated test assertions (71->72), README.md (71->72), SKILL.md (71->72), MCP test assertions (65->66 ops, 71->72 total)
- **Files modified:** tests/test_slc_compliance.py, tests/test_mcp/test_edit_server.py, README.md, skills/SKILL.md
- **Verification:** All 103 tests pass (SLC 25/25, MCP 46/46, schematic repair 32/32)
- **Committed in:** d96b546 (part of task commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Count update necessary for test suite integrity. No scope creep.

## Issues Encountered
- Test mocking required patching repair functions at their source module (kicad_agent.ops.repair.*) rather than in erc_auto_fix module, since functions are imported lazily via _get_repair_function dispatcher
- parse_erc final check (line 197 in erc_auto_fix.py) requires an extra mock return value in side_effect lists that was initially overlooked in 3 tests

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 72 operations registered and tested
- Plan 03 (remaining ops gap) can proceed
- erc_auto_fix meta-operation available for LLM/MCP callers

---
*Phase: 35-remaining-ops-gaps*
*Completed: 2026-05-31*

## Self-Check: PASSED

- erc_auto_fix.py: FOUND
- _schema_repair.py: FOUND
- schema.py: FOUND
- executor.py: FOUND
- test_schematic_repair.py: FOUND
- 35-02-SUMMARY.md: FOUND
- Commit d96b546: FOUND
