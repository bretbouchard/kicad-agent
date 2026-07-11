---
phase: 208
slug: manufacturer-handoff-package
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-11
---

# Phase 208 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/python -m pytest`) |
| **Quick run** | `.venv/bin/python -m pytest tests/test_handoff.py tests/test_registry.py tests/test_build_system.py -x -q -o addopts="" -o pythonpath="src tests"` |
| **Full suite** | `.venv/bin/python -m pytest tests/ -q -o addopts="" -o pythonpath="src tests"` |
| **Runtime** | ~15s (quick) |

## Per-Task Verification Map

| Task | Req | Test | Status |
|------|-----|------|--------|
| 1: Handoff orchestrator + HandoffResult | HANDOFF-01,02,03 | `test_handoff_creates_zip`, `test_handoff_includes_all_artifacts` | ⬜ |
| 2: Pre-handoff validation gate | HANDOFF-06 | `test_handoff_blocks_on_drc_failure`, `test_handoff_blocks_on_erc_failure` | ⬜ |
| 3: readme.md generation | HANDOFF-04 | `test_readme_contains_board_specs`, `test_readme_contains_validation_results` | ⬜ |
| 4: Profile-driven BOM + ManufacturerProfile extension | HANDOFF-05,08 | `test_bom_profile_jlcpcb`, `test_bom_profile_generic` | ⬜ |
| 5: STEP optional + DRC/ERC in manifest | HANDOFF-07,09 | `test_step_excluded_when_flag_false`, `test_manifest_contains_validation` | ⬜ |
| 6: Op registration + registry | IP-1,2 | `test_registry count==160` | ⬜ |

## Key Test Scenarios

| Test | Verifies |
|------|----------|
| `test_handoff_creates_zip` | handoff.zip exists in build directory |
| `test_handoff_includes_gerbers` | Zip contains .gbr files |
| `test_handoff_includes_drill` | Zip contains drill files |
| `test_handoff_includes_bom` | Zip contains BOM CSV |
| `test_handoff_includes_cpl` | Zip contains pick-and-place |
| `test_handoff_includes_manifest` | Zip contains manifest.json |
| `test_handoff_includes_readme` | Zip contains readme.md |
| `test_handoff_blocks_on_drc_failure` | DRC fails → no zip, error returned |
| `test_handoff_skip_validation` | skip_validation=True → zip created even if DRC would fail |
| `test_handoff_vendor_specific_bom` | vendor="jlcpcb" → BOM has JLCPCB columns |
| `test_handoff_step_optional` | include_step=False → no STEP in zip |
| `test_readme_has_board_name` | readme.md contains board title from title_block |
| `test_readme_has_surface_finish` | readme.md contains BoardSpec surface finish |
| `test_manifest_has_drc_result` | manifest.json contains drc_passed field |
| `test_target_file_unchanged` | .kicad_pcb byte-identical after handoff |
| `test_bom_profile_jlcpcb_columns` | JLCPCB profile produces Comment,Designator,Footprint,LCSC columns |
| `test_bom_profile_generic_columns` | Generic profile uses kicad-cli default columns |

## Validation Sign-Off
- [x] All tasks have automated verify
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true`
