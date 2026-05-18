---
phase: 07-gsd-skill-integration
plan: 03
subsystem: cli
tags: [argparse, cli, console-scripts, subprocess, pip-installable]

# Dependency graph
requires:
  - phase: 07-gsd-skill-integration/02
    provides: Skill handler routing (validate_operation, handle_operation, format_result)
  - phase: 02-operation-schema-and-ir-layer
    provides: Pydantic Operation schema with get_operation_schema()
provides:
  - pip-installable kicad-agent CLI command
  - argparse CLI with --schema, --dry-run, --verbose, --project-dir flags
  - Inline JSON or file path operation input
affects: [07-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [inline-vs-file input detection via startswith('{'), stderr for errors stdout for results, exit code tiers 0/1/2]

key-files:
  created:
    - src/kicad_agent/cli.py
    - tests/test_cli.py
  modified:
    - pyproject.toml

key-decisions:
  - "Inline JSON detected by startswith('{') heuristic -- simple and unambiguous for JSON objects"
  - "Exit code 0 success, 1 validation/operation failure, 2 reserved for unexpected exceptions"
  - "Tests invoke via python -m kicad_agent.cli to avoid PATH dependency"

patterns-established:
  - "CLI reads operation from inline JSON string or file path, routes through handler module"
  - "argparse CLI pattern with --schema for schema discovery and --dry-run for validation-only mode"

requirements-completed: [SKILL-03]

# Metrics
duration: 2min
completed: 2026-05-18
---

# Phase 7 Plan 3: CLI Wrapper for Direct Terminal Usage Summary

**Argparse CLI wrapper with console_scripts entry point, supporting inline JSON or file input, --schema/--dry-run flags, and subprocess-tested exit codes**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-18T18:50:15Z
- **Completed:** 2026-05-18T18:52:41Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created CLI module with argparse supporting positional JSON/file input and 4 optional flags
- Added [project.scripts] entry point to pyproject.toml for pip-installable kicad-agent command
- 8 subprocess-based tests covering schema, valid/invalid JSON, dry-run, file input, nonexistent file, and path traversal
- 436 total tests passing (428 baseline + 8 new)

## Task Commits

Each task was committed atomically:

1. **Task 2 (RED): Create CLI test suite** - `e056b8e` (test)
2. **Task 1 (GREEN): Create CLI module and update pyproject.toml** - `ff64811` (feat)

_Note: TDD flow executed RED (tests) before GREEN (implementation)._

## Files Created/Modified
- `src/kicad_agent/cli.py` - Argparse CLI with --schema, --dry-run, --verbose, --project-dir; routes through handler module
- `pyproject.toml` - Added [project.scripts] with kicad-agent = kicad_agent.cli:main entry point
- `tests/test_cli.py` - 8 subprocess tests covering all CLI behaviors

## Decisions Made
- Inline JSON detected by `startswith('{')` heuristic -- simple and unambiguous since all operations are JSON objects
- Exit code scheme: 0 for success, 1 for validation/operation failure, 2 reserved for unexpected exceptions
- Tests invoke CLI via `python -m kicad_agent.cli` instead of `kicad-agent` binary to avoid PATH dependency in test environments

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CLI is pip-installable and functional
- Plan 07-04 can build on the CLI for skill definition integration
- The CLI is the stable public interface for non-Claude usage

## TDD Gate Compliance

- RED gate: `e056b8e` test(07-03) commit exists
- GREEN gate: `ff64811` feat(07-03) commit exists after RED
- REFACTOR gate: Not needed (code is clean after single implementation pass)

## Self-Check: PASSED

All 3 files verified present. Both commits verified in git log. 436 tests passing.

---
*Phase: 07-gsd-skill-integration*
*Completed: 2026-05-18*
