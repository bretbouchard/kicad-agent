---
phase: 101-schematic-ops-bug-fixes
status: approved-scope
approved_date: 2026-06-25
origin: BUGS/P0-001 through P0-005 (analog-ecosystem backplane cleanup)
---

# Phase 101 — Schematic Ops Bug Fixes (Approved Scope)

## Origin

5 P0/P1 bugs discovered during analog-ecosystem backplane ERC cleanup (Phases 123-127, 2026-06-24). Bug reports live in `BUGS/` at repo root. They collectively block ~600 ERC violations from being addressed via script-driven cleanup on a 12-sheet KiCad 10 hierarchical schematic with 188 components.

The bugs are the primary reason backplane cleanup plateaued at 859 violations (from 915 baseline).

## Goal

Close all 5 bugs so kicad-agent's schematic ops are production-reliable for KiCad 10 multi-sheet projects. After this phase, the analog-ecosystem team can resume script-driven cleanup without manual intervention per violation.

## Dependencies

Standalone. All bugs are in existing ops — no new infrastructure needed.

## Requirements (from BUGS/ reports)

| ID | Bug | Severity | Root Cause Class |
|----|-----|----------|------------------|
| R-1 (P0-001) | `update_symbols_from_library` crashes with `'Symbol' object has no attribute 'name'` | P0 | Simple attribute access bug — Symbol class exposes `lib_id`, not `name` |
| R-2 (P0-002) | `place_missing_units` places multi-unit components at colliding positions (all units at same X,Y) | P0 | Position dedup missing — algorithm doesn't track placed positions per call |
| R-3 (P0-003) | `erc_auto_fix` rewrites entire file, corrupts KiCad 10 schematics (data loss — files unloadable) | P0 | kiutils re-serialization incompatible with KiCad 10 strict formatting. PWR_FLAG lib_symbol insertion at wrong nesting level. |
| R-4 (P0-004) | `place_no_connects_from_erc` places markers at wrong positions (creates `no_connect_connected` violations) | P0 | Position transform bug — doesn't apply symbol `(at X Y ANGLE)` rotation to local pin coords |
| R-5 (P0-005) | `remove_dangling_wires` uses geometric criteria, not KiCad ERC electrical criteria | P1 | Criteria mismatch — op uses def 1 (geometric endpoint), ERC uses def 2 (electrical connection) |

## Success Criteria (falsifiable)

1. **SC-1 (R-1)**: `update_symbols_from_library` completes without AttributeError on backplane `codecs.kicad_sch` — previously crashed immediately
2. **SC-2 (R-2)**: `place_missing_units` on backplane `audio-buffers.kicad_sch` (4× TL072 missing unit C) produces 4 distinct positions, zero collisions
3. **SC-3 (R-3)**: `erc_auto_fix` on backplane `codecs.kicad_sch` does NOT corrupt the file — `kicad-cli sch erc` still loads it post-op, and violations do not increase
4. **SC-4 (R-3)**: Both `erc_auto_fix` and `erc_auto_fix_hierarchical` are marked DEPRECATED in op metadata until raw S-expr rewrite ships (separate follow-up)
5. **SC-5 (R-4)**: `place_no_connects_from_erc` on backplane `codecs.kicad_sch` produces zero new `no_connect_connected` violations (net delta ≤ 0)
6. **SC-6 (R-5)**: `remove_dangling_wires` on a sheet with known ERC `wire_dangling` violations removes ≥90% of them (was 0%)
7. **SC-7 (regression)**: Existing Phase 23 (schematic repair) + Phase 38 (schematic routing) + Phase 40 (ERC root cause) tests still pass — zero regressions on op behavior

## Patterns Observed (from BUGS/README.md)

Three of five bugs (R-2, R-4, R-5) share a common theme: **position calculation without proper KiCad 10 transform handling**. Multi-unit symbols, pin positions, and dangling-wire detection all require applying symbol `(at X Y ANGLE)` transforms to local coordinates. The ops appear to use absolute or untransformed coordinates.

R-3 is a separate class: **kiutils re-serialization corrupting KiCad 10 files**. Already documented in project memory (`kiutils-root-sheet-danger.md`) but the `erc_auto_fix` ops were not updated to use raw S-expression manipulation.

R-1 is a simple attribute access bug.

## Recommended Fix Priority

1. **R-3 (P0-003)** — Mark `erc_auto_fix` ops DEPRECATED immediately (preventive, ~1 hour)
2. **R-1 (P0-001)** — Quick fix (attribute access), unblocks Phase 126 of analog-ecosystem (~2 hours)
3. **R-2 (P0-002) + R-4 (P0-004)** — Position transform bugs, fix together via shared `apply_symbol_transform()` helper (~1 day)
4. **R-5 (P0-005)** — Criteria alignment, lowest priority (op at least doesn't corrupt) (~half day)

## Out of Scope

- AI-assisted ERC repair (separate stream)
- New schematic ops (only fixing existing ones)
- Backplane-specific workarounds (must be general fixes)
- Full `erc_auto_fix` raw S-expr rewrite (defer to follow-up — this phase only deprecates)

## Fixture Boards

- Primary: `/Users/bretbouchard/apps/analog-ecosystem/hardware/backplane/` (12-sheet KiCad 10 hierarchical, 188 components) — all 5 bugs reproducible here
- Secondary: `tests/fixtures/` existing schematics for regression coverage

## Estimated Effort

3-5 plans, ~1 week. Real work is in R-2/R-4 (transform handling) and R-3 (deprecation + decision on long-term fix path).
