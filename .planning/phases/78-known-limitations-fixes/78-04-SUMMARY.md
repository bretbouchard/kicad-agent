---
phase: 78-known-limitations-fixes
plan: 04
subsystem: parser, routing
tags: [parser-warnings, unsupported-elements, via-optimization, documentation]

# Dependency graph
requires: []
provides:
  - _UNSUPPORTED_ELEMENTS frozenset constant in pcb_native_parser.py
  - _check_unsupported() warning logging helper
  - Warning emission for unsupported PCB elements during parsing
  - Enhanced via_cost_mm docstring documenting optimization gaps
  - 16 tests for constant membership, warning behavior, and helper function
affects: [routing, parser, documentation]

# Tech tracking
tech-stack:
  added: []
  patterns: [unsupported-element-warning-pattern, module-level-optimization-status-comment]

key-files:
  created:
    - tests/test_parser_warnings.py
  modified:
    - src/kicad_agent/parser/pcb_native_parser.py
    - src/kicad_agent/routing/constraints.py

key-decisions:
  - "Used _KNOWN_TOP_LEVEL set to distinguish known vs unknown blocks, avoiding false positives on nested elements"
  - "Added _check_unsupported as module-level function (not method) for testability"
  - "Module-level comment for via optimization status rather than inline on field (visibility)"

patterns-established:
  - "Unsupported element detection: frozenset constant + logging helper wired at dispatch point"

requirements-completed: [DOC-01, DOC-02]

# Metrics
started: 2026-06-07T05:08:23Z
completed: 2026-06-07T05:20:53Z
duration: 12m
duration_minutes: 12
commits: 2
files_modified: 3
---

# Phase 78 Plan 04: Parser Unsupported Element Warnings and Via Docs Summary

**_UNSUPPORTED_ELEMENTS frozenset with 9 PCB element types, parser warning logging at dispatch, and via_cost_mm optimization gap documentation**

## Performance

- **Duration:** 12m
- **Started:** 2026-06-07T05:08:23Z
- **Completed:** 2026-06-07T05:20:53Z
- **Tasks:** 2
- **Commits:** 2 (atomic task commits)
- **Files modified:** 3

## Accomplishments
- Added `_UNSUPPORTED_ELEMENTS` frozenset constant listing 9 unsupported PCB element types (thermal_relief_pads, keepout_areas, soldermask_expansion, paste_expansion, courtyard, fp_text, 3d_model_refs, page_info, title_block)
- Added `_check_unsupported()` helper function that logs warnings via `logger.warning` with element name, optional context, and reference to the constant for discoverability
- Wired `_check_unsupported` into `_build_board()` dispatch flow using a `_KNOWN_TOP_LEVEL` set to avoid false positives on nested elements
- Enhanced `RoutingConstraints` docstring with detailed `via_cost_mm` documentation including current optimization level, missing algorithms, and Freerouting delegation
- Added module-level "Via Optimization Status" comment block documenting the static per-via cost approach
- 16 tests covering constant membership, warning emission, helper function behavior, and context inclusion

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _UNSUPPORTED_ELEMENTS constant and warning logging to native parser** - `48d222f` (feat)
2. **Task 2: Enhance via_cost_mm docstring with optimization gap documentation** - `b03c33d` (docs)

## Files Created/Modified
- `src/kicad_agent/parser/pcb_native_parser.py` - Added _UNSUPPORTED_ELEMENTS constant (9 elements), _check_unsupported() helper, and dispatch wiring in _build_board()
- `src/kicad_agent/routing/constraints.py` - Enhanced via_cost_mm Attributes docstring, added module-level Via Optimization Status comment
- `tests/test_parser_warnings.py` - 16 tests: 10 constant membership tests, 2 warning emission tests, 4 helper function tests

## Decisions Made
- Used a `_KNOWN_TOP_LEVEL` set within `_build_board()` to distinguish known dispatched blocks from unknown ones, avoiding false positives on nested elements (e.g., `net` inside footprints is valid, only top-level unknown blocks trigger warnings)
- Added `_check_unsupported` as a module-level function rather than a method on `NativeParser` for direct testability and reusability
- Module-level comment block for via optimization status rather than extending the class docstring further (the dataclass `__init__` docstring generation already truncates long class docstrings; module-level comments are reliably visible)

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

- RED: Tests created first, failed with `ImportError: cannot import name '_UNSUPPORTED_ELEMENTS'` (test file cannot even be collected without the implementation)
- GREEN: Implementation added, all 16 tests pass
- Note: RED and GREEN committed together because the test file has import errors (not test failures) that prevent a valid standalone RED commit

## Known Stubs

None.

## Self-Check: PASSED

- [x] `src/kicad_agent/parser/pcb_native_parser.py` contains `_UNSUPPORTED_ELEMENTS` (verified via 10 tests)
- [x] `src/kicad_agent/parser/pcb_native_parser.py` contains `_check_unsupported` function (verified via 4 tests)
- [x] `src/kicad_agent/routing/constraints.py` contains enhanced `via_cost_mm` docstring (verified via source read)
- [x] `tests/test_parser_warnings.py` exists with 16 tests (verified via pytest)
- [x] Commit `48d222f` exists (verified via git log)
- [x] Commit `b03c33d` exists (verified via git log)

---
*Phase: 78-known-limitations-fixes*
*Plan: 04*
*Completed: 2026-06-07*
