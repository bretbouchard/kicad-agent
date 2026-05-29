---
phase: 25
plan: 02
subsystem: ops/remove
tags: [remove-operations, wire-adjacency, list-filter, safety-check]
dependency_graph:
  requires: ["25-01 (schemas + UUID lookup helpers)"]
  provides: ["remove_wire", "remove_label", "remove_junction", "remove_no_connect handlers"]
  affects: ["executor.py"]
tech_stack:
  added: [remove_ops.py]
  patterns: [list-filter, identity-check, dangling-endpoint-detection]
key_files:
  created:
    - src/kicad_agent/ops/remove_ops.py
    - tests/test_remove_ops.py
  modified:
    - src/kicad_agent/ops/executor.py
decisions:
  - Wire adjacency uses dangling-endpoint detection (not blanket refusal) -- only blocks if BOTH connections at an endpoint would be lost
  - Label removal uses label_type field to dispatch to correct kiutils list (labels, globalLabels, hierarchicalLabels)
  - All handlers use identity-check filtering (is not) matching remove_component.py pattern
  - base_dir passed as file_path.parent from executor module-level functions
metrics:
  duration: ~15min
  completed: 2026-05-29
  tasks: 1
  files_created: 2
  files_modified: 1
  tests_added: 27
---

# Phase 25 Plan 02: Remove Operation Handlers Summary

Four remove operation handlers with list-filter pattern, wire adjacency safety check (dangling-endpoint detection), and 27 comprehensive tests.

## What Was Built

### `src/kicad_agent/ops/remove_ops.py` (NEW)

Four handler functions following the list-filter pattern from `remove_component.py`:

- **`remove_wire(op, ir, file_path, base_dir)`** -- Removes a wire by UUID from `graphicalItems`. Before removal, checks both endpoints for remaining connections (pins, junctions, labels, other wires). Raises `RemoveOpError` if removal would leave any endpoint dangling.
- **`remove_label(op, ir, file_path, base_dir)`** -- Removes a label by UUID. Dispatches to `labels`, `globalLabels`, or `hierarchicalLabels` based on `label_type` field.
- **`remove_junction(op, ir, file_path, base_dir)`** -- Removes a junction by UUID from `junctions` list.
- **`remove_no_connect(op, ir, file_path, base_dir)`** -- Removes a no-connect by UUID from `noConnects` list.

Internal helper `_has_remaining_connection()` checks for pins, junctions, labels, and remaining wires at a given coordinate position within 0.0001mm tolerance.

### `src/kicad_agent/ops/executor.py` (MODIFIED)

Replaced four `NotImplementedError` stubs with actual handler imports and delegation to `remove_ops.py` functions.

### `tests/test_remove_ops.py` (NEW)

27 tests across 5 test classes:

| Class | Count | Coverage |
|-------|-------|----------|
| TestRemoveWire | 6 | Basic removal, dangling refusal, adjacency allowed, pin-at-endpoint, not-found, mutation log |
| TestRemoveLabel | 5 | Local, global, hierarchical removal, not-found, mutation log |
| TestRemoveJunction | 5 | Basic removal, not-found, count decrease, isolation, mutation log |
| TestRemoveNoConnect | 5 | Basic removal, not-found, count decrease, isolation, mutation log |
| TestExecutorDispatchRemoveOps | 6 | Executor dispatch for all 4 types, full pipeline, error on missing UUID |

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

```
tests/test_remove_ops.py: 27 passed
Full suite: 1593 passed, 1 skipped, 1 deselected
```

## Self-Check: PASSED

- All created files verified on disk
- Commit 27dbbdc confirmed in git log
