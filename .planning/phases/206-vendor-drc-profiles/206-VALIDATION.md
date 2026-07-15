---
phase: 206
slug: vendor-drc-profiles
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-10
---

# Phase 206 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via `.venv/bin/python -m pytest`) |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_vendor_drc.py tests/test_drc_vendor_ops.py tests/test_registry.py -x -q -o addopts="" -o pythonpath="src tests"` |
| **Full suite command** | `.venv/bin/python -m pytest tests/ -q -o addopts="" -o pythonpath="src tests"` |
| **Estimated runtime** | ~10 seconds (quick), ~90 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run quick command above
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 206-01-01 | 01 | 1 | DRC-02, DRC-03, DRC-06 | — | N/A (static data files) | unit | `test -f src/volta/manufacturing/drc_profiles/pcbway.kicad_dru && grep "Source:" src/volta/manufacturing/drc_profiles/pcbway.kicad_dru` | ❌ W0 | ⬜ pending |
| 206-01-02 | 01 | 1 | DRC-05, DRC-07 | — | N/A (model extension) | unit | `.venv/bin/python -c "from volta.dfm.profiles import ManufacturerProfile; p = ManufacturerProfile.example(); assert hasattr(p, 'drc_rules_path')"` | ❌ W0 | ⬜ pending |
| 206-01-03 | 01 | 1 | DRC-01 | — | Read-only (no file mutation) | unit | `.venv/bin/python -m pytest tests/test_vendor_drc.py -x -q` | ❌ W0 | ⬜ pending |
| 206-01-04 | 01 | 1 | DRC-01, DRC-04, DRC-08 | — | Read-only query, path validation | unit | `.venv/bin/python -m pytest tests/test_drc_vendor_ops.py -x -q` | ❌ W0 | ⬜ pending |
| 206-01-05 | 01 | 1 | IP-1, IP-2 | — | Registry/schema parity | unit | `.venv/bin/python -m pytest tests/test_registry.py -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_vendor_drc.py` — internal evaluator tests (track width, drill, annular ring, clearance, via diameter checks)
- [ ] `tests/test_drc_vendor_ops.py` — drc_vendor + list_vendor_drc_profiles operation tests

*Existing infrastructure covers framework needs — no framework install required.*

---

## Key Test Scenarios

### Vendor DRC Evaluator Tests
| Test Name | Verifies |
|-----------|----------|
| `test_track_width_below_limit` | Segment with width < min_trace_width_mm → violation |
| `test_track_width_at_limit` | Segment with width == min → no violation |
| `test_via_drill_below_limit` | Via with drill < min_drill_mm → violation |
| `test_annular_ring_below_limit` | Via with (size - drill)/2 < min_annular_ring_mm → violation |
| `test_via_diameter_below_limit` | Via with size < min_via_diameter_mm → violation |
| `test_clearance_below_limit` | Two tracks closer than min_clearance_mm → violation |
| `test_all_pass_on_clean_board` | Board with all features above limits → passed=True |
| `test_vendor_not_found` | Unknown vendor name → ValueError with available vendors listed |
| `test_generic_profile` | Generic conservative profile works on any board |

### Operation Tests
| Test Name | Verifies |
|-----------|----------|
| `test_drc_vendor_returns_result` | drc_vendor op returns VendorDrcResult with violations list |
| `test_drc_vendor_pcbway` | drc_vendor(vendor="pcbway") runs against PCBWay limits |
| `test_drc_vendor_generic` | drc_vendor(vendor="generic") runs against conservative defaults |
| `test_list_vendor_drc_profiles` | list_vendor_drc_profiles returns all profiles with capabilities |
| `test_list_profiles_has_capabilities` | Each profile entry has min_trace_width_mm, min_clearance_mm, etc. |

### Profile File Tests
| Test Name | Verifies |
|-----------|----------|
| `test_all_dru_files_have_attribution` | Every .kicad_dru file has Source, License, Last verified header |
| `test_pcbway_annular_ring_015` | PCBWay profile has min_annular_ring_mm=0.15 (DRC-07, not 0.25) |
| `test_dru_files_are_valid_sexpr` | Each .kicad_dru file parses as valid S-expression |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| .kicad_dru files load in KiCad GUI | DRC-02 | No headless GUI | Copy a .kicad_dru next to a test board, open in KiCad, verify rules appear in DRC config |

---

## Validation Sign-Off

- [x] All tasks have automated verify
- [x] Sampling continuity: every task has automated verify
- [x] Wave 0 covers all MISSING references (new test files)
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
