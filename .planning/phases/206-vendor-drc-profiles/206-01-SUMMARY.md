---
phase: 206-vendor-drc-profiles
plan: 01
subsystem: dfm
tags: [kicad-dru, drc, vendor-profiles, manufacturing, geometric-evaluator, pydantic, package-data]

# Dependency graph
requires: []
provides:
  - 9 verified .kicad_dru files (PCBWay, JLCPCB, AISLER 2/4/6/8L, OSH Park, Advanced Circuits, generic)
  - drc_profiles package with path-traversal-safe resolver + capabilities metadata registry
  - internal Python geometric DRC evaluator (manufacturing/vendor_drc.py)
  - drc_vendor op (run DRC against a vendor's limits as pre-flight gate)
  - list_vendor_drc_profiles op (enumerate bundled profiles)
  - ManufacturerProfile.drc_rules_path field linking profiles to DRU files
affects: [dfm-checker, ops-query-handlers, vendor-selection, pre-flight-gates]

# Tech tracking
tech-stack:
  added: []  # no new dependencies; pure stdlib (math, re, dataclasses, pathlib)
  patterns:
    - internal geometric evaluator replaces missing kicad-cli --custom-rules flag
    - dual-layer path-traversal defense (schema regex + resolver file-existence)
    - package-data declaration so .kicad_dru survive pip install/wheels
    - NativeParser.parse_pcb dual-path re-parse inside query handler

key-files:
  created:
    - src/volta/manufacturing/drc_profiles/__init__.py
    - src/volta/manufacturing/vendor_drc.py
    - src/volta/manufacturing/drc_profiles/pcbway.kicad_dru
    - src/volta/manufacturing/drc_profiles/jlcpcb.kicad_dru
    - src/volta/manufacturing/drc_profiles/aisler_2layer.kicad_dru
    - src/volta/manufacturing/drc_profiles/aisler_4layer.kicad_dru
    - src/volta/manufacturing/drc_profiles/aisler_6layer.kicad_dru
    - src/volta/manufacturing/drc_profiles/aisler_8layer.kicad_dru
    - src/volta/manufacturing/drc_profiles/oshpark.kicad_dru
    - src/volta/manufacturing/drc_profiles/advanced_circuits.kicad_dru
    - src/volta/manufacturing/drc_profiles/generic.kicad_dru
    - tests/test_vendor_drc.py
    - tests/test_drc_profiles.py
    - tests/test_drc_vendor_ops.py
  modified:
    - src/volta/dfm/profiles.py
    - src/volta/ops/_schema_pcb.py
    - src/volta/ops/schema.py
    - src/volta/ops/registry.py
    - src/volta/ops/handlers/query.py
    - pyproject.toml
    - tests/test_dfm_checker.py
    - tests/test_registry.py

key-decisions:
  - "Internal Python evaluator (Option C) replaces kicad-cli custom rules because kicad-cli pcb drc has NO --custom-rules flag in KiCad 10 (RESEARCH RQ1, verified empirically)"
  - ".kicad_dru files ship as the source-of-truth for vendor numeric limits AND for GUI use, but the automated drc_vendor op does NOT consume them — it reads ManufacturerProfile limits and walks NativeBoard geometry directly"
  - "Dual-layer path-traversal defense: schema pattern ^[a-z0-9_]+$ at the API boundary + resolver path.is_file() existence check as a second layer"
  - "Graceful degradation over crashes: every geometry access uses getattr with safe defaults + try/except per feature, so a single malformed track never aborts the whole evaluation"
  - "Floating-point tolerance via _EPS=1e-9: at-limit values pass (use limit - _EPS) rather than fail due to representation error like (0.7-0.4)/2.0 = 0.1499..."
  - "NativeVia uses .diameter (NOT .size) — verified by reading pcb_native_types.py:202 and pcb_native_parser.py:851 (the size token populates diameter)"

patterns-established:
  - "Frozen dataclass result objects (VendorDrcResult, Violation) for read-only query results"
  - "Handler re-parses via NativeParser.parse_pcb(file_path) because execute_query-built PcbIR has _native_board=None"
  - "Attribution headers (# Source:, # License:, # Last verified:, # Vendor:, # Capabilities:) required on all vendor .kicad_dru files"
  - "Co-located metadata registry (_PROFILE_INFOS dict) mirrors the existing _PROFILES pattern in dfm/profiles.py"
  - "Package-data declaration mandatory in pyproject.toml for non-.py package assets"

requirements-completed: [DRC-01, DRC-02, DRC-03, DRC-04, DRC-05, DRC-06, DRC-07, DRC-08]

# Metrics
started: 2026-07-10T22:53:18Z
completed: 2026-07-10T23:21:22Z
duration: 28m
duration_minutes: 28
commits: 6
files_modified: 21
---

# Phase 206-01: Vendor DRC Profiles Summary

**9 verified .kicad_dru files for PCBWay/JLCPCB/AISLER/OSH Park/Advanced Circuits + an internal Python geometric DRC evaluator exposing `drc_vendor` and `list_vendor_drc_profiles` ops (kicad-cli has no `--custom-rules` flag in KiCad 10)**

## Performance

- **Duration:** 28m
- **Started:** 2026-07-10T22:53:18Z
- **Completed:** 2026-07-10T23:21:22Z
- **Tasks:** 6
- **Commits:** 6 (5 atomic task commits + this summary)
- **Files modified:** 21 (13 created, 8 modified)

## Accomplishments
- Shipped 9 `.kicad_dru` files with attribution headers (source, license, last-verified date, vendor, capabilities) covering 5+ manufacturers across all layer-count variants
- Built a pure-Python geometric DRC evaluator (`manufacturing/vendor_drc.py`) that walks NativeBoard geometry and checks 5 constraint classes (track_width, clearance, hole_size, annular_width, via_diameter) against `ManufacturerProfile` limits
- Added 2 new query ops — `drc_vendor` (pre-flight gate against a vendor's limits) and `list_vendor_drc_profiles` (enumerate bundled profiles) — with schema, registry, and handler wiring
- Hardened the vendor-name input against path traversal at two layers (schema regex + resolver file-existence check) and made the evaluator degrade gracefully on malformed boards
- Corrected PCBWay/JLCPCB annular ring spec from 0.1mm to 0.15mm (DRC-07) to match vendors' published 6mil minimum
- Extended `ManufacturerProfile` with `drc_rules_path` and added 5 new profiles (Advanced Circuits + AISLER 2/4/6/8L), bringing the catalog from 5 to 10

## Task Commits

Each task was committed atomically:

1. **Task 1: DRU files + drc_profiles package + package-data** - `f9c613a` (feat)
2. **Task 2: ManufacturerProfile extension + annular correction + new profiles** - `ed3235f` (feat)
3. **Task 3: internal vendor DRC evaluator** - `ed55e34` (feat)
4. **Task 4: drc_vendor + list_vendor_drc_profiles schemas/handlers/registry** - `4b84e43` (feat)
5. **Task 5: registry assertions + evaluator/op/profile test suites** - `d5c5b15` (test)
6. **Task 6: SUMMARY.md** - this commit (docs)

## Files Created/Modified

**Created:**
- `src/volta/manufacturing/drc_profiles/__init__.py` - Package init, `VendorDrcProfileInfo` dataclass, `_PROFILE_INFOS` registry (9 entries), `get_drc_profile_path()` with path-traversal defense, `list_drc_profiles()`
- `src/volta/manufacturing/vendor_drc.py` - Internal DRC evaluator: `run_vendor_drc(board, profile) -> VendorDrcResult` with 5 checks (`_check_track_width`, `_check_drill_size`, `_check_annular_ring`, `_check_via_diameter`, `_check_clearance`) plus geometry helpers (`_pos_xy`, `_segment_gap`, `_point_to_segment_dist`, `_segments_intersect`)
- `src/volta/manufacturing/drc_profiles/*.kicad_dru` (9 files) - KiCad DRU rule files with attribution headers and constraint blocks
- `tests/test_vendor_drc.py` - 19 evaluator tests (one per check + robustness + frozen-result + vendor-specific)
- `tests/test_drc_profiles.py` - Attribution headers, annular values, registry completeness, path-traversal defense
- `tests/test_drc_vendor_ops.py` - Schema validation, handler-direct tests, read-only mtime verification

**Modified:**
- `src/volta/dfm/profiles.py` - Added `drc_rules_path` field, corrected JLCPCB/PCBWay annular 0.1→0.15mm, added Advanced Circuits + AISLER 2/4/6/8L profiles (catalog 5→10)
- `src/volta/ops/_schema_pcb.py` - Added `DrcVendorOp` (vendor pattern `^[a-z0-9_]+$`) and `ListVendorDrcProfilesOp`
- `src/volta/ops/schema.py` - Added both ops to import, `Operation` root union, and `__all__`
- `src/volta/ops/registry.py` - Added `_RAW_CATALOG` entries (both readonly, category=query, file_types=[.kicad_pcb])
- `src/volta/ops/handlers/query.py` - `_handle_drc_vendor` (re-parses via NativeParser, runs evaluator, optional graceful kicad DRC) and `_handle_list_vendor_drc_profiles`
- `pyproject.toml` - Added `[tool.setuptools.package-data]` declaring `*.kicad_dru` so they survive pip install/wheels
- `tests/test_dfm_checker.py` - Updated profile-count assertion (5→10), JLCPCB annular (0.1→0.15), reworked annular differentiator test to use AISLER 0.2mm vs JLCPCB 0.15mm
- `tests/test_registry.py` - Updated count (154→156), added both new ops to `expected_readonly` set

## Decisions Made
- **Internal evaluator over kicad-cli:** `kicad-cli pcb drc` has no `--custom-rules` flag in KiCad 10 (RESEARCH RQ1, verified empirically). The `drc_vendor` op therefore runs an internal Python evaluator that reads `ManufacturerProfile` numeric limits and walks `NativeBoard` geometry. The `.kicad_dru` files still ship as the documented source of truth and for GUI use.
- **Dual-layer path-traversal defense:** Schema pattern `^[a-z0-9_]+$` rejects slashes/dots at the API boundary; `get_drc_profile_path()` re-validates the same pattern and confirms `path.is_file()` before returning. Defense in depth against a buggy LLM or adversarial `vendor` string.
- **Graceful degradation:** Every geometry access uses `getattr(obj, field, default)` and dimension extraction is wrapped in try/except per feature. A single malformed track/via/pad produces a violation (or is skipped), never a crash. The evaluator never re-raises.
- **Floating-point tolerance (`_EPS=1e-9`):** At-limit values must pass, so all thresholds compare against `limit - _EPS`. Required because e.g. `(0.7 - 0.4) / 2.0 == 0.14999999999999997` in IEEE-754 and would spuriously fail a 0.15mm annular check.
- **NativeVia.diameter (not .size):** Critical context note #7 claimed `.size`, but reading `pcb_native_types.py:202` (`diameter: float = 0.0`) and `pcb_native_parser.py:851` (`diameter=diameter` from the `(size D)` token) confirmed `.diameter` is the correct field.

## Deviations from Plan

None - plan executed exactly as written. All 6 tasks, the threat-model mitigations, and the test suites were implemented as specified in `206-01-PLAN.md`.

## Issues Encountered

- **Pre-existing test drift surfaced by DRC-07.** Correcting the JLCPCB/PCBWay annular ring from 0.1mm to 0.15mm broke 3 existing `test_dfm_checker.py` assertions that encoded the old (incorrect) 0.1mm value. Updated all 3 to the corrected values: profile count (5→10), JLCPCB annular (0.1→0.15), and the annular differentiator test (now uses AISLER 0.2mm vs JLCPCB 0.15mm with a 0.72mm pad / 0.4mm drill → 0.16mm annular).
- **Pre-existing full-suite failures (92) unrelated to this plan.** The full regression run reported `92 failed, 7031 passed`. All 92 failures are in modules this plan never touched (`test_schematic_repair`, `test_undo_stack`, `test_training_eval`, `test_spatial_renderer`, `sim/test_eurorack_circuit`) plus `test_slc_compliance::test_skill_md_operation_count_matches`, which fails because `skills/SKILL.md` line 31 hardcodes "List all 149 operation types" — a number that was already stale (Phase 205 raised the count to 154) before this plan's +2 brought the schema to 156. There is zero file overlap between this plan's changes and the failing tests. This documentation drift is out of scope (SKILL.md is not in this plan's file list) and is left for the orchestrator to address.

## User Setup Required

None - no external service configuration required. The `.kicad_dru` files are static package data; the evaluator is pure stdlib.

## Next Phase Readiness
- All 8 requirements (DRC-01 through DRC-08) satisfied
- All 124 tests across the new/modified test files pass (`test_vendor_drc` 19, `test_drc_profiles`, `test_drc_vendor_ops`, `test_registry`, `test_dfm_checker`)
- Threat-model mitigations verified: path traversal blocked at resolver + schema layers; malformed board produces violations instead of crashing; no `--custom-rules` invocation anywhere in `manufacturing/`
- `package-data` declared so wheels include the `.kicad_dru` files
- Registry/schema parity maintained (count 156, both new ops readonly)

---
*Phase: 206-vendor-drc-profiles*
*Completed: 2026-07-10*
