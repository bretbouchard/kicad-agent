# P0-003: `erc_auto_fix` rewrites entire schematic file, stripping formatting and corrupting structure

**Severity:** P0 (data loss — corrupts KiCad 10 schematics)
**Discovered:** 2026-06-24, Phase 123 of analog-ecosystem backplane cleanup (and again Phase 125)
**Reproducible:** Yes, deterministic on KiCad 10 multi-sheet schematics

## Symptom

`erc_auto_fix` op (both per-sheet and hierarchical variants) rewrites the entire schematic file. The output is structurally different from the input:
- Formatting stripped (whitespace, indentation normalized)
- Fields reordered or dropped
- lib_symbol blocks reorganized
- In worst case: file becomes unloadable by kicad-cli ("Failed to load schematic")

## Reproduction

### Per-sheet variant:
```bash
PYTHONPATH=/Users/bretbouchard/apps/kicad-agent/src /opt/homebrew/bin/python3.11 -m kicad_agent.cli '{
  "op": "erc_auto_fix",
  "target_file": "hardware/backplane/codecs.kicad_sch"
}'
```
Result on codecs.kicad_sch: 202 → 204 violations (+2 net, introduced new errors)

### Hierarchical variant:
```bash
PYTHONPATH=/Users/bretbouchard/apps/kicad-agent/src /opt/homebrew/bin/python3.11 -m kicad_agent.cli '{
  "op": "erc_auto_fix_hierarchical",
  "target_file": "hardware/backplane/slot-connectors.kicad_sch"
}'
```
Result on slot-connectors.kicad_sch: **file corrupted** — kicad-cli reports "Failed to load schematic". Root cause: PWR_FLAG lib_symbols placed INSIDE other lib_symbol blocks with malformed formatting.

## Impact

This op is actively dangerous. It should never be used on production schematics without explicit backup. Phase 123 had to revert Wave 3 because of this.

Affects all KiCad 10 projects using kicad-agent — any call to `erc_auto_fix` risks file corruption.

## Suspected root cause

The op uses kiutils re-serialization (load → modify → save) which doesn't preserve KiCad 10's strict formatting requirements. Per project memory `kiutils-root-sheet-danger.md`: "NEVER to_file() on root sheets; cascading re-serialization breaks kicad-cli."

The hierarchical variant specifically has a bug where PWR_FLAG lib_symbol insertion places the new block at the wrong nesting level (inside another lib_symbol block instead of in the top-level lib_symbols container).

## Fix path

1. **Immediate:** Mark `erc_auto_fix` and `erc_auto_fix_hierarchical` as DEPRECATED in op metadata
2. **Short-term:** Fix PWR_FLAG lib_symbol placement to insert at correct nesting level (top-level lib_symbols container, not inside another block)
3. **Long-term:** Rewrite both ops to use raw S-expression manipulation (like Phase 101 PCB ops), NOT kiutils re-serialization
4. Add unit test that verifies file loadability via kicad-cli after op execution
5. Add unit test that verifies no NEW violations introduced (regression gate)

## Workaround

Do NOT use `erc_auto_fix` or `erc_auto_fix_hierarchical`. Use targeted individual ops instead:
- `add_no_connect` for individual pins
- `add_power` for PWR_FLAG placement
- `place_no_connects_from_erc` (but see P0-004 — also broken)

## Related

- Project memory: `kiutils-root-sheet-danger.md` (same root cause)
- Phase 123 Wave 3 revert documented in `.planning/phases/123-backplane-erc-cleanup/`
- Phase 124 discovered `patch_serializer.py` mutation schema mismatch (related serialization bug)
