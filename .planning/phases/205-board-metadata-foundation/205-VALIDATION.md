---
phase: 205
slug: board-metadata-foundation
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-10
---

# Phase 205 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via `.venv/bin/python -m pytest`) |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_pcb_native_parser.py tests/test_pcb_ops.py tests/test_registry.py tests/test_board_spec.py tests/test_board_metadata_ops.py -x -q` |
| **Full suite command** | `.venv/bin/python -m pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds (quick), ~90 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run quick command above
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 205-01-01 | 01 | 1 | META-06, META-07 | — | N/A (frozen dataclass, immutable) | unit | `.venv/bin/python -c "from kicad_agent.parser.pcb_native_types import NativeTitleBlock; tb = NativeTitleBlock(); assert tb.title == ''"` | ❌ W0 | ⬜ pending |
| 205-01-02 | 01 | 1 | META-04, META-05 | — | Atomic sidecar write (no torn files) | unit | `.venv/bin/python -m pytest tests/test_board_spec.py -x` | ❌ W0 | ⬜ pending |
| 205-01-03 | 01 | 1 | META-02, META-03, META-06 | — | Raw-writer mutation, round-trip fidelity | unit | `.venv/bin/python -c "from kicad_agent.ops.pcb_raw_writer import PcbRawWriter; assert hasattr(PcbRawWriter, 'set_title_block_fields')"` | ❌ W0 | ⬜ pending |
| 205-01-04 | 01 | 1 | META-01, META-02, META-03 | — | Registry/schema parity | unit | `.venv/bin/python -m pytest tests/test_registry.py -x` | ✅ | ⬜ pending |
| 205-01-05 | 01 | 1 | META-01, META-02, META-03 | — | Read-only query (no mutation); Transaction-wrapped mutation | unit | `.venv/bin/python -m pytest tests/test_board_metadata_ops.py -x` | ❌ W0 | ⬜ pending |
| 205-01-06 | 01 | 1 | META-01..03, META-06, META-07 | — | Round-trip + quoting variations | unit | `.venv/bin/python -m pytest tests/test_pcb_native_parser.py -k "title_block" -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_board_spec.py` — BoardSpec model, JSON round-trip, impedance requirements, enum serialization
- [ ] `tests/test_board_metadata_ops.py` — read_board_metadata, set_board_metadata, set_board_revision operation tests + round-trip fidelity
- [ ] `tests/test_pcb_native_parser.py` — extend with title_block parsing tests (may go in existing file or separate test class)

*Existing infrastructure (pytest, fixtures, `.venv`) covers framework needs — no framework install required.*

---

## Round-Trip Fidelity Tests (META-06, META-07 — Pitfall 2 Prevention)

These tests are the CRITICAL verification for title_block parsing. Each must create a PCB with the specified title_block, parse it, modify a field, serialize, re-parse, and assert zero data loss.

| Test Name | title_block Content | Verifies |
|-----------|---------------------|----------|
| `test_title_block_full_fields` | title="My Board", date="2026-07-10", rev="2.1", company="ACME", comment 1-9 populated | All fields parse + round-trip |
| `test_title_block_empty_fields` | title="", date="", rev="", company="" (all empty strings) | Empty field handling |
| `test_title_block_missing_fields` | Only `(title_block (date "..."))` — no title/rev/company | Missing field → default "" |
| `test_title_block_no_block` | No `(title_block ...)` at all | `NativeBoard.title_block` is None |
| `test_title_block_special_chars` | company="Smith & Co. LLC", title="Board v2.1 (prototype)" | Special character round-trip |
| `test_title_block_non_sequential_comments` | comment 1, comment 3, comment 9 (gaps) | Non-sequential comment numbering |
| `test_title_block_kicad_cli_valid` | Full fields → modify → run `kicad-cli pcb export stats` | KiCad accepts the modified file |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| KiCad GUI opens modified PCB correctly | META-06 | No headless GUI | Open the round-trip test PCB in KiCad GUI and verify title_block fields display correctly |

---

## Validation Sign-Off

- [x] All tasks have automated verify
- [x] Sampling continuity: every task has automated verify
- [x] Wave 0 covers all MISSING references (new test files)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
