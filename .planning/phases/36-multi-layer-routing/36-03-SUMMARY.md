---
phase: 36-multi-layer-routing
plan: 03
status: complete
subsystem: routing
tags: [schema, executor, impedance, length-matching, multi-layer]
key-decisions:
  - AutoRouteOp uses layers list for multi-layer, falls back to single layer field for backward compat
  - Impedance solver uses microstrip for surface layers, stripline for inner layers
  - Length matching applies sawtooth pattern to shorter net of each pair
  - Executor produces TrackSegments and ViaSegments via route_to_segments_multilayer
tech-stack:
  added:
    - Pydantic field_validator for layer name validation
    - IPC-2141 impedance integration via solve_trace_width
    - Sawtooth length matching via add_sawtooth_matching
  patterns:
    - Operation schema extension with backward-compatible defaults
    - Conditional multi-layer vs single-layer dispatch in executor handler
key-files:
  created: []
  modified:
    - src/kicad_agent/ops/_schema_pcb.py
    - src/kicad_agent/ops/executor.py
    - src/kicad_agent/routing/__init__.py
    - tests/test_routing.py
metrics:
  duration_min: 12
  completed: "2026-05-31"
  tasks: 1
  files: 4
---

# Phase 36 Plan 03: AutoRouteOp Schema Extension Summary

Extended the AutoRouteOp schema with multi-layer routing, impedance control, and length matching fields. Updated the executor handler to use the 3D routing graph, impedance solver, and sawtooth matching engine from Plans 36-01 and 36-02.

## What Was Built

1. **AutoRouteOp schema extension** (`_schema_pcb.py`): Added three new fields:
   - `layers: list[str]` -- multi-layer routing target (empty = single-layer mode)
   - `impedance_target: Optional[float]` -- target impedance in ohms (gt=0, le=200)
   - `length_match_pairs: Optional[list[tuple[str, str, float]]]` -- net pairs for length matching
   - `field_validator` for layer names matching KiCad copper layer pattern

2. **Executor handler update** (`executor.py`): `_handle_auto_route` now:
   - Builds 3D routing graph when `layers` has more than one entry
   - Calls `solve_trace_width` per layer when `impedance_target` is set (microstrip for surface, stripline for inner)
   - Applies `add_sawtooth_matching` to shorter net of each `length_match_pairs` entry
   - Produces TrackSegments with per-layer widths and ViaSegments at layer transitions
   - Returns impedance and length matching feedback in result dict

3. **Routing exports** (`routing/__init__.py`): Added exports for TrackSegment, ViaSegment, ImpedanceResult, solve_trace_width, LengthMatchResult, add_sawtooth_matching

4. **Integration tests** (`test_routing.py`): 16 new tests:
   - TestAutoRouteOpSchema (11 tests): field validation, backward compat, invalid input rejection
   - TestMultiLayerIntegration (5 tests): single-layer compat, multi-layer vias, impedance width adjustment, length matching, full pipeline

## Test Results

```
146 passed in 2.98s
```

- 130 existing tests (all pass, backward compatible)
- 16 new tests (all pass)

## Key Files Modified

| File | Change |
|------|--------|
| `src/kicad_agent/ops/_schema_pcb.py` | Added layers, impedance_target, length_match_pairs fields with validators |
| `src/kicad_agent/ops/executor.py` | Updated _handle_auto_route for multi-layer + impedance + length matching |
| `src/kicad_agent/routing/__init__.py` | Added 6 new exports (TrackSegment, ViaSegment, ImpedanceResult, etc.) |
| `tests/test_routing.py` | Added 16 integration tests |

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

All 5 files verified present. Both commits (86b1801, 964fa79) verified in git log.
