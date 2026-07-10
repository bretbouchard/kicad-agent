---
phase: 207
slug: versioned-build-system
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-10
---

# Phase 207 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/python -m pytest`) |
| **Quick run** | `.venv/bin/python -m pytest tests/test_build_system.py tests/test_registry.py -x -q -o addopts="" -o pythonpath="src tests"` |
| **Full suite** | `.venv/bin/python -m pytest tests/ -q -o addopts="" -o pythonpath="src tests"` |
| **Runtime** | ~10s (quick), ~90s (full) |

## Per-Task Verification Map

| Task | Req | Test | Status |
|------|-----|------|--------|
| 1: Build model + manifest serialization | BUILD-02,03,05 | `test_build_round_trip`, `test_manifest_save_load` | ⬜ |
| 2: build_create op | BUILD-01,04,06 | `test_build_create_creates_dir`, `test_build_create_records_git_sha` | ⬜ |
| 3: build_list + build_show ops | BUILD-07,08 | `test_build_list_returns_builds`, `test_build_show_returns_details` | ⬜ |
| 4: Build diffing | BUILD-10 | `test_diff_builds_detects_changes` | ⬜ |
| 5: .gitignore + registry | BUILD-09, IP-1,2 | `grep builds/ .gitignore`, `test_registry count==159` | ⬜ |

## Key Test Scenarios

| Test | Verifies |
|------|----------|
| `test_build_create_creates_directory` | `builds/v{rev}_{timestamp}/` exists after build_create |
| `test_build_create_records_board_rev` | Build record has board_rev from title_block |
| `test_build_create_records_git_sha` | Build record has git_sha (or "unknown") |
| `test_build_create_no_partial_state_on_failure` | If validation fails, NO build directory is created |
| `test_manifest_round_trip` | save → load produces identical ManufacturingManifest |
| `test_build_list_returns_all_builds` | Multiple builds → list returns all with correct count |
| `test_build_show_returns_manifest` | build_show returns full manifest with artifacts |
| `test_diff_builds_detects_source_changes` | Diff detects added/removed source files |
| `test_diff_builds_detects_status_change` | Diff detects status changes |
| `test_target_file_unchanged_after_build` | .kicad_pcb byte-identical after build_create (query op safety) |
| `test_git_sha_unknown_when_not_repo` | Git SHA returns "unknown" gracefully |
| `test_builds_dir_in_gitignore` | `grep "^builds/" .gitignore` matches |

## Validation Sign-Off
- [x] All tasks have automated verify
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true`
