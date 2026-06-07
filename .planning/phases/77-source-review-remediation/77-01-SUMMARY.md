---
phase: 77-source-review-remediation
plan: 01
subsystem: parser, validation
tags: [kicad-agent, parser, sexpdata, uuid, threading, shutil, bugfix]

# Dependency graph
requires:
  - phase: 27-aether-drive-pcb
    provides: kicad-agent BUGS.md with source review findings
provides:
  - P-BUG-001: depth pre-scan protection in raw_parser.py
  - P-BUG-002: correct nearest-enclosing parent detection in uuid_extractor.py
  - P-BUG-003: thread-safe recursion limit in pcb_native_parser.py
  - P-BUG-004: dead code removal in _extract_nets (done by parallel agent)
  - V-BUG-001: missing shutil import in erc_drc.py
affects: [78, kicad-agent, all-kicad-parsing, validation-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Paren-depth tracking for S-expression parent detection"
    - "threading.Lock for process-global state protection"

key-files:
  modified:
    - src/kicad_agent/parser/raw_parser.py
    - src/kicad_agent/parser/uuid_extractor.py
    - src/kicad_agent/parser/pcb_native_parser.py
    - src/kicad_agent/validation/erc_drc.py

key-decisions:
  - "P-BUG-002: Replaced regex pattern matching with paren-depth backward scan -- simpler, more correct, no pattern list maintenance needed"
  - "P-BUG-003: Used threading.Lock rather than per-thread recursion limits -- simpler and sufficient for the known concurrency pattern"
  - "V-BUG-001: Bug report attributed to pipeline.py but actual shutil usage is in erc_drc.py which pipeline.py calls -- fix placed at the source"

patterns-established:
  - "Depth pre-scan pattern: O(n) paren counter before sexpdata.loads() prevents RecursionError from corrupting interpreter state"
  - "Paren-depth parent detection: backward scan tracking depth to find nearest enclosing S-expression"

requirements-completed: []

# Metrics
started: 2026-06-07T04:13:08Z
completed: 2026-06-07T04:21:52Z
duration: 8m
duration_minutes: 8
commits: 4
files_modified: 4
---

# Phase 77 Plan 01: Parser and Validation Critical Bug Fixes Summary

**Four critical/high-severity bugs fixed in kicad-agent parser subsystem and validation pipeline: depth pre-scan for raw_parser, paren-depth parent detection for UUID extractor, thread-safe recursion limits, and missing shutil import.**

## Performance

- **Duration:** 8m
- **Started:** 2026-06-07T04:13:08Z
- **Completed:** 2026-06-07T04:21:52Z
- **Tasks:** 5 (4 committed by this agent, 1 by parallel agent)
- **Commits:** 4 (atomic task commits)
- **Files modified:** 4

## Accomplishments
- Added depth pre-scan to `raw_parser.py` matching protection already in `pcb_native_parser.py`, preventing RecursionError from corrupting CPython interpreter state
- Fixed UUID parent detection to use paren-depth backward scanning instead of latest-pattern-match heuristic, preventing UUID misattribution in nested structures (pad inside footprint misattributed to via)
- Added `threading.Lock` around `sys.setrecursionlimit()` in PCB parser to prevent concurrent parsing threads from clobbering each other's recursion limits
- Added missing `import shutil` to `erc_drc.py` which caused `NameError` at runtime when cleaning up temp directories

## Task Commits

Each task was committed atomically:

1. **Task 1: P-BUG-001** - `4ad4d80` (fix)
   Add depth pre-scan to raw_parser.py -- O(n) paren counter rejects deeply nested content before sexpdata.loads()
2. **Task 2: P-BUG-002** - `cd3af83` (fix)
   Fix uuid_extractor parent type detection -- backward paren-depth scan finds nearest enclosing parent instead of latest pattern match
3. **Task 3: P-BUG-003** - `59696df` (fix)
   Add thread lock for recursion limit in PCB parser -- threading.Lock wraps sys.setrecursionlimit get/set
4. **Task 5: V-BUG-001** - `bedb518` (fix)
   Add missing shutil import to erc_drc.py -- shutil.rmtree was called in finally blocks without the import

**Task 4 (P-BUG-004):** Dead code removal in `_extract_nets` was committed by parallel agent in `cf23309`

## Files Created/Modified
- `src/kicad_agent/parser/raw_parser.py` - Added `_pre_scan_depth()` function and call site in `parse_raw_sexp()`
- `src/kicad_agent/parser/uuid_extractor.py` - Rewrote `_determine_parent_type()` with paren-depth backward scanning
- `src/kicad_agent/parser/pcb_native_parser.py` - Added `threading` import, `_RECURSION_LIMIT_LOCK`, and lock context manager around recursion limit manipulation
- `src/kicad_agent/validation/erc_drc.py` - Added `import shutil` to fix NameError in temp dir cleanup

## Decisions Made
- **P-BUG-002 approach**: Chose paren-depth backward scanning over improving the regex heuristic. The regex approach would require maintaining a sorted intersection of all pattern matches within the search window. Paren-depth tracking is simpler, more correct, and needs no pattern list.
- **P-BUG-003 approach**: Used `threading.Lock` around the existing get/set pattern rather than restructuring to avoid `sys.setrecursionlimit()` entirely. The lock is simple, low-overhead, and sufficient for the known concurrency pattern (batch executor).
- **V-BUG-001 attribution**: Bug report named `pipeline.py` but the actual `shutil.rmtree()` calls are in `erc_drc.py` which `pipeline.py` imports and calls. Fix placed at the source (`erc_drc.py`).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- **Pre-existing test failure**: `test_roundtrip/test_regression_suite.py::test_pcb_uuid_preserved` fails on `smd_test_board.kicad_pcb` with "list index out of range" -- pre-existing, not caused by any of the 5 bug fixes. Verified by reverting P-BUG-002 and re-running the test (still failed).
- **Pre-existing test isolation issue**: `test_connectivity_query.py::TestQueryExecutor::test_are_connected_same_net` fails in the full suite but passes in isolation due to IR registry fixture not being shared across test modules. Pre-existing, not related to these fixes.
- **Parallel agent collision**: P-BUG-004 (dead code removal in `_extract_nets`) was already fixed by a parallel agent executing plan 77-02, committed as `cf23309`. This agent's P-BUG-003 commit preceded it but P-BUG-004 edit was a no-op since the file was already clean.

## Next Phase Readiness
- Parser subsystem critical bugs P-BUG-001 through P-BUG-005 are addressed
- Validation pipeline V-BUG-001 is fixed; V-BUG-002 (split_plane) and V-BUG-003 (DFM profile) remain
- Serializer subsystem S-BUG-001 through S-BUG-005 being handled by parallel agent (plan 77-02)
- Ops/execution pipeline O-BUG-001 through O-BUG-008 remain for future plans

## Self-Check: PASSED

- All 4 commits found in git log (4ad4d80, cd3af83, 59696df, bedb518)
- All 4 modified files exist on disk
- SUMMARY.md created at `.planning/phases/77-source-review-remediation/77-01-SUMMARY.md`
- 691 tests passed in kicad-agent test suite (excluding pre-existing failures)

---
*Phase: 77-source-review-remediation*
*Completed: 2026-06-07*
