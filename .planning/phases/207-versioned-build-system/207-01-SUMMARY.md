---
phase: 207-versioned-build-system
plan: 01
subsystem: manufacturing
tags: [build-system, manifest, serialization, frozen-dataclass, git-sha, uuid]

# Dependency graph
requires:
  - phase: 205-board-metadata
    provides: NativeTitleBlock.rev field (board_rev source)
  - phase: 206-vendor-drc
    provides: query-op handler pattern + registry/schema/readonly-set plumbing
provides:
  - "Build frozen dataclass (build_id, board_rev, source_files, git_sha, status, artifacts, manifest_path, build_dir)"
  - "BuildStatus lifecycle enum (DRAFT/VALIDATED/EXPORTED/HANDED_OFF) with forward-only transition_to"
  - "ManufacturingManifest serialization (to_json/save/load) + ManufacturingArtifact (to_dict/from_dict) lossless round-trip"
  - "build_create op (snapshot source files, capture git SHA + board rev, write manifest)"
  - "build_list op (scan builds/ for build records)"
  - "build_show op (load build by build_id, optional diff)"
  - "diff_builds() utility + BuildDiff dataclass (source/artifact/status/sha/rev diffs)"
  - "_get_git_sha helper (never raises, returns 'unknown')"
  - "builds/ in .gitignore"
affects: [208-handoff-package, 209-cli-mcp]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass-lifecycle, atomic-write-persistence, query-op-side-effects, build-envelope-two-file]

key-files:
  created:
    - src/kicad_agent/manufacturing/build.py
    - src/kicad_agent/ops/handlers/build.py
    - tests/test_build_system.py
  modified:
    - src/kicad_agent/validation/gates/manufacturing_manifest.py
    - src/kicad_agent/ops/_schema_pcb.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/registry.py
    - src/kicad_agent/ops/handlers/__init__.py
    - tests/test_registry.py
    - .gitignore

key-decisions:
  - "build_create/build_list/build_show registered as query ops (category=query, is_readonly=True) not cross-file ops -- IP-4 deviation. They create side-effect artifacts in builds/ without touching the .kicad_pcb source. execute_query skips source serialization."
  - "Two files on disk per build: manifest.json (manufacturing subset) + build.json (full Build envelope). build_show round-trips losslessly via Build.load(build.json). Avoids coupling the ManufacturingManifest dataclass with build-level fields."
  - "Simplified v1 validation: build_create defaults to BuildStatus.DRAFT (PCB parses). Full ManufacturingReadinessGate requires context (DRC/DFM/exports) deferred to Phase 208. DRAFT is honest -- avoids Pitfall 5 false confidence."
  - "board_rev read via re-parse (NativeParser.parse_pcb) not ir.board -- query path has _native_board=None (dual-path issue, same as drc_vendor)."
  - "Diffing is a parameter on build_show (diff_build_id), NOT a separate op -- keeps registry delta at +3 not +4."

patterns-established:
  - "Query-op-with-side-effects: handlers registered as readonly query ops may write side-effect artifacts in a separate tree (builds/) as long as the target source file is untouched. Target byte-identity (hash + mtime) asserted in tests."
  - "Build envelope two-file persistence: manifest.json (manufacturing subset via ManufacturingManifest.save) + build.json (full Build record via Build.save). Build.load round-trips losslessly including enum status and tuples."
  - "No-partial-state error path: build_create wraps all steps in try/except and rmtree's the build dir before returning the error dict (BUILD-04)."
  - "Path-traversal rejection: project_dir with '..' in .parts is rejected with a clear error (threat model #1). Board rev sanitized to [A-Za-z0-9._-] before interpolating into directory names."

requirements-completed:
  - BUILD-01
  - BUILD-02
  - BUILD-03
  - BUILD-04
  - BUILD-05
  - BUILD-06
  - BUILD-07
  - BUILD-08
  - BUILD-09
  - BUILD-10

# Metrics
started: 2026-07-11T00:13:45Z
completed: 2026-07-11T00:35:37Z
duration: 22m
duration_minutes: 22
commits: 5
files_modified: 10
---

# Phase 207 Plan 01: Versioned Build System Summary

**Frozen Build record with UUID/git-SHA/board-rev, manifest serialization round-trip, and three query ops (build_create/list/show) that snapshot source files into a versioned builds/ tree without touching the .kicad_pcb**

## Performance

- **Duration:** 22m
- **Started:** 2026-07-11T00:13:45Z
- **Completed:** 2026-07-11T00:35:37Z
- **Tasks:** 5
- **Commits:** 5 (atomic task commits)
- **Files modified:** 10

## Accomplishments
- Build data model with forward-only BuildStatus lifecycle (DRAFT→VALIDATED→EXPORTED→HANDED_OFF) via dataclasses.replace; disallowed transitions raise ValueError
- ManufacturingManifest/ManufacturingArtifact gained lossless to_json/save/load + to_dict/from_dict using atomic_write (no regressions in test_manufacturing_gate.py)
- build_create snapshots .kicad_pcb/.kicad_sch/.kicad_pro via shutil.copy2, hashes each artifact, captures git SHA, writes manifest.json + build.json, and cleans up partial state on any failure (BUILD-04)
- build_list/build_show handlers with BUILD-10 diff integration as a build_show parameter; corrupt build dirs skipped without crashing the list
- Registry 156→159, readonly set +3 ops, validate_registry_completeness passes (schema + registry in sync)

## Task Commits

Each task was committed atomically:

1. **Task 1: Build model + manifest serialization** - `d0285b3` (feat)
2. **Task 2: Schema + registry + handler wiring** - `9ab76c0` (feat)
3. **Task 3: build_create handler** - `60cd836` (feat)
4. **Task 4: build_list + build_show + diff** - `a03ca6d` (feat)
5. **Task 5: .gitignore + verification** - `1113326` (chore)

## Files Created/Modified
- `src/kicad_agent/manufacturing/build.py` - Build, BuildStatus, BuildDiff, diff_builds, _get_git_sha
- `src/kicad_agent/ops/handlers/build.py` - _BUILD_HANDLERS + 3 query handlers + shared helpers
- `tests/test_build_system.py` - 35 tests across TestBuildModel/TestBuildCreate/TestBuildList/TestBuildShow
- `src/kicad_agent/validation/gates/manufacturing_manifest.py` - to_json/save/load + to_dict/from_dict (additive)
- `src/kicad_agent/ops/_schema_pcb.py` - BuildCreateOp/BuildListOp/BuildShowOp
- `src/kicad_agent/ops/schema.py` - Operation union + import + __all__ (+3 ops)
- `src/kicad_agent/ops/registry.py` - _RAW_CATALOG (+3 query ops)
- `src/kicad_agent/ops/handlers/__init__.py` - _BUILD_HANDLERS import + _QUERY_HANDLERS.merge
- `tests/test_registry.py` - count 159, readonly set +3
- `.gitignore` - builds/

## Decisions Made
- Two-file persistence (manifest.json + build.json) over single-file super-manifest: keeps ManufacturingManifest focused on manufacturing fields; build.json carries the full Build envelope for lossless round-trip
- Diffing as a build_show parameter (diff_build_id) rather than a 4th op: keeps registry delta at +3, matches CONTEXT.md decision
- Path-traversal defense via `..` in Path.parts check + is_relative_to on resolved candidates + rev sanitization (threat model mitigations baked into the handler)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Full test suite shows 92 pre-existing failures (SLC SKILL.md operation-count drift `149 != 156` predates Phase 207, ngspice/kicad-cli external deps absent in this environment, image-processing/training/undo-stack tests). Verified at base commit 178cf0c that the SLC drift was already failing. None of the 92 failures are attributable to Phase 207 changes; all Phase 207 tests (35) and regression suites (test_registry, test_manufacturing_gate, test_board_metadata_ops) pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Build record model + manifest serialization complete; Phase 208 can assemble full ManufacturingReadinessGate context (DRC/DFM/exports) and transition builds DRAFT→VALIDATED, then EXPORTED/HANDED_OFF
- build_handoff_export (Phase 208) should follow the same query-op-with-side-effects pattern established here
- CLI subcommands / MCP exposure (Phase 209) can wrap build_create/list/show + expose diff_builds as `build diff`

---
*Phase: 207-versioned-build-system*
*Completed: 2026-07-11*
