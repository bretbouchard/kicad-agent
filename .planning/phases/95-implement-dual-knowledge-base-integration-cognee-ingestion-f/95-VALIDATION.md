---
phase: 95
slug: implement-dual-knowledge-base-integration-cognee-ingestion-f
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-14
---

# Phase 95 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_knowledge.py -x -q` |
| **Full suite command** | `python -m pytest tests/test_knowledge.py tests/test_text_prompts.py -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 95-01-01 | 01 | 1 | D-01 | — | N/A | unit | `python -m pytest tests/test_knowledge.py::test_ingest_cognee -x -q` | ❌ W0 | ⬜ pending |
| 95-01-02 | 01 | 1 | D-01 | — | N/A | unit | `python -m pytest tests/test_knowledge.py::test_cognee_search -x -q` | ❌ W0 | ⬜ pending |
| 95-02-01 | 02 | 1 | D-02 | T-95-01 | No path traversal in file resolution | unit | `python -m pytest tests/test_knowledge.py::test_load_reference_docs -x -q` | ❌ W0 | ⬜ pending |
| 95-02-02 | 02 | 1 | D-02/D-03 | — | N/A | unit | `python -m pytest tests/test_knowledge.py::test_section_chunking -x -q` | ❌ W0 | ⬜ pending |
| 95-02-03 | 02 | 1 | D-03 | — | N/A | unit | `python -m pytest tests/test_knowledge.py::test_op_section_mapping -x -q` | ❌ W0 | ⬜ pending |
| 95-03-01 | 03 | 2 | D-04 | — | N/A | unit | `python -m pytest tests/test_knowledge.py::TestTokenBudget -x -q` | ❌ W0 | ⬜ pending |
| 95-03-02 | 03 | 2 | D-02/D-05 | T-95-01 | Graceful fallback if docs missing | unit | `python -m pytest tests/test_knowledge.py::test_missing_docs_fallback -x -q` | ❌ W0 | ⬜ pending |
| 95-03-03 | 03 | 2 | D-02 | T-95-05 | No injection patterns in knowledge content | unit | `python -m pytest tests/test_knowledge.py::test_knowledge_sanitize -x -q` | ❌ W0 | ⬜ pending |
| 95-03-04 | 03 | 2 | D-02/D-03 | — | N/A | integration | `python -m pytest tests/test_knowledge.py::TestPromptIntegration -x -q` | ❌ W0 | ⬜ pending |
| 95-03-05 | 03 | 2 | D-02 | — | N/A | integration | `python -m pytest tests/test_knowledge.py::TestExecutionWiring -x -q` | ❌ W0 | ⬜ pending |
| 95-03-06 | 03 | 2 | D-02 | — | N/A | unit | `python -m pytest tests/test_knowledge.py::TestCoverageAssertion -x -q` | ❌ W0 | ⬜ pending |
| 95-03-07 | 03 | 2 | D-02/D-03 | — | N/A | unit | `python -m pytest tests/test_text_prompts.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_knowledge.py` — stubs for all D-XX decisions
- [ ] `tests/conftest.py` — shared fixtures (mock docs, mock Cognee)

*Existing infrastructure: pytest already configured in pyproject.toml*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cognee semantic search returns relevant results | D-01 | Requires running Cognee server | Run ingestion, then search for "pin at coordinate" — verify schematic reference section returned |
| Knowledge injection improves local model output | D-02/D-04 | Requires local model inference | Run intent_parse with and without knowledge — compare output quality |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
