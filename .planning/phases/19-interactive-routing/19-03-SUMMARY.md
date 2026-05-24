---
phase: 19
plan: 3
subsystem: routing
tags: [routing, interactive, session, approval, constraint-adaptation]
dependency_graph:
  requires: [19-01, 19-02]
  provides: [interactive-routing-session]
  affects: [routing/__init__.py, routing/interactive.py]
tech-stack:
  added: [dataclasses, enum, RoutingSuggestion, SuggestionStatus, InteractiveRoutingSession]
  patterns: [approve-reject-reroute cycle, differential pair coupling, constraint adaptation]
key-files:
  created:
    - src/kicad_agent/routing/interactive.py
  modified:
    - src/kicad_agent/routing/__init__.py
    - tests/test_routing.py
decisions:
  - RoutingSuggestion is mutable (not frozen) to allow status transitions
  - Differential pair approve/reject propagates to complement net
  - Constraint adaptation rebuilds graph only when clearance increases
  - Locked route waypoints become SpatialBox obstacles during reroute
metrics:
  duration: 2min
  tasks: 1
  files: 3
  tests_added: 14
  tests_total: 54
completed: "2026-05-24"
---

# Phase 19 Plan 3: Interactive Routing Session Summary

Interactive routing session with suggestion/approval API, constraint adaptation, and differential pair coupling -- enabling iterative review cycles for PCB trace routing.

## What Was Built

### SuggestionStatus (str, Enum)
Three-state lifecycle: `PENDING` -> `APPROVED` or `REJECTED`. Rejected nets become eligible for reroute.

### RoutingSuggestion (dataclass, mutable)
Per-net routing result with mutable status, reject_reason, and user_constraints dict. Tracks whether the net is part of a differential pair with its complement name.

### InteractiveRoutingSession
Full session lifecycle:
- **Construction**: Routes all nets (batch for regular, `route_differential_pair` for diff pairs), creates PENDING suggestions
- **approve(net_name)**: Locks route, propagates to diff pair complement
- **reject(net_name, reason)**: Marks for reroute, propagates to complement
- **set_constraint(net_name, key, value)**: Per-net override (e.g., increased clearance)
- **reroute_rejected()**: Rebuilds graph with locked route obstacles, re-routes only rejected nets, increments iteration counter
- **summary()**: Returns iteration/total/approved/rejected/pending/max_iterations counts
- **is_complete**: True when all suggestions are approved

## Test Coverage

14 new tests in `TestInteractiveSession`:
- Suggestion generation (3 nets -> 3 pending)
- Approve/Reject lifecycle with status verification
- Reroute produces new PENDING suggestions
- Max iterations enforcement (RuntimeError)
- Constraint persistence and validation
- Locked routes excluded from reroute
- Summary dict accuracy
- KeyError for nonexistent nets
- Differential pair routing, approve propagation, reject propagation
- is_complete property

**54 total routing tests pass, 0 regressions.**

## Key Decisions

1. **Mutable RoutingSuggestion**: Unlike frozen RouteResult, suggestions must transition between PENDING/APPROVED/REJECTED states, requiring a mutable dataclass.

2. **Constraint adaptation triggers graph rebuild**: When a rejected net has a user-override increasing clearance beyond the session default, the routing graph is rebuilt with the updated constraints. This is a deliberate trade-off of rebuild cost for correctness.

3. **Locked routes as SpatialBox obstacles**: Approved route waypoints are converted to small SpatialBox obstacles (trace_width/2 padding) during reroute, preventing new routes from overlapping locked paths.

4. **Diff pair coupling**: Approve/reject on one net of a differential pair automatically propagates to the complement, maintaining pair consistency.

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check

- `src/kicad_agent/routing/interactive.py`: EXISTS (484 lines)
- `src/kicad_agent/routing/__init__.py`: EXISTS (exports SuggestionStatus, RoutingSuggestion, InteractiveRoutingSession)
- `tests/test_routing.py`: EXISTS (54 tests passing)
- Commit `5e91963`: EXISTS in git log
