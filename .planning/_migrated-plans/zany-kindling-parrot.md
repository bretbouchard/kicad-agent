# Plan: Commit Bug B Fix + Roadmap Bug C

## Context

`place_missing_units` in kicad-agent had three bugs. Bug A (graphic wrapper) fixed in `aeeca58`. Bug B (unit identification) is fixed and tested. Bug C (position) requires connectivity tracing beyond simple wire-endpoint matching.

**Why Bug C can't be solved with spatial matching alone:**
- NE5532 units 1 and 2 have **identical pin offset patterns** (same 3 offset pairs, different pin numbers)
- Wire-endpoint matching can't tell "a wire for pin 3" from "a wire for pin 5" when the offsets are the same
- Filtering placed-pin positions removed only 2/133 anchors — insufficient signal
- The wires for missing unit pins are NOT dangling (zero `unconnected_wire_endpoint` in EQ Stage) — they're connected to labels, junctions, and other components
- A real fix requires connectivity tracing: follow wires through junctions to labels, match net names to pin functions

**Decision:** Ship Bug B (correct unit identification). Bug C deferred to a future phase that builds a connectivity tracer.

## Step 1: Commit Bug B fix to kicad-agent

### Files modified:
- `src/kicad_agent/ops/repair.py` — core fix + 3 new helpers
- `tests/test_schematic_repair.py` — 10 new tests

### Changes in `repair.py`:

**New helper functions (lines ~918-1037):**
- `_get_unit_pin_map(lib_sym)` — parses sub-symbol names `ParentName_X_Y` to extract unit_number → pin_numbers mapping. Skips graphic-only units (no pins).
- `_get_unit_pin_offsets(lib_sym, unit_num)` — returns pin_number → (px, py) offsets for a specific unit from the lib symbol
- `_find_position_for_unit(...)` — wire-endpoint + label position matching with proximity filtering. Uses Y-inversion pattern from `get_pin_positions()`. Requires ≥2 pin agreement. Center-based radius filter prevents cross-component matches.

**Replaced logic in `place_missing_units()`:**
- OLD: `range(placed_count, len(available))` — sequential array index iteration
- NEW: `_get_unit_pin_map()` → set difference → `sorted(unit_pin_map.keys() - placed_unit_nums)` — correct KiCad unit number detection
- OLD: `comp.unit` never set on clones (always 1)
- NEW: `new_comp.unit = missing_num` — correct sub-symbol rendering
- OLD: `unit_letter = chr(ord("A") + unit_index)` — wrong for non-sequential units
- NEW: `unit_letter = chr(ord("A") + missing_num - 1)` — derived from actual unit number
- NEW: Fallback uses sequential offset (not stacking) to avoid `different_unit_net` violations

### New tests (42 total, 32 existing + 10 new):
- `TestGetUnitPinMap` (3 tests): NE5532 mapping, CD4066BE mapping, graphic wrapper skip
- `TestGetUnitPinOffsets` (2 tests): specific unit offsets, unknown unit returns empty
- `TestFindPositionForUnit` (3 tests): wire endpoint matching, no wires returns None, label position matching
- `TestPlaceMissingUnits` (2 tests): dry run on eq-stage, NE5532 U3 correctly identifies unit 2

## Step 2: Verify

```bash
cd /Users/bretbouchard/apps/kicad-agent
python -m pytest tests/test_schematic_repair.py -x -q   # 42 passed
python -m pytest tests/ -x -q                            # 3171 passed (full suite)
```

Dry run confirms correct unit identification on channel strip:
```
eq-stage:      U3B(unit 2), U4B(unit 2), U4C(unit 3), U4D(unit 4), U5B(unit 2) = 5 units
input-stage:   U1B(2), U1C(3), U1D(4), U2B(2), U2C(3), U2D(4) = 6 units
compressor-stage: U21B(2), U21C(3), U21D(4), U23B(2), U23C(3), U23D(4), U24B(2) = 7 units
preamp-stage:  U8B(2), U8C(3), U8D(4) = 3 units
output-stage:  U9B(2), U10B(2) = 2 units
Total: 23 missing units correctly identified
```

## Step 3: Revert eq-stage to clean baseline

The eq-stage was modified during testing (offset placement → 221 violations). Restore from backup:
```bash
cp hardware/network-io/channel-strip/eq-stage.kicad_sch.bak hardware/network-io/channel-strip/eq-stage.kicad_sch
kicad-cli sch erc hardware/network-io/channel-strip/analog-board.kicad_sch  # expect 193
```

## Step 4: Commit

```
fix(kicad-agent): correct unit identification in place_missing_units

Bug B fix: uses KiCad unit numbers from sub-symbol names instead of
sequential array indices. Sets comp.unit on clones so the correct
sub-symbol graphics render. Includes wire-endpoint position matching
with proximity filtering (Bug C partial - works for some units, falls
back to offset for others).

Adds 10 tests: _get_unit_pin_map, _get_unit_pin_offsets,
_find_position_for_unit, and integration tests against channel strip.
```

## Out of Scope — Bug C Roadmap

**Problem:** Dual op-amps (NE5532) have identical pin offset patterns for units 1 & 2. Wire-endpoint matching can't distinguish which wires belong to which unit.

**Future approach — connectivity tracer:**
1. Export KiCad netlist: `kicad-cli sch export netlist <sch> -o net.net`
2. Parse netlist to find net-to-pin mappings for placed units
3. For missing unit pin numbers, identify which nets they should connect to (from IC datasheet or pin function inference)
4. Trace those nets to find physical wire/label positions in the schematic
5. Calculate component position from those positions

This requires building a netlist parser and connectivity graph — a significant feature (~200-400 lines) best handled as a dedicated phase.
