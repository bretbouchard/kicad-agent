---
phase: 15-ai-generation-wiring
plan: 03
subsystem: llm
tags: [claude, tool-use, refinement, erc, drc, error-fixer, iteration, stagnation]

# Dependency graph
requires:
  - phase: 15-01
    provides: "LLMClient, ContextBuilder, conftest_llm.py shared fixtures"
  - phase: 10
    provides: "analyze_erc_errors, _apply_place_no_connects, _apply_wire_snapping, run_erc"
provides:
  - "ErrorFixer: ERC/DRC violations to fix operations via Claude tool use"
  - "FixResult: frozen dataclass for fix results"
  - "FIX_TOOL: Claude tool definition with full operation schema"
  - "llm_refine_design: LLM-augmented refinement loop combining deterministic and LLM fixes"
  - "LLMRefinementResult/LLMRefinementIteration: result tracking with llm_fixes counts"
affects: [15-04, generation-pipeline, production-ai]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deterministic-first-fix: run free/reliable fixes before LLM calls"
    - "Stagnation detection: stop loop after 3 consecutive same-count iterations"
    - "Prompt caching on system prompts with large tool schemas"

key-files:
  created:
    - src/kicad_agent/llm/error_fixer.py
    - src/kicad_agent/llm/refinement.py
    - tests/test_llm_error_fixer.py
    - tests/test_llm_refinement.py
  modified:
    - src/kicad_agent/llm/__init__.py

key-decisions:
  - "Deterministic fixes run as fast first pass; LLM only called for 'other' error category"
  - "Prompt caching on FIX_SYSTEM_PROMPT to reduce costs from 51KB operation schema"
  - "Stagnation threshold of 3 consecutive iterations with same error count"
  - "Hard iteration cap of 10 enforced regardless of max_iterations argument"

patterns-established:
  - "Deterministic-then-LLM: always run free fixes first, LLM as fallback for unknown errors"
  - "Iteration history tracking: LLM receives previous attempts to avoid repeating failed fixes"
  - "Operation validation: LLM operations validated via Operation.model_validate() before execution"

requirements-completed: [AIGEN-04]

# Metrics
duration: 3min
completed: 2026-05-24
---

# Phase 15 Plan 03: LLM Error Fixer and Refinement Loop Summary

**ErrorFixer converts ERC/DRC violations to fix operations via Claude tool use; llm_refine_design combines deterministic fixes (fast/free) with LLM fixes for "other" errors, with stagnation detection and hard iteration cap**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-24T00:26:11Z
- **Completed:** 2026-05-24T00:29:22Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- ErrorFixer sends violations to Claude with full operation schema as tool definition, receives structured fix operations
- llm_refine_design runs deterministic fixes (pin_not_connected, wire_not_connected) first, then LLM for "other" category
- Stagnation detection stops loop after 3 consecutive iterations with same error count
- Hard iteration cap of 10 enforced for DoS prevention (T-15-11)
- LLM not called when only deterministic errors exist (saves API cost)
- Iteration history passed to LLM so it avoids repeating failed fixes
- Prompt caching on system prompt to reduce API costs with 51KB operation schema

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for ErrorFixer and refinement loop** - `4f73ccc` (test)
2. **Task 1 (GREEN): ErrorFixer and LLM-augmented refinement loop** - `a5e8c4c` (feat)

## Files Created/Modified
- `src/kicad_agent/llm/error_fixer.py` - ErrorFixer class, FixResult dataclass, FIX_TOOL/FIX_SYSTEM_PROMPT definitions
- `src/kicad_agent/llm/refinement.py` - llm_refine_design function, LLMRefinementResult/LLMRefinementIteration dataclasses
- `tests/test_llm_error_fixer.py` - 8 tests for ErrorFixer (mock LLM, FixResult, iteration history, schema validation)
- `tests/test_llm_refinement.py` - 10 tests for refinement loop (deterministic-only, LLM trigger, stagnation, hard cap, history)
- `src/kicad_agent/llm/__init__.py` - Added barrel exports for ErrorFixer, FixResult, llm_refine_design, LLMRefinementResult, LLMRefinementIteration

## Decisions Made
- Deterministic fixes run first as fast/free/reliable first pass; LLM only handles what code cannot
- Prompt caching on system prompt since FIX_TOOL contains ~51KB operation schema
- Stagnation threshold of 3 (not 2) gives LLM enough room to try different approaches
- Operation execution via _execute_operation validates with Operation.model_validate() (T-15-10)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test assertion for convergence iteration count**
- **Found during:** Task 1 GREEN phase (test_converges_when_erc_passes)
- **Issue:** Test expected total_iterations == 1 but loop runs ERC at start of each iteration, so convergence happens on iteration 2 (iter 1: fail+fix, iter 2: pass+converge)
- **Fix:** Updated test assertion to total_iterations == 2 with explanatory comment
- **Files modified:** tests/test_llm_refinement.py
- **Verification:** All 21 tests pass
- **Committed in:** a5e8c4c (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Test expectation was incorrect; implementation behavior is correct. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ErrorFixer and llm_refine_design ready for integration into the generation pipeline
- Plan 15-04 can wire these into the full generation workflow
- LLM refinement loop depends on ErrorFixer injection for testability

---
*Phase: 15-ai-generation-wiring*
*Completed: 2026-05-24*

## Self-Check: PASSED

All 4 created files exist. Both TDD commits (4f73ccc RED, a5e8c4c GREEN) found in git log.
