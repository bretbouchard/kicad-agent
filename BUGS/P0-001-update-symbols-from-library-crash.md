# P0-001: `update_symbols_from_library` crashes with `'Symbol' object has no attribute 'name'`

**Severity:** P0 (blocks 242 ERC violations on backplane + likely affects all multi-sheet projects)
**Discovered:** 2026-06-24, Phase 126 of analog-ecosystem backplane cleanup
**Reproducible:** Yes, deterministic

## Symptom

Calling `update_symbols_from_library` op on any schematic with lib_symbol_mismatch violations crashes:

```
AttributeError: 'Symbol' object has no attribute 'name'
```

## Reproduction

```bash
PYTHONPATH=/Users/bretbouchard/apps/kicad-agent/src /opt/homebrew/bin/python3.11 -m kicad_agent.cli '{
  "op": "update_symbols_from_library",
  "target_file": "hardware/backplane/codecs.kicad_sch"
}'
```

Expected: Updates lib_symbols from canonical KiCad library, resolving lib_symbol_mismatch violations.

Actual: Crash before any file modification.

## Impact

Blocks Phase 126 (library symbol reconciliation) on analog-ecosystem backplane. 153 lib_symbol_mismatch + 61 footprint_link_issues + 28 lib_symbol_issues = **242 violations cannot be addressed** without this op working.

Same pattern likely affects:
- All dumb-cartridge builds (Phase 26+)
- All future multi-sheet KiCad 10 projects using kicad-agent

## Suspected root cause

The op iterates lib_symbols and accesses `.name` attribute, but the `Symbol` class doesn't expose `name` (likely should be `.lib_id` or accessed via a property/getter).

## Fix path

1. Inspect `src/kicad_agent/symbols/<symbol_class>.py` — find the `Symbol` class
2. Identify the attribute access pattern that uses `.name`
3. Either:
   - Add `name` property returning `lib_id`
   - OR update `update_symbols_from_library` handler to use correct attribute
4. Add unit test exercising the op on a schematic with lib_symbol_mismatch

## Workaround

Manual per-sheet RC4 fix script (`hardware/fix_lib_symbols_graphics.py`) handles some cases but doesn't fully reconcile lib_symbols with canonical library.

## Related

- Discovered alongside P0-002 through P0-005 during backplane cleanup
- Project memory: `kicad-agent-pcb-limitations.md` (similar pattern for PCB ops)
