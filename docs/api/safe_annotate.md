# safe_annotate — Non-Destructive Reference Designator Renumbering

Replaces the forbidden `annotate` op ([P0-006](../../BUGS/P0-006-annotate-corrupts-files.md)) which corrupts KiCad 10 schematics via kiutils re-serialization.

## Overview

`safe_annotate` renumbers reference designators (R1, R2, C1, U1, ...) using **raw S-expression edits**. It never calls `kiutils.Schematic.to_file()`, preserving every byte outside the targeted `(property "Reference" ...)` value strings. This is the same proven pattern as `safe_sync_pcb_from_schematic` (ae-26).

Key properties:

- **Non-destructive:** only `(property "Reference" "OLD")` value strings change. All other bytes (whitespace, indentation, UUIDs, effects blocks, lib_symbols) are preserved.
- **Cross-sheet dedup:** when `scope="whole_project"`, walks all sub-sheets via `(sheet ...)` block recursion and renumbers so each ref is unique across the entire project. Required when exported netlists collapse duplicate refs.
- **Fail-closed:** raises on paren imbalance before any file is written. Original files are preserved on any error.
- **Idempotent:** clean schematics produce zero file writes (verified via byte-identical assertion in TC-1).

## Request Schema

```json
{
  "op": "safe_annotate",
  "target_file": "path/to/board.kicad_sch",
  "scope": "whole_project",
  "reset": false,
  "order": "by_x_position",
  "dry_run": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `op` | `"safe_annotate"` | (required) | Discriminator literal. |
| `target_file` | string | (required) | Path to the target schematic. For `scope="whole_project"`, this is the root sheet; sub-sheets are discovered automatically. |
| `scope` | `"whole_project"` \| `"current_sheet"` | `"whole_project"` | Annotation scope. `whole_project` walks all sub-sheets via `(sheet ...)` block recursion. |
| `reset` | boolean | `false` | Strip all refs to `<prefix>?` before renumbering. **Required when cross-sheet duplicates exist.** |
| `order` | `"by_x_position"` \| `"by_y_position"` \| `"sheet_order"` | `"by_x_position"` | Sort order for sequential ref assignment. `by_x_position` matches KiCad GUI default. Tie-break: see handler docstring. |
| `dry_run` | boolean | `false` | Return the rename plan without writing files. |

## Response Schema

```json
{
  "annotated": [
    {"sheet": "input-stage.kicad_sch", "uuid": "...", "old_ref": "R?", "new_ref": "R1"},
    {"sheet": "usb-midi.kicad_sch", "uuid": "...", "old_ref": "R1", "new_ref": "R42", "note": "cross-sheet duplicate renamed"}
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

## Examples

### Example 1: Dry-run on a clean schematic (idempotency check)

```json
{
  "op": "safe_annotate",
  "target_file": "my_project.kicad_sch",
  "scope": "current_sheet",
  "dry_run": true
}
```

Response (clean schematic — nothing to do):
```json
{
  "annotated": [],
  "stats": {"sheets_touched": 0, "refs_renamed": 0, "duplicates_resolved": 0, "placekeepers_filled": 0},
  "skipped": [],
  "paren_balance_check": "PASS",
  "format_preservation_check": "PASS",
  "dry_run": true
}
```

The file is NOT modified. Use this to check what would change before committing.

### Example 2: Single-sheet annotation (R? → R1)

```json
{
  "op": "safe_annotate",
  "target_file": "my_project.kicad_sch",
  "scope": "current_sheet"
}
```

Renames placeholder refs (`R?`, `C?`, `U?`) to sequential numbers (R1, R2, ..., C1, C2, ..., U1, U2, ...). Only one line per renamed ref changes in the diff — the rest of the file is byte-identical.

### Example 3: Whole-project dedup with reset

When a multi-sheet project has cross-sheet duplicate refs (e.g., two sheets both have `R1`), the exported netlist collapses the duplicate nets. Use `reset=true` to strip all refs to `?` and renumber from scratch:

```json
{
  "op": "safe_annotate",
  "target_file": "my_project.kicad_sch",
  "scope": "whole_project",
  "reset": true
}
```

This walks all sub-sheets, strips all refs to `<prefix>?`, sorts by X position per prefix, and assigns sequential numbers (R1, R2, ..., C1, C2, ..., U1, U2, ...). Cross-sheet duplicates are resolved. (Example path is illustrative — substitute your own root sheet.)

## Error Cases

### Root Sheet Guard

If `target_file` is a root sheet (contains `(sheet ...)` hierarchy blocks but no placed components of its own) AND `scope="current_sheet"`, the op refuses:

```
ValueError: safe_annotate operates per-sheet; root sheet contains hierarchy only — use sub-sheet scope
```

Use `scope="whole_project"` instead — the op walks the children and annotates them.

### Paren Imbalance (fail-closed)

If a raw edit produces unbalanced parentheses (indicating a bug or a malformed input), the op raises BEFORE writing:

```
RuntimeError: Paren imbalance after refdes edit on <sheet_path>
```

No file is written. The original files are preserved.

## Why Not `annotate`?

The existing `annotate` op corrupts KiCad 10 schematics. See [BUGS/P0-006](../../BUGS/P0-006-annotate-corrupts-files.md) for the full reproduction (1183 insertions / 1131 deletions while reporting `annotated: []`). `safe_annotate` is the replacement, using the same raw-edit pattern proven by `safe_sync_pcb_from_schematic`.

The forbidden `annotate` op emits a `DeprecationWarning` on every invocation pointing users to `safe_annotate`.

## Validation

Proven on minimal multi-sheet fixtures (2 sub-sheets, 2 duplicate refs) via the Phase 102 test suite:

- **TC-1:** idempotency — clean schematic + dry_run → `annotated: []`, file byte-identical
- **TC-2:** single rename — `R?` → `R1`, only one line changes per ref
- **TC-3:** cross-sheet dedup — 2 sheets each with `R1` + `whole_project, reset:true` → one renamed, paren balance preserved, kicad-cli parses both children
- **TC-4:** P0-006 regression — diff line count ≤ `refs_renamed * 4 + 4` (NOT proportional to file size)
- **TC-5:** root sheet guard refuses `current_sheet` on a root sheet
- **TC-6:** AST grep — handler source has zero `to_file` Call nodes
- **TC-7:** paren balance preserved after every edit
- **TC-8:** op registered in `SELF_SERIALIZING_OPS`, `OPERATION_REGISTRY`, schema imports cleanly

Full real-world validation (47+ cross-sheet duplicates across 16 sub-sheets) is deferred to Phase 145 manual verification.
