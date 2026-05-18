---
phase: 03-validation-pipeline
plan: 01
subsystem: validation
tags: [kicad-cli, erc, drc, subprocess, json-parsing, frozen-dataclass]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: KiCad file parsing infrastructure
provides:
  - run_erc() ERC wrapper with structured ErcResult
  - run_drc() DRC wrapper with structured DrcResult
  - Frozen Violation, ErcResult, DrcResult dataclasses
  - Severity enum mapping kicad-cli values
  - Graceful error handling (error_message instead of exceptions)
affects: [03-02, 03-03, 04-mutation-engine]

# Tech tracking
tech-stack:
  added: [kicad-cli subprocess invocation, JSON report parsing]
  patterns: [graceful-degradation-result-type, tempdir-cleanup-finally]

key-files:
  created:
    - src/kicad_agent/validation/erc_drc.py
    - tests/test_erc_drc.py
  modified:
    - src/kicad_agent/validation/__init__.py

key-decisions:
  - "Used --output flag with explicit tempdir path instead of relying on kicad-cli CWD behavior"
  - "Graceful error results (error_message field) instead of exceptions for all failure modes"
  - "passed=True defined as zero errors for ERC, zero errors AND zero unconnected for DRC"

patterns-established:
  - "Graceful degradation: CLI wrappers return result objects with error_message set instead of raising"
  - "Tempdir with finally cleanup: subprocess output captured via tempdir, cleaned in finally block"

requirements-completed: [VAL-01, VAL-02]

# Metrics
duration: 4min
completed: 2026-05-18
---

# Phase 3 Plan 1: ERC/DRC Wrappers Summary

**kicad-cli ERC and DRC wrappers with frozen dataclass results, JSON report parsing, and graceful error handling via subprocess invocation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-18T07:10:22Z
- **Completed:** 2026-05-18T07:14:25Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- ERC wrapper invokes kicad-cli sch erc with JSON output parsing into structured ErcResult
- DRC wrapper invokes kicad-cli pcb drc with unconnected items and schematic parity capture
- Frozen dataclasses (ErcResult, DrcResult, Violation) for immutable result types
- Severity enum mapping kicad-cli JSON severity values (error, warning, exclusion)
- kicad-cli discovery with clear FileNotFoundError and install instructions
- Graceful error handling: all failure modes return error_message field, never crash
- 24 new tests including integration tests against real Arduino_Mega fixtures

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ERC/DRC wrapper module with structured result types** - `a86429e` (feat)
2. **Task 2: Create ERC/DRC test suite and update barrel exports** - `1daf292` (test)

## Files Created/Modified
- `src/kicad_agent/validation/erc_drc.py` - ERC/DRC wrappers with run_erc(), run_drc(), frozen result types
- `tests/test_erc_drc.py` - 24 tests: unit tests for types, integration tests with kicad-cli, error handling
- `src/kicad_agent/validation/__init__.py` - Updated barrel exports to include ERC/DRC symbols

## Decisions Made
- Used `--output` flag with explicit tempdir path for kicad-cli JSON report capture (more reliable than CWD-based output)
- Graceful degradation pattern: CLI wrappers return result objects with `error_message` field set instead of raising exceptions, enabling callers to handle failures uniformly
- `passed=True` defined as zero errors for ERC (warnings non-fatal), zero errors AND zero unconnected items for DRC

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed DRC test assertion for Arduino_Mega fixture**
- **Found during:** Task 2 (test suite creation)
- **Issue:** Test assumed Arduino_Mega PCB has DRC errors (severity=error), but actual kicad-cli output shows only warnings and unconnected items -- no severity=error violations
- **Fix:** Changed assertion from `result.error_count > 0` to `result.warning_count > 0 or len(result.unconnected_items) > 0` to match real output
- **Files modified:** tests/test_erc_drc.py
- **Verification:** All 24 tests pass against real kicad-cli output
- **Committed in:** 1daf292 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Test assertion corrected to match actual kicad-cli output. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ERC and DRC wrappers ready for use in Phase 3 Plans 02 and 03
- run_erc() and run_drc() available via `from kicad_agent.validation import run_erc, run_drc`
- DRC schematic_parity capture ready for VAL-03 prerequisite

## Self-Check: PASSED

All files and commits verified:
- src/kicad_agent/validation/erc_drc.py: FOUND
- tests/test_erc_drc.py: FOUND
- src/kicad_agent/validation/__init__.py: FOUND
- .planning/phases/03-validation-pipeline/03-01-SUMMARY.md: FOUND
- a86429e (Task 1): FOUND
- 1daf292 (Task 2): FOUND

---
*Phase: 03-validation-pipeline*
*Completed: 2026-05-18*
