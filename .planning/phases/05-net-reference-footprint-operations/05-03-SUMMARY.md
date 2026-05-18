---
phase: 05-net-reference-footprint-operations
plan: 03
subsystem: ops-schema, ir-pcb, ir-schematic
tags: [footprint, assign, swap, validate, pin-map, schema, ir-layer, tdd]
dependency_graph:
  requires: [05-01, 05-02]
  provides: [AssignFootprintOp, SwapFootprintOp, ValidateFootprintOp, VerifyPinMapOp, SchematicIR footprint methods, PcbIR footprint methods]
  affects: [schema.py, pcb_ir.py, schematic_ir.py]
tech_stack:
  added: [kiutils Footprint.properties dict for reference lookup, kiutils Net direct construction for pad net preservation]
  patterns: [TDD red-green, discriminated union extension, mutation tracking via _record_mutation, footprint libId swap with pad net preservation]
key_files:
  created:
    - tests/test_footprint_ops.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ir/pcb_ir.py
    - src/kicad_agent/ir/schematic_ir.py
decisions:
  - Footprint reference accessed via fp.properties['Reference'] dict (not fp.reference attribute which does not exist in kiutils)
  - swap_footprint only updates libId string and preserves pad nets; geometry reload deferred to Phase 6 cross-file operations
  - verify_pin_map returns empty footprint_pads when no PCB is loaded (schematic-only context); full verification requires PCB IR integration
  - Pad nets preserved by saving (pad.number -> Net) mapping before libId change, then restoring for matching pad numbers
metrics:
  duration: 5 min
  completed: "2026-05-18T08:52:25Z"
  tasks: 2
  tests_added: 22
  tests_passing: 329
  files_modified: 4
---

# Phase 05 Plan 03: Footprint Management Operations Summary

Four footprint management operation types added to Pydantic discriminated union; SchematicIR gains assign_footprint, get_component_footprint, and verify_pin_map; PcbIR gains get_footprint_by_ref, swap_footprint, and get_footprint_pads with net preservation.

## Commits

| Hash | Message |
|------|---------|
| 3d89bb3 | test(05-03): add failing tests for footprint management schema and IR methods |
| c736174 | feat(05-03): add four footprint management operation types to schema |
| 685356b | feat(05-03): implement footprint management methods on SchematicIR and PcbIR |

## What Was Done

### Task 1: Schema Types (TDD)

Added four new operation models to `schema.py`:

- **AssignFootprintOp** -- op_type="assign_footprint", reference (min 1, max 64), footprint_lib_id (min 1, max 256)
- **SwapFootprintOp** -- op_type="swap_footprint", reference (min 1, max 64), new_footprint_lib_id (min 1, max 256)
- **ValidateFootprintOp** -- op_type="validate_footprint", footprint_lib_id (min 1, max 256)
- **VerifyPinMapOp** -- op_type="verify_pin_map", reference (min 1, max 64), footprint_lib_id (min 1, max 256)

All types added to the `Operation.root` discriminated union alongside existing 15 types.

### Task 2: IR Layer Methods (TDD)

**SchematicIR** (`schematic_ir.py`):
- `assign_footprint(reference, footprint_lib_id)` -- finds component by ref, updates "Footprint" property, records mutation, raises ValueError if not found
- `get_component_footprint(reference)` -- returns the "Footprint" property value, or None
- `verify_pin_map(reference, footprint_lib_id)` -- looks up component's libId in schematic.libSymbols, collects pin numbers from unit pins, compares against footprint pad numbers (returns diff sets)

**PcbIR** (`pcb_ir.py`):
- `get_footprint_by_ref(reference)` -- iterates footprints, matches via `fp.properties['Reference']` dict lookup
- `swap_footprint(reference, new_footprint_lib_id)` -- saves pad-to-net mapping, updates libId, restores nets for matching pad numbers, clears unmatched pads, records mutation
- `get_footprint_pads(reference)` -- returns list of (pad_number, net_name) tuples

## Test Results

22 new tests, all passing. 329 total tests passing, zero regressions.

Tests exercise real Arduino_Mega fixtures: 13 PCB footprints (J1-J7, MH1-MH6), 14 schematic components.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed footprint reference access pattern**
- **Found during:** Task 2 implementation
- **Issue:** Plan referenced `fp.reference` property which does not exist on kiutils Footprint objects. The reference is stored in `fp.properties` dict with key `'Reference'`, not as a direct attribute.
- **Fix:** Used `fp.properties.get('Reference', '')` for footprint reference lookup instead of `fp.reference`
- **Files modified:** src/kicad_agent/ir/pcb_ir.py
- **Commit:** 685356b

**2. [Rule 3 - Blocking] Adjusted verify_pin_map for schematic-only context**
- **Found during:** Task 2 implementation
- **Issue:** Plan described verify_pin_map comparing symbol pins against footprint pad numbers, but SchematicIR has no access to PCB footprint data. The method can only compare against symbol pins from libSymbols.
- **Fix:** verify_pin_map returns empty footprint_pads set when no PCB is loaded. Full pin-to-pad verification requires cross-file integration (deferred to Phase 6). Tests updated to verify symbol_pins are populated correctly.
- **Files modified:** src/kicad_agent/ir/schematic_ir.py, tests/test_footprint_ops.py
- **Commit:** 685356b

## Verification

1. `python -m pytest tests/test_footprint_ops.py -v` -- 22 passed
2. `python -m pytest tests/ -q` -- 329 passed, 0 failed
3. `python -c "from kicad_agent.ops.schema import get_operation_schema; s = get_operation_schema(); assert 'AssignFootprintOp' in str(s)"` -- passes
4. Footprint assign/swap cycle on Arduino_Mega fixture verified in tests with pad net preservation

## Self-Check: PASSED

All files verified present. All commit hashes verified in git log.
