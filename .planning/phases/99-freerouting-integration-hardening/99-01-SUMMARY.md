---
phase: 99-freerouting-integration-hardening
plan: 01
subsystem: routing
tags: [freerouting, dsn, native-parser, snap-angle, net-class, zone-keepout, phase-99]
requires:
  - "Phase 76 NativeParser (NativeBoard, NativeFootprint, NativeNetClass, NativeZone, NativeGraphicItem)"
  - "Phase 89 freerouting.py (export_dsn, route_with_freerouting, FreeroutingResult)"
provides:
  - "dsn_generator.generate_dsn now consumes NativeBoard (NativeParser.parse_pcb_content)"
  - "R-1 courtyard-accurate (outline (rect ...)) on every (image ...) with pad-bbox fallback"
  - "R-2 per-net-class (class ...) emission with H-2 self-contained per-class via padstacks"
  - "R-3 3-way zone classification: plane / routing-keepout / placement-only-skip (C-1 fix)"
  - "R-5 (control (snap_angle ...)) emission with enum validation (T-99-01-04)"
  - "BLOCKER-1: snap_angle kwarg threaded through export_dsn + route_with_freerouting"
  - "NativeZone.keepout_* fields + is_routing_keepout property (C-1 fix)"
affects:
  - "Plan 99-02 (stackup-based via padstacks — per-class padstacks already handled here)"
  - "Plan 99-03 SC-5 test (route_with_freerouting snap_angle no longer TypeErrors)"
  - "Freerouting v2.2.4 (richer DSN structures consumed without Java-side changes)"
tech-stack:
  added: []
  patterns:
    - "NativeBoard-backed DSN generation (replaces regex extraction for components/pads/nets/zones)"
    - "Rotation-aware AABB outline computation (math.cos/sin transform of local footprint coords)"
    - "Defense-in-depth enum validation (snap_angle validated unconditionally at function entry)"
    - "3-way zone classification (net_name / is_routing_keepout / skip)"
key-files:
  created:
    - tests/test_phase99_r7_comment_sweep.py
    - tests/test_phase99_dsn_r1_footprints.py
    - tests/test_phase99_dsn_r1_courtyard.py
    - tests/test_phase99_dsn_r5_snap_angle.py
    - tests/test_phase99_dsn_r2_netclass.py
    - tests/test_phase99_dsn_r3_zones.py
    - tests/test_phase99_snap_angle_threading.py
  modified:
    - src/kicad_agent/routing/dsn_generator.py
    - src/kicad_agent/routing/freerouting.py
    - src/kicad_agent/parser/pcb_native_types.py
    - src/kicad_agent/parser/pcb_native_parser.py
    - src/kicad_agent/handler.py
    - src/kicad_agent/ir/pcb_ir.py
    - src/kicad_agent/ops/_schema_pcb.py
    - src/kicad_agent/ops/handlers/pcb.py
    - src/kicad_agent/routing/pathfinder.py
    - src/kicad_agent/routing/graph.py
decisions:
  - "Keep _extract_board_outline on regex (M-3 deferred Bead) — NativeBoard.outline migration is larger refactor; hybrid state documented and tracked"
  - "Emit per-class via padstacks in Plan 99-01 not 99-02 (H-2 fix) — DSN must be self-contained after this plan alone"
  - "Validate snap_angle against fixed enum at every layer (generate_dsn/export_dsn/route_with_freerouting) per T-99-01-04 mitigation"
  - "Rotation-aware AABB is conservative (overestimates courtyard for 45° rotations) — always safe, never under-blocks"
  - "Placement-only keepouts skipped entirely rather than emitted as (place_keepout ...) — Freerouting v2.2.4 ignores place_keepout, so skipping is safest (C-1)"
metrics:
  duration: "16 min"
  completed: "2026-06-25"
  tasks: 4
  files_created: 7
  files_modified: 10
  tests_added: 22
---

# Phase 99 Plan 01: DSN Generator NativeBoard Refactor + R-1/R-2/R-3/R-5/R-7 Summary

Refactored `dsn_generator.py` from brittle regex extraction to typed `NativeBoard` consumption, emitting courtyard-accurate footprint obstacles (R-1), per-net-class rules with self-contained via padstacks (R-2 + H-2), 3-way zone classification (R-3 + C-1), 45° trace mode (R-5), and threaded `snap_angle` through the full `route_with_freerouting → export_dsn → generate_dsn` chain (BLOCKER-1). Also swept 19 stale "Phase 122B" comment references to "Phase 99" across 7 files (R-7).

## What Shipped

### R-7: Comment Sweep (Task 1)
Swept the literal substring `Phase 122B` → `Phase 99` across 7 source files (19 occurrences), preserving all `Gap N` suffixes. Pure-Python `pathlib.rglob` test replaces subprocess grep (WARN-5). Files: handler.py, pcb_ir.py, pcb_native_parser.py, _schema_pcb.py, handlers/pcb.py, pathfinder.py, graph.py.

### R-1: Courtyard-Accurate Footprint Outlines (Task 2a)
Every `(image ...)` block now contains an `(outline (rect F.Cu X1 Y1 X2 Y2))` element. Outlines are computed from `F.CrtYd`/`B.CrtYd` graphic items with footprint rotation applied (L-2 fix: `math.cos`/`sin` transform of local coords before AABB). Falls back to pad bounding box (rotation-transformed, ± half pad size) when no CrtYd graphics exist. Conservative AABB overestimates for 45° rotations but never under-blocks.

### R-2: Per-Net-Class Rules + H-2 Self-Contained Padstacks (Task 2b)
Named net classes (`(net_class "Power" ...)`) now emit `(class "Power" NET1 NET2 ... (circuit (use_layer ...) (use_via "Via[Power]")) (rule (width 500) (clearance 300)))` blocks with mm→um conversion. H-2 fix: when a class has `via_diameter > 0`, a matching `(padstack "Via[Power]" ...)` is emitted in the library block of THIS plan — so the DSN is valid standalone without waiting for Plan 99-02. Plan 99-02 now only handles stackup-based via padstacks (THT/blind/buried).

### R-3: 3-Way Zone Classification (Task 2b, C-1 fix)
Replaced the old binary `net_name == ""` check with 3-way classification driven by `NativeZone.is_routing_keepout`:
- **Category 1** (`net_name != ""`): copper pour → emit `(plane "NET" (layer L) (polygon ...))`. Multi-layer zones emit one plane per layer.
- **Category 2** (`is_routing_keepout == True`, i.e. tracks OR vias `not_allowed`): routing keepout → emit `(keepout "NAME" (polygon ...))`.
- **Category 3** (placement-only, only `footprints not_allowed`): SKIP. The old binary logic would have emitted a routing `(keepout ...)` for these, telling Freerouting to avoid a region the source PCB allows tracks through. Verified against `tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_pcb` (PoE placement-only keepout, `tracks allowed`, `vias allowed`, `footprints not_allowed`).

### R-5: 45° Trace Mode (Task 2a)
`generate_dsn(..., snap_angle="fortyfive_degree")` emits `(control (snap_angle fortyfive_degree))` inside the `(structure ...)` block, AFTER `(boundary ...)` and zones (M-2 fix: canonical DSN ordering per RESEARCH.md). Default `"none"` omits the control line. Enum validated unconditionally at function entry (L-1 fix, T-99-01-04 mitigation): `{"none", "fortyfive_degree", "ninety_degree"}`.

### BLOCKER-1: snap_angle Threading (Task 3)
`export_dsn()` and `route_with_freerouting()` now both accept `snap_angle: str = "none"` and thread it through to `generate_dsn()`. Plan 99-03 Task 1 SC-5 test (`route_with_freerouting(fixture, max_passes=2, snap_angle="fortyfive_degree")`) will no longer TypeError.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed standalone `(net_name ...)` field not parsed in zones**
- **Found during:** Task 2b (R-3 copper-pour test failed)
- **Issue:** Real KiCad zones emit `(net N)` and `(net_name "NAME")` as SEPARATE sibling fields, but `_extract_zones` only read the combined `(net N "NAME")` form. Copper-pour zones (Category 1, depend on `net_name != ""`) were misclassified as placement-only.
- **Fix:** Added fallback `_find_string_child(zone_block, "net_name")` after the `(net ...)` block parse in `pcb_native_parser.py:_extract_zones`.
- **Files modified:** src/kicad_agent/parser/pcb_native_parser.py
- **Commit:** 10004a9

### Deferred Items (M-3 fix)

**M-3 deferred Bead: Complete dsn_generator.py regex removal — migrate _extract_board_outline to NativeBoard.outline**

The board boundary extraction (`_extract_board_outline`) still uses regex. All other data (footprints, pads, nets, net_classes, zones) now comes from `NativeBoard`. This hybrid state is intentional — `NativeBoard.outline` parsing (Edge.Cuts graphic items → bounding box) is a larger refactor that would touch `NativeBoardOutline.items` handling and deserves its own plan. The regex path works correctly for all current fixtures.

**Resolution plan:**
1. Extend `NativeParser._extract_board_outline` to populate `NativeBoard.board_outline.items` with Edge.Cuts `gr_line`/`gr_rect`/`gr_poly` graphic items (already parsed into `NativeGraphicItem` by `_extract_graphic_items`).
2. Add a `NativeBoardOutline.bounding_box()` helper that computes the AABB across all items.
3. Replace `_extract_board_outline(pcb_content)` call in `generate_dsn()` with `board.board_outline.bounding_box()`.
4. Delete `_extract_board_outline` and its `_find_matching_close` helper (last regex user).
5. Remove the `re` import if no longer needed.

**Bead tracking note:** Beads MCP tools (`mcp__beads__beads_create`) are not available in this worktree executor's restricted tool set. This SUMMARY documents the deferral per bureaucracy §10. The orchestrator or a subsequent session should create the Bead with `labels: "deferred,refactor,phase-99"`, `priority: "2"`, depending on the current Phase 99 task bead.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond what the plan's `<threat_model>` already covers. T-99-01-04 (snap_angle enum validation) implemented as specified.

## Known Stubs

None. All code paths produce real data from `NativeBoard`. No hardcoded empty values, placeholder text, or unwired components.

## TDD Gate Compliance

All 4 tasks followed RED/GREEN cycle with commits:
- **Task 1 (R-7):** test file written first → sweep applied → 2 tests pass
- **Task 2a (R-1/R-5):** 3 test files written first (8 tests, all RED) → refactor implemented → all GREEN
- **Task 2b (R-2/R-3/C-1/H-2):** 2 test files written first (9 tests, 3 RED) → NativeZone extended → all GREEN
- **Task 3 (BLOCKER-1):** test file written first (4 tests, 3 RED) → snap_angle threaded → all GREEN

## Test Results

- **New Phase 99 tests:** 22 tests across 7 files, all passing
- **Regression (routing/bridge):** 159 existing tests, all passing
- **Regression (native parser/adapter):** 140 existing tests, all passing
- **Total verified:** 321 tests green

## Self-Check: PASSED

Verified post-commit:
- All 7 created test files exist at expected absolute paths
- All 4 task commits present in git log (1ac3031, df2e766, 10004a9, bb8d0be)
- Zero `122B` references remain in `src/` (pure-Python scan)
- `snap_angle` appears 6 times in freerouting.py (≥4 required)
- `_extract_components` / `_extract_pads` fully removed from dsn_generator.py
- `is_routing_keepout` property present on NativeZone (2 hits in pcb_native_types.py)
