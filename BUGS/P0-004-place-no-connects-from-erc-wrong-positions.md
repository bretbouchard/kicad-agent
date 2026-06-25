# P0-004: `place_no_connects_from_erc` places no_connect markers at wrong positions

**Severity:** P0 (creates new violations — actively makes ERC worse)
**Discovered:** 2026-06-24, Phase 123 of analog-ecosystem backplane cleanup (confirmed in hardware CLAUDE.md memory)
**Reproducible:** Yes, deterministic

## Symptom

`place_no_connects_from_erc` op is supposed to read ERC violations and place `no_connect` markers on pins that are flagged as unconnected-but-should-be. Instead, it places markers at positions that don't correspond to actual unused pins, creating `no_connect_connected` violations (marker on a pin that IS connected).

## Reproduction

```bash
PYTHONPATH=/Users/bretbouchard/apps/kicad-agent/src /opt/homebrew/bin/python3.11 -m kicad_agent.cli '{
  "op": "place_no_connects_from_erc",
  "target_file": "hardware/backplane/codecs.kicad_sch"
}'
```

Result on codecs.kicad_sch: 202 → 204 violations (+2). New violations are `no_connect_connected` — markers placed on pins that have wires attached.

## Impact

The op cannot be trusted for batch no_connect placement. Each call may increase violations rather than decrease them.

Already documented in project hardware CLAUDE.md: "place_no_connects_from_erc puts no_connects at wrong positions."

## Suspected root cause

The op parses ERC report for pin positions, but the position calculation likely uses:
- Wrong coordinate system (symbol-local vs sheet-absolute)
- OR wrong pin offset (pad vs pin center vs pin tip)
- OR doesn't account for symbol rotation

KiCad ERC reports pin positions in sheet-absolute coordinates, but symbol pins are defined in symbol-local coordinates with rotation transforms. The op appears to not apply the inverse transform.

## Fix path

1. Inspect `place_no_connects_from_erc` handler in `src/kicad_agent/ops/handlers/`
2. Find the pin position calculation
3. Verify against actual pin position in schematic by:
   - Loading symbol
   - Getting symbol `(at X Y ANGLE)`
   - Getting pin `(at X Y ROTATION)` (relative to symbol)
   - Computing absolute pin position with rotation transform
4. Add unit test that places a no_connect and verifies it lands on the intended pin
5. Add regression test: place on a sheet with mixed connected + unconnected pins, verify zero new `no_connect_connected` violations

## Workaround

Use individual `add_no_connect` op with manually-verified pin coordinates. Slower but correct.

## Related

- Discovered alongside P0-001, P0-002, P0-003, P0-005
- Hardware CLAUDE.md (analog-ecosystem) already documents this as known issue
- Similar class of bug as P0-002: position calculation without proper transform handling
