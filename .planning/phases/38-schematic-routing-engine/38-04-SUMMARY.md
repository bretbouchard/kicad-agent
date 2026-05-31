---
phase: 38-schematic-routing-engine
plan: 04
subsystem: schematic-routing
tags: [batch-wiring, regenerate-wiring, global-labels, netlist-definition, tdd]
dependency_graph:
  requires:
    - phase: 38-01
      provides: PinResolver for pin position resolution
    - phase: 38-02
      provides: CollisionDetector for collision zone data
    - phase: 38-03
      provides: NetConnector with connect_pins() method
  provides:
    - BatchWiring with batch_connect() and regenerate_wiring()
    - BatchConnectOp and RegenerateWiringOp schemas
    - NetDef and GlobalLabelSpec helper schemas
    - Executor handlers for batch_connect and regenerate_wiring
  affects: []
tech-stack:
  added: [batch_wiring.py]
  patterns: [aggregate-statistics-collection, kiutils-stripping, auto-collision-detection]
key-files:
  created:
    - src/kicad_agent/schematic_routing/batch_wiring.py
    - tests/test_batch_wiring.py
  modified:
    - src/kicad_agent/ops/_schema_schematic_routing.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
decisions:
  - batch_connect returns aggregate statistics across all nets (sum of wires/labels)
  - Auto-detection of collision zones via CollisionDetector when none explicitly provided
  - regenerate_wiring uses kiutils from_file/to_file for element stripping (not raw S-expression manipulation)
  - Global labels generated as data dicts with name/position/shape for executor to apply via ir.add_label
  - Test fixture uses kiutils-generated valid KiCad schematic content (not hand-written S-expressions)
metrics:
  duration: 7m
  tasks: 2
  files: 5
  tests: 30
  completed: "2026-05-31"
---

# Phase 38 Plan 04: Batch Wiring Summary

High-level batch wiring operations for full schematic wiring: batch_connect processes multiple nets with auto-detected collision zones and global label generation; regenerate_wiring strips all existing wires/labels/no_connects via kiutils and reconnects from a netlist definition.

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-31T22:14:13Z
- **Completed:** 2026-05-31T22:21:05Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- BatchConnectOp and RegenerateWiringOp schemas with NetDef and GlobalLabelSpec helpers
- BatchWiring.batch_connect() with auto collision detection, aggregate stats, global labels
- BatchWiring.regenerate_wiring() strips wires/labels/no_connects via kiutils and reconnects
- Executor handlers registered with IR mutation for wires/labels/global labels
- 30 TDD tests covering schemas, batch processing, auto-detection, stripping, full pipeline

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Add failing tests** - `76d3a37` (test)
2. **Task 1 (GREEN): Implement schemas and BatchWiring** - `f72ce74` (feat)
3. **Task 2: Register handlers and wire into Operation union** - `f855153` (feat)

## Files Created/Modified
- `src/kicad_agent/schematic_routing/batch_wiring.py` - BatchWiring with batch_connect() and regenerate_wiring()
- `src/kicad_agent/ops/_schema_schematic_routing.py` - BatchConnectOp, RegenerateWiringOp, NetDef, GlobalLabelSpec
- `src/kicad_agent/ops/schema.py` - Added BatchConnectOp, RegenerateWiringOp to Operation union
- `src/kicad_agent/ops/executor.py` - Registered batch_connect and regenerate_wiring handlers
- `tests/test_batch_wiring.py` - 30 tests covering all behavioral requirements

## Decisions Made
- Auto-detection of collision zones happens inside batch_connect when none provided, converting CollisionDetector output to CollisionZone-compatible dicts
- regenerate_wiring uses kiutils `Schematic.from_file()` / `sch.to_file()` for stripping, which is the correct kiutils API (not `parse`/`serialize`)
- Global labels generated as plain dicts with name/position/shape, letting the executor handler call `ir.add_label()` with label_type="global"
- Test fixture content generated via kiutils `Schematic.create_new()` to ensure valid parseable KiCad files

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] kiutils API: from_file/to_file, not parse/serialize**
- **Found during:** Task 1 GREEN phase (test_regenerate_wiring_strips_existing_content failed)
- **Issue:** Plan referenced `Schematic.parse()` and `sch.serialize()` but kiutils uses `Schematic.from_file()` and `sch.to_file()`
- **Fix:** Updated `_strip_wiring_elements()` to use correct kiutils API
- **Files modified:** batch_wiring.py
- **Commit:** f72ce74

**2. [Rule 1 - Bug] Test fixture not parseable by kiutils**
- **Found during:** Task 1 GREEN phase (kiutils could not parse hand-written S-expression)
- **Issue:** `_mock_schematic_content()` returned hand-written S-expressions that lacked required KiCad fields (version, generator, sheet_instances)
- **Fix:** Replaced with kiutils-generated content using `Schematic.create_new()` plus programmatic addition of wires/labels/no_connects
- **Files modified:** test_batch_wiring.py
- **Commit:** f72ce74

**3. [Rule 3 - Blocking] Test mock patches not active during method calls**
- **Found during:** Task 1 GREEN phase (test_batch_connect_auto_detects_collision_zones failed)
- **Issue:** `_make_batch_wiring()` started and stopped patches during construction, so when batch_connect() created a new CollisionDetector, the real class was used instead of the mock
- **Fix:** Restructured test helper to store mocks on instance and use `_call_batch_connect()` wrapper that re-enters patches during the actual method call
- **Files modified:** test_batch_wiring.py
- **Commit:** f72ce74

## Verification Results

```
30 passed in 1.21s  (tests/test_batch_wiring.py)
14 passed in 0.25s  (tests/test_pin_resolver.py)
22 passed in 0.26s  (tests/test_collision_detector.py)
19 passed in 0.23s  (tests/test_net_connector.py)
8 passed in 0.40s   (tests/test_executor_ops.py -- no regressions)
Schema import OK    (BatchConnectOp, RegenerateWiringOp, ConnectPinsOp)
```

## Self-Check: PASSED

- All 3 created/modified source files verified on disk
- All 3 commits verified in git log (76d3a37, f72ce74, f855153)
- No stubs found (no TODO, FIXME, placeholder patterns)
- No new threat surface beyond plan's threat_model
- No accidental file deletions in any commit
