# FEATURE-008: Safe Annotate — Non-Destructive Reference Designator Renumbering

**Issue:** kicad-agent-XX (to be filed)
**Priority:** P0 — blocks Phase 145 channel-strip routing completion (analog-ecosystem)
**Date:** 2026-06-29
**Status:** OPEN
**Requested by:** Bret Bouchard (via Claude Code orchestrator, Phase 145 Wave 1 checkpoint)

---

## Problem Statement

The existing `annotate` op is FORBIDDEN (P0-006) because it re-serializes schematic files via kiutils, corrupting KiCad 10 formatting even when reporting "no changes." This leaves kicad-agent with **no safe way to perform reference designator (refdes) renumbering** — a critical operation for any schematic that has accumulated duplicate or missing annotations.

There is currently **no scriptable alternative**. The only safe path is the KiCad GUI (Tools → Edit Annotations → "Reset existing annotation" checked), which requires human intervention and breaks autonomous pipelines.

### Concrete blocker (Phase 145, 2026-06-29)

Analog-ecosystem channel-strip `analog-board.kicad_sch` has **47 cross-sheet duplicate reference designators** + **12 within-sheet duplicates** across 16 sub-sheets. KiCad's netlist exporter silently collapses duplicate refs — when two components share `R1` across sheets, only one's pins make it into the netlist. The GNDA power rail is missing from the exported netlist (count=0) because every GNDA-connected pin happens to be on the losing side of the collapse.

Phase 145 Wave 1 Plan 145-01 was designed to fix this via KiCad GUI annotation (human-action checkpoint). The user had to leave the session to perform the annotation manually at home. **This is the second time in two phases that annotation has blocked an autonomous pipeline.**

### What we need

A non-destructive `safe_annotate` op (akin to the proven `safe_sync_pcb_from_schematic` pattern) that:
1. Renames reference designators via **targeted raw S-expression edits** (NOT kiutils re-serialization)
2. Preserves all formatting, indentation, field ordering, and lib_symbol structure
3. Supports "reset existing annotation" semantics (renumber everything from scratch, dedup across sheets)
4. Reports the rename map: `{"renames": [{"old": "R?", "new": "R17", "sheet": "input-stage.kicad_sch", "uuid": "..."}], ...}`
5. Validates paren balance before and after edits
6. Refuses to operate on root sheets (same guard rail as P0-005 `remove_dangling_wires` workaround)

---

## Proposed API

### Op: `safe_annotate`

```json
{
  "op": "safe_annotate",
  "target_file": "hardware/network-io/channel-strip/analog-board.kicad_sch",
  "scope": "whole_project",
  "reset": true,
  "order": "by_x_position",
  "dry_run": false
}
```

**Parameters:**
- `target_file` (str, required): Root schematic path. Sub-sheets resolved via `(sheet ...)` blocks.
- `scope` (enum): `current_sheet` | `whole_project` (default: `whole_project`). Whole-project is required to dedup cross-sheet refs.
- `reset` (bool, default: `false`): If `true`, strip all existing refdes back to `?` before renumbering. Required when duplicates already exist (otherwise annotator only fills `?` placeholders and duplicates persist).
- `order` (enum): `by_x_position` | `by_y_position` | `sheet_order` (default: `by_x_position`). Matches KiCad GUI "Sort by X position" option.
- `dry_run` (bool, default: `false`): If `true`, return the proposed rename map without modifying files. Useful for inspection.

**Response:**
```json
{
  "annotated": [
    {"sheet": "input-stage.kicad_sch", "uuid": "abc123-...", "old_ref": "R?", "new_ref": "R1"},
    {"sheet": "input-stage.kicad_sch", "uuid": "def456-...", "old_ref": "C?", "new_ref": "C1"},
    {"sheet": "usb-midi.kicad_sch", "uuid": "ghi789-...", "old_ref": "R1", "new_ref": "R42", "note": "cross-sheet duplicate renamed"},
    ...
  ],
  "stats": {
    "sheets_touched": 16,
    "refs_renamed": 188,
    "duplicates_resolved": 47,
    "placekeepers_filled": 12
  },
  "skipped": [],
  "paren_balance_check": "PASS",
  "format_preservation_check": "PASS"
}
```

---

## Implementation Approach

Mirror the **raw S-expression edit pattern** proven in:
- `safe_sync_pcb_from_schematic` (Phase 144 ae-26 workaround — non-destructive PCB sync via raw edits)
- `swap_symbol` (manual symbol swap without kiutils re-serialization)
- `add_no_connect` (targeted insertion preserving file structure)

### Algorithm sketch

1. **Parse the project tree** — walk `(sheet ...)` blocks from root, resolve absolute paths for all sub-sheets.
2. **Collect components** — for each sheet, parse `(symbol ...)` blocks with `(property "Reference" "X")` where X is `?` or a duplicate.
3. **Build the rename plan** — sort by absolute X coordinate, assign sequential refs per prefix (R1, R2, ... C1, C2, ... U1, U2, ...). Detect duplicates across the project and renumber as needed.
4. **Apply edits raw** — for each rename, locate the `(property "Reference" "OLD")` and replace with `(property "Reference" "NEW")` via line-based or paren-balanced S-expression edit. **Do NOT call `kiutils.sch.Schematic.to_file()`** — that path is what corrupts files per P0-003/P0-006.
5. **Validate** — run `kicad-cli sch erc <sheet>` per sheet (paren balance + parse check). Run `kicad-cli sch export netlist` to confirm netlist is now complete.

### Critical invariant

**Never invoke `Schematic.to_file()` or any kiutils writer.** All edits must be applied via direct S-expression manipulation, mirroring the raw-edit pattern in `pcb_populate.py:instantiate_footprint` (Phase 144 P2 patch — preserves full library fidelity via raw edits, not kiutils).

---

## Validation Suite

Per `BUGS/P0-006-annotate-corrupts-files.md`, the failure mode is "file re-serialization despite reporting no changes." Validation must prove the new op does NOT re-serialize:

### Test 1: Idempotency
- Input: a clean (already-annotated) schematic
- Op call with `dry_run: true`
- Assert: `annotated: []`, file byte-identical after op

### Test 2: Single rename
- Input: schematic with `R?` placeholder
- Op call with `scope: current_sheet`
- Assert: `R?` → `R1`, only one line changed in diff, file otherwise byte-identical

### Test 3: Cross-sheet dedup (the Phase 145 case)
- Input: 2 sheets each with `R1` (duplicate)
- Op call with `scope: whole_project, reset: true`
- Assert: one R1 renamed (e.g., to `R2`), paren balance preserved, netlist no longer collapses the rail

### Test 4: Regression vs P0-006
- Input: Phase 145 pre-annotation baseline (`hardware/network-io/channel-strip/analog-board.kicad_sch` + 16 sub-sheets)
- Op call with `scope: whole_project, reset: true`
- Assert: GNDA rail present in exported netlist with >0 nodes (the exact acceptance criterion of Phase 145 Plan 145-01)

### Test 5: Root sheet guard
- Input: root sheet passed as target
- Assert: op refuses to operate, returns error `"safe_annotate operates per-sheet; root sheet contains hierarchy only — use sub-sheet scope"`

---

## Why This Matters

### Cost of not having it

- **Phase 133** (backplane cleanup): annotation blockers consumed a full session
- **Phase 143** (pre-routing closeout): annotation workarounds pushed PCB footprint population to Phase 144
- **Phase 144** (analog-board clean rebuild): GNDA missing from netlist traced to annotation collapse — deferred to Phase 145
- **Phase 145** (current): user had to leave session to perform GUI annotation. Autonomous pipeline halted.

This is a recurring tax. Every multi-sheet KiCad 10 schematic that needs annotation work pays it.

### Precedent

The exact same pattern was solved for PCB sync (`safe_sync_pcb_from_schematic` — created as a non-destructive alternative to the destructive GUI flow). The PCB side now has a safe, scriptable path. The schematic side does not.

### Asymmetric risk

The GUI path works but breaks autonomy. The existing `annotate` op claims to work but corrupts files. There is no third option today. `safe_annotate` fills that gap.

---

## Related Artifacts

- **BUGS/P0-006-annotate-corrupts-files.md** — the underlying bug that makes the existing `annotate` op forbidden
- **BUGS/P0-003-erc-auto-fix-corrupts-files.md** — same kiutils re-serialization root cause
- **analog-ecosystem `.planning/phases/145-.../145-01-PLAN.md`** — the consumer side showing exactly how this op would be used (replace checkpoint:human-action with `autonomous: true`)
- **analog-ecosystem memory `feedback-kicad-update-pcb-blocked-by-erc.md`** — UI flow that safe_annotate would replace

---

## Acceptance Criteria

- [ ] Op `safe_annotate` implemented in `src/kicad_agent/schematic/safe_annotate.py`
- [ ] Test suite in `tests/schematic/test_safe_annotate.py` covering all 5 validation cases above
- [ ] Zero calls to `kiutils.scch.Schematic.to_file()` or any kiutils writer in the new code path
- [ ] Diff validation: op produces ONLY the targeted `(property "Reference" ...)` line changes, nothing else
- [ ] Phase 145 analog-board annotation completes via `safe_annotate` (replaces the current human-action checkpoint)
- [ ] Documentation in `docs/api/schematic.md` with the JSON schema + examples
- [ ] BUGS/P0-006-annotate-corrupts-files.md updated to add reference: "Use `safe_annotate` instead"

---

## Estimated Effort

- Implementation: 4-6 hours (raw S-expression edit pattern is proven, just needs to be applied to refdes properties)
- Test suite: 2-3 hours (5 validation cases + edge cases)
- Documentation: 1 hour
- **Total: ~1 day of focused work**

ROI: pays back on the next multi-sheet schematic project (Phase 145 immediately, future backplane cartridge work, etc.)

---

## Requested By

**Bret Bouchard** via Phase 145 Wave 1 human-action checkpoint (2026-06-29)

Phase 145 Plan 145-01 is currently paused waiting for manual GUI annotation. Once `safe_annotate` ships, the plan can be updated to `autonomous: true` and the checkpoint removed. This unlocks fully autonomous rebuild pipelines for any multi-sheet schematic.

---

*Feature request ID: FEATURE-008*
*Filed: 2026-06-29*
*Repo: bretbouchard/kicad-agent*
