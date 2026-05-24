---
phase: "19"
plan: "02"
subsystem: routing
tags: [differential-pair, length-matching, serpentining, routing]
dependency_graph:
  requires: ["19-01-routing-graph-pathfinder"]
  provides: [diff-pair-routing, serpentine-length-matching]
  affects: [routing-engine]
tech_stack:
  added: [diff_pair.py]
  patterns: [frozen-dataclass, measure-and-refine-loop, arc-length-parameterization]
key_files:
  created:
    - src/kicad_agent/routing/diff_pair.py
  modified:
    - src/kicad_agent/routing/__init__.py
    - tests/test_routing.py
decisions:
  - "Measure-and-refine amplitude loop instead of geometric model to handle
     nonlinear relationship between amplitude and actual path length"
  - "1% overshoot factor on target delta ensures convergence from above rather
     than asymptotically approaching from below"
  - "Arc-length parameterization of path for bump placement rather than
     per-segment approach to handle short grid segments"
metrics:
  duration: 8 min
  completed: "2026-05-24"
---

# Phase 19 Plan 02: Differential Pair Routing with Length Matching Summary

Differential pair routing with accordion serpentine length matching using measure-and-refine amplitude convergence.

## Changes Made

### New Files

- **`src/kicad_agent/routing/diff_pair.py`** -- Core differential pair routing module:
  - `DiffPairResult` frozen dataclass: net_positive, net_negative, lengths, mismatch, spacing, validity
  - `route_differential_pair()`: Routes both nets via A* pathfinder, applies serpentine bumps to shorter path
  - `_path_length()`: Euclidean path length computation
  - `_interpolate_path()`: Arc-length parameterization for point lookup along path
  - `_direction_at()`: Unit direction and perpendicular at a given arc-length position
  - `_bump_extra_length()`: Geometric model for extra length per bump
  - `_add_serpentining()`: Measure-and-refine amplitude loop (10 iterations, 1% overshoot)
  - `_generate_bumps()`: Actual bump point generation at a given amplitude

### Modified Files

- **`src/kicad_agent/routing/__init__.py`** -- Added `DiffPairResult` and `route_differential_pair` to barrel exports
- **`tests/test_routing.py`** -- Added 6 new tests for ROUTE-03 differential pair coverage

## Test Results

All 40 tests pass (30 existing + 10 new path length tests + 6 new diff pair tests -- some overlap in counting):
- `test_path_length` (5 variants): unit test for `_path_length` utility
- `test_diff_pair_basic`: Both nets route on clear board, valid=True
- `test_diff_pair_length_matching`: Asymmetric paths, serpentining brings mismatch within 2.0mm tolerance
- `test_diff_pair_blocked_positive`: Blocked positive net returns valid=False
- `test_diff_pair_blocked_negative`: Blocked negative net returns valid=False
- `test_diff_pair_serpentine_bounded`: Amplitude bounded to spacing_mm * 2

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Serpentine per-segment approach failed with short grid segments**
- **Found during:** Implementation of `_add_serpentining`
- **Issue:** Original per-segment bump insertion required bump_interval (~4mm) to fit within each 1mm grid segment, which was impossible
- **Fix:** Rewrote to use arc-length parameterization across the entire path, treating it as a continuous curve rather than individual segments
- **Files modified:** `src/kicad_agent/routing/diff_pair.py`
- **Commit:** 088fc45

**2. [Rule 1 - Bug] Geometric model `extra=2*amplitude` did not match actual bump geometry**
- **Found during:** Testing `test_diff_pair_length_matching`
- **Issue:** The U-shape bump adds extra length via hypotenuse-based legs, not simple `2*amplitude`. Binary search using the geometric model found amplitudes that were too small.
- **Fix:** Replaced geometric model with measure-and-refine loop: generate bumps at a trial amplitude, measure actual path length, scale amplitude proportionally, repeat up to 10 iterations with 1% overshoot
- **Files modified:** `src/kicad_agent/routing/diff_pair.py`
- **Commit:** 088fc45

## Key Decisions

1. **Measure-and-refine over geometric model**: The relationship between amplitude and actual extra path length is nonlinear and depends on path geometry. A measure-and-refine loop converges reliably regardless of path shape.

2. **1% overshoot factor**: Proportional scaling converges asymptotically from below. Adding a 1% overshoot ensures convergence from above within a few iterations, which is more reliable.

3. **Arc-length parameterization**: Treating the entire path as a continuous curve parameterized by arc length allows bump placement independent of individual segment lengths.

## Self-Check: PASSED

- [x] `src/kicad_agent/routing/diff_pair.py` exists
- [x] `src/kicad_agent/routing/__init__.py` updated with exports
- [x] `tests/test_routing.py` updated with 6 new tests
- [x] Commit 088fc45 exists in git log
- [x] All 40 routing tests pass
