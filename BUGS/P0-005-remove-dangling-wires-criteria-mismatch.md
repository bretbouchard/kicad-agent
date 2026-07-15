# P0-005: `remove_dangling_wires` uses different "dangling" criteria than KiCad ERC

**Severity:** P1 (silently no-ops on real wire_dangling violations — misleading)
**Discovered:** 2026-06-24, Phase 123 + Phase 125-127 of analog-ecosystem backplane cleanup
**Reproducible:** Yes, deterministic

## Symptom

`remove_dangling_wires` op reports "0 wires removed" even when KiCad ERC reports dozens of `wire_dangling` violations on the same sheet. The op's definition of "dangling" doesn't match KiCad ERC's definition.

## Reproduction

```bash
# On a sheet with known wire_dangling violations
kicad-cli sch erc hardware/backplane/codecs.kicad_sch --output /tmp/erc.rpt
grep -c "wire_dangling" /tmp/erc.rpt
# (returns 30+)

PYTHONPATH=/Users/bretbouchard/apps/volta/src /opt/homebrew/bin/python3.11 -m volta.cli '{
  "op": "remove_dangling_wires",
  "target_file": "hardware/backplane/codecs.kicad_sch"
}'
# (returns: removed 0 wires)
```

## Impact

The op appears to work (no crash, returns success) but silently leaves wire_dangling violations unaddressed. Cleanup phases that rely on this op make no progress.

Phase 123 Wave 2 DID succeed with this op (removed 143 violations across 9 sheets), but Phase 125-127 saw it return 0 even when violations clearly existed. The behavior is inconsistent — likely depends on which specific "dangling" pattern is present.

## Suspected root cause

Two possible definitions of "dangling wire":

1. **Geometric:** Wire endpoint has no other wire/pin/junction at the same coordinate
2. **Electrical:** Wire endpoint forms no electrical connection (KiCad ERC definition — includes wires ending at label positions, wires crossing without junction, etc.)

The op appears to use definition 1 only. KiCad ERC uses definition 2. When a wire endpoint lands on a label position but the label is of wrong type (local vs hierarchical), ERC flags it as dangling but the op sees a "connection" at the coordinate.

## Fix path

1. Inspect `remove_dangling_wires` handler
2. Align the dangling-detection logic with KiCad ERC's rules:
   - Wire endpoint must connect to: another wire endpoint, a pin, a junction, OR a label of correct type
   - If endpoint only has a label of wrong type, it's dangling
3. Add unit test that runs op on a sheet with known ERC wire_dangling violations
4. Verify op output matches `kicad-cli sch erc` report

## Workaround

Parse ERC report directly and remove specific wire segments by UUID. More work but catches all ERC-flagged dangling wires.

## Note on inconsistent behavior

Phase 123 Wave 2 successfully removed 143 wire_dangling violations using this op. The op DOES work for some dangling patterns (likely purely geometric cases). The bug is that it doesn't catch ALL ERC-flagged patterns. Recommend the fix be: if ERC reports wire_dangling at position X, the op should remove that wire even if its internal criteria don't flag it.

## Related

- Discovered alongside P0-001 through P0-004
- This is the LEAST severe of the 5 bugs (op doesn't corrupt files, just silently no-ops)
- But it blocks Phase 127 (wire cleanup) effectiveness
