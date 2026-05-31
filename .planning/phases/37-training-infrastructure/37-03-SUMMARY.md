---
phase: 37-training-infrastructure
plan: 03
subsystem: infra
tags: [mcp, health-check, graceful-shutdown, smoke-test, pytorch, sft, grpo]

# Dependency graph
requires:
  - phase: 37-01
    provides: "configure_logging() function for structured logging"
  - phase: 37-02
    provides: "DataManifest, regression detection, cleanup utilities"
provides:
  - "health_check MCP tool returning status, uptime, executor_ready, in_flight_operations"
  - "Graceful shutdown with SIGTERM/SIGINT signal handlers and in-flight drain tracking"
  - "run_sft_smoke_test and run_grpo_smoke_test for pipeline validation"
affects: [mcp-servers, training-pipeline, ci]

# Tech tracking
tech-stack:
  added: []
  patterns: [health-check-endpoint, signal-handler-shutdown, in-flight-counter, smoke-test-guard]

key-files:
  created:
    - src/kicad_agent/training/smoke_test.py
    - tests/test_mcp_health_check.py
    - tests/test_mcp_graceful_shutdown.py
    - tests/test_pipeline_smoke.py
  modified:
    - src/kicad_agent/mcp/edit_server.py
    - src/kicad_agent/mcp/server.py
    - tests/test_mcp/test_edit_server.py

key-decisions:
  - "Shutdown rejection applies to all tools except health_check (not just operation tools)"
  - "global _in_flight_count declared at top of dispatch_tool to avoid SyntaxError with prior reads"
  - "Smoke tests use tempfile.mkdtemp for output isolation"

patterns-established:
  - "health_check: readOnly meta-tool returning JSON status with uptime and counters"
  - "Graceful shutdown: _shutdown_requested flag + signal handler + drain counter"
  - "Smoke test: torch_available() guard with pytest.mark.skipif"

requirements-completed: [INFRA-02, INFRA-03, TRAIN-03]

# Metrics
duration: 9min
completed: 2026-05-31
---

# Phase 37 Plan 03: MCP Health Check + Graceful Shutdown + Smoke Tests Summary

**health_check tool with uptime/in-flight/executor status, graceful shutdown via signal handlers, SFT+GRPO smoke tests on 10 samples in under 60s**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-31T20:32:56Z
- **Completed:** 2026-05-31T20:42:08Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- health_check MCP tool in both edit_server and component search server, returning structured JSON with status, uptime_seconds, executor_ready, project_dir, in_flight_operations, total_tools_available
- Graceful shutdown via _shutdown_requested flag set by SIGTERM/SIGINT signal handlers, rejecting all new operations while health_check still works during drain
- In-flight operation counter with try/finally decrement for operation tracking
- SFT smoke test trains RewardModel on 10 synthetic samples, 2 epochs, loss decreases from initial to final
- GRPO smoke test runs full training loop on 10 samples, 1 epoch, completes without error
- Both smoke tests complete under 60 seconds on CPU (29s total for 5 tests)

## Task Commits

Each task was committed atomically (TDD: RED then GREEN):

1. **Task 1 RED: Failing tests for health check and graceful shutdown** - `af97cfe` (test)
2. **Task 1 GREEN: Implement health check + graceful shutdown in MCP servers** - `2fb04e2` (feat)
3. **Task 2 RED: Failing tests for training pipeline smoke tests** - `57122f3` (test)
4. **Task 2 GREEN: Implement training pipeline smoke tests** - `a5fd989` (feat)

## Files Created/Modified
- `src/kicad_agent/mcp/edit_server.py` - health_check tool, shutdown rejection, in-flight counter, signal handler, configure_logging (already wired from 37-01)
- `src/kicad_agent/mcp/server.py` - health_check tool, shutdown rejection, in-flight counter, signal handler
- `src/kicad_agent/training/smoke_test.py` - run_sft_smoke_test and run_grpo_smoke_test functions
- `tests/test_mcp_health_check.py` - 5 tests for health_check status, in-flight, project_dir, total_tools, meta_tools
- `tests/test_mcp_graceful_shutdown.py` - 4 tests for shutdown rejection, health during shutdown, in-flight tracking
- `tests/test_pipeline_smoke.py` - 5 tests for SFT/GRPO smoke completion, convergence, timing
- `tests/test_mcp/test_edit_server.py` - Updated meta tool count from 6 to 7, total from 80 to 81

## Decisions Made
- Shutdown rejection applies to ALL tools except health_check (not just operation tools), so meta-tools like get_operation_schema are also rejected during shutdown -- simpler and safer
- global _in_flight_count declared at function top in dispatch_tool to avoid Python SyntaxError when the variable is read earlier (in health_check handler) before the global declaration
- Smoke tests use tempfile.mkdtemp for output isolation so multiple runs don't interfere

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Moved global declaration to avoid SyntaxError**
- **Found during:** Task 1 (edit_server.py implementation)
- **Issue:** `global _in_flight_count` was placed after the health_check handler which reads `_in_flight_count`, causing "name is used prior to global declaration" SyntaxError
- **Fix:** Moved `global _in_flight_count` to the top of dispatch_tool function
- **Files modified:** src/kicad_agent/mcp/edit_server.py
- **Verification:** All 55 tests pass
- **Committed in:** 2fb04e2 (Task 1 GREEN commit)

**2. [Rule 1 - Bug] Shutdown rejection scope widened to cover all tools**
- **Found during:** Task 1 (test_mcp_graceful_shutdown.py test failure)
- **Issue:** Test expected get_operation_schema to be rejected during shutdown, but initial implementation only rejected operation tools (after meta-tools section)
- **Fix:** Moved shutdown check to right after health_check handler, before all other tool handling
- **Files modified:** src/kicad_agent/mcp/edit_server.py
- **Verification:** All 55 tests pass, including shutdown tests
- **Committed in:** 2fb04e2 (Task 1 GREEN commit)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both auto-fixes were necessary for correctness. No scope creep.

## Issues Encountered
None beyond the two auto-fixed issues documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- MCP servers now have production-ready health check and graceful shutdown
- Training pipeline smoke tests available for CI validation
- Phase 37 complete -- all three plans (37-01, 37-02, 37-03) delivered

---
*Phase: 37-training-infrastructure*
*Completed: 2026-05-31*

## Self-Check: PASSED

- All 6 created/modified files verified present on disk
- All 4 commit hashes verified in git log (af97cfe, 2fb04e2, 57122f3, a5fd989)
- No unexpected file deletions in any commit
