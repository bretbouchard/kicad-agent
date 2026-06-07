---
phase: 79-gap-analysis-smarter-faster-better
plan: 05
subsystem: inference, training
tags: [threadpoolexecutor, confidence-scoring, real-world-data, inference, best-of-n]

# Dependency graph
requires:
  - phase: 13
    provides: "RealBoardDataset with JSONL serialization for real-world PCB data"
  - phase: 78
    provides: "Cleaned training pipeline (supervised, not circular GRPO)"
provides:
  - "Parallel chain generation via ThreadPoolExecutor in InferenceWrapper"
  - "InferenceConfidence scoring for all AI inference outputs"
  - "TrainingPipelineConfig.real_data_dir for Phase 13 data integration"
  - "LocalLLMClient.unload_model() for memory management"
affects: [inference, training, llm]

# Tech tracking
tech-stack:
  added: []
  patterns: ["ThreadPoolExecutor for concurrent inference", "frozen dataclass for confidence metrics", "TYPE_CHECKING guard for optional type hints"]

key-files:
  created:
    - src/kicad_agent/inference/confidence_scorer.py
    - tests/test_inference_parallel.py
    - tests/test_inference_confidence.py
    - tests/test_training_realworld_mix.py
  modified:
    - src/kicad_agent/inference/wrapper.py
    - src/kicad_agent/inference/best_of_n.py
    - src/kicad_agent/inference/__init__.py
    - src/kicad_agent/llm/local_client.py
    - src/kicad_agent/training/pipeline.py

key-decisions:
  - "ThreadPoolExecutor instead of asyncio for simplicity -- model inference is sync, threads share read-only weights"
  - "Confidence scorer is advisory (T-79-03 accept) -- low confidence does not block output"
  - "real_data_dir supplements synthetic data, does not replace it"
  - "max_workers capped at min(n_best, 4) to prevent unbounded thread creation (T-79-04)"
  - "TYPE_CHECKING guard on InferenceConfidence import in best_of_n.py to avoid circular imports"

patterns-established:
  - "Pattern: Concurrent inference with ThreadPoolExecutor, bounded workers, read-only shared weights"
  - "Pattern: Advisory confidence metrics as frozen dataclass attached to result objects"

requirements-completed: [AI-01]

# Metrics
started: 2026-06-07T22:33:34Z
completed: 2026-06-07T22:42:00Z
duration: 9m
duration_minutes: 9
commits: 2
files_modified: 9
---

# Phase 79 Plan 05: Parallel Inference, Confidence Scoring, Real-World Data Summary

**ThreadPoolExecutor parallel chain generation, InferenceConfidence advisory scoring, and Phase 13 real-world PCB data integration into training pipeline**

## Performance

- **Duration:** 9m
- **Started:** 2026-06-07T22:33:34Z
- **Completed:** 2026-06-07T22:42:00Z
- **Tasks:** 2
- **Commits:** 2 (atomic task commits)
- **Files modified:** 9

## Accomplishments
- InferenceWrapper.analyze() generates N chains concurrently via ThreadPoolExecutor (was sequential for-loop)
- InferenceConfidence dataclass quantifies chain agreement and variance for all inference outputs
- TrainingPipelineConfig.real_data_dir loads Phase 13 GitHub crawler output (train.jsonl) into training
- LocalLLMClient.unload_model() enables memory management without process restart
- ScoredChain.confidence field provides uncertainty quantification to consumers
- 16 new tests across 3 test files, 30 total with existing wrapper tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Parallel chain generation in InferenceWrapper** - `59fd814` (test)
2. **Task 2: Confidence scoring and real-world training data integration** - `6196e0c` (feat)

_Note: TDD tasks combined RED+GREEN into single commits per task_

## Files Created/Modified
- `src/kicad_agent/inference/confidence_scorer.py` - InferenceConfidence dataclass and compute_confidence() function
- `src/kicad_agent/inference/wrapper.py` - ThreadPoolExecutor parallel generation, confidence wiring in analyze()
- `src/kicad_agent/inference/best_of_n.py` - Added confidence field to ScoredChain (TYPE_CHECKING guard)
- `src/kicad_agent/inference/__init__.py` - Exported InferenceConfidence and compute_confidence
- `src/kicad_agent/llm/local_client.py` - Added unload_model() method for memory management
- `src/kicad_agent/training/pipeline.py` - Added real_data_dir to config, loads RealBoardDataset from train.jsonl
- `tests/test_inference_parallel.py` - 9 tests for parallel inference, thread safety, unload_model
- `tests/test_inference_confidence.py` - 7 tests for confidence scoring and ScoredChain integration
- `tests/test_training_realworld_mix.py` - 7 tests for real-world data loading and mixed training

## Decisions Made
- ThreadPoolExecutor chosen over asyncio: inference is synchronous, threads naturally share read-only model weights with per-thread activations
- Confidence metrics are advisory (threat T-79-03 accepted): low confidence logs warning but does not block output
- max_workers capped at min(n_best, 4): prevents unbounded thread creation while utilizing parallelism
- real_data_dir supplements synthetic maze data without replacing it: synthetic data provides controlled difficulty, real-world provides diversity

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed duplicate `from __future__ import annotations` in best_of_n.py**
- **Found during:** Task 2 (adding confidence field to ScoredChain)
- **Issue:** Edit prepended new imports but kept old ones, creating duplicate `from __future__` and duplicate imports
- **Fix:** Rewrote best_of_n.py with correct single import block using TYPE_CHECKING guard
- **Files modified:** src/kicad_agent/inference/best_of_n.py
- **Verification:** All 30 tests pass, no SyntaxError

**2. [Rule 1 - Bug] Fixed predict_reward mock not caught by new confidence scoring code**
- **Found during:** Task 2 (regression in test_inference_parallel.py)
- **Issue:** New confidence scoring in wrapper.py imports predict_reward directly, bypassing patch on best_of_n module
- **Fix:** Added `patch("kicad_agent.training.reward_model.predict_reward")` to all Task 1 tests that call analyze()
- **Files modified:** tests/test_inference_parallel.py
- **Verification:** All 30 tests pass with both patches

**3. [Rule 1 - Bug] Fixed score_idx out-of-range in test_best_of_n_returns_highest_score**
- **Found during:** Task 2 (regression from double predict_reward calls)
- **Issue:** predict_reward now called twice per chain (confidence + best_of_n), exhausting the sequential score list
- **Fix:** Changed to modular indexing (`score_idx[0] % len(scores)`) for consistent per-chain scoring
- **Files modified:** tests/test_inference_parallel.py
- **Verification:** All 30 tests pass

---

**Total deviations:** 3 auto-fixed (all Rule 1 - bugs)
**Impact on plan:** All auto-fixes necessary for correctness. No scope creep.

## Issues Encountered
- None beyond the auto-fixed issues above

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Parallel inference infrastructure ready for scale testing with real models
- Confidence scoring provides foundation for adaptive inference (retry on low confidence)
- Real-world data pipeline fully wired -- Phase 13 output flows directly into training
- No base model upgrade performed (per plan requirements)

## Self-Check: PASSED

All 10 files verified present. Both commits (59fd814, 6196e0c) verified in git log. All 30 tests pass (23 new + 7 existing inference wrapper). Zero regressions in training tests (54 passed).

---
*Phase: 79-gap-analysis-smarter-faster-better*
*Completed: 2026-06-07*
