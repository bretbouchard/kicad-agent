---
phase: 102-safe-annotate-non-destructive-refdes-renumbering
plan: 03
subsystem: ops
tags: [kicad-10, refdes, raw-sexpr, p0-006, multi-sheet, deprecation, api-docs]

# Dependency graph
requires:
  - phase: 102-02
    provides: "working safe_annotate op (handler + schema + SELF_SERIALIZING_OPS + registry)"
provides:
  - "TC-3 GREEN — cross-sheet dedup proven on minimal multi-sheet fixtures (2 sheets, 2 duplicate refs)"
  - "TC-4 GREEN — P0-006 regression bound (total_changed_lines <= refs_renamed * 4 + 4)"
  - "Root sheet guard refined: fires only for current_sheet scope (whole_project walks children)"
  - "Cross-component dedup detection under reset mode (stats.duplicates_resolved populated correctly)"
  - "docs/api/safe_annotate.md published with 6-field request schema, response schema, 3 examples, error cases"
  - "BUGS/P0-006 formally closed: RESOLVED callout, item 3 DELIVERED, Workaround points to safe_annotate"
  - "_handle_annotate emits DeprecationWarning at entry pointing to safe_annotate + P0-006"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reset-mode dedup detection via pre-pass Counter on original refs — subsequent owners of a duplicate ref are marked deduped=True so stats.duplicates_resolved counts them"
    - "Scope-conditional root sheet guard: only current_sheet scope triggers the guard; whole_project is the correct way to annotate a root (walks children)"
    - "DeprecationWarning at handler entry (mirrors erc_auto_fix.py:255-262) — fires BEFORE any file mutation, stacklevel=2 points to caller"

key-files:
  created:
    - docs/api/safe_annotate.md
    - BUGS/P0-006-annotate-corrupts-files.md
  modified:
    - tests/test_safe_annotate.py
    - src/kicad_agent/ops/handlers/schematic.py

key-decisions:
  - "Rule 1 bug (root sheet guard): original guard fired unconditionally on any root sheet. But CONTEXT.md LOCKED API contract says whole_project scope WALKS children when given a root — so the guard must only fire for current_sheet scope on a root. TC-3 was blocked until this fix. Refined to `if op.scope == 'current_sheet' and has_sheet_blocks and not has_placed_components`."
  - "Rule 1 bug (reset-mode dedup tracking): original _build_rename_plan only set `deduped=True` in the non-reset branch. Under reset=True, all refs become `<prefix>?` so they all hit the annotation branch — but the original duplicate relationship was lost. TC-3 reported `duplicates_resolved=0` despite renaming one of two R1's. Fixed via pre-pass Counter on original refs: any ref appearing 2+ times in annotatable components is added to original_dup_refs; subsequent owners (after sort) are marked deduped=True."
  - "Docs use generic my_project.kicad_sch path per L-04 finding (Council Gate 1). Original plan suggested analog-board.kicad_sch which lives in external repo (analog-ecosystem) and would confuse users."
  - "DeprecationWarning pattern mirrors erc_auto_fix exactly (stacklevel=2, points to caller not handler). Message references both BUGS/P0-006 and docs/api/safe_annotate.md so users have both the why and the how."
  - "BUGS/P0-006 was previously untracked (created in earlier session but never committed). Committed in Task 2 alongside the Fix path / Workaround updates."

patterns-established:
  - "Pre-pass Counter for cross-component duplicate detection — useful any time stats need to reflect relationships in the ORIGINAL data after a reset transform"
  - "Scope-conditional guards: when an op has both narrow and wide scope, guards should fire only when the narrow scope is requested; wide scope is the expected path for the data shape the guard rejects"

requirements-completed: [TC-3, TC-4]

# Metrics
started: 2026-06-29T23:02:00Z
completed: 2026-06-29T23:05:26Z
duration: 3m
duration_minutes: 3
commits: 2
files_modified: 5
---

# Phase 102 Plan 03: Safe Annotate Integration Tests + Docs + Deprecation Summary

**TC-3/TC-4 GREEN via 2 Rule 1 handler fixes (scope-conditional guard + reset-mode dedup), API docs published, P0-006 formally closed, forbidden annotate op deprecated. Phase 102 ready for /gsd-verify-work.**

## Performance

- **Duration:** 3m
- **Started:** 2026-06-29T23:02:00Z
- **Completed:** 2026-06-29T23:05:26Z
- **Tasks:** 2
- **Commits:** 2 (atomic task commits)
- **Files modified:** 5 (2 source + 1 test + 1 docs + 1 BUGS)

## Accomplishments

- All 8 safe_annotate tests now GREEN (was 6 GREEN + 2 RED stubs)
- TC-3 (cross-sheet dedup): 3-file multi-sheet fixture, whole_project+reset, asserts duplicates_resolved >= 1, paren balance on both children, root unchanged, kicad-cli sch erc parses both children (returncode <= 1)
- TC-4 (P0-006 regression): asserts total_changed_lines <= refs_renamed * 4 + 4 (P0-006 produced 2314 changed lines on similar file; safe_annotate produces ~2 per ref). Failure message explicitly diagnoses SELF_SERIALIZING_OPS membership or to_file calls.
- docs/api/safe_annotate.md published with 6-field request schema, response schema, 3 examples (dry-run, single-sheet, whole-project dedup), error cases, and validation summary referencing TC-1 through TC-8
- BUGS/P0-006 formally closed: RESOLVED callout at top of Fix path, item 3 marked DELIVERED (Phase 102), Workaround leads with safe_annotate example invocation
- _handle_annotate emits DeprecationWarning at entry pointing to safe_annotate + P0-006 + docs/api/safe_annotate.md (mirrors erc_auto_fix.py:255-262)
- Zero regressions: 17/17 sibling tests (test_safe_sync_pcb_from_schematic.py + test_schematic_raw_writer.py) still pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Make TC-3/TC-4 GREEN + Rule 1 handler fixes** — `6832ef09` (feat)
2. **Task 2: API docs + BUGS/P0-006 closure + DeprecationWarning** — `39d85ff8` (docs)

## Files Created/Modified

- `tests/test_safe_annotate.py` — replaced 2 NotImplementedError stubs (TC-3, TC-4) with real test bodies. TC-3 copies 3-file project to tmpdir, runs whole_project+reset, asserts duplicates_resolved >= 1, paren balance on both children, root unchanged, kicad-cli parses both children. TC-4 computes difflib.unified_diff per file and asserts total_changed_lines <= refs_renamed * 4 + 4 with diagnostic message on failure.
- `src/kicad_agent/ops/handlers/schematic.py` — 3 edits: (1) root sheet guard refined to `if op.scope == "current_sheet" and has_sheet_blocks and not has_placed_components` (was unconditional). (2) `_build_rename_plan` pre-pass Counter detects cross-component duplicate original refs; subsequent owners marked `deduped=True` under reset mode. (3) `_handle_annotate` emits DeprecationWarning at entry (stacklevel=2, message references P0-006 + safe_annotate docs).
- `docs/api/safe_annotate.md` — NEW: full API reference. Overview + 6-field request schema table + response schema + 3 examples + 2 error cases + P0-006 link + validation summary (TC-1 through TC-8 + Phase 145 deferral note per H-03).
- `BUGS/P0-006-annotate-corrupts-files.md` — NEW (was untracked): full P0-006 report + Fix path with RESOLVED callout + Workaround leading with safe_annotate example.

## Decisions Made

- **Rule 1 (root sheet guard):** The LOCKED API contract says `scope=whole_project` walks children when given a root sheet. The original guard fired unconditionally on any root, blocking TC-3. Refined to scope-conditional: `if op.scope == "current_sheet" and has_sheet_blocks and not has_placed_components`. This preserves the guard's purpose (refusing `current_sheet` annotation on a root, which would be a no-op) while unblocking the correct usage pattern.
- **Rule 1 (reset-mode dedup tracking):** Under `reset=True`, all refs become `<prefix>?` and enter the annotation branch. The non-reset dedup path (`if old_ref in used_refs`) never fires because all refs start fresh. The plan/test contract says `stats.duplicates_resolved` should count cross-sheet duplicates resolved — so the pre-pass Counter approach was needed: count original refs before reset, mark subsequent owners of any duplicate as `deduped=True`. This produces correct stats without changing the assignment algorithm.
- **L-04 finding (docs path):** Plan 102-03 Task 2 originally suggested `analog-board.kicad_sch` as Example 3 path. Council Gate 1 L-04 finding flagged this as confusing (analog-board lives in external analog-ecosystem repo). Switched all examples to generic `my_project.kicad_sch` with a note that the path is illustrative.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Root sheet guard blocked whole_project scope**
- **Found during:** Task 1 (TC-3 first run — ValueError instead of duplicate resolution)
- **Issue:** Guard fired unconditionally: `if has_sheet_blocks and not has_placed_components: raise ValueError(...)`. But TC-3 passes the root sheet as target with `scope="whole_project"`, which is the correct usage — the handler walks children. The guard was rejecting the correct path.
- **Fix:** Refined condition to `if op.scope == "current_sheet" and has_sheet_blocks and not has_placed_components`. Guard now fires only for the genuinely incorrect usage (current_sheet on a root, which would no-op).
- **Files modified:** `src/kicad_agent/ops/handlers/schematic.py`
- **Verification:** TC-3 now proceeds past the guard; whole_project walks both children; one R1 renamed.
- **Committed in:** `6832ef09`

**2. [Rule 1 - Bug] Reset-mode dedup not detected in stats**
- **Found during:** Task 1 (TC-3 after guard fix — duplicates_resolved=0 despite renaming one of two R1's)
- **Issue:** `_build_rename_plan` only set `deduped=True` in the non-reset dedup branch. Under `reset=True`, all refs become `<prefix>?` and enter the annotation branch — bypassing the dedup detection. TC-3 reported `duplicates_resolved=0` which made the test assertion fail.
- **Fix:** Added pre-pass: `Counter(c["ref"] for c in annotatable if c["ref"])` identifies refs that appear 2+ times. After sort, the first owner keeps the original ref (as `<prefix>?` → first sequential number); subsequent owners are marked `deduped=True` so `stats.duplicates_resolved` counts them correctly.
- **Files modified:** `src/kicad_agent/ops/handlers/schematic.py`
- **Verification:** TC-3 now reports `duplicates_resolved=1` (one of two R1's renamed to R2). TC-4 unaffected (still asserts total_changed_lines <= 4 = 1*4+4).
- **Committed in:** `6832ef09`

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs — handler logic gaps not anticipated by the plan)
**Impact on plan:** Zero scope creep. Both fixes are correctness requirements directly caused by this plan's test assertions.

## Issues Encountered

None beyond the two Rule 1 bugs above. Commit message validator accepted the multi-`-m` flag format used throughout Phase 102 (same workaround as Plans 01/02).

## Threat Flags

None. All files created/modified are within the plan's documented threat model (T-102-03-01 regression bound, T-102-03-02 deprecation warning, T-102-03-03 docs accuracy). The two Rule 1 fixes strengthen T-102-03-01 (TC-3 now actually exercises dedup; TC-4 bound still enforced) and do not introduce new threat surface.

## Known Stubs

None. All 8 tests are GREEN. TC-3 and TC-4 stubs (NotImplementedError from Plan 01) have real test bodies. No production code stubs were introduced.

The H-03 deferral (real-world multi-sheet validation at scale — 47+ cross-sheet duplicates across 16 sub-sheets) is documented in the plan and reflected in the success criteria: "proven on minimal multi-sheet fixtures; full real-world validation deferred to Phase 145 manual verification per VALIDATION.md line 69." The minimal fixtures prove the MECHANISM; the analog-board use case proves the SCALE.

## User Setup Required

None — no external service configuration required. All tests run via pytest with local fixtures. kicad-cli 10.0.3 verified available at `/usr/local/bin/kicad-cli`.

## Next Phase Readiness

- Phase 102 is ready for `/gsd-verify-work` — all 8 LOCKED/supporting tests GREEN, docs published, bug formally closed
- Council Gate 2 (Execution Review) is the next gate per bureaucracy §7.5
- H-03 (real-world multi-sheet validation at scale) remains DEFERRED-TO-NAMED-TARGET — trigger: Phase 145 manual verification on `analog-board.kicad_sch`
- H-02 Option B (handler co-edits `(instances ...)` blocks for real-world schematics) remains DEFERRED-TO-NAMED-TARGET — same trigger as H-03

## TDD Gate Compliance

- Task 1 (tdd="true"): TC-3 and TC-4 transitioned from RED (NotImplementedError in Plan 01) to GREEN (real test bodies). RED gate commit `5c9129d6` (Plan 01); GREEN gate commit `6832ef09` (this plan). Rule 1 handler fixes applied during GREEN transition are correctness requirements surfaced by the test assertions — not plan deviations.
- Task 2: No TDD gate (docs + BUGS + deprecation warning are not behavior changes). Verification via Python assertions + grep.

Both tasks have appropriate gate commits. No gate violations.

## Self-Check: PASSED

- 5 files verified present (1 test + 1 source + 1 docs + 1 BUGS + 1 SUMMARY)
- 2 commits verified in git log (`6832ef09`, `39d85ff8`)
- 8/8 safe_annotate tests GREEN
- 17/17 sibling tests GREEN (zero regression)
- DeprecationWarning fires (grep returns 1 match in handlers/schematic.py)
- Docs exist and reference safe_annotate
- BUGS/P0-006 contains safe_annotate + DELIVERED

**Self-Check Result: PASSED** — all files exist on disk, both commit hashes present in git log, verified 2026-06-29T23:06:00Z.

---
*Phase: 102-safe-annotate-non-destructive-refdes-renumbering*
*Plan: 03 of 03*
*Completed: 2026-06-29*
