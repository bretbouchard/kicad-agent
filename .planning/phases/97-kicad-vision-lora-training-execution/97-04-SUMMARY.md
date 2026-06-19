---
phase: 97-kicad-vision-lora-training-execution
plan: 04
subsystem: training
tags: [mlx-vlm, verification, adapter, inference, cross-platform, peft]

# Dependency graph
requires:
  - phase: 97-01
    provides: maze vision dataset (rendered PNGs + chains)
  - phase: 97-02
    provides: Vast.ai training scripts (vast_train_kicad.py, vast_launch_kicad.sh)
  - phase: 97-03
    provides: unified dataset merge + adapter metadata registry
provides:
  - scripts/verify_adapter.py — CLI to verify trained adapter loads locally via mlx-vlm
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [cli-verification-wrapper, mlx-vlm-inference, cross-platform-peft]

key-files:
  created:
    - scripts/verify_adapter.py
  modified: []

key-decisions:
  - "Used spectral-primitives venv as fallback for mlx-vlm import (not in project venv)"
  - "No InferenceWrapper modification — D-18 explicitly deferred to future phase"

patterns-established:
  - "CLI verification script pattern: argparse + path validation + load + generate + quality check"

requirements-completed: [D-16, D-17]

# Metrics
started: 2026-06-19T06:30:00Z
completed: 2026-06-19T06:32:00Z
duration: 2m
duration_minutes: 2
commits: 1
files_modified: 1
---

# Phase 97 Plan 04: Adapter Verification Summary

**Created verify_adapter.py CLI script for cross-platform LoRA adapter verification via mlx-vlm on Apple Silicon**

## Performance

- **Duration:** 2m
- **Tasks:** 1 (Task 2 is human checkpoint)
- **Commits:** 1
- **Files modified:** 1

## Accomplishments

- Created `verify_adapter.py` — CLI wrapper that loads trained adapter via `mlx_vlm.load()` with `adapter_path`, runs inference with `mlx_vlm.generate()`, and reports quality indicators
- All 8 acceptance criteria pass (def main, adapter-path, test-image, adapter_path=str, mlx_vlm import, sys.path.insert, no InferenceWrapper, --help exits 0)
- No InferenceWrapper modification (D-18 compliance)

## Task Commits

1. **Task 1: Create verify_adapter.py** - `5d89ff0` (feat)

## Checkpoint: Full Pipeline Execution

Task 2 requires human execution of the full training pipeline:
1. Maze vision conversion (local, ~30-60 min for test)
2. Full maze conversion (~2-4 hours)
3. Dataset merge (~142K samples)
4. Vast.ai training (requires credits + HF_TOKEN, ~$0.20-0.55)
5. Adapter download + local mlx-vlm verification
6. Training metadata via AdapterRegistry

**Status:** Awaiting human execution.

## Deviations from Plan

None — plan executed as specified.

## User Setup Required

For full pipeline execution:
1. HF_TOKEN environment variable (HuggingFace gated Gemma 4 access)
2. VAST_API_KEY environment variable (Vast.ai account)
3. $5+ Vast.ai balance
4. spectral-primitives venv for mlx-vlm: `/Users/bretbouchard/apps/spectral-primitives/.venv-brew/bin/python3`

## Next Phase Readiness

All code artifacts are complete. Full pipeline requires human execution of training on remote GPU.

## Self-Check: PASSED

---
*Phase: 97-kicad-vision-lora-training-execution*
*Completed: 2026-06-19*
