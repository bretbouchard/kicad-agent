---
phase: 102-safe-annotate-non-destructive-refdes-renumbering
plan: 01
subsystem: testing
tags: [kicad-10, fixtures, pytest, tdd, raw-sexpr, refdes]

# Dependency graph
requires:
  - phase: 101-schematic-ops-bug-fixes
    provides: P0-005 raw-rewrite pattern (remove_dangling_wires trust_erc) — sibling non-destructive schematic op precedent
provides:
  - "8 RED test stubs (TC-1..TC-8) in tests/test_safe_annotate.py — executable spec for Plan 02/03 to turn GREEN"
  - "5 KiCad 10 fixture schematics under tests/fixtures/safe_annotate/ — minimal single-sheet + multi-sheet project"
  - "H-02 INVARIANT proven: zero (instances ...) blocks across all fixtures (grep returns empty)"
affects:
  - 102-02 (core op implementation — turns TC-1, 2, 5, 6, 7, 8 GREEN)
  - 102-03 (integration tests + docs — turns TC-3, 4 GREEN)

# Tech tracking
tech-stack:
  added: []  # no new deps; pytest 8.4.2 + Python 3.11.11 already configured
  patterns:
    - "RED stubs via NotImplementedError — collection succeeds, all tests fail (TDD Wave 0)"
    - "Function-scoped AST grep stub pattern documented for TC-6 (inspect.getsource(_handle_safe_annotate) per H-01)"
    - "H-02 fixture invariant: omit (instances ...) blocks to prevent silent partial-annotation"

key-files:
  created:
    - tests/test_safe_annotate.py
    - tests/fixtures/safe_annotate/single_sheet_unannotated.kicad_sch
    - tests/fixtures/safe_annotate/single_sheet_annotated_clean.kicad_sch
    - tests/fixtures/safe_annotate/multi_sheet_root.kicad_sch
    - tests/fixtures/safe_annotate/multi_sheet_child_a.kicad_sch
    - tests/fixtures/safe_annotate/multi_sheet_child_b.kicad_sch
  modified: []

key-decisions:
  - "All 5 fixtures omit (instances ...) blocks entirely (H-02 Option A). KiCad netlist exporter reads refdes from (reference ...) inside instances — not from (property \"Reference\" ...). If fixtures inherited them from complete_led.kicad_sch template, the Plan 02 handler would edit property values while leaving stale (reference \"R1\") entries — silent partial-annotation identical to P0-006."
  - "Multi-sheet root fixture has ZERO placed component symbols (only 2 (sheet ...) blocks). This ensures the TC-5 root sheet guard fires correctly: has (sheet ...) blocks (children) + no own components = root sheet."
  - "TC-6 stub documents function-scoped AST grep pattern (inspect.getsource(_handle_safe_annotate)) per H-01 finding. Mirrors tests/test_safe_sync_pcb_from_schematic.py:74-88 exactly. A whole-module walk of handlers/schematic.py would false-positive if any future sibling handler legitimately uses .to_file()."
  - "H-02 Option B (handler co-edits instances blocks for real-world schematics) is DEFERRED-TO-NAMED-TARGET per four-state taxonomy. Trigger: Phase 145 manual verification on analog-board.kicad_sch fails (GNDA rail still collapses after safe_annotate). Visibility: this SUMMARY + ROADMAP Deferred section."

patterns-established:
  - "RED stubs raise NotImplementedError with named plan in message ('Plan 02: ...', 'Plan 03: ...') — makes ownership of each GREEN transition unambiguous"
  - "Test file imports only stdlib (ast, shutil, difflib, pathlib) + pytest at module top; all Plan 02 source imports go inside _execute_op or test bodies (T-102-01-02 mitigate) — collection succeeds even before Plan 02 source exists"
  - "Stable hard-coded UUIDs (aaaaaaaa-0001..0004) — deterministic tests, no random UUIDs"

requirements-completed: [TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7, TC-8]

# Metrics
started: 2026-06-29T22:33:48Z
completed: 2026-06-29T22:38:46Z
duration: 5m
duration_minutes: 5
commits: 2
files_modified: 6
---

# Phase 102 Plan 01: Safe Annotate Test Infrastructure Summary

**8 RED pytest stubs (TC-1..TC-8) + 5 KiCad 10 fixtures (single-sheet + 3-sheet hierarchy) with zero `(instances ...)` blocks — H-02 invariant verified, foundation locked for Plans 02/03**

## Performance

- **Duration:** 5m
- **Started:** 2026-06-29T22:33:48Z
- **Completed:** 2026-06-29T22:38:46Z
- **Tasks:** 2
- **Commits:** 2 (atomic task commits)
- **Files modified:** 6 (1 test file + 5 fixtures)

## Accomplishments

- All 8 required test stubs collectable by pytest — collection succeeds, all 8 fail via NotImplementedError (RED state confirmed: 8 failed in 0.43s)
- 5 KiCad 10 fixture schematics created, all paren-balanced, all parseable by `kicad-cli sch erc` (valid KiCad 10)
- **H-02 INVARIANT PASS:** `grep -r '(instances ' tests/fixtures/safe_annotate/` returns zero matches across all 5 fixtures (Option A applied per Council Gate 1 finding)
- Multi-sheet root fixture has 2 `(sheet ...)` blocks referencing child_a and child_b, ZERO placed components — TC-5 root sheet guard will fire correctly
- Multi-sheet child_a and child_b each contain exactly one `(property "Reference" "R1")` — the cross-sheet duplicate condition for TC-3/TC-4
- No source code mutations outside tests/ — zero changes to src/ (Plan 01 is test-infra only, per success criteria)
- Foundation laid for Plan 02 (makes TC-1, 2, 5, 6, 7, 8 GREEN) and Plan 03 (makes TC-3, 4 GREEN)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create 5 KiCad 10 fixture schematics (NO `(instances ...)` blocks)** — `3e65114f` (test)
2. **Task 2: Create tests/test_safe_annotate.py with 8 RED test stubs** — `5c9129d6` (test)

_Note: This plan is Wave 0 (test infrastructure). Tasks are TDD-typed but Wave 0 produces only RED stubs — Plans 02 and 03 drive the GREEN transitions per the canonical TDD cycle._

## Files Created/Modified

- `tests/test_safe_annotate.py` — 8 RED test stubs (TC-1 idempotency, TC-2 single rename, TC-3 cross-sheet dedup, TC-4 P0-006 regression, TC-5 root guard, TC-6 kiutils avoidance via function-scoped AST grep, TC-7 paren balance, TC-8 registration). Module-top imports limited to stdlib + pytest; Plan 02 source imports are lazy inside `_execute_op` (collection-safe).
- `tests/fixtures/safe_annotate/single_sheet_unannotated.kicad_sch` — one placed Device:R with `(property "Reference" "R?")` at (50, 50, 0), UUID `aaaaaaaa-0001-0000-0000-000000000001`. For TC-1, TC-2.
- `tests/fixtures/safe_annotate/single_sheet_annotated_clean.kicad_sch` — identical to unannotated but Reference is "R1" (already annotated). For TC-1 idempotency (dry_run on clean → annotated: []).
- `tests/fixtures/safe_annotate/multi_sheet_root.kicad_sch` — root sheet with 2 `(sheet ...)` blocks (UUIDs bbbbbbbb-0001/0002) referencing child_a and child_b via `(property "Sheetfile" ...)`. ZERO placed component symbols. For TC-3, TC-4, TC-5.
- `tests/fixtures/safe_annotate/multi_sheet_child_a.kicad_sch` — child sheet with one placed Device:R, `(property "Reference" "R1")`, UUID `aaaaaaaa-0003-...`.
- `tests/fixtures/safe_annotate/multi_sheet_child_b.kicad_sch` — child sheet with one placed Device:R, `(property "Reference" "R1")` (duplicate — the bug condition), UUID `aaaaaaaa-0004-...`.

## Decisions Made

- **H-02 Option A (fixtures omit `(instances ...)`)** chosen over Option B (handler co-edits instances). Rationale: Phase 102 ships on minimal fixtures; Option B is straightforward to add later if real-world schematics require it. Option B is DEFERRED-TO-NAMED-TARGET with concrete trigger (Phase 145 manual verification failure on analog-board.kicad_sch). Per four-state taxonomy §7.
- **Multi-sheet root has empty `(lib_symbols)` block.** Rationale: root sheet has no placed components of its own, so no lib_symbols needed. KiCad 10 accepts an empty `(lib_symbols)` container. This keeps the root fixture minimal while remaining parseable.
- **Test file uses module-top stdlib imports only.** Rationale: T-102-01-02 mitigation — lazy imports inside `_execute_op` mean pytest collection succeeds in Plan 01 (before Plan 02 source exists), making the RED state observable. Top-level imports of Plan 02 modules would have broken collection.
- **All UUIDs hard-coded and deterministic.** Rationale: test reproducibility — future runs see identical UUIDs, no random variation. Pattern: `aaaaaaaa-000N-0000-0000-00000000000N` for symbols, `bbbbbbbb-000N-...` for sheets, `cccccccc-...` for pins.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Commit message subject casing rejected by commit-msg hook**
- **Found during:** Task 1 commit attempt
- **Issue:** First commit attempt with subject `test(102): add 5 KiCad 10 fixtures for safe_annotate test suite` was rejected by the conventional commits validator — the validator requires lowercase subjects and "KiCad" contains uppercase letters
- **Fix:** Retried with subject `test(102): add 5 kicad 10 fixtures for safe_annotate test suite` (lowercased "kicad"). Body content moved to this SUMMARY instead (the body also tripped the validator on paragraph-initial capitalized tokens like "Council")
- **Files modified:** None (commit message only)
- **Verification:** Commit `3e65114f` succeeded on retry
- **Committed in:** N/A (process fix)

---

**Total deviations:** 1 auto-fixed (1 blocking — commit message formatting)
**Impact on plan:** Zero scope creep. Commit content unchanged; only the commit message subject was reformatted to satisfy the project's conventional commits hook.

## Issues Encountered

- Initial `python3 -m pytest` invocation picked up the system `/Applications/Xcode.app/.../python3.9` with an incompatible urllib3/OpenSSL, causing a collection-time traceback. Resolved by using the project's pyenv-installed Python 3.11.11 directly (`~/.pyenv/versions/3.11.11/bin/python3.11 -m pytest`). This is the same interpreter described in CLAUDE.md (Python 3.11.11). Not a code issue — environment shell configuration.

## Threat Flags

None. All files created are test fixtures and a test stub file — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. The threat surface for Plan 01 is entirely test-side (T-102-01-01 through T-102-01-03 in the plan's threat model — all mitigated as documented).

## Known Stubs

All 8 tests in `tests/test_safe_annotate.py` are intentional RED stubs (NotImplementedError). This is the explicit purpose of Plan 01 — lock the contract before implementation. Each stub names the plan that will turn it GREEN:

| Test | Stub Body | GREEN Plan |
|------|-----------|------------|
| test_idempotency_clean_schematic (TC-1) | `raise NotImplementedError("Plan 02: wire to safe_annotate op")` | 102-02 |
| test_single_rename_current_sheet (TC-2) | `raise NotImplementedError("Plan 02: wire to safe_annotate op")` | 102-02 |
| test_cross_sheet_dedup_whole_project (TC-3) | `raise NotImplementedError("Plan 03: integration test with multi-sheet fixtures")` | 102-03 |
| test_p0_006_regression_no_reserialization (TC-4) | `raise NotImplementedError("Plan 03: diff assertion test")` | 102-03 |
| test_root_sheet_guard_refuses (TC-5) | `raise NotImplementedError("Plan 02: wire to safe_annotate op")` | 102-02 |
| test_handler_does_not_use_kiutils_to_file (TC-6) | `raise NotImplementedError("Plan 02: function-scoped AST grep test via inspect.getsource")` | 102-02 |
| test_paren_balance_preserved (TC-7) | `raise NotImplementedError("Plan 02: paren balance test")` | 102-02 |
| test_safe_annotate_registered (TC-8) | `raise NotImplementedError("Plan 02: registration test")` | 102-02 |

## User Setup Required

None — no external service configuration required. Fixtures are committed test artifacts; pytest configuration is unchanged.

## Next Phase Readiness

- Plan 02 can begin immediately — all 8 stubs are in place, all 5 fixtures are valid KiCad 10, H-02 invariant is locked in
- Plan 02 will add `SchematicRawWriter.replace_reference_property`, `SafeAnnotateOp` schema, `_handle_safe_annotate` handler, SELF_SERIALIZING_OPS registration, and turn TC-1, 2, 5, 6, 7, 8 GREEN
- Plan 03 will add the multi-sheet integration tests (TC-3, TC-4) requiring `kicad-cli sch export netlist` — already verified available at `/usr/local/bin/kicad-cli` (KiCad 10.0.1)
- H-02 Option B remains DEFERRED-TO-NAMED-TARGET — no work required unless Phase 145 manual verification fails

## TDD Gate Compliance

**Wave 0 note:** This plan is the RED-gate foundation for the phase. Per the plan's `<objective>`: "All tests start RED (NotImplementedError or assertion failure). Plan 02 turns TC-1, TC-2, TC-5, TC-6, TC-7, TC-8 GREEN; Plan 03 turns TC-3, TC-4 GREEN."

RED gate commit: `5c9129d6` (test) — 8 stubs committed, all fail via NotImplementedError.
GREEN gate commits: deferred to Plan 02 (expected) and Plan 03 (expected).

No TDD gate violation — the plan explicitly defers GREEN to subsequent plans per Wave 0 methodology.

## Self-Check: PASSED

- 7 files verified present (1 test file + 5 fixtures + 1 SUMMARY)
- 2 commits verified in git log (`3e65114f`, `5c9129d6`)
- All 5 fixtures paren-balanced and `(instances ...)`-free (H-02)
- All 8 tests collected by pytest; all 8 RED via NotImplementedError

---
*Phase: 102-safe-annotate-non-destructive-refdes-renumbering*
*Plan: 01 of 03*
*Completed: 2026-06-29*
