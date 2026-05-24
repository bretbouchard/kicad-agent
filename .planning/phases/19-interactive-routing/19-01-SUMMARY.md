---
phase: 19-interactive-routing
plan: 19-01
subsystem: routing
tags: [routing, pathfinding, drc, astar, networkx]
dependency_graph:
  requires: [08-visual-primitives]
  provides: [routing-graph, astar-pathfinder, drc-constraints]
  affects: []
tech_stack:
  added: [networkx.Graph, shapely.STRtree]
  patterns: [frozen-dataclass, lazy-import, grid-routing]
key_files:
  created:
    - src/kicad_agent/routing/__init__.py
    - src/kicad_agent/routing/constraints.py
    - src/kicad_agent/routing/graph.py
    - src/kicad_agent/routing/pathfinder.py
    - tests/test_routing.py
  modified: []
decisions:
  - Shapely Point.within excludes boundary points; boundary grid nodes remain in graph
  - DRC clearance check uses strict less-than at edge midpoints for obstacle proximity
  - route_all_nets sorts by Euclidean distance (shortest first) for maximum routability
  - SpatialQueryEngine reused from spatial module for obstacle proximity queries
metrics:
  duration: 4 min
  completed: 2026-05-24
---

# Phase 19 Plan 01: Routing Graph and A* Pathfinder Summary

Routing graph model with DRC-aware edge costs and A* pathfinding engine using networkx, with 30 passing tests covering grid construction, obstacle exclusion, clearance enforcement, and batch routing.

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `src/kicad_agent/routing/__init__.py` | 28 | Barrel exports for routing package |
| `src/kicad_agent/routing/constraints.py` | 75 | RoutingConstraints frozen dataclass with validation |
| `src/kicad_agent/routing/graph.py` | 203 | RoutingGraph with grid construction and DRC edge costs |
| `src/kicad_agent/routing/pathfinder.py` | 141 | A* pathfinding, batch routing, convenience builder |
| `tests/test_routing.py` | 295 | 30 tests across 6 test classes |

## Key Implementation Details

- **RoutingConstraints**: Frozen dataclass with `__post_init__` validation enforcing clearance_mm > 0, grid_resolution_mm >= 0.1, max_nodes <= 1,000,000
- **RoutingGraph**: Builds grid nodes at `grid_resolution_mm` intervals, excludes nodes inside obstacles (via `Shapely Point.within`), creates 4-directional edges with DRC-aware cost calculation
- **Edge cost model**: `segment_length + DRC_PENALTY` if midpoint within clearance zone; edges omitted entirely if midpoint closer than `clearance_mm + trace_width_mm/2` to any obstacle
- **Pathfinding**: Uses `networkx.astar_path` with Euclidean distance heuristic; `route_all_nets` sorts nets by estimated distance (shortest first)
- **Lazy imports**: networkx and shapely imported at runtime, not at module level

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DRC clearance test geometry mismatch**
- **Found during:** Test execution (first run)
- **Issue:** Original test assumed node (24,24) on obstacle boundary would be excluded by `within` check, but Shapely `Point.within` only excludes strictly interior points
- **Fix:** Adjusted test to use 0.5mm grid with large clearance (1.0mm), verifying edges at midpoints (9.25mm, 9.75mm from obstacle) are correctly omitted
- **Files modified:** tests/test_routing.py
- **Commit:** c44302b

**2. [Rule 1 - Bug] Path interior assertion too strict**
- **Found during:** Test execution (second run)
- **Issue:** test_route_with_obstacle used `5 <= x <= 8` which matched boundary node (8.0, 5.0) -- not actually inside the obstacle
- **Fix:** Changed to strict interior check `5 < x < 8 and 5 < y < 8`
- **Files modified:** tests/test_routing.py
- **Commit:** c44302b

## Test Results

```
30 passed in 1.87s
```

Coverage: 6 test classes covering constraints (6 tests), graph construction (7 tests), pathfinding (5 tests), batch routing (4 tests), RouteResult (3 tests), convenience builder (3 tests).

## Self-Check: PASSED

All 5 created files exist. Commit c44302b verified in git log.
