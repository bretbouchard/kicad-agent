---
phase: 234
slug: 1000-schematic-swift-erc-batch-test
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-14
---

# Phase 234 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (Python) + XCTest (Swift) |
| **Config file** | `/Users/bretbouchard/apps/kicad-agent/pytest.ini` |
| **Quick run command** | `pytest scripts/test_parity_thresholds.py -x` |
| **Full suite command** | `pytest .planning/tests/ --tb=short` |
| **Estimated runtime** | ~10 minutes for 1000-schematic batch |

---

## Sampling Rate

- **After every task commit:** Run relevant unit tests
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** All tests must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 234-01 | 1 | 1 | Acquire and stage 1000 schematics from corpus | T-101-01 | Verify SHA256 checksums, validate .kicad_sch format | integration | `pytest scripts/test_corpus_staging.py` | ❌ Wave 0 | pending |
| 234-02 | 1 | 1 | Implement parity comparison driver | T-102-01 | Normalize severity levels, match by check_id/net/ref | unit | `pytest scripts/test_parity_driver.py` | ❌ Wave 0 | pending |
| 234-03 | 2 | 1 | Execute full parity test | T-103-01 | Process all 1000 schematics, handle errors gracefully | integration | `pytest scripts/test_batch_execution.py` | ❌ Wave 0 | pending |
| 234-04 | 2 | 1 | Generate parity report | T-104-01 | Markdown renders correctly, JSON is valid | unit | `pytest scripts/test_report_format.py` | ❌ Wave 0 | pending |
| 234-05 | 3 | 1 | Validate thresholds (FP/FN <= 5%) | T-105-01 | Fail if agreement < 95% | unit | `pytest scripts/test_parity_thresholds.py` | ❌ Wave 0 | pending |
| 234-06 | 3 | 1 | Verify discrepancy patterns documented | T-106-01 | Top-10 patterns extracted, example paths provided | unit | Manual review | ❌ Wave 0 | pending |
| 234-07 | 3 | 2 | Verify fix reduces FP/FN count | T-107-01 | Re-run test, verify improvement | integration | `pytest scripts/test_fix_verification.py` | ❌ Wave 0 | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

- [ ] `{scripts/test_corpus_staging.py}` — verifies 1000 schematics acquired
- [ ] `{scripts/test_parity_thresholds.py}` — validates FP/FN <= 5%
- [ ] `{scripts/conftest.py}` — shared pytest fixtures for corpus paths
- [ ] Python test framework installed: `pip install pytest`

*If none: Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Discrepancy pattern analysis | REQ-234-06 | Requires human judgment to categorize root causes | 1. Review parity-results.json 2. Group by check_id and pattern 3. Document top 10 with example paths |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---

## Known Edge Cases

| Case | Handling | Location |
|------|----------|----------|
| Empty schematics | Skip (document in report) | batch_erc_parity.py |
| Missing power flags | Report as FN | Comparison layer |
| Rotated components | Position rounding to 2 decimals | Normalized comparison |
| Hierarchical sheets | Single sheet test | corpus sampling |
| Parse errors | Record as failure, continue | Error handling |

---

## Verification Ladder (RED → GREEN → REFACTOR)

Per TDD requirements, each implementation task follows the verification ladder:

### Phase 1: RED (Test-First)
1. Write failing test before implementation
2. Verify test fails with expected error
3. Commit: `test(234): add failing test for [behavior]`

### Phase 2: GREEN (Minimal Implementation)
1. Write minimal code to pass test
2. Verify test passes
3. Commit: `feat(234): implement [behavior]`

### Phase 3: REFACTOR (Code Quality)
1. Clean up code while maintaining behavior
2. Verify all tests still pass
3. Commit: `refactor(234): improve [aspect]`

---

## Requirements Traceability

| Req ID | Behavior | Test File | Automated Command |
|--------|----------|-----------|-------------------|
| REQ-01 | Swift engine runs on 1000 schematics | `tests/test_swift_erc_run.py` | `python scripts/batch_erc_parity.py --engine swift --sample 1000` |
| REQ-02 | Python reference runs on 1000 schematics | `tests/test_python_erc_run.py` | `python scripts/batch_erc_parity.py --engine python --sample 1000` |
| REQ-03 | Parity report generated | `tests/test_report_generation.py` | `python scripts/batch_erc_parity.py --report` |
| REQ-04 | FP count <= 5% | `scripts/test_parity_thresholds.py` | `pytest scripts/test_parity_thresholds.py::test_fp_rate` |
| REQ-05 | FN count <= 5% | `scripts/test_parity_thresholds.py` | `pytest scripts/test_parity_thresholds.py::test_fn_rate` |
| REQ-06 | Patterns documented (top-10) | `tests/test_pattern_documentation.py` | `pytest tests/test_pattern_documentation.py` |

---

## Coverage Requirements

| Metric | Target | Rationale |
|--------|--------|-----------|
| Line Coverage | >= 80% | Industry standard for production code |
| Branch Coverage | >= 75% | Ensures edge cases handled |
| Path Coverage | >= 70% | Critical logic paths tested |
| Mutation Score | >= 80% | Tests can detect faults |

---

## Test Types

| Test Type | Purpose | Run Command |
|-----------|---------|-------------|
| Unit Tests | Test individual functions | `pytest tests/unit/` |
| Integration Tests | Test component interactions | `pytest tests/integration/` |
| Parity Tests | Compare Swift vs Python results | `pytest tests/parity/` |
| E2E Tests | Full system workflow | `gsd-browser` scripts |
| Performance Tests | Benchmark execution time | `pytest tests/performance/` |

---

## Quality Gates

| Gate | Pass Condition | Failure Action |
|------|----------------|----------------|
| Pre-commit | All files pass lint/type | Block commit |
| Unit Test | >= 80% coverage | Fail build |
| Integration Test | API endpoints respond | Fail build |
| Parity Test | Agreement >= 95% | Alert, investigate |
| Performance | < 5s per schematic | Profile, optimize |

---

## Test Data Management

| Category | Location | Update Frequency |
|----------|----------|------------------|
| Corpus Schematics | `.planning/phases/234/corpus/` | Updated per sampling |
| Test Fixtures | `tests/fixtures/` | Stable, rarely changed |
| Expected Results | `tests/expected/` | Updated with verified outputs |
| Seed Data | `tests/seed/` | Updated for new test categories |

---

## Continuous Validation

| Check | Tool | Schedule |
|-------|------|----------|
| Type checking | mypy/pyright | Pre-commit hook |
| Linting | ruff/flake8 | Pre-commit hook |
| Formatting | ruff format | Pre-commit hook |
| Unit tests | pytest | Per-task execution |
| Integration tests | pytest | Per-wave execution |
| Parity thresholds | pytest | Pre-wave execution