---
phase: 51-pcb-spatial-intelligence
plan: 02
subsystem: spatial
tags: [pcb, spatial, shapely, board-outline, edge-cuts, strtree, dirty-flag, query-engine]
dependency_graph:
  requires: [spatial/pcb_model.py, spatial/query.py, spatial/extractor.py, ir/pcb_ir.py]
  provides: [spatial/board_outline.py, spatial/pcb_model.py (updated)]
  affects: [spatial/__init__.py, tests/test_pcb_spatial_model.py]
tech_stack:
  added: [shapely.ops.linemerge, shapely.ops.polygonize, shapely.ops.unary_union]
  patterns: [snap-tolerance-closure, lazy-query-engine-rebuild, attribute-presence-type-detection]
key_files:
  created:
    - src/kicad_agent/spatial/board_outline.py
  modified:
    - src/kicad_agent/spatial/pcb_model.py
    - src/kicad_agent/spatial/__init__.py
    - tests/test_pcb_spatial_model.py
decisions:
  - Arc center computed via perpendicular bisector intersection; 32-segment LineString approximation
  - 1nm snap tolerance closes floating-point gaps before polygonize (manufacturing tolerance >> 1nm)
  - Graphic item type detection by attribute presence (has start/end/mid/center), not isinstance
  - SpatialQueryEngine rebuilt lazily on access when dirty; mark_dirty invalidates cached engine
metrics:
  duration: 7 minutes
  completed: "2026-06-01T19:34:00Z"
  tasks_completed: 2
  tests_added: 15
  tests_passing: 51
  files_created: 1
  files_modified: 3
---

# Phase 51 Plan 02: Board Outline, Dirty-Flag Lifecycle, Spatial Query Integration Summary

Board outline extraction from Edge.Cuts graphic items with arc interpolation and snap-tolerance closure, dirty-flag lifecycle with lazy SpatialQueryEngine rebuild, and convenience query methods -- all backed by 15 new tests (51 total passing).

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Board outline extraction from Edge.Cuts | c2ea86d | board_outline.py, __init__.py |
| 2 | Integrate board outline, query engine, and tests | a945fc1 | pcb_model.py, __init__.py, test_pcb_spatial_model.py |

## Key Changes

### Task 1: Board outline extraction from Edge.Cuts

- **extract_board_outline**: Filters board.graphicItems for Edge.Cuts layer, converts each graphic item type to Shapely geometry:
  - GrLine: LineString from start/end
  - GrArc: 32-segment LineString approximation via perpendicular bisector center computation
  - GrCircle: Point.buffer(radius) polygon
  - GrRect: 4-corner LineString
- **_arc_to_linestring**: Private helper that computes arc center via perpendicular bisector intersection, determines CW/CCW direction by checking if mid-angle is on the shorter arc, and interpolates N points. Falls back to simple 3-point LineString for degenerate cases.
- **Snap tolerance**: 1nm (_SNAP_TOLERANCE = 1e-6) closes floating-point gaps between first/last coordinates of merged linestrings before polygonize. This is critical because arc interpolation introduces sub-nanometer coordinate drift.
- **Type detection**: Uses attribute presence checks (has start/end/mid/center) rather than isinstance, since kiutils types may vary and MagicMock tests need control.

### Task 2: PcbSpatialModel integration and tests

- **board_outline property**: Returns Shapely Polygon/MultiPolygon/None extracted during _build()
- **board_bounds property**: Returns (minx, miny, maxx, maxy) tuple or None
- **query_engine property**: Lazy SpatialQueryEngine construction with auto-rebuild when dirty
- **Convenience methods**: find_near, find_in_box, find_clearance delegate to SpatialQueryEngine
- **Dirty-flag lifecycle**: mark_dirty() sets _dirty=True and invalidates _query_engine. rebuild() calls _build() only when dirty. query_engine access triggers rebuild if dirty.
- **15 new tests**: TestBoardOutline (5), TestDirtyFlagLifecycle (6), TestSpatialQueryIntegration (4)

## Verification Results

- 51/51 tests pass in tests/test_pcb_spatial_model.py
- 26/26 existing spatial tests pass (no regression in test_spatial_extractor.py or test_spatial_query.py)
- Arduino_Mega board outline: Polygon, area=5373.8 sq mm, bounds=(100.0, 46.66, 201.6, 100.0)
- All imports from kicad_agent.spatial work without error

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Floating-point gap prevents polygonize from closing outline**
- **Found during:** Task 1 verification
- **Issue:** Merged linestring from Edge.Cuts arcs had sub-nanometer gap between first and last coordinates (198.298, 100.0 vs 198.298, 100.00000000000001), preventing polygonize from detecting a closed ring.
- **Fix:** Added snap tolerance (1nm) check before polygonize. If merged LineString first/last point distance is < 1e-6 but > 0, snap last coordinate to first.
- **Files modified:** board_outline.py
- **Commit:** c2ea86d

**2. [Rule 3 - Blocking] MagicMock auto-creates attributes breaking type detection**
- **Found during:** Task 2 test run
- **Issue:** `del item.mid` on MagicMock doesn't prevent `hasattr(mock, 'mid')` from returning True, causing test_outline_with_only_lines to create arc items instead of line items.
- **Fix:** Used `MagicMock(spec=["layer", "start", "end"])` to restrict allowed attributes.
- **Files modified:** tests/test_pcb_spatial_model.py
- **Commit:** a945fc1

## Test Coverage

| Class | Tests | Coverage |
|-------|-------|----------|
| TestLayerClassifier | 9 | All 7 methods + empty string + classify |
| TestLayerStackup | 6 | from_board, dielectric, thickness, empty, frozen x2 |
| TestNetClassGeometry | 4 | default, from_net_class_def, build_map, frozen |
| TestPcbSpatialModel | 13 | Build, layers, geometry, copper, net_class, dirty, batch, tolerance, stackup, copy |
| TestClearanceTolerance | 3 | False positive, real gap, overlapping |
| TestBoardOutline | 5 | Arduino outline exists, is Polygon, bounds, empty board, only lines |
| TestDirtyFlagLifecycle | 6 | Initial not dirty, mark sets, rebuild clears, noop, batch, query auto-rebuild |
| TestSpatialQueryIntegration | 4 | find_near, find_in_box, board_bounds, no net classes |

## Known Stubs

None. All modules are fully implemented with real data sources.

## Threat Flags

None. No new security surface introduced beyond what the threat model covers.

## Self-Check: PASSED

All files and commits verified present.
