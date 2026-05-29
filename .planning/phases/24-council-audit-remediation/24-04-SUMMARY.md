---
phase: 24-council-audit-remediation
plan: 04
subsystem: training, ops, serializer
tags: [integrity, testing, security, training-pipeline]
dependency_graph:
  requires: [24-03]
  provides: [training-integrity-fixes, core-ops-tests, serializer-tests, e2e-tests]
  affects: [training, inference, ops, serializer, handler]
tech_stack:
  added: [union-find for net propagation]
  patterns: [transaction-rollback-e2e, advantage-clipping-GRPO]
key_files:
  created:
    - tests/test_training_integrity.py
    - tests/test_executor_ops.py
    - tests/test_serializer.py
    - tests/test_e2e_pipeline.py
  modified:
    - src/kicad_agent/inference/best_of_n.py
    - src/kicad_agent/training/evaluation.py
    - src/kicad_agent/training/grpo.py
    - src/kicad_agent/training/grpo_trainer.py
    - src/kicad_agent/training/reward_model.py
    - src/kicad_agent/training/sft/templates.py
    - src/kicad_agent/training/sft/trainer.py
    - src/kicad_agent/ops/repair.py
    - src/kicad_agent/handler.py
    - tests/test_best_of_n.py
decisions:
  - "Kept both GRPO implementations (grpo.py and grpo_trainer.py) since both serve different purposes and are imported by active code"
  - "Kept compute_kl_penalty methods in both GRPO files since they are tested utilities even if not called in the training loop"
  - "Used union-find algorithm for wire-connected short detection in repair.py"
  - "Added catch-all Exception handler in handler.py to properly return OperationError for custom operation exceptions"
metrics:
  duration_minutes: 32
  completed_date: 2026-05-29
  test_count: 1567
  test_delta: +33
  files_created: 4
  files_modified: 10
---

# Phase 24 Plan 04: Training Pipeline Integrity + Test Coverage Summary

Fixed training pipeline integrity issues and added comprehensive test coverage for core operations.

## What Changed

### Task 1: Training Pipeline Integrity (commit 6d6e218)

- **best_of_n.py**: Raises `ValueError` when `reward_model=None` instead of returning fake 0.5 scores
- **reward_model.py**: Added validation loss computation during training when `val_texts`/`val_labels` are provided, with per-epoch logging
- **sft/trainer.py**: Uses `torch.float32` on MPS device (prevents NaN losses from float16)
- **grpo.py**: Removed per-step RNG reset in `train_step` -- uses `random.Random()` without fixed seed for exploration diversity
- **sft/templates.py**: Implemented task-based template selection (routing, placement, clearance, spatial_reasoning) instead of always returning "spatial_reasoning"
- **grpo_trainer.py**: Fixed docstring to clarify "advantage clipping" (GRPO variant) not "PPO ratio clipping"
- **evaluation.py**: Removed `run_ablation` stub that was identical to `run_baseline`
- **test_training_integrity.py**: 12 new tests covering all integrity fixes

### Task 2: Dead Repair Code and Test Coverage (commit 2b2ecdd)

- **repair.py**: Replaced dead net-short detection loop (body was `pass`) with union-find based wire-connected short detection that finds shorts across wire-connected labels, not just co-located labels
- **handler.py**: Added catch-all `Exception` handler for custom operation errors (e.g., `MoveComponentError`) that were escaping the error handling chain
- **test_executor_ops.py**: 8 tests for core schematic ops (add_wire, add_label, add_power, add_no_connect, add_junction) plus error cases
- **test_serializer.py**: 7 tests for schematic serializer, normalizer (scientific notation, quoted strings, tabs), and round-trip consistency
- **test_e2e_pipeline.py**: 6 end-to-end integration tests validating JSON intent -> executor -> IR mutation -> serialize -> file output, including transaction rollback

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Handler did not catch custom operation exceptions**
- **Found during:** Task 2 (e2e transaction rollback test)
- **Issue:** `MoveComponentError` inherits from `Exception` directly, not caught by the existing `(RuntimeError, OSError, KeyError)` tuple
- **Fix:** Added catch-all `Exception` handler after the specific exception handlers
- **Files modified:** src/kicad_agent/handler.py
- **Commit:** 2b2ecdd

### Plan Interpretation Notes

**GRPO consolidation decision:** The plan directed removal of the "dead" GRPO implementation. Analysis revealed both `grpo.py` (low-level PyTorch) and `grpo_trainer.py` (high-level ReST/MLX) are actively imported by production code and tests. Neither is dead. Kept both.

**KL divergence methods kept:** `compute_kl_penalty()` exists in both GRPO files and is tested but not called in the training loop (KL is hardcoded to 0.0 in supervised mode). Kept as tested utility methods since removing them would break existing tests without any benefit.

**Circular evaluation:** Pipeline already had `dataset.split()` producing train/val/test sets. No fix needed -- the existing implementation correctly uses separate splits.

**Pipeline.py grpo_config field:** The `TrainingPipelineConfig` still has a `grpo_config` attribute in its docstring but no longer in its fields (removed in prior phase). This is a doc-only issue tracked as out of scope.

## Test Results

- **Before:** 1534 passed, 1 skipped
- **After:** 1567 passed, 1 skipped
- **New tests:** +33 (12 training integrity + 8 executor ops + 7 serializer + 6 e2e)

## Self-Check: PASSED

- tests/test_training_integrity.py -- FOUND
- tests/test_executor_ops.py -- FOUND
- tests/test_serializer.py -- FOUND
- tests/test_e2e_pipeline.py -- FOUND
- 24-04-SUMMARY.md -- FOUND
- Commit 6d6e218 (Task 1) -- FOUND
- Commit 2b2ecdd (Task 2) -- FOUND
