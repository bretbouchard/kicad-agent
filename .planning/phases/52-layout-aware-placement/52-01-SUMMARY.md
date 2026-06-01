---
phase: 52-layout-aware-placement
plan: 01
subsystem: placement
tags: [signal-flow, footprint-geometry, layout-aware, placement, zone-assignment]
dependency_graph:
  requires:
    - "placement/engine.py (HybridPlacementEngine)"
    - "placement/interactive.py (ConstraintSet)"
    - "analysis/subcircuit_detector.py (Subcircuit, SubcircuitType)"
    - "analysis/intent_schemas.py (SubcircuitIntent)"
  provides:
    - "placement/signal_flow.py (SignalFlowGrouper, SignalFlowGroup, SignalFlowZone)"
    - "placement/footprint_geometry.py (ComponentGeometry, extract_footprint_geometry)"
    - "placement/layout_aware.py (LayoutAwarePlacer, LayoutAwareRequest)"
  affects:
    - "placement/__init__.py (exports updated)"
tech_stack:
  added: [dataclasses, pydantic, BFS-graph-algorithms]
  patterns: [wrapper-pattern, frozen-dataclasses, zone-based-constraint-injection]
key_files:
  created:
    - src/kicad_agent/placement/signal_flow.py
    - src/kicad_agent/placement/footprint_geometry.py
    - src/kicad_agent/placement/layout_aware.py
    - tests/test_layout_aware_placement.py
  modified:
    - src/kicad_agent/placement/__init__.py
decisions:
  - "LayoutAwarePlacer wraps HybridPlacementEngine rather than subclassing -- composition over inheritance"
  - "Zone boundaries are soft constraints (logged, not enforced) to avoid rejecting valid placements"
  - "ThermalProfile forward-declared as Any in LayoutAwareRequest for Plan 52-02"
  - "Type priority fallback when signal flow ordering is ambiguous (no clear entry/exit nets)"
metrics:
  duration_s: 346
  completed: "2026-06-01"
  tasks: 2
  tests: 16
  files_created: 4
  files_modified: 1
---

# Phase 52 Plan 01: Layout-Aware Placement Infrastructure Summary

SignalFlowGrouper, ComponentGeometry extraction from PcbIR, and LayoutAwarePlacer wrapping HybridPlacementEngine with signal-flow-driven zone assignment.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SignalFlowGrouper and footprint geometry extraction | 23eb37e | signal_flow.py, footprint_geometry.py, test_layout_aware_placement.py |
| 2 | LayoutAwarePlacer wrapping HybridPlacementEngine | 23eb37e | layout_aware.py, __init__.py, test_layout_aware_placement.py |

## Implementation Details

### SignalFlowGrouper (signal_flow.py)
- Converts `Subcircuit[]` to `SignalFlowGroup[]` using BFS on boundary-net adjacency graph
- Signal flow ordering: subcircuits with input_nets not in other subcircuits' boundary_nets are "entry" zones; follows boundary_net chain for ordering
- Type priority fallback (`_TYPE_PRIORITY`): PREAMP/processing types = 10, OUTPUT_STAGE = 20, POWER_SUPPLY = 30, UNKNOWN = 40
- Zone type mapping: PREAMP/FILTER/VCA/MIXER etc. -> "processing", OUTPUT_STAGE -> "output", POWER_SUPPLY -> "power", UNKNOWN -> "ungrouped"
- Identifies `signal_entry_nets` and `signal_exit_nets` from intent I/O nets minus boundary nets

### ComponentGeometry (footprint_geometry.py)
- Extracts bounding boxes from PcbIR footprint pads: computes min/max x/y extents accounting for pad size
- `pad_positions` relative to footprint origin
- `thermal_area_mm2` = width * height (conservative)
- `centroid_offset` for fine-tuning placement center
- Graceful fallback: None PcbIR -> empty dict, no pads -> 2.0x2.0mm default

### LayoutAwarePlacer (layout_aware.py)
- 6-phase pipeline: signal flow grouping -> zone assignment -> constraint injection -> geometry injection -> delegated placement -> zone adherence logging
- Zone assignment: groups laid out left-to-right with `_ZONE_MARGIN_MM = 2.0` between zones
- Constraint injection: zone center components fixed to zone center, with geometry-based centroid adjustment
- Pure passthrough when no subcircuits/geometry provided
- Returns `PlacementOutput` with `source="layout_aware"`

## Verification Results

- 16/16 new tests pass
- 70/70 existing placement tests pass (zero regression)
- All module imports clean
- Pydantic validation rejects negative board dimensions and negative clearance

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

- `thermal_profiles` field in `LayoutAwareRequest` is typed as `list[Any] | None` -- forward-declared for Plan 52-02 which will define `ThermalProfile` properly
- `constraints` field in `LayoutAwareRequest` is typed as `list[Any]` -- Phase 50 `PCBConstraint` hierarchy not yet implemented

## Self-Check: PASSED
