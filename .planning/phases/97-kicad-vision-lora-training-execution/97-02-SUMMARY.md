---
phase: 97-kicad-vision-lora-training-execution
plan: 02
subsystem: training
tags: [vastai, lora, gemma-4, cuda, sft, peft, bitsandbytes]

# Dependency graph
requires:
  - phase: 97-01
    provides: unified KiCad vision dataset (maze + PCB analysis)
provides:
  - scripts/vast_train_kicad.py — CUDA LoRA training script for Gemma 4 12B
  - scripts/vast_launch_kicad.sh — Vast.ai instance launch and training orchestration
  - tests/test_vast_train_kicad.py — 14 config validation tests
affects: [97-03, 97-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [copy-adapt-config-only, scp-dataset-upload, env-var-credentials]

key-files:
  created:
    - scripts/vast_train_kicad.py
    - scripts/vast_launch_kicad.sh
    - tests/test_vast_train_kicad.py
  modified: []

key-decisions:
  - "max_seq_length increased to 4096 (from 2048) because KiCad exploration chains can exceed 3000 characters"
  - "Dataset transfer via SCP upload instead of Kaggle API — KiCad dataset is local, not on Kaggle"
  - "Disk allocation increased to 50GB (from 40GB) for larger unified vision dataset"

patterns-established:
  - "Copy-adapt pattern: copy spectral-primitives scripts, change only config values, preserve all proven code"
  - "SCP-based dataset transfer for Vast.ai training (replaces Kaggle download)"

requirements-completed: [D-06, D-07, D-08, D-09, D-10, D-11, D-12]

# Metrics
started: 2026-06-19T06:08:22Z
completed: 2026-06-19T06:12:11Z
duration: 3m
duration_minutes: 3
commits: 3
files_modified: 3
---

# Phase 97 Plan 02: Vast.ai Training Scripts Summary

**Adapted spectral-primitives Vast.ai LoRA training scripts for KiCad vision — Gemma 4 12B with rank-16 LoRA, 4-bit quantization, and SCP-based dataset upload**

## Performance

- **Duration:** 3m
- **Started:** 2026-06-19T06:08:22Z
- **Completed:** 2026-06-19T06:12:11Z
- **Tasks:** 3
- **Commits:** 3 (atomic task commits)
- **Files modified:** 3

## Accomplishments
- Created `vast_train_kicad.py` — CUDA LoRA training script preserving all battle-tested spectral-primitives classes (HeartbeatCallback, Gemma4VisionCollator, dequantize_vision_encoder) with KiCad-specific config
- Created `vast_launch_kicad.sh` — Vast.ai orchestration script with SCP dataset upload, KiCad-labeled instances, and increased disk allocation
- 14 config validation tests confirming all proven code preserved and KiCad config values correct

## Task Commits

Each task was committed atomically:

1. **Task 1: Create vast_train_kicad.py** - `6d1e812` (feat)
2. **Task 2: Create vast_launch_kicad.sh** - `3a81244` (feat)
3. **Task 3: Config validation tests** - `4ca55fd` (test)

## Files Created/Modified
- `scripts/vast_train_kicad.py` - Gemma 4 12B LoRA training script (361 lines) adapted from spectral-primitives with 5 targeted changes
- `scripts/vast_launch_kicad.sh` - Vast.ai launch script (190 lines) with KiCad-specific config, SCP dataset upload, no hardcoded credentials
- `tests/test_vast_train_kicad.py` - 14 tests validating script syntax, proven classes, config values, and security

## Decisions Made
- max_seq_length 4096 (from 2048): KiCad exploration chains can exceed 3000 characters, per RESEARCH.md Open Question 3
- SCP dataset upload (instead of Kaggle): KiCad unified vision dataset is built locally, not hosted on Kaggle
- Disk 50GB (from 40GB): Larger unified dataset (maze + PCB) needs more space, per RESEARCH.md Pitfall 4
- All spectral-primitives proven code preserved unchanged: minimizes risk by changing config, not code

## Deviations from Plan

None - plan executed exactly as written. All 3 tasks completed with no auto-fixes needed.

## Issues Encountered

- Worktree branch base was from an older commit (c8fd467 instead of 28d2a02). The safety-net hook blocked `git reset --hard`, but since no conflicting files existed at the branch point, all new files were created cleanly without interference.

## User Setup Required

None - no external service configuration required. To use the scripts:
1. Set `HF_TOKEN` environment variable for gated Gemma 4 access
2. Ensure vastai CLI installed (`pip install vastai`)
3. Ensure unified vision dataset exists at `training_output/unified_vision_data/`

## Next Phase Readiness
- Training scripts ready for Vast.ai execution
- 97-03 (data preparation pipeline) and 97-04 (training execution) can proceed
- No blockers or concerns

## Self-Check: PASSED

---
*Phase: 97-kicad-vision-lora-training-execution*
*Completed: 2026-06-19*
