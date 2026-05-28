---
phase: 22-agent-integration-evaluation
plan: 01
subsystem: inference
tags: [mlx-lm, grpo, reward-model, best-of-n, cli, pcb-analysis]

# Dependency graph
requires:
  - phase: 21
    provides: GRPO training pipeline, reward model, LocalLLMClient
provides:
  - InferenceWrapper with analyze() method for GRPO model chain generation
  - best_of_n_select() for reward-model-scored chain selection
  - generate_analysis() one-shot Python API
  - CLI analyze subcommand with --n-best, --reward-model, --verbose flags
  - ScoredChain frozen dataclass for typed chain results
affects: [cli, inference, evaluation]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass-results, lazy-model-loading, best-of-n-selection]

key-files:
  created:
    - src/kicad_agent/inference/__init__.py
    - src/kicad_agent/inference/wrapper.py
    - src/kicad_agent/inference/best_of_n.py
    - tests/test_inference_wrapper.py
    - tests/test_best_of_n.py
  modified:
    - src/kicad_agent/cli.py
    - tests/test_cli.py

key-decisions:
  - "InferenceWrapper accesses ParseResult.kiutils_obj.footprints (not .modules) for correct kiutils Board attribute"
  - "Board stats extraction delegated to InferenceWrapper._extract_board_stats() shared by CLI and Python API"
  - "Chains generated sequentially (not batched) to limit MPS peak memory per T-22-04"
  - "n_best capped at 16 to prevent DoS per T-22-02"

patterns-established:
  - "InferenceWrapper: lazy-load LLM client and reward model on first use"
  - "best_of_n_select: score all chains with predict_reward, return highest composite"
  - "CLI analyze: delegate to generate_analysis() with argparse flag passthrough"

requirements-completed: [LLM-09, LLM-10, LLM-11]

# Metrics
duration: 12min
completed: 2026-05-28
---

# Phase 22 Plan 01: Inference Wrapper Summary

**InferenceWrapper with best-of-N chain selection scored by reward model, wired to CLI analyze subcommand and Python API**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-28T07:56:28Z
- **Completed:** 2026-05-28T08:08:35Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- InferenceWrapper loads GRPO model via LocalLLMClient and reward model via RewardModel.load_trained()
- best_of_n_select() scores N chains with predict_reward() and returns highest composite
- generate_analysis(pcb_path) one-shot API returning ScoredChain with scores and timing
- CLI analyze subcommand enhanced with --n-best, --reward-model, and --verbose flags
- 27 tests passing (8 best_of_n + 7 inference_wrapper + 4 analyze + 8 existing CLI)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create inference module with InferenceWrapper, best-of-N selector, and generate_analysis API** - `252fb3b` (feat)
2. **Task 2: Enhance CLI analyze subcommand to use generate_analysis with best-of-N and add --n-best flag** - `bd0cd43` (feat)

## Files Created/Modified
- `src/kicad_agent/inference/__init__.py` - Public API exports (InferenceWrapper, generate_analysis, ScoredChain, best_of_n_select)
- `src/kicad_agent/inference/wrapper.py` - InferenceWrapper class with analyze(), BoardStats, generate_analysis()
- `src/kicad_agent/inference/best_of_n.py` - ScoredChain frozen dataclass, best_of_n_select() with reward model scoring
- `tests/test_inference_wrapper.py` - 7 tests for InferenceWrapper (board stats, prompts, generate_analysis)
- `tests/test_best_of_n.py` - 8 tests for best_of_n (immutability, selection, scoring, improvement)
- `src/kicad_agent/cli.py` - Enhanced _handle_analyze() with generate_analysis(), --n-best, --reward-model, --verbose
- `tests/test_cli.py` - 4 new analyze tests (subcommand, n-best, missing file, verbose)

## Decisions Made
- Used `ParseResult.kiutils_obj.footprints` (not `.modules`) for correct kiutils Board attribute access
- Board stats extraction delegated to shared `_extract_board_stats()` static method used by both CLI and Python API
- Chains generated sequentially to limit MPS peak memory (threat T-22-04)
- n_best capped at 16 to prevent DoS (threat T-22-02)
- CLI analyze uses `_extract_board_stats()` for display header then delegates to `generate_analysis()` for full pipeline

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ParseResult attribute access in InferenceWrapper**
- **Found during:** Task 1 (inference module creation)
- **Issue:** Plan referenced `pcb.modules` but parse_pcb returns ParseResult wrapping a kiutils Board with `footprints` attribute
- **Fix:** Changed to `result.kiutils_obj.footprints` and `result.kiutils_obj.nets` for correct access pattern
- **Files modified:** src/kicad_agent/inference/wrapper.py
- **Verification:** Tests pass with mocked ParseResult wrapper
- **Committed in:** 252fb3b (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed CLI test mocking approach for analyze subcommand**
- **Found during:** Task 2 (CLI enhancement)
- **Issue:** Initial tests tried subprocess invocation with in-process mocking (mock doesn't cross process boundaries) and patched lazy import at wrong path
- **Fix:** Changed to in-process `main()` calls and patched `kicad_agent.inference.wrapper.generate_analysis` at source module
- **Files modified:** tests/test_cli.py
- **Verification:** All 12 CLI tests pass including 4 new analyze tests
- **Committed in:** bd0cd43 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes necessary for correctness and testability. No scope creep.

## Issues Encountered
- None beyond the auto-fixed deviations above

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Inference module complete, ready for end-to-end evaluation (plan 22-02)
- generate_analysis() and CLI analyze available for integration testing with real model artifacts
- All interfaces are mockable for testing without GPU/model artifacts

---
*Phase: 22-agent-integration-evaluation*
*Completed: 2026-05-28*
