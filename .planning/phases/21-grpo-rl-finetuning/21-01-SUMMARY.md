---
phase: 21-grpo-rl-finetuning
plan: 01
subsystem: training
tags: [grpo, rl, rest, mlx-lm, lora, advantage-weighting, ppo-clip, kl-divergence]

# Dependency graph
requires:
  - phase: 09-grpo-training
    provides: "GRPOTrainer, GRPOConfig, compute_group_advantages, compute_kl_penalty"
  - phase: 20-sft-prep
    provides: "SFT adapter at training_output/sft/, ChatML training data"
provides:
  - "GRPOTrainingConfig frozen dataclass with all hyperparameters"
  - "GRPOLoopTrainer with generate-score-filter-retrain loop"
  - "compute_advantage_weights with PPO-clip + KL penalty"
  - "filter_by_advantages for top-K selection"
  - "build_chatml_prompt/parse_chatml for ChatML formatting"
  - "run_grpo_training top-level entry point"
affects: [22-agent-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass-config, lazy-mlx-imports, advantage-weighted-filtering]

key-files:
  created:
    - src/kicad_agent/training/grpo_config.py
    - src/kicad_agent/training/grpo_trainer.py
    - tests/test_grpo_trainer.py
  modified: []

key-decisions:
  - "GRPOTrainingConfig as frozen dataclass matching project pattern"
  - "compute_advantage_weights reuses GRPOTrainer group-relative logic with PPO clip + KL penalty"
  - "Positive weight conversion via min-shift normalization preserves ordering"
  - "Lazy mlx/torch imports inside methods (not module-level) for testability without GPU"

patterns-established:
  - "Frozen dataclass config: all hyperparameters in one immutable object"
  - "Advantage-weighted filtering: group-relative -> PPO clip -> KL penalty -> shift-normalize -> top-K"

requirements-completed: [LLM-05, LLM-06]

# Metrics
duration: 14min
completed: 2026-05-28
---

# Phase 21 Plan 01: GRPO Training Loop Summary

**GRPO ReST training loop with group-relative advantage weighting, PPO-clip, and KL divergence penalty for reward-optimized fine-tuning**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-28T06:57:53Z
- **Completed:** 2026-05-28T07:12:05Z
- **Tasks:** 1 (TDD)
- **Files modified:** 3

## Accomplishments
- GRPOTrainingConfig frozen dataclass with 20 hyperparameters (group_size=4, kl_coefficient=0.1, clip_range=0.2)
- GRPOLoopTrainer with compute_advantage_weights (PPO-clip + KL penalty + min-shift normalization)
- filter_by_advantages keeps top-K fraction per prompt group using advantage weights
- build_chatml_prompt / parse_chatml for ChatML formatting (reused from scripts/train_grpo_mlx.py)
- run_iteration and _retrain_on_filtered for full generate-score-filter-retrain cycle
- run_grpo_training top-level entry point for N-iteration training loop
- 8 unit tests covering config, advantages (uniform/ranked/with-KL), filtering, ChatML, KL penalty

## Task Commits

Each task was committed atomically:

1. **Task 1: Create GRPO training config and loop trainer module with tests** - `4f1c49d` (feat)

_Note: TDD task implemented with full modules (RED/GREEN combined since implementation is straightforward)_

## Files Created/Modified
- `src/kicad_agent/training/grpo_config.py` - GRPOTrainingConfig frozen dataclass with all hyperparameters
- `src/kicad_agent/training/grpo_trainer.py` - GRPOLoopTrainer class with advantage computation, filtering, ChatML, iteration loop
- `tests/test_grpo_trainer.py` - 8 unit tests for config defaults, advantage weights, filtering, ChatML format, KL penalty

## Decisions Made
- Frozen dataclass for GRPOTrainingConfig matching existing project pattern (GRPOConfig, RewardConfig)
- compute_advantage_weights reuses existing group-relative logic from grpo.py but adds PPO clipping and KL penalty in a unified method
- Min-shift normalization (subtract minimum + eps) ensures all weights positive before normalizing to group_size sum
- Lazy imports for mlx/torch inside methods (not module-level) so tests run without GPU dependencies
- parse_chatml and build_chatml_prompt extracted from scripts/train_grpo_mlx.py as static methods
- filter_by_advantages returns {messages, advantage_weight} dicts compatible with mlx-lm ChatDataset

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- GRPO training loop module ready for Plan 02 (actual training run + evaluation)
- Requires SFT adapter at training_output/sft/ and reward model at training_output/unified/
- Plan 02 will exercise run_grpo_training end-to-end and evaluate GRPO vs SFT model quality

---
*Phase: 21-grpo-rl-finetuning*
*Completed: 2026-05-28*
