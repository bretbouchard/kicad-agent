---
phase: 2
slug: operation-schema-and-ir-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-18
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q --tb=short` |
| **Full suite command** | `python -m pytest tests/ -x -v --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest tests/ -x -v --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | OPS-01 | T-02-01 | Schema rejects invalid intents | unit | `python -m pytest tests/test_ops_schema.py -x -v` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | OPS-04 | T-02-02 | JSON Schema export complete | unit | `python -m pytest tests/test_ops_schema.py::test_json_schema_export -x -v` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | OPS-02 | — | IR wraps kiutils correctly | unit | `python -m pytest tests/test_ir_layer.py -x -v` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | OPS-02 | — | Mutation tracking works | unit | `python -m pytest tests/test_ir_layer.py::test_mutation_tracking -x -v` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 2 | FND-07 | T-02-03 | Rollback restores pre-mutation state | unit | `python -m pytest tests/test_transaction.py -x -v` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 2 | FND-07 | — | Auto-rollback on exception | unit | `python -m pytest tests/test_transaction.py::test_auto_rollback -x -v` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 2 | FND-08 | — | Deterministic serialization output | unit | `python -m pytest tests/test_normalizer.py -x -v` | ❌ W0 | ⬜ pending |
| 02-03-04 | 03 | 2 | FND-08 | — | KiCad-native byte-identical | unit | `python -m pytest tests/test_normalizer.py::test_byte_identical -x -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_ops_schema.py` — stubs for OPS-01, OPS-04
- [ ] `tests/test_ir_layer.py` — stubs for OPS-02
- [ ] `tests/test_transaction.py` — stubs for FND-07
- [ ] `tests/test_normalizer.py` — stubs for FND-08

*Existing Phase 1 test infrastructure covers shared fixtures and conftest.py.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | — | — |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
