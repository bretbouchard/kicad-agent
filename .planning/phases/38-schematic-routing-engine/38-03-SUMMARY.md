---
phase: 38-schematic-routing-engine
plan: 03
subsystem: schematic-routing
tags: [net-connector, wire-routing, label-generation, collision-avoidance, tdd]
dependency_graph:
  requires:
    - phase: 38-01
      provides: PinResolver for pin position resolution
    - phase: 38-02
      provides: CollisionDetector for collision zone data format
  provides:
    - NetConnector with connect_pins() method
    - ConnectPinsOp schema with PinRef and CollisionZone helpers
    - Executor handler that applies wires and labels to SchematicIR
  affects: [38-04]
tech-stack:
  added: [net_connector.py]
  patterns: [label-at-body-position, wire-through-collision-check, l-shaped-routing]
key-files:
  created:
    - src/kicad_agent/schematic_routing/net_connector.py
    - tests/test_net_connector.py
  modified:
    - src/kicad_agent/ops/_schema_schematic_routing.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
key-decisions:
  - Labels generated at body_position (not wire endpoint) for better visual placement and guaranteed connectivity
  - L-shaped wires use horizontal-first path (horizontal segment, then vertical segment)
  - Collision zone check covers full wire segment x/y range, not just endpoints
  - Pin lookup falls back to pin_name search when pin number not found
patterns-established:
  - "Label-at-body-position: net labels placed at pin body_position for visual clarity"
  - "Wire-through-collision-check: segments checked against collision zones before generation"
  - "L-shaped-routing: non-axis-aligned pins connected via horizontal-then-vertical wire pair"
requirements-completed: [SCH-ROUTE-03]
metrics:
  duration: 4m
  tasks: 2
  files: 5
  tests: 19
  completed: "2026-05-31"
---

# Phase 38 Plan 03: Connect Pins Operation Summary

Net connector with three routing strategies (wire_first, label_only, hybrid), collision zone avoidance, labels at every pin body_position, and executor handler wiring wires and labels into SchematicIR.

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-31T22:07:31Z
- **Completed:** 2026-05-31T22:11:39Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- ConnectPinsOp schema with PinRef and CollisionZone helper models and S-expression injection protection
- NetConnector.connect_pins() with three strategies generating correct wire/label distributions
- Executor handler that applies generated wires and labels directly to SchematicIR
- 19 TDD tests covering schema validation, all strategies, collision avoidance, format correctness, edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Add failing tests** - `a1fa91c` (test)
2. **Task 1 (GREEN): Implement ConnectPinsOp and NetConnector** - `783d73d` (feat)
3. **Task 2: Register handler and wire into Operation union** - `5d0ba00` (feat)

_Note: TDD tasks have multiple commits (test then feat)._

## Files Created/Modified
- `src/kicad_agent/schematic_routing/net_connector.py` - NetConnector with connect_pins() method
- `src/kicad_agent/ops/_schema_schematic_routing.py` - ConnectPinsOp, PinRef, CollisionZone schemas
- `src/kicad_agent/ops/schema.py` - Added ConnectPinsOp to Operation union, PinRef/CollisionZone exports
- `src/kicad_agent/ops/executor.py` - Registered connect_pins handler with IR mutation
- `tests/test_net_connector.py` - 19 tests covering all behavioral requirements

## Decisions Made
- Labels placed at body_position (not wire endpoint) for better KiCad visual placement and reliable connectivity
- L-shaped wires go horizontal-first (matches common schematic drawing convention)
- Collision zone check validates entire wire segment range, catching wires that pass through zones between endpoints
- Pin lookup has fallback from pin number to pin name search for flexible referencing

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness
- NetConnector ready for 38-04 (batch_connect + regenerate_wiring)
- connect_pins handler registered and functional in executor
- All 63 routing-related tests pass (19 + 14 + 22 + 8 executor)

---
*Phase: 38-schematic-routing-engine*
*Completed: 2026-05-31*
