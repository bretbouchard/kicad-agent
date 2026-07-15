# P0-006: `annotate` op re-serializes schematic via kiutils, corrupting KiCad 10 files

**Severity:** P0 (data loss — same root cause as P0-003)
**Discovered:** 2026-06-27, Phase 133 of analog-ecosystem backplane cleanup (Plan 133-03)
**Reproducible:** Yes, deterministic on KiCad 10 multi-sheet schematics

## Symptom

The `annotate` op (reference designator renumbering) claims to perform in-place annotation but actually rewrites the entire schematic file via kiutils re-serialization. The output is structurally different from the input:
- Formatting stripped (whitespace, indentation normalized)
- Fields reordered or dropped
- lib_symbol blocks reorganized
- Net connections silently broken when lib_symbols move

In the Phase 133 reproduction, the op was invoked on `hardware/backplane/mcu.kicad_sch` to fix 2 missing-annotation violations. The op reported `annotated: []` (no changes needed) but the file was re-serialized: **1183 insertions / 1131 deletions** in the diff. The file became unloadable by kicad-cli in the same failure mode as P0-003.

## Reproduction

```bash
PYTHONPATH=/Users/bretbouchard/apps/volta/src /opt/homebrew/bin/python3.11 -m volta.cli '{
  "op": "annotate",
  "target_file": "hardware/backplane/mcu.kicad_sch"
}'
```

Result on mcu.kicad_sch:
- Op response: `{"annotated": []}` (claims no changes)
- Actual diff: 1183 insertions / 1131 deletions — full file re-serialization
- ERC after op: file fails to load cleanly (same corruption pattern as P0-003)

Immediately reverted via `git checkout hardware/backplane/mcu.kicad_sch`. Root ERC returned to 860 baseline.

## Impact

This op is actively dangerous for the same reason as P0-003: **kiutils re-serialization does not preserve KiCad 10's strict formatting requirements.** Per project memory `kiutils-root-sheet-danger.md`: "NEVER to_file() on root sheets; cascading re-serialization breaks kicad-cli."

Affects all KiCad 10 projects using volta — any call to `annotate` risks file corruption regardless of whether the op reports making changes.

## Suspected root cause

The op uses kiutils re-serialization (load → modify → save) regardless of whether any references actually changed. The "no changes needed" early-return path was not implemented — the file is always rewritten even when `annotated: []`.

This is the same class of bug as P0-003. Both ops:
1. Load the schematic via kiutils
2. Modify (or attempt to modify) the in-memory representation
3. Save back via `Schematic.to_file()`
4. KiCad 10's strict formatting requirements are violated by kiutils' default serialization

## Fix path

> **RESOLVED (Phase 102):** Use the [`safe_annotate`](../docs/api/safe_annotate.md) op instead. It performs the same reference designator renumbering via raw S-expression edits, never kiutils re-serialization. The long-term fix (item 3 below) is delivered.

1. **Immediate:** Mark `annotate` as DEPRECATED in op metadata (same as `erc_auto_fix` per P0-003)
2. **Short-term:** Add early-return path — if no references need annotation, do not rewrite the file
3. **Long-term (DELIVERED Phase 102):** `safe_annotate` op uses raw S-expression manipulation via `SchematicRawWriter`, NOT kiutils re-serialization. See `docs/api/safe_annotate.md`.
4. Add unit test that verifies file hash unchanged when op reports `annotated: []` ✅ (TC-1)
5. Add unit test that verifies file loadability via kicad-cli after op execution ✅ (TC-3, TC-4)

## Workaround

**Use the `safe_annotate` op** (Phase 102+). It is the direct replacement for `annotate` and handles all the same use cases without corruption.

```bash
PYTHONPATH=src /opt/homebrew/bin/python3.11 -m volta.cli '{
  "op": "safe_annotate",
  "target_file": "my_project.kicad_sch",
  "scope": "whole_project",
  "reset": true
}'
```

For reference designator renumbering on older volta versions (pre-Phase 102):
- Use KiCad GUI (Tools → Edit Annotations → Annotate Schematic)
- Or use `kicad-cli sch export bom` to inspect current annotations, then manually update via `modify_property` op per ref (preserves formatting)

## Related

- **P0-003** (`erc-auto-fix-corrupts-files.md`) — same root cause, same fix path
- Discovered during Phase 133 Plan 133-03 execution on `hardware/backplane/mcu.kicad_sch`
- Phase 133 SUMMARY: `.planning/phases/133-backplane-erc-zero-violation-cleanup-via-volta-pipelin/133-03-SUMMARY.md`
- Project memory: `kiutils-root-sheet-danger.md`
