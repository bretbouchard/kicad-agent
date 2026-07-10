# kicad-Agent Feature Gaps — Discovered During Channel Strip ERC Cleanup

**Source:** Analog Ecosystem channel strip (hardware/network-io/channel-strip/)
**Date:** 2026-06-01
**Context:** 193 ERC violations across 15-sheet hierarchical schematic. Agent attempted to build custom tools instead of using kicad-agent, revealing capability gaps.

---

## Priority 1: High-Value Analysis Operations

### 1. `detect_component_shorts` — Component-Shorting Wire Detection
**Problem:** Wires that run alongside 2-pin passive components (R, C, L), connecting both pins and bypassing the component's function. This creates `multiple_net_names` ERC violations.
**Input:** Schematic file
**Output:** List of wires that connect both pins of the same 2-pin passive, with component ref, wire coordinates, and whether it's a genuine short vs shared junction (resistor ladder).
**Filter rules:**
- Skip if both endpoints have pins from OTHER components (shared junction / ladder)
- Skip connectors (multi-pin, wires between adjacent pins are normal)
- Flag only when BOTH endpoints have pins from the same component AND no other component pins
**Reference:** `schematic_model.py` in channel-strip implements this detection

### 2. `analyze_shorted_net` — Shorted Net Root Cause Analysis
**Problem:** Given a `multiple_net_names` ERC violation, trace the exact wire path creating the short.
**Input:** Schematic file + violation position + net names
**Output:**
- All wires in the shorted net group
- The specific bridging wire(s) that connect the two different-named nets
- Component pins on each side
- Suggested fix: which wire to break, where to reroute
**Reference:** Union-find connectivity analysis in `schematic_model.py`

### 3. `query_net_at_point` — Net Connectivity Query
**Problem:** "What net names are at position (x,y)?" and "Are these two points on the same net?"
**Input:** Schematic file + point(s)
**Output:** Net names, connected points, component pins on the net
**Note:** kicad-agent has internal union-find but may not expose it as a query API

## Priority 2: Repair Operations

### 4. `reroute_wire` — Atomic Wire Replace + Route
**Problem:** Removing a shorting wire and adding a proper replacement is two operations. Should be atomic.
**Input:** Remove wire (x1,y1,x2,y2) + Add wire (x3,y3,x4,y4)
**Output:** Both operations applied atomically (rollback on failure)

### 5. `fix_shorted_nets` — Automated Shorted Net Repair
**Problem:** The full workflow: detect short → analyze root cause → break wire → reroute → verify.
**Input:** Schematic file
**Output:** Fixed schematic, zero multiple_net_names violations
**Note:** `erc_auto_fix` may already cover this partially

## Priority 3: Architecture Operations

### 6. `convert_to_hierarchical` — Flat-to-Hierarchical Conversion
**Problem:** Channel strip uses global labels for cross-sheet connectivity (flat hierarchy). Root sheet has 139 violations from wires/labels not connecting to sub-sheet symbols. Converting to hierarchical labels + sheet pins would fix all 139.
**Input:** Root schematic with global labels + sub-sheet symbols
**Output:**
- Sub-sheets: `global_label` → `hierarchical_label` for cross-sheet signals
- Root sheet: Add hierarchical pins to sub-sheet symbols
- Root sheet: Wire labels to sheet pins
**Reference:** This would fix 72% of the channel strip violations (139/193)

---

## Priority 4: Bugs in Existing Operations

### 7. `erc_auto_fix` — Two Coordinate Bugs (CRITICAL)

**Bug A (FIXED): `_extract_positions` in `erc_parser.py` — ×100 unit mismatch**
- **Root cause:** KiCad 10's `kicad-cli --format json` outputs positions in a unit 100× smaller than mm (e.g., `97.79mm` appears as `0.9779`). The parser returned raw values without conversion.
- **Fix applied:** Multiplied positions by 100 in `_extract_positions()`. Verified: parser now returns `(97.79, 44.45)` instead of `(0.9779, 0.4445)`.
- **Status:** Fixed in `src/kicad_agent/ops/erc_parser.py`.

**Bug B (FIXED): Cross-sheet violation filtering in erc_auto_fix**
- **Root cause:** Not a coordinate system mismatch. ERC reports violations from ALL sheets in a hierarchical schematic, but `erc_auto_fix` operates on one sheet's IR at a time. When run on the root sheet, it tried to fix sub-sheet violations (12 pin_not_connected, 7 power_pin_not_driven) using root-sheet pin/label positions. The positions didn't match because they're in different sheet coordinate spaces → no_connect_dangling and missing-label regressions.
- **Fix applied:** Added `sheet_filter` parameter (default `"/"`) to `erc_auto_fix`, `erc_auto_fix_root_cause`, and `extract_violation_positions`. Violations are now filtered to the current sheet before repair dispatch. Pass `sheet_filter=None` to include all sheets (for callers that iterate sheets).
- **Status:** Fixed in `src/kicad_agent/ops/erc_auto_fix.py` and `src/kicad_agent/ops/erc_parser.py`. Verified on channel-strip analog-board (193 violations): root sheet now correctly shows 0 pin_not_connected and 0 power_pin_not_driven to fix (those are all in sub-sheets).

**Bug C (OPEN): `break_wire_shorts` can't find sub-sheet shorts**
- **Problem:** `multiple_net_names` violations are reported on root sheet but the shorting wires are in sub-sheets. `break_wire_shorts` only operates on the target file's IR, so it finds 0 shorts.
- **Example:** `+9V`/`AGND` short at (256.54, 118.11) — the wire connecting these nets is in `eq-stage.kicad_sch`, but the ERC reports it on the root sheet because global labels connect across sheets.
- **Fix needed:** `break_wire_shorts` must support hierarchical schematic traversal, or the caller must target the correct sub-sheet.

### 8. `place_missing_units` — Two Bugs Fixed, Position Bug Remains (PARTIAL FIX)
**Bug A (FIXED):** Graphic-only unit wrapper. KiCad standard library symbols (R, C, L, power) report 2 units. Fixed guard at `repair.py:989`: `len(available_units) <= 2 and len(available_units[0].pins) == 0`. Commit `aeeca58`.

**Bug B (FIXED):** Wrong unit selected. Function used kiutils array indices instead of actual KiCad unit numbers. NE5532 has unit numbers {1, 2, 3} but the function placed kiutils[2] (unit 3 = power) when unit 2 (op-amp B) was actually missing. Also never set `comp.unit` on clones — all got unit=1.
- Fix: Extract unit→pin mapping from raw sub-symbol names (`NE5532_1_1`, `NE5532_2_1`, etc.), match against placed components' `comp.unit` values, determine which unit numbers are actually missing, set correct `comp.unit` on clone.

**Bug C (OPEN):** Wrong position. Placed units go to offset positions where no wires exist. Pins float → `pin_not_connected` (+58) and `different_unit_net` (+49) violations. 193→321.
- Root cause: Function uses `comp_x + (i * 25.4)` offset but has no way to know where existing wires/labels connect to the missing unit's pins.
- Fix needed: `find_pin_wire_positions` operation that looks up wire endpoints matching the missing unit's pin positions, then calculates the correct component position so pins align with existing wires.
- Alternative: Accept that placement position requires GUI interaction, and focus on getting the unit number and reference correct (which we've achieved).

**Result:** 23 units placed with correct unit numbers and references. Positions need manual adjustment in GUI.

### 9. `erc_auto_fix` / kiutils Serializer Reformatting (HIGH)
**Problem:** Both kicad-agent and kiutils `to_file()` rewrite the entire file with different whitespace/formatting. Diff shows thousands of lines changed even for a single component addition.
**Impact:** Running any write operation on sub-sheets causes ERC regressions. Only safe approach is raw S-expression insertion (appending before the last `)` parenthesis) which preserves formatting exactly.
**Workaround:** Bypass kiutils serialization — insert raw sexpr strings directly into the file.
**Fix needed:** kiutils and kicad-agent should preserve original formatting for unchanged portions of the file.

### 10. `remove_wire` — Requires UUID Not Coordinates (MEDIUM)
**Problem:** `remove_wire` operation requires the wire's UUID, but the ERC report and most workflows provide coordinates. There's no lookup operation to find a wire UUID by coordinate.
**Fix needed:** Either accept coordinates in `remove_wire` or provide a `find_wire_at(x, y)` query operation.

---

## Implementation Priority
1. ~~**`erc_auto_fix` coordinate bug**~~ — **FIXED** (commits 1171914, f8ee8a3)
2. ~~**`place_missing_units` graphic wrapper bug**~~ — **FIXED** (commit aeeca58)
3. **`place_missing_units` wrong-unit bug** — FIXED in script, needs upstream fix
4. **`place_missing_units` position bug** — OPEN, needs `find_pin_wire_positions`
5. **kiutils serializer reformatting** — HIGH, all write operations reformat entire file
6. **`convert_to_hierarchical`** — highest ROI (fixes 143/193 = 74% of violations)
7. **`break_wire_shorts` sub-sheet support** — HIGH, can't detect shorts across hierarchy
8. `detect_component_shorts` — immediate value for ERC cleanup
9. `analyze_shorted_net` — enables automated fix workflow
10. `query_net_at_point` — developer experience improvement

## Test Results Summary (2026-06-01)

| Operation | Target | Result | Status |
|-----------|--------|--------|--------|
| `erc_auto_fix` (root) | analog-board | 193→193, zero regressions | SAFE |
| `erc_auto_fix` (gpio-expanders) | gpio-expanders | 66→68, serializer regression | BLOCKED |
| `place_missing_units` (correct units, no wiring) | all 5 sheets | 193→321 | BUG (position) |
| `break_wire_shorts` (root) | analog-board | 0 shorts found | BLOCKED |
| `break_wire_shorts` (eq-stage) | eq-stage | 0 shorts found (short is cross-hierarchy) | BLOCKED |
| `add_no_connect` | preamp-stage | Wrong fix (pin needs wire, not NC) | WRONG APPROACH |
| `remove_wire` | eq-stage | Requires UUID, not coordinates | BLOCKED |
