---
phase: 101-schematic-ops-bug-fixes
plan: 01
subsystem: ops/registry
tags: [deprecation, registry, erc-auto-fix, p0-003]
dependency_graph:
  requires: []
  provides:
    - "OpMeta.deprecated field (bool, default False)"
    - "deprecated=True metadata on erc_auto_fix + erc_auto_fix_hierarchical"
    - "Runtime DeprecationWarning at both handler entry points"
  affects:
    - "src/kicad_agent/ops/registry.py (OpMeta schema + 2 catalog entries)"
    - "src/kicad_agent/ops/erc_auto_fix.py (handler entry points)"
tech_stack:
  added: []
  patterns:
    - "Pydantic model field addition with default for backward compat"
    - "Runtime DeprecationWarning with stacklevel=2 for caller attribution"
key_files:
  created: []
  modified:
    - "src/kicad_agent/ops/registry.py"
    - "src/kicad_agent/ops/erc_auto_fix.py"
    - "tests/test_erc_auto_fix.py"
decisions:
  - "D-2 (locked): Deprecate only this phase — full raw S-expr rewrite deferred to follow-up"
  - "Added `deprecated: bool = False` field to OpMeta (vs description-string prefix) for type safety and queryability"
  - "Warning fires at handler entry, before any file mutation, so callers see it even if op later fails"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-25"
  tasks: 2
  files: 3
  tests_added: 6
---

# Phase 101 Plan 01: Deprecate erc_auto_fix Ops Summary

Added `deprecated` field to OpMeta and marked both `erc_auto_fix` and `erc_auto_fix_hierarchical` as deprecated with runtime DeprecationWarning emission at handler entry, preventing ongoing KiCad 10 data-loss corruption (P0-003) while the raw S-expr rewrite is deferred.

## What Was Built

**OpMeta schema extension** (`registry.py`):
- Added `deprecated: bool = False` field to the Pydantic `OpMeta` model after `conflicts`. Default False preserves backward compatibility for all 98+ existing ops.
- Marked `"deprecated": True` on both `_RAW_CATALOG["erc_auto_fix"]` and `_RAW_CATALOG["erc_auto_fix_hierarchical"]`.
- Registry population (`OpMeta(op_type=k, **data)`) picks up the new field automatically — no changes to iteration/construction logic needed.

**Runtime deprecation warnings** (`erc_auto_fix.py`):
- Added `import warnings` at module top-level.
- Inserted `warnings.warn(..., DeprecationWarning, stacklevel=2)` at the TOP of `erc_auto_fix()` (after docstring, before `mode == "root_cause"` dispatch).
- Inserted identical warning at the TOP of `erc_auto_fix_hierarchical()` (after docstring, before `parse_schematic` import).
- Warning message contains "DEPRECATED", "P0-003", alternative op recommendations, and a `BUGS/P0-003.md` reference.
- `stacklevel=2` ensures the warning points to the CALLER, not the handler.

**Test coverage** (`test_erc_auto_fix.py`):
- `TestOpMetaDeprecatedField` — 4 tests covering field existence, default False, both target ops marked True, and 5 sample non-target ops remain False.
- `TestErcAutoFixDeprecationWarning` — 2 tests covering both handlers emit DeprecationWarning with required message content ("DEPRECATED" + "P0-003"), using `warnings.catch_warnings(record=True)` pattern.

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| Task 1 tests | `pytest tests/test_erc_auto_fix.py -k "deprecated or opmeta"` | 4 passed |
| Task 2 tests | `pytest tests/test_erc_auto_fix.py -k "deprecation_warning"` | 2 passed |
| Full erc_auto_fix suite | `pytest tests/test_erc_auto_fix.py` | 30 passed, 0 failed |
| Sibling regression | `pytest tests/test_schematic_repair.py tests/test_place_no_connects_power_aware.py` | 92 passed, 1 skipped, 8 expected DeprecationWarnings |
| deprecated=True count | `grep -c '"deprecated": True' registry.py` | 2 (exactly the two target ops) |

The 8 DeprecationWarnings in sibling tests are expected — they come from existing tests that call the now-deprecated `erc_auto_fix`. This confirms the warning fires correctly in real usage.

## Deviations from Plan

None — plan executed exactly as written.

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (Task 1) | `566488a` test(101-01): add failing tests for OpMeta deprecated field | PASS — tests failed before implementation |
| GREEN (Task 1) | `b31be4b` feat(101-01): add deprecated field to OpMeta + mark erc_auto_fix ops | PASS — tests pass after implementation |
| RED (Task 2) | `c4bdde6` test(101-01): add failing tests for erc_auto_fix DeprecationWarning | PASS — tests failed before implementation |
| GREEN (Task 2) | `497a249` feat(101-01): emit DeprecationWarning at erc_auto_fix entry points | PASS — tests pass after implementation |

No REFACTOR gate needed — implementation is minimal and clean.

## Self-Check: PASSED

- [x] `src/kicad_agent/ops/registry.py` contains `deprecated: bool = False` in OpMeta
- [x] `src/kicad_agent/ops/registry.py` contains exactly 2 `"deprecated": True` catalog entries
- [x] `src/kicad_agent/ops/erc_auto_fix.py` contains 2 `warnings.warn(..., DeprecationWarning)` calls
- [x] `tests/test_erc_auto_fix.py` contains `test_erc_auto_fix_registry_deprecated_flag`
- [x] `tests/test_erc_auto_fix.py` contains `test_erc_auto_fix_hierarchical_registry_deprecated_flag`
- [x] `tests/test_erc_auto_fix.py` contains `test_erc_auto_fix_emits_deprecation_warning`
- [x] `tests/test_erc_auto_fix.py` contains `test_erc_auto_fix_hierarchical_emits_deprecation_warning`
- [x] Commit `566488a` exists (RED Task 1)
- [x] Commit `b31be4b` exists (GREEN Task 1)
- [x] Commit `c4bdde6` exists (RED Task 2)
- [x] Commit `497a249` exists (GREEN Task 2)
- [x] All 30 test_erc_auto_fix.py tests pass
- [x] Zero regression on sibling test files (92 passed, 1 skipped)
