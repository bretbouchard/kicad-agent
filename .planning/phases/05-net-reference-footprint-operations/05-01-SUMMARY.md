---
phase: 05-net-reference-footprint-operations
plan: 01
subsystem: ops-schema, ir-pcb, ir-schematic
tags: [net, bus, schema, ir-layer, tdd]
dependency_graph:
  requires: [04-01, 04-02, 04-03]
  provides: [AddNetOp, RemoveNetOp, RenameNetOp, AddBusOp, RemoveBusOp, PcbIR net CRUD, SchematicIR label/bus accessors]
  affects: [schema.py, pcb_ir.py, schematic_ir.py]
tech_stack:
  added: [Pydantic field_validator for whitespace rejection, kiutils Net direct construction]
  patterns: [TDD red-green, discriminated union extension, mutation tracking via _record_mutation]
key_files:
  created:
    - tests/test_net_ops.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ir/pcb_ir.py
    - src/kicad_agent/ir/schematic_ir.py
decisions:
  - Whitespace-only net names rejected via field_validator (not just min_length, since "   " has length 3)
  - Rename creates new Net() objects for pad.net to avoid shared-reference mutation issues
  - Auto-named nets use N_<number> pattern for predictable naming
  - Test 14 fixed to verify no pads connected to removed net rather than matching by libId+padNum (multiple footprints share libId)
metrics:
  duration: 6 min
  completed: "2026-05-18T08:29:04Z"
  tasks: 2
  tests_added: 28
  tests_passing: 283
  files_modified: 4
---

# Phase 05 Plan 01: Net and Bus Operation Schema and IR Methods Summary

Pydantic discriminated union extended with five net/bus operation types; PcbIR gains full net CRUD with pad propagation; SchematicIR gains label query and bus alias accessors.

## Commits

| Hash | Message |
|------|---------|
| fb2d365 | test(05-01): add failing tests for net and bus operation schema and IR methods |
| 2f4529f | feat(05-01): add five net/bus operation types to schema discriminated union |
| c339e78 | feat(05-01): implement net CRUD on PcbIR and bus/label accessors on SchematicIR |

## What Was Done

### Task 1: Schema Types (TDD)

Added five new operation models to `schema.py`:

- **AddNetOp** -- op_type="add_net", net_name (empty=auto, max 64), net_number (optional, auto-assign)
- **RemoveNetOp** -- op_type="remove_net", net_name (required, min 1, max 64)
- **RenameNetOp** -- op_type="rename_net", old_name + new_name (both required)
- **AddBusOp** -- op_type="add_bus", bus_name (required), member_nets (1-32 items, each max 64)
- **RemoveBusOp** -- op_type="remove_bus", bus_name (required)

All types added to the `Operation.root` discriminated union. Whitespace-only names rejected via `field_validator`. String length constraints per M-04 pattern.

### Task 2: IR Layer Methods (TDD)

**PcbIR** (`pcb_ir.py`):
- `add_net(net_name, net_number)` -- creates Net with auto-number, auto-name if empty, duplicate check
- `remove_net(net_name)` -- removes net, disconnects all pads (sets pad.net=None), net 0 reserved
- `rename_net(old_name, new_name)` -- renames net in board.nets AND propagates to all connected pads (creates new Net objects to avoid shared reference issues)
- `get_net_by_name(net_name)` -- returns Net or None
- `get_net_pads(net_name)` -- returns list of (footprint_libId, pad_number) tuples

**SchematicIR** (`schematic_ir.py`):
- `get_labels_by_name(name)` -- returns list of LocalLabel objects matching text
- `bus_aliases` property -- access to schematic busAliases

## Test Results

28 new tests, all passing. 283 total tests passing, zero regressions.

Tests exercise real Arduino_Mega fixtures: 79 PCB nets, 76 schematic labels.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test 14 pad verification after remove_net**
- **Found during:** Task 2 GREEN phase
- **Issue:** Test matched pads by (libId, pad_number) across footprints -- multiple footprints share the same libId, causing false positive assertions on pads that were never connected to GND
- **Fix:** Changed verification to assert no pads in the entire board are connected to "GND" after removal
- **Files modified:** tests/test_net_ops.py
- **Commit:** c339e78

**2. [Rule 2 - Security] Added whitespace-only rejection via field_validator**
- **Found during:** Task 1 GREEN phase
- **Issue:** Pydantic min_length=1 does not reject whitespace-only strings like "   " (length 3), which are not valid net names
- **Fix:** Added field_validator on all name fields that rejects strings where strip() produces empty
- **Files modified:** src/kicad_agent/ops/schema.py
- **Commit:** 2f4529f

None - plan executed exactly as written with these two auto-fixes.

## Verification

1. `python -m pytest tests/test_net_ops.py -v` -- 28 passed
2. `python -m pytest tests/ -q` -- 283 passed, 0 failed
3. `python -c "from kicad_agent.ops.schema import get_operation_schema; s = get_operation_schema(); assert 'AddNetOp' in str(s)"` -- passes
4. Net add/remove/rename cycle on Arduino_Mega fixture verified in tests

## Self-Check: PASSED

All files verified present. All commit hashes verified in git log.
