---
phase: 43-regression-benchmark-suite
plan: 01
subsystem: benchmarks
tags: [benchmark, regression, ci, github-actions, pydantic, tdd]

# Dependency graph
requires:
  - phase: 41-02
    provides: BenchmarkRunner, BenchmarkResult, BenchmarkModel, BaselineHeuristic, CLI
  - phase: 42-01
    provides: BenchmarkDataset, BenchmarkQuestion schemas
provides:
  - RegressionDetector with compare(), store_result(), load_history(), set_baseline()
  - RegressionReport schema with delta, is_regression, regression_categories
  - GitHub Actions CI workflow for automated benchmark on every PR
  - Initial baseline.json from heuristic model (31.4% accuracy)
  - CLI --regression-check and --baseline flags
affects: [44-adversarial-testing, future-model-training]

# Tech tracking
tech-stack:
  added: [pydantic RegressionReport, RegressionDetector, GitHub Actions workflow]
  patterns: [regression-detection, baseline-comparison, ci-benchmark-gate, tdd-red-green]

key-files:
  created:
    - src/kicad_agent/benchmarks/regression.py
    - .github/workflows/benchmark.yml
    - benchmarks/results/baseline.json
    - tests/test_benchmark_regression.py
  modified:
    - src/kicad_agent/benchmarks/__main__.py

key-decisions:
  - "RegressionDetector uses configurable threshold (default 2%) per-category, not overall accuracy"
  - "Baseline stored as benchmarks/results/baseline.json, version-controlled for audit trail"
  - "CI workflow runs BaselineHeuristic model (fast, deterministic) for regression checks on PRs"
  - "CLI --regression-check exits with code 1 on regression for CI blocking (Council HIGH-10)"
  - "load_history() skips baseline.json to keep baseline separate from run history"
  - "Missing categories treated as accuracy=0 for comparison"

patterns-established:
  - "Regression detection: compare current vs baseline per-category, flag drops > threshold"
  - "Baseline management: set_baseline overwrites, load_baseline raises FileNotFoundError if missing"
  - "Historical tracking: store_result writes timestamped JSON, load_history skips baseline.json"

requirements-completed: [BENCH-04]

# Metrics
duration: 4min
completed: 2026-06-01
tests: 39
baseline_accuracy: 31.4%
---

# Phase 43 Plan 01: Regression Benchmark Suite Summary

**RegressionDetector with configurable threshold (2%) per-category comparison, GitHub Actions CI gate on every PR, CLI regression flags, and baseline tracking from heuristic model**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-01T00:18:35Z
- **Completed:** 2026-06-01T00:23:17Z
- **Tasks:** 2 (Task 1: TDD RED/GREEN, Task 2: CI + baseline + CLI)
- **Files modified:** 5

## Accomplishments
- RegressionDetector compares BenchmarkResult objects with per-category delta computation and configurable threshold
- Historical result storage with timestamped JSON files in benchmarks/results/
- GitHub Actions CI workflow runs benchmark + regression check on every PR to main/master
- Initial baseline established from BaselineHeuristic model (31.4% accuracy, 500 questions)
- CLI --regression-check and --baseline flags added to __main__.py (Council HIGH-10)
- 39 tests covering regression detection, report schema, historical tracking, CI validation, and baseline file

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for regression detection** - `5bb36ef` (test)
2. **Task 1 (GREEN): RegressionDetector implementation** - `497a26b` (feat)
3. **Task 2: CI workflow, baseline, and CLI regression flags** - `8791380` (feat)

_Note: Task 1 followed TDD cycle (RED -> GREEN). Task 2 added CI workflow, baseline generation, and CLI --regression-check/--baseline flags._

## Files Created/Modified
- `src/kicad_agent/benchmarks/regression.py` - RegressionDetector and RegressionReport implementation (168 lines)
- `.github/workflows/benchmark.yml` - CI workflow for benchmark on PR
- `benchmarks/results/baseline.json` - Initial baseline from BaselineHeuristic
- `tests/test_benchmark_regression.py` - 39 tests across 5 test classes
- `src/kicad_agent/benchmarks/__main__.py` - Added --regression-check and --baseline CLI flags

## Decisions Made
- Per-category threshold (not overall accuracy) prevents masking regressions in one category by improvements in another
- Baseline is version-controlled so git history provides audit trail for baseline changes
- CI uses BaselineHeuristic model because it is fast and deterministic, suitable for CI environments
- CLI --regression-check exits with code 1 on regression for CI blocking
- CLI --baseline defaults to benchmarks/results/baseline.json
- PyYAML `on` key parsed as Python `True` boolean -- test handles both `parsed.get("on")` and `parsed.get(True)` for robustness

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed PyYAML `on` key parsing in CI workflow test**
- **Found during:** Task 2 (CI workflow tests)
- **Issue:** PyYAML converts YAML `on:` key to Python boolean `True`, causing `assert "on" in parsed` to fail
- **Fix:** Changed test to use `parsed.get("on") or parsed.get(True)` for cross-version robustness
- **Files modified:** tests/test_benchmark_regression.py
- **Verification:** All 39 tests pass including TestCIWorkflow.test_workflow_triggers_on_pull_request
- **Committed in:** 8791380 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug), 1 race condition (no impact)
**Impact on plan:** Minimal -- all files correct, all tests passing, no scope creep.

## Issues Encountered
- Task 2 files (CI workflow, baseline.json) were also committed in parallel commit `0cd5784` due to worktree race condition. Content is correct in both commits.

## TDD Gate Compliance

| Gate | Commit | Description |
|------|--------|-------------|
| RED | 5bb36ef | test(43-01): add failing tests for regression detection and CI workflow |
| GREEN | 497a26b | feat(43-01): implement RegressionDetector with comparison and historical tracking |

All gates present. RED commit has collection errors (module not found). GREEN commit has all 39 tests passing. No REFACTOR gate needed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Regression detection pipeline complete and ready for Phase 44 (adversarial testing)
- CI workflow will run on every PR automatically once pushed to GitHub
- Baseline can be updated with `detector.set_baseline(new_result)` when a better model is available

---
*Phase: 43-regression-benchmark-suite*
*Completed: 2026-06-01*

## Self-Check: PASSED

- [x] src/kicad_agent/benchmarks/regression.py -- FOUND
- [x] .github/workflows/benchmark.yml -- FOUND
- [x] benchmarks/results/baseline.json -- FOUND
- [x] tests/test_benchmark_regression.py -- FOUND
- [x] src/kicad_agent/benchmarks/__main__.py -- FOUND
- [x] .planning/phases/43-regression-benchmark-suite/43-01-SUMMARY.md -- FOUND
- [x] Commit 5bb36ef (test RED) -- FOUND
- [x] Commit 497a26b (feat GREEN) -- FOUND
- [x] Commit 8791380 (CI + baseline + CLI) -- FOUND
- [x] Commit 62a49b9 (docs summary) -- FOUND
