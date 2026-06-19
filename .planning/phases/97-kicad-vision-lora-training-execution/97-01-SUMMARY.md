---
phase: 97-kicad-vision-lora-training-execution
plan: 01
subsystem: training
tags: [maze-vision, huggingface, matplotlib, lo-ra-training, dataset-conversion]

# Dependency graph
requires:
  - phase: 97-research
    provides: maze_samples_100k.jsonl schema, chains_100k.jsonl schema, rendering code examples
provides:
  - maze_vision_converter.py: joins chains with maze_samples by sample_id, renders maze grids as PNGs, outputs HuggingFace vision format
  - convert_maze_vision.py: CLI wrapper for batch conversion
  - Test suite: 10 unit tests with synthetic fixtures
affects: [97-02, 97-03, 97-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Maze vision converter follows vision_data_builder.py structure (D-20 analog pattern)"
    - "matplotlib Agg backend with plt.close(fig) per render to prevent memory leak"
    - "buffer_rgba() over deprecated tostring_rgb() for matplotlib 3.8+ compatibility"
    - "HuggingFace Dataset save with JSONL fallback for environments without datasets lib"

key-files:
  created:
    - src/kicad_agent/training/maze_vision_converter.py
    - tests/test_maze_vision_converter.py
    - scripts/convert_maze_vision.py
  modified: []

key-decisions:
  - "Used buffer_rgba() instead of tostring_rgb() to avoid matplotlib 3.10 deprecation"
  - "Streamed chains file instead of loading all into memory (T-97-02 DoS mitigation)"
  - "Vision messages format matches PCB vision schema exactly for dataset merge compatibility"

patterns-established:
  - "Pattern: JSONL streaming with sample_id lookup for cross-file joins"
  - "Pattern: Guarded HuggingFace import with JSONL fallback"

requirements-completed: [D-02, D-04, D-05, D-20]

# Metrics
started: 2026-06-19T06:08:04Z
completed: 2026-06-19T06:14:42Z
duration: 6m
duration_minutes: 6
commits: 2
files_modified: 3
---

# Phase 97 Plan 01: Maze Vision Converter Summary

**One-liner:** Maze chain-to-vision converter that joins 200K chains with maze samples by sample_id, renders grids as 1024x768 PNGs via matplotlib, filters to is_correct=True, and outputs HuggingFace vision dataset format matching the existing PCB vision schema.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Maze vision converter module with grid rendering and chain joining | 5bba826 | `src/kicad_agent/training/maze_vision_converter.py`, `tests/test_maze_vision_converter.py` |
| 2 | CLI wrapper for maze vision conversion | 8e25b29 | `scripts/convert_maze_vision.py` |

## What Was Built

### maze_vision_converter.py (317 lines)

Core module implementing the maze chain to vision format conversion pipeline:

- **`build_maze_vision_dataset()`**: Main entry point. Streams chains JSONL, builds maze_samples lookup by sample_id, filters `is_correct=True` + non-empty `chain_text`, renders PNG images, outputs HuggingFace Dataset (with JSONL fallback).
- **`_load_maze_samples_index()`**: Streams JSONL, builds `{sample_id: sample_dict}` lookup for O(1) join.
- **`_reconstruct_grid()`**: Boolean grid from board dimensions and obstacle positions (chains.py pattern).
- **`_render_maze_grid()`**: matplotlib Agg renderer producing 1024x768 RGB PNGs with green source, red target, blue solution path, dark gray obstacles.
- **`_create_vision_messages()`**: PCB-vision-schema-compatible message format (image + text multimodal).
- **`_row_to_hf_format()`**: HuggingFace row with keys `images`, `messages`, `task_type`, `source_file`.
- **`_save_dataset()`**: HuggingFace Dataset.from_list() with Sequence(HFImage()) cast, JSONL fallback.

### convert_maze_vision.py (69 lines)

CLI wrapper following `train_kicad_vision.py` pattern:

- `--chains-file` (required): Path to chains_100k.jsonl
- `--maze-samples-file` (required): Path to maze_samples_100k.jsonl
- `--output-dir`: Output directory (default: `training_output/maze_vision_data`)
- `--max-samples`: Limit conversion count (None = all)
- Validates input file existence before conversion

### Test Suite (10 tests)

All 10 unit tests pass with synthetic fixtures (no 200K file dependencies):

1. `test_reconstruct_grid_basic` -- 6x6 grid with obstacles at correct positions
2. `test_reconstruct_grid_empty_obstacles` -- all-False grid
3. `test_load_maze_samples_index` -- sample_id lookup correctness
4. `test_join_chains_with_samples_filtering` -- 5 valid chains from 8 total
5. `test_filter_is_correct_excludes_invalid` -- verifies filter rationale
6. `test_row_to_hf_format` -- PCB vision schema key match
7. `test_render_maze_grid_returns_pil_image` -- 1024x768 RGB output
8. `test_create_vision_messages_format` -- exact message structure match
9. `test_build_maze_vision_dataset_full` -- end-to-end: 5 samples, 5 PNGs, dataset output
10. `test_build_maze_vision_dataset_max_samples` -- max_samples limit

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed matplotlib deprecation warning**
- **Found during:** Task 1 GREEN phase
- **Issue:** `fig.canvas.tostring_rgb()` deprecated in matplotlib 3.8, will be removed in 3.10
- **Fix:** Replaced with `fig.canvas.buffer_rgba()` + `PILImage.frombytes("RGBA", ...).convert("RGB")`
- **Files modified:** `src/kicad_agent/training/maze_vision_converter.py`
- **Commit:** 5bba826

**2. [Rule 3 - Blocking] Installed PyGithub dependency for test collection**
- **Found during:** Task 1 RED phase
- **Issue:** `training/__init__.py` imports `real_dataset` which requires `github` (PyGithub). Tests could not import the module.
- **Fix:** `python3.11 -m pip install --ignore-installed cffi PyGithub` (cffi conflict with brew-installed version)
- **Files modified:** None (runtime dependency only)
- **Impact:** Pre-existing import chain in `training/__init__.py`, not introduced by this plan

## Threat Flags

None -- no new trust boundaries introduced beyond file I/O specified in threat model.

## Known Stubs

None. All functions are fully implemented with complete logic paths.

## Self-Check: PASSED

- [x] `src/kicad_agent/training/maze_vision_converter.py` exists with `build_maze_vision_dataset`, `_reconstruct_grid`, `_render_maze_grid`, `MAZE_VISION_PROMPT`
- [x] `tests/test_maze_vision_converter.py` exists with `class TestMazeVisionConverter` and 10 test methods
- [x] `scripts/convert_maze_vision.py` exists with `def main() -> int:` and required argparse flags
- [x] Commit 5bba826 exists
- [x] Commit 8e25b29 exists
- [x] `python3.11 -m pytest tests/test_maze_vision_converter.py -x -q` exits 0 (10 passed)
- [x] `python3.11 scripts/convert_maze_vision.py --help` exits 0
