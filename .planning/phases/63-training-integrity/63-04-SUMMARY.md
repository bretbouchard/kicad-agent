---
phase: 63-training-integrity
plan: 04
subsystem: training
tags: [reward-model, scoring, self-reference, independent, best-of-n]

# Dependency graph
requires: []
provides:
  - Independent heuristic scoring function (_independent_score)
  - generate() method using deterministic heuristics instead of self-evaluation
  - Optional reference_model parameter for external neural scoring
affects: [training, reward-model, grpo]

# Tech tracking
tech-stack:
  added: []
  patterns: ["independent scoring heuristic", "no self-reference in best-of-N"]

key-files:
  created: []
  modified: [src/kicad_agent/training/reward_model.py, tests/test_phase63_training.py]

key-decisions:
  - "Independent scoring uses format validation + step count (no model dependency)"
  - "reference_model parameter allows optional external neural scoring when available"
  - "50/50 blend of heuristic + neural when reference model provided"

requirements-completed: []

# Metrics
started: 2026-06-01T00:00:00Z
completed: 2026-06-01T00:00:00Z
duration: <1m
duration_minutes: 0
commits: 1
files_modified: 2
---

# Phase 63 Plan 04: Fix Self-Referential Best-of-N Summary

**Independent heuristic scoring in best-of-N selection eliminates self-referential reward hacking, with optional external reference model**

## Performance

- **Duration:** <1m (part of single Phase 63 commit)
- **Started:** 2026-06-01T00:00:00Z
- **Completed:** 2026-06-01T00:00:00Z
- **Tasks:** 1
- **Commits:** 1 (atomic commit)
- **Files modified:** 2

## Accomplishments
- `_independent_score()` function uses deterministic heuristics: format validation (section header detection) + step count depth (capped at 8 steps)
- `RewardModel.generate()` no longer calls `predict_reward(self, ...)` for scoring
- Optional `reference_model` parameter for external neural scoring with 50/50 blend when provided
- 5 regex patterns for section detection: Observation, Reasoning, coordinate, Conclusion, Step

## Task Commits

1. **Task 1: Independent scoring for best-of-N** - `a13438b` (feat)

## Files Created/Modified
- `src/kicad_agent/training/reward_model.py` - Added `_independent_score()` function with format + depth scoring; rewrote `generate()` to use independent scoring with optional reference model blending
- `tests/test_phase63_training.py` - Added `TestIndependentScore` class (8 tests) and `TestRewardModelGenerate` class (4 tests)

## Decisions Made
- Independent scoring avoids circular dependency: model trains on scores it cannot manipulate
- Heuristic scoring based on chain structure (section headers + step count) is deterministic and model-free
- When reference model is provided, 50/50 blend balances heuristic stability with neural precision
- Score range [0.0, 1.0] with format (0-1) and depth (0-1) averaged

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Best-of-N scoring is now independent and safe from reward hacking
- All 4 plans complete; Phase 63 is fully done

---
*Phase: 63-training-integrity*
*Completed: 2026-06-01*
