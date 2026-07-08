# kicad-agent P0 Bugs

Critical bugs discovered during analog-ecosystem backplane ERC cleanup (Phases 123-127, 133 — 2026-06-24 through 2026-06-27).

## Summary

| ID | Bug | Severity | Impact |
|----|-----|----------|--------|
| [P0-001](P0-001-update-symbols-from-library-crash.md) | `update_symbols_from_library` crashes with `'Symbol' object has no attribute 'name'` | P0 | Blocks 242 ERC violations on backplane |
| [P0-002](P0-002-place-missing-units-collides-positions.md) | `place_missing_units` places multi-unit components at colliding positions | P0 | Creates +29 ERC regression per call |
| [P0-003](P0-003-erc-auto-fix-corrupts-files.md) | `erc_auto_fix` rewrites entire file, corrupts KiCad 10 schematics | P0 | Data loss — files become unloadable |
| [P0-004](P0-004-place-no-connects-from-erc-wrong-positions.md) | `place_no_connects_from_erc` places markers at wrong positions | P0 | Creates new `no_connect_connected` violations |
| [P0-005](P0-005-remove-dangling-wires-criteria-mismatch.md) | `remove_dangling_wires` uses different dangling criteria than KiCad ERC | P1 | Silently no-ops on real wire_dangling violations |
| [P0-006](P0-006-annotate-corrupts-files.md) | `annotate` re-serializes file via kiutils even when no changes needed (same root cause as P0-003) | P0 | Data loss — 1183/1131 ins/del on mcu.kicad_sch despite `annotated: []` |

## Discovery context

All 6 bugs surfaced during execution of Phases 123-127 and Phase 133 on `/Users/bretbouchard/apps/analog-ecosystem/hardware/backplane/` — a 12-sheet KiCad 10 hierarchical schematic with 188 components.

The bugs collectively block ~600 ERC violations from being addressed via script-driven cleanup. They are the primary reason backplane cleanup plateaued at 859 violations (from 915 baseline).

## Patterns observed

Three of the six bugs (P0-002, P0-004, P0-005) share a common theme: **position calculation without proper KiCad 10 transform handling**. Multi-unit symbols, pin positions, and dangling-wire detection all require applying symbol `(at X Y ANGLE)` transforms to local coordinates. The ops appear to use absolute or untransformed coordinates.

P0-003 and P0-006 are a separate class: **kiutils re-serialization corrupting KiCad 10 files**. This is already documented in project memory (`kiutils-root-sheet-danger.md`) but the affected ops (`erc_auto_fix`, `erc_auto_fix_hierarchical`, `annotate`) were not updated to use raw S-expression manipulation. P0-006 specifically has the additional defect of re-serializing even when the early-return path (`annotated: []`) should have skipped the write.

P0-001 is a simple attribute access bug (`Symbol.name` doesn't exist).

## Recommended fix priority

1. **P0-003** — Mark `erc_auto_fix` ops DEPRECATED immediately (preventive)
2. **P0-001** — Quick fix (attribute access), unblocks Phase 126
3. **P0-002** + **P0-004** — Position transform bugs, fix together
4. **P0-005** — Criteria alignment, lowest priority (op at least doesn't corrupt)

## Related

- Discovery phase reports: `/Users/bretbouchard/apps/analog-ecosystem/.planning/phases/{123,124,125-127}-*`
- Existing limitations: `~/apps/kicad-agent/KNOWN_LIMITATIONS.md`
- Existing PCB op gaps: `/Users/bretbouchard/apps/analog-ecosystem/hardware/KICAD-AGENT-GAP-SPECS.md`

## Handoff

These bugs are queued for the kicad-agent team alongside the router expansion work (memory: `channel-strip-router-handoff.md`). The team has:
- This BUGS/ directory with detailed reports
- Reproduction steps
- Fix path recommendations
- Test board at `hardware/backplane/` for verification
