---
phase: 101-schematic-ops-bug-fixes
plan: 03
subsystem: ops/repair (place_missing_units, place_no_connects_from_erc)
tags: [bug-fix, position-transform, dedup-bypass, tolerance-matching, p0-002, p0-004]
dependency_graph:
  requires:
    - "101-01 (erc_auto_fix deprecation — unrelated, no code dep)"
    - "101-02 (update_symbols_from_library fix — unrelated, no code dep)"
  provides:
    - "place_missing_units produces N distinct positions for N missing units (zero collisions) regardless of position source"
    - "place_no_connects_from_erc uses tolerance-based pin electrical-type lookup (no false 'passive' defaults on sub-0.01mm offsets)"
    - "place_no_connects_from_erc does not place no_connect markers on connected/unsafe pins (zero new no_connect_connected)"
    - "_lookup_pin_type_with_tolerance helper reusable by future position-comparison ops"
  affects:
    - "src/kicad_agent/ops/repair_components.py (place_missing_units dedup loop moved outside fallback branch; dry_run now records _occupied_positions)"
    - "src/kicad_agent/ops/repair_erc.py (new _lookup_pin_type_with_tolerance helper; pos_to_type dict removed; violation loop calls helper)"
    - "tests/test_schematic_repair.py (2 new tests + 4 fixture helpers for TL072 multi-unit scenario)"
    - "tests/test_place_no_connects_power_aware.py (2 new tests for X/Y rounding-boundary tolerance matching)"
tech_stack:
  added: []
  patterns:
    - "Position dedup applies to ALL position sources, not just fallback — prevents wire-endpoint-voting convergence collisions"
    - "Tolerance-based dict replacement: replace round(x, 2) key lookup with per-axis abs(x - p.x) <= tolerance when comparing KiCad coordinates from independent sources (ERC JSON vs IR pin positions)"
    - "Record occupied positions immediately after dedup resolution (not after placement branch) so dry_run mode stays accurate"
key_files:
  created: []
  modified:
    - "src/kicad_agent/ops/repair_components.py"
    - "src/kicad_agent/ops/repair_erc.py"
    - "tests/test_schematic_repair.py"
    - "tests/test_place_no_connects_power_aware.py"
decisions:
  - "Dedup while-loop moved OUTSIDE the `if pos is None:` block so it applies to both _find_position_for_unit output AND fallback. Nudge direction is +offset_x/+offset_y (the configured unit spacing, default 25.4mm/0.0mm) — matches the fallback's pre-existing direction. Per RESEARCH.md Open Question 3: post-call dedup is sufficient; _find_position_for_unit itself is NOT modified."
  - "Added _occupied_positions.add() immediately after dedup resolution (before the dry_run continue) so dry_run mode returns accurate distinct positions. Previously dry_run skipped the placement branch where the add() lived, causing the dedup set to stay empty and all parents to report colliding positions."
  - "Tolerance helper uses per-axis abs(x - p.x) <= SNAP_TOLERANCE (not Euclidean distance). Matches the existing _near_anchor / co-location check pattern in the same file (repair_erc.py:319-325) for consistency. SNAP_TOLERANCE=0.01mm covers the rounding-boundary gap (typical mismatch is 0.001mm)."
  - "Removed the dead pos_to_type dict (was lines 229-232). Verified nothing else reads it (grep across src/ and tests/). pin_positions list retained — still used by co-location check."
  - "Default 'passive' fallback preserved in the tolerance helper for backward compatibility (pins not in the list still default to 'passive', same as the old dict .get())."
metrics:
  duration: "~25 minutes"
  completed: "2026-06-25"
  tasks: 2
  files: 4
  tests_added: 4
---

# Phase 101 Plan 03: Fix place_missing_units Collisions + place_no_connects_from_erc Wrong Positions (P0-002, P0-004) Summary

Closed two position-calculation bugs that actively made schematics worse: `place_missing_units` placed multi-unit components at colliding positions (dedup bypass in happy path), and `place_no_connects_from_erc` placed markers on power pins due to a rounding-boundary dict-key mismatch. Both fixes reuse existing project patterns (`_occupied_positions` set from Issue #3, `SNAP_TOLERANCE` from `_near_anchor`).

## What Was Built

### R-2 (P0-002): place_missing_units dedup bypass fix

**`src/kicad_agent/ops/repair_components.py`** (lines 639-675 of `place_missing_units`):

Moved the `_occupied_positions` dedup while-loop OUTSIDE the `if pos is None:` fallback branch so it applies to ALL position sources. Previously, when `_find_position_for_unit` returned a position derived from shared wire endpoints (within `max_distance=100mm` of multiple parent components), all parents received the SAME position, bypassing the collision check. Now every position — whether from `_find_position_for_unit` or the fallback — is checked against `_occupied_positions` and nudged by `offset_x`/`offset_y` until clear.

Also fixed a dry_run-specific bug: `_occupied_positions.add()` was only called in the non-dry_run placement branch (line 707), so dry_run mode returned colliding positions because the dedup set stayed empty. Now records the position immediately after dedup resolution, covering both paths.

### R-4 (P0-004): tolerance-based pin-type lookup

**`src/kicad_agent/ops/repair_erc.py`**:

Added `_lookup_pin_type_with_tolerance(x, y, pin_positions, tolerance)` helper that finds a pin's electrical type by per-axis distance comparison (within `SNAP_TOLERANCE=0.01mm`), defaulting to `"passive"`. Replaced the exact dict-key lookup `pos_to_type.get(pos_key, "passive")` at the violation processing loop with a call to this helper. Removed the now-dead `pos_to_type` dict (it was only read by the replaced line).

The root cause: `pos_to_type` used `round(p["x"], 2)` keys (10μm grid). ERC violation positions have sub-micron precision, so a pin at `x=127.015` (rounds to `127.02`) and a violation at `x=127.014` (rounds to `127.01`) produce DIFFERENT keys despite being only 0.001mm apart. The lookup missed, defaulted to `"passive"`, and the `UNSAFE_PIN_TYPES` check was skipped — placing a no_connect on a `power_in` pin and creating a `no_connect_connected` violation.

### Regression tests

**`tests/test_schematic_repair.py`** (new class `TestPlaceMissingUnitsNoCollisions`):
- `test_place_missing_units_no_collisions` — 2 TL072 instances with shared wire endpoints that cause `_find_position_for_unit` to return the same position for both. Asserts 2 distinct positions.
- `test_place_missing_units_four_instances_distinct` — 4 TL072 instances (U30/U31/U32/U33 backplane scenario) with shared wire endpoints within range of all 4. Asserts 4 distinct positions.
- 4 fixture helpers: `_TL072_LIB_SYMBOL`, `_make_tl072_component`, `_write_tl072_schematic`, `_make_wire` — build minimal raw S-expression schematics with precise control over lib_symbol units, component positions, and wire endpoints.

**`tests/test_place_no_connects_power_aware.py`** (new class `TestPlaceNoConnectsFromErcToleranceMatching`):
- `test_no_connect_tolerance_matching` — X-axis rounding boundary: pin at `x=127.015` (key 127.02), violation at `x=127.014` (key 127.01). Asserts the pin is correctly identified as `power_in` and skipped (not defaulted to `passive`).
- `test_no_connect_tolerance_matching_y_boundary` — Y-axis rounding boundary: pin at `y=85.995` (key 86.00), violation at `y=85.994` (key 85.99). Asserts the `input` pin is correctly skipped.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] dry_run mode did not populate _occupied_positions**
- **Found during:** Task 1 GREEN phase — first fix attempt passed non-dry_run scenarios but tests still failed in dry_run.
- **Issue:** `_occupied_positions.add(_round_pos(new_x, new_y))` was at line 707, inside the non-dry_run placement branch. Dry_run hit a `continue` at line 679 before reaching the add(), so the dedup set stayed empty and all parents reported the same colliding position even after the dedup loop was moved.
- **Fix:** Added `_occupied_positions.add(_round_pos(new_x, new_y))` immediately after the dedup while-loop resolves `new_x, new_y`, BEFORE the dry_run check. Now both paths record the position.
- **Files modified:** `src/kicad_agent/ops/repair_components.py`
- **Commit:** 59c6c77

**2. [Rule 3 - Blocking] Initial test fixtures did not trigger the R-2 bug**
- **Found during:** Task 1 RED phase — first test attempt passed before any fix.
- **Issue:** Original wire positions (y=110, y=109) did not cause `_find_position_for_unit`'s candidate-voting to converge — each candidate had count=1, the function returned None, and the fallback (which already had dedup) handled placement. The bug only manifests when pin offsets from BOTH unit-3 pins vote for the same candidate, which requires wires spaced exactly `2 * pin_offset_y` apart.
- **Fix:** Computed wire positions that trigger count=2 convergence: for TL072 unit 3 (pins at y=-7.62 and y=+7.62), wires at y=102.38 and y=117.62 (15.24mm apart) cause pin 4 and pin 8 to both vote for candidate y=110.0. Verified end-to-end that both parents return `(112.5, 110.0)` before the fix.
- **Files modified:** `tests/test_schematic_repair.py`
- **Commit:** 25badb7 (RED test commit, revised fixture before commit)

**3. [Rule 3 - Blocking] Initial R-4 test positions did not cross rounding boundary**
- **Found during:** Task 2 RED phase — first test positions (pin 127.003, violation 127.00) rounded to the SAME 2-decimal key (127.0) due to Python's banker's rounding.
- **Issue:** The round(x, 2) boundary is at .XX5, but Python uses banker's rounding so 127.005 actually rounds to 127.0 (not 127.01). Needed positions where the rounding definitively crosses a boundary.
- **Fix:** Used pin_x=127.015 (rounds to 127.02) and violation_x=127.014 (rounds to 127.01) — verified these produce different keys. Added a second test with Y-axis boundary (pin_y=85.995 vs violation_y=85.994) for coverage.
- **Files modified:** `tests/test_place_no_connects_power_aware.py`
- **Commit:** 9e85011 (RED test commit, revised positions before commit)

## TDD Gate Compliance

**RED gate:** Two `test(101-03):` commits (25badb7, 9e85011) — both verified failing before fix.
**GREEN gate:** Two `fix(101-03):` commits (59c6c77, a7ee24d) — both verified passing after fix.
**REFACTOR gate:** Dead-code removal of `pos_to_type` dict folded into GREEN commit a7ee24d (minor cleanup, no behavior change).

All three gates present in git log, in order.

## Test Results

**Before plan (baseline):** 94 passed, 1 skipped in `test_schematic_repair.py` + `test_place_no_connects_power_aware.py`.

**After plan:** 98 passed, 1 skipped in the same files (+4 new tests, zero regression).

**Broader regression (including `test_erc_auto_fix.py`):** 128 passed, 1 skipped — `erc_auto_fix` depends on `repair_erc` and still works correctly (the deprecation warning from Plan 101-01 still fires).

## Threat Model Compliance

| Threat ID | Category | Disposition | Status |
|-----------|----------|-------------|--------|
| T-101-05 | Tampering (position dedup) | mitigate | MITIGATED — dedup now covers all position sources |
| T-101-06 | Info Disclosure (pin type lookup) | accept | ACCEPTED — tolerance lookup reveals no sensitive data, "passive" default is safe |
| T-101-07 | DoS (infinite dedup loop) | mitigate | MITIGATED — offset_x defaults to 25.4mm (non-zero), progress guaranteed; observed no hangs in 4-instance test |

No new threat surface introduced. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries.

## Self-Check: PASSED

**Files verified to exist:**
- FOUND: `src/kicad_agent/ops/repair_components.py`
- FOUND: `src/kicad_agent/ops/repair_erc.py`
- FOUND: `tests/test_schematic_repair.py`
- FOUND: `tests/test_place_no_connects_power_aware.py`
- FOUND: `.planning/phases/101-schematic-ops-bug-fixes/101-03-SUMMARY.md`

**Commits verified in git log:**
- FOUND: 25badb7 (test 101-03 RED R-2)
- FOUND: 59c6c77 (fix 101-03 GREEN R-2)
- FOUND: 9e85011 (test 101-03 RED R-4)
- FOUND: a7ee24d (fix 101-03 GREEN R-4)

**Test gate verified:**
- 98 passed, 1 skipped in the two affected test files (was 94 before, +4 new, zero regression)
