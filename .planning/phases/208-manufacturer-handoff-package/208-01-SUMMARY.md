---
phase: 208-manufacturer-handoff-package
plan: 01
subsystem: manufacturing
tags: [zipfile, gerber, bom, jlcpcb, drc, erc, pydantic, manufacturing-handoff]

# Dependency graph
requires:
  - phase: 205-board-metadata
    provides: BoardSpec sidecar, NativeParser title_block access
  - phase: 206-vendor-drc-profiles
    provides: ManufacturerProfile, load_profile, run_vendor_drc
  - phase: 207-build-system
    provides: ManufacturingManifest, ManufacturingArtifact, Build dataclass
provides:
  - export_handoff orchestrator producing a single handoff.zip bundle
  - Profile-driven BOM formatter (export_bom_profile) replacing hard-coded JLCPCB
  - Pre-handoff validation gate (DRC/ERC/vendor DRC) with no-zip-on-failure
  - ManufacturingManifest validation fields (drc/erc proof of manufacturability)
  - build_handoff_export operation (query op, single_file, read-only)
  - readme.md generation from title_block + BoardSpec + board stats + validation
affects: [209-handoff-cli-mcp, manufacturing-readiness-gate]

# Tech tracking
tech-stack:
  added: [zipfile (stdlib, ZIP_DEFLATED streaming)]
  patterns: [tri-state validation via error_message, streaming zip write, profile-driven output spec]

key-files:
  created:
    - src/volta/manufacturing/handoff.py
    - tests/test_handoff.py
  modified:
    - src/volta/dfm/profiles.py
    - src/volta/validation/gates/manufacturing_manifest.py
    - src/volta/export/bom.py
    - src/volta/ops/_schema_pcb.py
    - src/volta/ops/schema.py
    - src/volta/ops/registry.py
    - src/volta/ops/handlers/build.py
    - tests/test_registry.py

key-decisions:
  - "Tri-state validation: error_message set => None (inconclusive, graceful); not-passed with no error_message => False (BLOCK); passed => True. Only False blocks the handoff (graceful degradation when kicad-cli absent)."
  - "Streaming zip via zipfile.ZipFile('w', ZIP_DEFLATED) + zf.write(path, arcname=basename) — handles 100MB STEP files without memory blow-up (Pitfall 7). Arcname is ALWAYS basename (TM-2 zip-slip mitigation)."
  - "export_jlcpcb_bom refactored to delegate to export_bom_profile (backward compat); handoff orchestrator NEVER calls the hard-coded function (Pitfall 3)."
  - "Critical exports (gerbers, drill, cpl, bom) failing blocks the handoff + rmtree (no partial state); non-critical (step, pdfs, netlist) failures are logged and tolerated."
  - "JLCPCB_4LAYER profile also gets bom_columns (Council LOW-1) since it's the same vendor."

patterns-established:
  - "Profile-driven output: adding a new vendor's BOM format is adding a profile entry, not writing code (bom_columns/bom_filename_pattern on ManufacturerProfile)."
  - "Tri-state validation mapping: _tri_state(passed, error_message) -> bool|None centralizes the None/False/True semantics."
  - "No-partial-state cleanup: try/except around the whole pipeline -> shutil.rmtree(build_dir, ignore_errors=True) mirrors build_create."
  - "CSV formula-injection defense: _sanitize_csv_cell prefixes =,+,-,@,tab,cr with a single quote (TM-5)."

requirements-completed: [HANDOFF-01, HANDOFF-02, HANDOFF-03, HANDOFF-04, HANDOFF-05, HANDOFF-06, HANDOFF-07, HANDOFF-08, HANDOFF-09]

# Metrics
started: 2026-07-10T21:52:00Z
completed: 2026-07-10T22:12:00Z
duration: 20m
duration_minutes: 20
commits: 6
files_modified: 10
---

# Phase 208 Plan 01: Manufacturer Handoff Package Summary

**One-call `build_handoff_export` op producing a complete zip bundle (gerbers, drill, BOM, CPL, STEP, PDFs, readme, manifest) with a pre-handoff DRC/ERC/vendor-DRC validation gate that blocks incomplete bundles, plus a profile-driven BOM formatter replacing the hard-coded JLCPCB function.**

## Performance

- **Duration:** 20m
- **Started:** 2026-07-10T21:52:00Z
- **Completed:** 2026-07-10T22:12:00Z
- **Tasks:** 6
- **Commits:** 6 (atomic task commits)
- **Files modified:** 10

## Accomplishments
- `export_handoff` orchestrator implements the full 11-step pipeline: schematic discovery, NativeBoard parse, tri-state validation gate, build dir creation, critical/non-critical export runs, ManufacturingArtifact records, readme.md generation, manifest save, streaming zip, no-partial-state cleanup.
- Pre-handoff validation gate returns `success=False` with NO zip created on any hard DRC/ERC/vendor-DRC failure (HANDOFF-06); inconclusive (kicad-cli absent) does NOT block.
- `export_bom_profile` generalizes the hard-coded JLCPCB BOM into a profile-driven formatter; `export_jlcpcb_bom` now delegates to it (backward compat). CSV formula-injection defense (TM-5) applied.
- `ManufacturerProfile` extended with 4 output-format fields (bom_columns, bom_filename_pattern, cpl_filename_pattern, include_step_by_default); `ManufacturingManifest` extended with 5 validation fields (drc/erc/vendor_drc passed + violation counts).
- `build_handoff_export` op fully wired (schema + registry + handler); registry count 159 -> 160.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend data models (ManufacturerProfile + ManufacturingManifest)** - `267a17d` (feat)
2. **Task 2: Profile-driven BOM formatter (export_bom_profile)** - `eae517b` (feat)
3. **Tasks 3 & 4: Handoff orchestrator + readme generation** - `44d5298` (feat)
4. **Task 5: build_handoff_export op wiring (schema + registry + handler)** - `46d904a` (feat)
5. **Task 6: Update registry test assertions (159 -> 160, +1 readonly)** - `a22eb31` (test)

_Note: Tasks 3 & 4 were committed together because `_generate_readme` (Task 4) is a private function within the handoff.py module created in Task 3._

## Files Created/Modified
- `src/volta/manufacturing/handoff.py` - CREATED: export_handoff orchestrator, HandoffResult/HandoffValidation dataclasses, _generate_readme, tri-state validation, streaming zip
- `tests/test_handoff.py` - CREATED: 21 tests (BOM profile formatter + handoff orchestrator + readme generation), all use monkeypatch stubs (run in CI without kicad-cli)
- `src/volta/export/bom.py` - MODIFIED: added export_bom_profile + _sanitize_csv_cell (TM-5), refactored export_jlcpcb_bom to delegate
- `src/volta/dfm/profiles.py` - MODIFIED: +4 output-format fields on ManufacturerProfile, set on _JLCPCB_STANDARD + _JLCPCB_4LAYER
- `src/volta/validation/gates/manufacturing_manifest.py` - MODIFIED: +5 validation fields, to_json/load round-trip
- `src/volta/ops/_schema_pcb.py` - MODIFIED: +BuildHandoffExportOp (Phase 208 section, vendor pattern TM-3)
- `src/volta/ops/schema.py` - MODIFIED: +import, +union, +__all__ (3 edits)
- `src/volta/ops/registry.py` - MODIFIED: +build_handoff_export _RAW_CATALOG entry
- `src/volta/ops/handlers/build.py` - MODIFIED: +_handle_build_handoff_export handler
- `tests/test_registry.py` - MODIFIED: count 159->160, +1 readonly entry

## Decisions Made
- Tasks 3 & 4 combined into a single commit because `_generate_readme` (Task 4) is a private function inside `handoff.py` (created in Task 3). Splitting would leave Task 3's module incomplete or Task 4 with no file to edit.
- Export wrappers imported at module top of handoff.py (not lazily) so tests can monkeypatch them on the module namespace. Validation functions (run_drc/run_erc/run_vendor_drc) imported lazily inside export_handoff because they're monkeypatched on their source modules during tests.
- `_sanitize_csv_cell` only inspects the first character (formula interpretation is first-char-driven in spreadsheet apps); defensive single-quote prefix is harmless if the value isn't opened in a spreadsheet.
- `include_render` is accepted by export_handoff but reserved (no render wrapper in the handoff path in v1); reserved for future use per the plan's `export_pcb_pdf`/render split.

## Deviations from Plan

### Auto-fixed Issues

**1. [Council LOW-1] JLCPCB_4LAYER profile also gets bom_columns**
- **Found during:** Task 1 (data model extension)
- **Issue:** Plan critical-context item #15 noted that `_JLCPCB_4LAYER` should also get `bom_columns` since it's the same vendor, but the main action steps only listed `_JLCPCB_STANDARD`.
- **Fix:** Added `bom_columns`, `bom_filename_pattern`, `cpl_filename_pattern` to `_JLCPCB_4LAYER` in addition to `_JLCPCB_STANDARD`.
- **Files modified:** src/volta/dfm/profiles.py
- **Verification:** `.venv/bin/python -c "from volta.dfm.profiles import load_profile; p=load_profile('jlcpcb-4layer'); assert p.bom_columns==('Comment','Designator','Footprint','LCSC')"` passes.
- **Committed in:** `267a17d` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (council directive)
**Impact on plan:** Trivial additive change improving vendor consistency. No scope creep.

## Issues Encountered
- `test_slc_compliance.py::test_skill_md_operation_count_matches` fails (SKILL.md says 149 operations, schema has 160). This is a pre-existing documentation-lag issue (SKILL.md never updated for Phase 205/206/207's +7 ops nor Phase 208's +1). It is NOT in Phase 208's scope (plan does not mention SKILL.md) and predates this work. The relevant Phase 208 tests (test_registry, test_handoff, test_build_system) all pass.
- `test_playground.py` fails to collect (missing `httpx2` module). Pre-existing, unrelated to Phase 208 (does not import any changed module).
- 92 total failures in the full suite are all pre-existing and unrelated (verified: none of the failing test files reference handoff, manufacturing_manifest, export_bom_profile, BuildHandoffExport, or the new profile fields).

## User Setup Required
None - no external service configuration required. The handoff package uses kicad-cli (already a dependency) and stdlib zipfile.

## Next Phase Readiness
- The `build_handoff_export` op is ready for CLI subcommand + MCP exposure (Phase 209).
- The `HandoffResult` dataclass and `export_handoff` function are stable public surfaces for Phase 209's CLI wrapper.
- Full `ManufacturingReadinessGate` integration (5-check gate) remains deferred; the handoff's own DRC/ERC/vendor-DRC gate is sufficient for v1.

---
*Phase: 208-manufacturer-handoff-package*
*Completed: 2026-07-10*
