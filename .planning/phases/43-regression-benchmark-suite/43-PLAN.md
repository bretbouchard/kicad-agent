# Phase 43: Regression Benchmark Suite

**Status:** PLANNING
**Requirements:** BENCH-04
**Depends on:** Phase 41 (PCB MMLU benchmark), Phase 42 (QA dataset)
**Milestone:** v2.5

## Goal

Create an automated benchmark runner with regression detection and CI integration. Every PR runs the benchmark suite; if scores drop, the PR is blocked.

## Plans

### Plan 43-01: Regression Benchmark Suite + CI Integration (BENCH-04)

**Goal:** Automated benchmark pipeline with historical tracking, regression detection, and CI integration.

**Schema:**
```python
class BenchmarkHistory(BaseModel):
    entries: list[BenchmarkResult]
    baseline: BenchmarkResult  # Reference result to compare against

class RegressionReport(BaseModel):
    current: BenchmarkResult
    baseline: BenchmarkResult
    delta: dict[str, float]  # Per-category accuracy delta
    is_regression: bool      # True if any category drops > 2%
    regression_categories: list[str]
```

**Features:**
1. **Historical tracking** — store results in `benchmarks/results/` with timestamps
2. **Regression detection** — compare current vs baseline, flag if any category drops > 2%
3. **CI integration** — GitHub Actions workflow that runs benchmarks on every PR
4. **Trend reporting** — show accuracy over time per category

**Implementation:**
1. Create `src/kicad_agent/benchmarks/regression.py` — regression detection logic
2. Create `.github/workflows/benchmark.yml` — CI workflow
3. Create `benchmarks/results/baseline.json` — initial baseline
4. CLI: `python -m kicad_agent.benchmarks --regression-check`

**CI workflow:**
```yaml
name: Benchmark
on: [pull_request]
jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .
      - run: python -m kicad_agent.benchmarks --dataset benchmarks/pcb-mmlu-v1.json --model heuristic --output /tmp/results.json
      - run: python -m kicad_agent.benchmarks --regression-check --baseline benchmarks/results/baseline.json --current /tmp/results.json
```

**Tests:**
- Regression detection flags > 2% drop in any category
- No regression when scores are equal or improved
- Historical tracking stores and retrieves results correctly
- CI workflow YAML is valid

**Success Criteria:**
1. Regression detection works with configurable threshold
2. Historical results tracked in JSON files
3. CI workflow runs benchmarks on every PR
4. Baseline comparison produces clear pass/fail report
