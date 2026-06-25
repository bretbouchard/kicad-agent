---
phase: 101
slug: schematic-ops-bug-fixes
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-25
---

# Phase 101 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

Source: `101-RESEARCH.md` § Validation Architecture (lines 474-508).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `cd ~/apps/kicad-agent && python3 -m pytest tests/test_schematic_repair.py tests/test_erc_auto_fix.py tests/test_place_no_connects_power_aware.py -x -q` |
| **Full suite command** | `cd ~/apps/kicad-agent && python3 -m pytest tests/ -x -q --ignore=tests/inference --ignore=tests/integration` |
| **Estimated runtime** | ~15s quick, ~3min full |

---

## Sampling Rate

- **After every task commit:** Run quick suite (schematic repair + ERC + place_no_connects). ~15 seconds.
- **After every wave merge:** Run full suite (excludes inference/integration). ~3 minutes.
- **Phase gate:** Quick suite green + `kicad-cli sch erc` before/after comparison on at least one fixture from `tests/fixtures/`.

---

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Status |
|--------|----------|-----------|-------------------|-------------|
| R-1 (SC-1) | `update_symbols_from_library` does not crash on schematic with lib_symbol_mismatch | unit | `python3 -m pytest tests/test_schematic_repair.py -k update_symbols -x` | Extend existing |
| R-2 (SC-2) | `place_missing_units` produces N distinct positions for N missing units | unit | `python3 -m pytest tests/test_schematic_repair.py -k place_missing_units_collisions -x` | Wave 0 — new |
| R-3 (SC-3, SC-4) | `erc_auto_fix` registry entry has `deprecated=True`; handler emits DeprecationWarning | unit | `python3 -m pytest tests/test_erc_auto_fix.py -k deprecation -x` | Wave 0 — new |
| R-4 (SC-5) | `place_no_connects_from_erc` produces zero new `no_connect_connected` violations | integration | `python3 -m pytest tests/test_place_no_connects_power_aware.py -k tolerance -x` | Extend existing |
| R-5 (SC-6) | `remove_dangling_wires` removes ≥90% of ERC `wire_dangling` violations | integration | `python3 -m pytest tests/test_schematic_repair.py -k dangling_erc -x` | Wave 0 — new |
| SC-7 (regression) | Existing Phase 23, 38, 40 tests pass | regression | `python3 -m pytest tests/test_schematic_repair.py tests/test_erc_auto_fix.py tests/test_place_no_connects_power_aware.py -x` | Existing |

---

## Wave 0 Gaps (must land before implementation tasks)

These test files must exist before implementation tasks run, per TDD discipline:

- `tests/test_schematic_repair.py::test_place_missing_units_no_collisions` — R-2 (SC-2). Build minimal schematic with 2+ instances of same multi-unit component, assert distinct positions.
- `tests/test_erc_auto_fix.py::test_erc_auto_fix_deprecation_warning` — R-3 (SC-4). Assert `warnings.simplefilter("always")` catches `DeprecationWarning` on op execution.
- `tests/test_erc_auto_fix.py::test_erc_auto_fix_registry_deprecated_flag` — R-3 (SC-4). Assert `OPERATION_REGISTRY["erc_auto_fix"].deprecated is True`.
- `tests/test_schematic_repair.py::test_remove_dangling_wires_erc_passthrough` — R-5 (SC-6). Build schematic with known `wire_dangling` pattern, verify ≥90% removal with `trust_erc=True`.
- `tests/test_place_no_connects_power_aware.py::test_no_connect_tolerance_matching` — R-4 (SC-5). Build schematic with pins at sub-0.01mm precision offsets, verify no false `passive` defaults.

---

## Bug Fix Verification Strategy

Each bug fix has a **grep-verifiable acceptance criterion** in its respective plan. Verification path:

| Bug | Grep Pattern | Expected Location |
|-----|--------------|-------------------|
| P0-001 (R-1) | `sym.entryName` (NOT `sym.name`) | `src/kicad_agent/ops/repair_components.py:146` |
| P0-002 (R-2) | Dedup loop OUTSIDE `if pos is None:` block | `src/kicad_agent/ops/repair_components.py` `place_missing_units` |
| P0-003 (R-3) | `deprecated: bool = False` field + `DeprecationWarning` emit | `src/kicad_agent/ops/registry.py` + `erc_auto_fix.py` |
| P0-004 (R-4) | `_lookup_pin_type_with_tolerance()` helper | `src/kicad_agent/ops/repair_erc.py` |
| P0-005 (R-5) | `trust_erc: bool = True` parameter | `src/kicad_agent/ops/repair_wires.py` + `_schema_repair.py` |

---

## Regression Coverage

The following existing test suites MUST remain green after Phase 101:

- `tests/test_schematic_repair.py` — Phase 23 (schematic repair ops)
- `tests/test_schematic_routing.py` — Phase 38 (schematic routing engine)
- `tests/test_erc_smart.py` — Phase 40 (ERC root cause analysis)
- `tests/test_place_no_connects_power_aware.py` — Phase 40 extension
- `tests/test_erc_auto_fix.py` — Phase 23 erc_auto_fix (will gain deprecation tests)

Zero regressions tolerated. Any test that breaks must be fixed in-plan or block the phase.
