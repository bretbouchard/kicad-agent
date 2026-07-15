# P0-002: `place_missing_units` places multi-unit components at colliding positions

**Severity:** P0 (creates +29 ERC regression per affected component — actively makes schematics worse)
**Discovered:** 2026-06-24, Phase 123 of analog-ecosystem backplane cleanup
**Reproducible:** Yes, deterministic

## Symptom

`place_missing_units` op is supposed to place missing units of multi-unit components (e.g., TL072 unit C power pins) at appropriate positions. Instead, it places multiple unit instances at the SAME coordinates, creating duplicate placement.

## Reproduction

```bash
PYTHONPATH=/Users/bretbouchard/apps/volta/src /opt/homebrew/bin/python3.11 -m volta.cli '{
  "op": "place_missing_units",
  "target_file": "hardware/backplane/audio-buffers.kicad_sch"
}'
```

On backplane audio-buffers.kicad_sch with TL072 U30/U31/U32/U33 (each missing unit C):
- Expected: Each TL072 gets unit C placed at a unique non-overlapping position
- Actual: All unit C instances placed at (167.6, 87.6) — same coordinates for U30, U31, U32, U33

## Impact

Each collision creates +29 new ERC violations (duplicate symbol placement + pin conflicts). On backplane: 12 missing_unit violations → +29 regression = net worse.

Same issue would affect any multi-unit component (TL074, CD4069, op-amp arrays, etc.) across all projects.

## Suspected root cause

The op computes a position based on the parent unit (unit A) but doesn't deduplicate across multiple parent instances. All U30/U31/U32/U33 reference the same "TL072" footprint, so the algorithm places unit C at the same offset from each.

## Fix path

1. Inspect `place_missing_units` handler in `src/volta/ops/handlers/`
2. Track placed positions per call — refuse to place at coordinates already used
3. When collision detected, offset by component body width + clearance (e.g., +10mm X)
4. Add unit test exercising op on a sheet with 4+ instances of same multi-unit component
5. Verify zero position collisions in test output

## Workaround

Manual placement via `add_component` op with explicit coordinates per unit. Slow but correct.

## Related

- Discovered alongside P0-001, P0-003, P0-004, P0-005
- 12 missing_unit/power_pin/input_pin violations on backplane remain unfixed due to this bug
