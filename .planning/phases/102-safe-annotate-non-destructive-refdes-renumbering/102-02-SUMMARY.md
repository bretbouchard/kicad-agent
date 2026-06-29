---
phase: 102-safe-annotate-non-destructive-refdes-renumbering
plan: 02
subsystem: ops
tags: [kicad-10, refdes, raw-sexpr, self-serializing, p0-006, ast-grep]

# Dependency graph
requires:
  - phase: 102-01
    provides: "8 RED test stubs (TC-1..TC-8) + 5 KiCad 10 fixtures"
provides:
  - "safe_annotate op fully functional for current_sheet scope and dry_run"
  - "SchematicRawWriter.replace_reference_property static method (UUID-targeted raw Reference value replacement)"
  - "SafeAnnotateOp Pydantic schema (6 fields, LOCKED defaults)"
  - "SELF_SERIALIZING_OPS membership for safe_annotate (bypasses kiutils serialize_schematic)"
  - "Root sheet guard with LOCKED error message"
  - "Function-scoped AST grep proof (H-01): zero to_file Call nodes in _handle_safe_annotate"
affects:
  - 102-03 (integration tests + docs — turns TC-3, TC-4 GREEN)

# Tech tracking
tech-stack:
  added: []  # no new deps; pydantic + re + pathlib all existing
  patterns:
    - "SELF_SERIALIZING_OPS bypass with inline M-01 comment (P0-006 rationale documented in code)"
    - "Function-scoped AST grep via inspect.getsource (H-01) — NOT whole-module walk"
    - "Lazy cross-handler import (M-02): validate_paren_balance imported inside handler body"
    - "UUID regex accepts both KiCad 10 unquoted (uuid abc) and legacy quoted (uuid \"abc\") forms"
    - "Tie-break docstring (M-03): _build_rename_plan documents sort key for all 3 order options"

key-files:
  created:
    - tests/test_schematic_raw_writer.py
  modified:
    - src/kicad_agent/ops/schematic_raw_writer.py
    - src/kicad_agent/ops/_schema_reference.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/execution.py
    - src/kicad_agent/ops/registry.py
    - src/kicad_agent/ops/handlers/schematic.py
    - tests/test_safe_annotate.py

key-decisions:
  - "Rule 1 bug fixed during execution: UUID regex originally expected quoted form (uuid \"abc\") but KiCad 10 fixtures use unquoted form (uuid abc). Made regex accept both via \"?...\"? optional-quote pattern. Applied to both _extract_symbols_with_refs and SchematicRawWriter.replace_reference_property."
  - "schema.py re-exports SafeAnnotateOp in three locations (import block line 191, union line 396, __all__ line 566) mirroring AnnotateOp placement — keeps the schema union exhaustive so Operation.model_validate accepts safe_annotate payloads."
  - "Test invocation uses OperationExecutor(base_dir=tmp_path) + Operation.model_validate({'root': {...}}) + executor.execute(op). target_file is relative basename; path confinement check requires base_dir containment. Mirrors tests/test_modify_property.py:266-282 sibling pattern."
  - "M-01 inline comment placed on a single line containing literal 'MUST bypass serialize_schematic()' (not split across lines) so the grep done criterion matches character-for-character."

patterns-established:
  - "safe_annotate mirrors safe_sync_pcb_from_schematic raw-edit pattern but uses SELF_SERIALIZING_OPS (single_file scope) instead of CROSS_FILE_OP_TYPES (multi-file scope) — different dispatch paths for different file-scope semantics"
  - "Component extraction regex: placed symbols must have (lib_id \"...\") AND (at X Y) — filters out lib_symbol definitions which use (symbol \"Name\" ...) form"
  - "Power symbols (#PWR?, #PWR01) skipped via ref.startswith('#') filter — KiCad manages them separately"

requirements-completed: [TC-1, TC-2, TC-5, TC-6, TC-7, TC-8]

# Metrics
started: 2026-06-29T22:46:23Z
completed: 2026-06-29T22:56:00Z
duration: 9m
duration_minutes: 9
commits: 3
files_modified: 8
---

# Phase 102 Plan 02: Safe Annotate Core Op Implementation Summary

**safe_annotate op ships end-to-end: schema + SELF_SERIALIZING_OPS registration + registry entry + raw-edit handler + 6 GREEN tests (TC-1, 2, 5, 6, 7, 8). Zero kiutils re-serialization, function-scoped AST-proven.**

## Performance

- **Duration:** 9m
- **Started:** 2026-06-29T22:46:23Z
- **Completed:** 2026-06-29T22:56:00Z
- **Tasks:** 3
- **Commits:** 3 (atomic task commits)
- **Files modified:** 8 (5 source + 2 test + 1 schema re-export)

## Accomplishments

- safe_annotate op fully functional for `scope="current_sheet"` and `dry_run=true` (TC-1, TC-2 GREEN)
- Root sheet guard fires with exact LOCKED error message when target is a hierarchy-only root sheet (TC-5 GREEN)
- Function-scoped AST grep (H-01) PROVES zero `to_file` Call nodes in `_handle_safe_annotate` source via `inspect.getsource` — not a whole-module walk (TC-6 GREEN)
- Paren balance preserved after every edit (TC-7 GREEN)
- Op registered in `SELF_SERIALIZING_OPS`, `OPERATION_REGISTRY`, and `SafeAnnotateOp` exported from schema.py (TC-8 GREEN)
- 5 new unit tests for `SchematicRawWriter.replace_reference_property` — basic replacement, UUID targeting (duplicate dedup), not-found no-op, byte-preservation (difflib), quote rejection (T-102-02-01)
- TC-3 and TC-4 remain RED (NotImplementedError) — Plan 03 territory (multi-sheet integration with kicad-cli)
- Zero regression: 12/12 sibling `test_safe_sync_pcb_from_schematic.py` tests still pass
- Rule 1 bug fixed during execution: UUID regex now matches both KiCad 10 unquoted and legacy quoted forms

## Task Commits

Each task was committed atomically:

1. **Task 1: Add replace_reference_property to SchematicRawWriter + 5 unit tests** — `33b9b997` (feat)
2. **Task 2: Add SafeAnnotateOp schema + SELF_SERIALIZING_OPS + registry entry** — `82dd9cb1` (feat)
3. **Task 3: Implement _handle_safe_annotate handler + make TC-1, 2, 5, 6, 7, 8 GREEN** — `b8be12bb` (feat)

## Files Created/Modified

- `src/kicad_agent/ops/schematic_raw_writer.py` — added `replace_reference_property` static method: locates `(symbol ...)` block by `(uuid "...")` containment via depth-tracked paren matching, then within that block replaces exactly the value of `(property "Reference" "OLD")` via `regex.subn(count=1)`. Uses `re.escape()` on UUID (T-102-02-01), raises `ValueError` if `new_ref` contains a double quote, returns content unchanged on not-found (no silent corruption). UUID regex accepts both quoted and unquoted forms (Rule 1 fix).
- `src/kicad_agent/ops/_schema_reference.py` — added `SafeAnnotateOp` Pydantic model with 6 fields: `op_type` (Literal "safe_annotate"), `target_file` (TargetFile), `scope` (Literal whole_project/current_sheet, default whole_project), `reset` (bool, default False), `order` (Literal by_x_position/by_y_position/sheet_order, default by_x_position), `dry_run` (bool, default False).
- `src/kicad_agent/ops/schema.py` — wired `SafeAnnotateOp` into three re-export locations (import block, Operation union, `__all__`).
- `src/kicad_agent/ops/execution.py` — added `"safe_annotate"` to `SELF_SERIALIZING_OPS` frozenset with M-01 inline comment (`MUST bypass serialize_schematic()`, P0-006 reference) so executor skips kiutils re-serialization.
- `src/kicad_agent/ops/registry.py` — added `safe_annotate` registry entry: category=reference, file_types=[.kicad_sch], is_readonly=False, scope=single_file.
- `src/kicad_agent/ops/handlers/schematic.py` — added `_handle_safe_annotate` handler + 3 module-level helpers (`_collect_children`, `_extract_symbols_with_refs`, `_build_rename_plan`, `_extract_number`). Handler: root sheet guard (LOCKED message), scope dispatch, raw edits via SchematicRawWriter, pre-write paren balance validation (M-02 lazy import), atomic_write per sheet, dry_run short-circuit. Top-of-file imports added: `re`, `atomic_write`, `SchematicRawWriter`.
- `tests/test_safe_annotate.py` — replaced 6 NotImplementedError stubs with real test bodies (TC-1, 2, 5, 6, 7, 8). TC-3, TC-4 remain as NotImplementedError (Plan 03). Test invocation uses `OperationExecutor(base_dir=tmp_path)` + `Operation.model_validate({"root": {...}})`.
- `tests/test_schematic_raw_writer.py` — NEW: 5 unit tests for `replace_reference_property` (basic, UUID targeting, not-found, byte-preservation, quote rejection).

## Decisions Made

- **Rule 1 bug (UUID regex):** The plan's UUID regex `\(uuid\s+"([^"]+)"` expected quoted UUIDs but KiCad 10 fixtures use unquoted form `(uuid abc-123)`. Fixed by making quotes optional: `\(uuid\s+"?([^")\s]+)"?`. Applied to both `_extract_symbols_with_refs` in the handler and `replace_reference_property` in SchematicRawWriter. Without this fix, component extraction returned empty and the rename plan was empty — TC-2 would have silently passed with zero renames.
- **schema.py re-export wiring:** The plan's Task 2 Step 4 said "check if exports need updating" — they do. `schema.py` re-exports `_schema_reference` classes in three locations (import block, union, `__all__`). All three updated so `Operation.model_validate` accepts safe_annotate payloads. Without this, `Operation.model_validate({"root": {"op_type": "safe_annotate", ...}})` would raise a union validation error.
- **Test invocation pattern:** The plan's `_execute_op` used a non-existent `from kicad_agent.ops.executor import execute`. The executor is a class (`OperationExecutor`) requiring `base_dir`. Updated to mirror `tests/test_modify_property.py:266-282`: `OperationExecutor(base_dir=tmp_path)` + `Operation.model_validate({"root": op_json})` + `executor.execute(op)`. `target_file` is the relative basename inside `tmp_path` (path confinement check rejects absolute paths).
- **M-01 inline comment placement:** The done criteria requires `grep -q 'MUST bypass serialize_schematic'` to succeed. Initially the phrase was split across two comment lines (`MUST\n#   bypass`) which grep couldn't match as a single string. Consolidated onto one line: `# safe_annotate (Phase 102): MUST bypass serialize_schematic() to avoid`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] UUID regex did not match KiCad 10 unquoted format**
- **Found during:** Task 3 (TC-2 returned empty annotated list)
- **Issue:** Plan's regex `\(uuid\s+"([^"]+)"` expected quoted UUIDs. KiCad 10 fixtures use unquoted form `(uuid aaaaaaaa-0001-...)`. Component extraction returned empty, rename plan was empty, no edits applied.
- **Fix:** Made quotes optional in both `_extract_symbols_with_refs` (handler) and `replace_reference_property` (SchematicRawWriter): `\(uuid\s+"?([^")\s]+)"?`. Matches both `(uuid abc-123)` and `(uuid "abc-123")`.
- **Files modified:** `src/kicad_agent/ops/handlers/schematic.py`, `src/kicad_agent/ops/schematic_raw_writer.py`
- **Verification:** TC-2 now passes (R? → R1, one rename in annotated list). TC-1, TC-5, TC-6, TC-7, TC-8 unaffected.
- **Committed in:** `b8be12bb`

**2. [Rule 3 - Blocking] OperationExecutor API mismatch**
- **Found during:** Task 3 (TC-1 import failed: `cannot import name 'execute' from 'kicad_agent.ops.executor'`)
- **Issue:** Plan's `_execute_op` used `from kicad_agent.ops.executor import execute` but the executor is a class (`OperationExecutor`) with no module-level `execute` function.
- **Fix:** Updated `_execute_op` to use `OperationExecutor(base_dir=base_dir)` + `Operation.model_validate({"root": op_json})` + `executor.execute(op)`. Mirrors `tests/test_modify_property.py:266-282`.
- **Files modified:** `tests/test_safe_annotate.py`
- **Verification:** All 6 GREEN tests now invoke the executor correctly.
- **Committed in:** `b8be12bb`

**3. [Rule 3 - Blocking] schema.py re-export gap**
- **Found during:** Task 2 verification (would have caused Task 3 to fail at `Operation.model_validate`)
- **Issue:** Plan's Task 2 Step 4 said "check if exports need updating" but didn't specify where. `schema.py` re-exports `_schema_reference` classes in 3 locations (import block, union, `__all__`).
- **Fix:** Added `SafeAnnotateOp` to all 3 locations in `schema.py`.
- **Files modified:** `src/kicad_agent/ops/schema.py`
- **Verification:** `from kicad_agent.ops.schema import SafeAnnotateOp` works; `Operation.model_validate` accepts safe_annotate payloads.
- **Committed in:** `82dd9cb1`

**4. [Rule 3 - Blocking] M-01 comment split across lines**
- **Found during:** Task 2 verification (`grep -q 'MUST bypass serialize_schematic'` failed)
- **Issue:** Comment text was wrapped `MUST\n#   bypass serialize_schematic()` which grep couldn't match as a literal substring.
- **Fix:** Consolidated onto one line: `# safe_annotate (Phase 102): MUST bypass serialize_schematic() to avoid`.
- **Files modified:** `src/kicad_agent/ops/execution.py`
- **Verification:** `grep -q 'MUST bypass serialize_schematic'` succeeds.
- **Committed in:** `82dd9cb1`

---

**Total deviations:** 4 auto-fixed (1 Rule 1 bug + 3 Rule 3 blocking issues)
**Impact on plan:** Zero scope creep. All fixes are correctness requirements directly caused by this plan's code.

## Issues Encountered

- Commit message validator (`gsd-validate-commit.sh`) only inspects the first line and uses a regex that doesn't match multi-line heredoc messages. Worked around by using two `-m` flags (subject + body) instead of `$(cat <<'EOF' ... EOF)`. Same issue documented in Plan 01 SUMMARY.

## Threat Flags

None. All files created/modified are within the plan's documented threat model (T-102-02-01 through T-102-02-05). No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond what the plan specifies. The UUID regex fix (Rule 1) actually STRENGTHENS the T-102-02-01 mitigation by ensuring `re.escape()` is applied to UUIDs extracted from both quoted and unquoted forms.

## Known Stubs

TC-3 (`test_cross_sheet_dedup_whole_project`) and TC-4 (`test_p0_006_regression_no_reserialization`) remain as intentional RED stubs (NotImplementedError). These are Plan 03 territory — they require multi-sheet integration with `kicad-cli sch export netlist`. The handler code already supports `scope="whole_project"` via `SchematicGraph.from_hierarchy` tree walk; Plan 03 only needs to wire the integration tests.

## User Setup Required

None — no external service configuration required. All tests run via pytest with local fixtures.

## Next Phase Readiness

- Plan 03 can begin immediately — handler is fully functional for current_sheet scope; whole_project scope is implemented but untested
- Plan 03 will: (1) write TC-3 and TC-4 integration tests using the multi-sheet fixtures, (2) add API docs at `docs/api/safe_annotate.md`, (3) emit DeprecationWarning from the forbidden `annotate` op pointing to `safe_annotate`
- H-02 Option B (handler co-edits `(instances ...)` blocks for real-world schematics) remains DEFERRED-TO-NAMED-TARGET — trigger: Phase 145 manual verification on analog-board.kicad_sch fails

## TDD Gate Compliance

- Task 1: RED gate (5 tests fail with AttributeError) → GREEN gate (5 tests pass after method added). Single commit per task (TDD combined since the method and tests are one logical unit).
- Task 2: No RED gate (schema/registry changes are wiring, not behavior). Verification via Python import assertions + grep.
- Task 3: TC-1, 2, 5, 6, 7, 8 transitioned from RED (NotImplementedError in Plan 01) to GREEN (real test bodies). TC-3, TC-4 remain RED (Plan 03).

All three tasks have appropriate TDD gate commits. No gate violations.

## Self-Check: PASSED

- 8 files verified present (5 source + 2 test + 1 new test file)
- 3 commits verified in git log (`33b9b997`, `82dd9cb1`, `b8be12bb`)
- 11 tests GREEN (6 safe_annotate TCs + 5 raw writer unit tests)
- 2 tests intentionally RED (TC-3, TC-4 — Plan 03 territory)
- 12/12 sibling `test_safe_sync_pcb_from_schematic.py` tests pass (zero regression)
- Function-scoped AST grep clean (H-01)
- M-01, M-02, M-03 Council findings all addressed

**Self-Check Result: PASSED** — all 9 files exist on disk, all 3 commit hashes present in git log, verified 2026-06-29T22:57:00Z.

---
*Phase: 102-safe-annotate-non-destructive-refdes-renumbering*
*Plan: 02 of 03*
*Completed: 2026-06-29*
