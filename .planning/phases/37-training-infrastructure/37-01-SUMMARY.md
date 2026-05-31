---
phase: 37-training-infrastructure
plan: 01
subsystem: infra
tags: [structlog, logging, structured-logging, json, observability]

# Dependency graph
requires: []
provides:
  - "configure_logging() function for structured log output across all 70 getLogger sites"
  - "KICAD_LOG_LEVEL and KICAD_LOG_FORMAT environment variable support"
  - "JSON mode for machine-parseable logs, console mode for human operators"
affects: [37-02, 37-03, training-pipeline, mcp-servers, cli]

# Tech tracking
tech-stack:
  added: [structlog-25.5.0]
  patterns: [stdlib-processor-formatter, env-var-log-config, idempotent-handler-setup]

key-files:
  created:
    - src/kicad_agent/logging_config.py
    - tests/test_structured_logging.py
  modified:
    - src/kicad_agent/cli.py
    - src/kicad_agent/mcp/edit_server.py
    - src/kicad_agent/mcp/server.py

key-decisions:
  - "Excluded filter_by_level from foreign_pre_chain -- incompatible with stdlib records (AttributeError on NoneType)"
  - "Level filtering handled by root logger setLevel() instead of structlog processor"
  - "Local import of configure_logging in MCP server entry points to match existing pattern"

patterns-established:
  - "configure_logging() at entry point start, before any other work"
  - "KICAD_LOG_LEVEL and KICAD_LOG_FORMAT env vars for runtime configuration"
  - "ProcessorFormatter bridges structlog and stdlib without per-file changes"

requirements-completed: [INFRA-01]

# Metrics
duration: 6min
completed: 2026-05-31
---

# Phase 37 Plan 01: Structured Logging Summary

**structlog 25.5.0 with ProcessorFormatter intercepts all 70 existing getLogger sites, JSON mode for machines, console mode for humans**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-31T20:11:48Z
- **Completed:** 2026-05-31T20:17:50Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- configure_logging() sets up structlog with stdlib ProcessorFormatter for zero per-file changes
- JSON mode (KICAD_LOG_FORMAT=json) produces valid JSON log lines parseable by jq
- Console mode (default) produces human-readable colored output
- All 3 entry points (cli.py, edit_server.py, server.py) wired
- 8 tests covering level config, JSON/console output, idempotency, stdlib interception, env vars, invalid input

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for structured logging** - `0a252fe` (test)
2. **Task 1 (GREEN): Implement structured logging via structlog** - `11888aa` (feat)
3. **Task 2: Wire configure_logging into all entry points** - `35a28aa` (feat)

## Files Created/Modified
- `src/kicad_agent/logging_config.py` - configure_logging() with structlog ProcessorFormatter, env var support
- `tests/test_structured_logging.py` - 8 tests for logging configuration
- `src/kicad_agent/cli.py` - Replaced logging.basicConfig with configure_logging() in 3 locations
- `src/kicad_agent/mcp/edit_server.py` - Replaced logging.basicConfig with configure_logging()
- `src/kicad_agent/mcp/server.py` - Added configure_logging() before asyncio.run()

## Decisions Made
- Excluded filter_by_level from shared processors -- it requires a structlog logger object which is None when processing stdlib foreign records via foreign_pre_chain. Level filtering is handled by root logger setLevel() which is sufficient for stdlib loggers.
- Used local import pattern in MCP server entry points to match existing code style.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed filter_by_level from shared processors**
- **Found during:** Task 1 (logging_config.py implementation)
- **Issue:** structlog.stdlib.filter_by_level raises AttributeError: 'NoneType' object has no attribute 'disabled' when processing stdlib log records through foreign_pre_chain
- **Fix:** Removed filter_by_level from shared_processors. Level filtering is already handled by root logger setLevel() and handler level, which covers all stdlib logger output.
- **Files modified:** src/kicad_agent/logging_config.py
- **Verification:** All 8 tests pass, manual verification with minimal reproduction script
- **Committed in:** 11888aa (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary fix. filter_by_level is incompatible with the foreign_pre_chain pattern. Level filtering still works correctly via stdlib's built-in mechanism.

## Issues Encountered
None beyond the filter_by_level incompatibility documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Structured logging foundation complete, ready for Plans 02 and 03 to build on it
- All 70 existing getLogger sites automatically produce structured output
- Plans 02/03 can rely on configure_logging() being called at all entry points

---
*Phase: 37-training-infrastructure*
*Completed: 2026-05-31*

## Self-Check: PASSED

- All 3 created files verified present on disk
- All 3 commit hashes verified in git log (0a252fe, 11888aa, 35a28aa)
- No unexpected file deletions in any commit
