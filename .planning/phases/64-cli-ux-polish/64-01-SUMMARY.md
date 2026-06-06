---
phase: 64-cli-ux-polish
plan: 01
subsystem: cli
tags: [argparse, path-resolution, route, ValueError, cwd]

# Dependency graph
requires: []
provides:
  - Safe path resolution for route subcommand with try/except ValueError
  - Fallback to absolute path when PCB file is outside CWD
affects: [cli, routing]

# Tech tracking
tech-stack:
  added: []
  patterns: ["try/except ValueError for relative_to fallback"]

key-files:
  created: [tests/test_phase64_cli.py]
  modified: [src/kicad_agent/cli.py]

key-decisions:
  - "Fall back to absolute path when relative_to raises ValueError (file outside CWD)"
  - "No new dependencies needed -- standard pathlib API sufficient"

requirements-completed: []

# Metrics
started: 2026-06-01T00:00:00Z
completed: 2026-06-01T00:00:00Z
duration: <1m
duration_minutes: 0
commits: 1
files_modified: 2
---

# Phase 64 Plan 01: Fix Route Crash on Paths Outside CWD Summary

**Route subcommand no longer crashes with ValueError when PCB file is outside CWD -- falls back to absolute path**

## Performance

- **Duration:** <1m (part of single Phase 64 commit)
- **Started:** 2026-06-01T00:00:00Z
- **Completed:** 2026-06-01T00:00:00Z
- **Tasks:** 1
- **Commits:** 1 (atomic commit)
- **Files modified:** 2

## Accomplishments
- `_handle_route` wraps `resolve().relative_to(Path.cwd())` in try/except ValueError
- Falls back to `resolve()` absolute path when file is outside CWD
- 3 regression tests: outside-CWD, absolute path verification, inside-CWD regression

## Task Commits

1. **Task 1: Fix route crash on paths outside CWD** - `e0bb8cd` (feat)

## Files Created/Modified
- `src/kicad_agent/cli.py` - Added try/except ValueError in _handle_route (lines 426-429)
- `tests/test_phase64_cli.py` - 3 tests in TestRoutePathOutsideCwd

## Decisions Made
None - followed plan as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Route subcommand safe for any file path (relative or absolute)
- No downstream impact on other subcommands

---
*Phase: 64-cli-ux-polish*
*Completed: 2026-06-01*
