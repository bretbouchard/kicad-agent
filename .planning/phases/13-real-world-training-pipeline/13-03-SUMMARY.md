---
phase: 13-real-world-training-pipeline
plan: 03
subsystem: training
tags: [jsonl, deduplication, sha256, quality-filter, dataset, grpo, train-val-test-split]

# Dependency graph
requires:
  - phase: 13-01
    provides: GithubDiscovery, KicadFilePair, FileFetcher for repo discovery and file fetching
  - phase: 13-02
    provides: BoardGraphResult, build_board_graph for graph construction from file pairs
  - phase: 09
    provides: MazeDataset pattern (frozen dataclass + JSONL + split) for GRPO compatibility
provides:
  - RealBoardSample frozen dataclass matching BoardGraphResult fields
  - RealBoardDataset with JSONL serialization and train/val/test split
  - SHA256 dedup via board_hash (O(n) set lookup)
  - Quality filter (min 3 components, min 2 nets)
  - run_pipeline() end-to-end wiring: discovery -> fetch -> parse -> dedup -> filter -> dataset
affects: [grpo-training, real-world-data]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass-jsonl, streaming-pipeline, sha256-dedup-set-lookup]

key-files:
  created:
    - src/kicad_agent/training/real_dataset.py
    - tests/test_real_dataset.py
  modified:
    - src/kicad_agent/training/__init__.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "RealBoardSample mirrors BoardGraphResult 1:1 so conversion is lossless"
  - "Streaming pipeline accumulates only RealBoardSample (all primitives), discarding live IR after graph build"
  - "Quality thresholds (3 components, 2 nets) chosen to filter trivial boards while keeping minimal but real designs"

patterns-established:
  - "Frozen dataclass + JSONL + split: same pattern as MazeDataset for GRPO compatibility"
  - "O(n) dedup via set of board_hash strings, keeps first occurrence"

requirements-completed: [RW-04, RW-05]

# Metrics
duration: 4min
completed: 2026-05-23
---

# Phase 13 Plan 03: RealBoardDataset Summary

**RealBoardDataset with SHA256 dedup, quality filter, JSONL round-trip, train/val/test split, and end-to-end pipeline wiring discovery to dataset assembly**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-23T23:51:52Z
- **Completed:** 2026-05-23T23:55:53Z
- **Tasks:** 1
- **Files modified:** 4

## Accomplishments
- RealBoardSample frozen dataclass with all serializable fields (str/int/float only)
- RealBoardDataset with to_jsonl/from_jsonl round-trip and deterministic split
- SHA256 deduplication removes duplicate boards appearing in multiple repos
- Quality filter removes trivial boards (<3 components or <2 nets)
- run_pipeline() wires GithubDiscovery + FileFetcher + build_board_graph in streaming pipeline
- Full test suite at 973 tests (20 new), zero failures

## Task Commits

Each task was committed atomically:

1. **Task 1: RealBoardSample, RealBoardDataset with dedup/quality/JSONL/split, and run_pipeline** - `c3d5a79` (feat)

## Files Created/Modified
- `src/kicad_agent/training/real_dataset.py` - RealBoardSample, RealBoardDataset, dedup, quality filter, run_pipeline
- `src/kicad_agent/training/__init__.py` - Barrel updated with real_dataset exports
- `tests/test_real_dataset.py` - 20 tests covering all functionality
- `.planning/REQUIREMENTS.md` - RW-01 through RW-05 added with traceability

## Decisions Made
- RealBoardSample mirrors BoardGraphResult fields exactly for lossless conversion
- Streaming: only RealBoardSample accumulates (all primitives), live IR discarded after build_board_graph
- Quality thresholds (3 components, 2 nets) filter trivial boards while keeping minimal real designs
- Audit metadata includes n_discovered, n_parsed, n_failed, n_duplicates_removed, n_quality_removed, difficulty_counts (T-13-12)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Test file initially missing imports for KicadFilePair, GithubDiscovery, FileFetcher (from external modules) -- fixed by adding the needed imports
- Test for split determinism iterated over RealBoardDataset directly instead of .samples -- fixed to use .samples attribute

## Next Phase Readiness
- Phase 13 complete. Real-world training pipeline fully operational: discovery -> graph building -> dataset assembly
- RealBoardDataset format compatible with Phase 9 GRPO training pipeline
- 973 total tests passing, 0 failures

## Self-Check: PASSED

All files verified present:
- src/kicad_agent/training/real_dataset.py -- FOUND
- tests/test_real_dataset.py -- FOUND
- src/kicad_agent/training/__init__.py -- FOUND
- .planning/REQUIREMENTS.md -- FOUND
- 13-03-SUMMARY.md -- FOUND

Commit c3d5a79 verified in git log.

---
*Phase: 13-real-world-training-pipeline*
*Completed: 2026-05-23*
