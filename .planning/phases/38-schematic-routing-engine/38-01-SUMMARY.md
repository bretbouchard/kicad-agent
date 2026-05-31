---
phase: 38-schematic-routing-engine
plan: 01
subsystem: schematic-routing
tags: [pin-resolution, multi-unit, rotation, tdd]
dependency_graph:
  requires: []
  provides: [PinResolver, ResolvePinPositionsOp]
  affects: [schema.py, executor.py]
tech-stack:
  added: [pin_resolver.py, _schema_schematic_routing.py]
  patterns: [unit-aware-lib-symbol-indexing, tdd-red-green]
key-files:
  created:
    - src/kicad_agent/ops/_schema_schematic_routing.py
    - src/kicad_agent/schematic_routing/pin_resolver.py
    - tests/test_pin_resolver.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
decisions:
  - Unit-aware lib symbol indexing via _build_unit_index() maps (lib_id, unit) to correct sub-symbol pins
  - PinResolver reuses _parse_lib_pins from schematic_graph rather than reimplementing parsing
  - Multi-unit components merge pins across unit instances via ref-keyed dict update
  - DoS mitigations enforce 10MB file limit and 10000 pin count limit
metrics:
  duration: 6m
  tasks: 2
  files: 5
  tests: 14
  completed: "2026-05-31"
---

# Phase 38 Plan 01: Pin Position Resolution Summary

Unit-aware pin position resolver for schematic routing, with Pydantic schema, executor handler registration, and 14 TDD tests covering R/C passives, multi-unit ICs, named pins, rotation transforms, and DoS mitigations.

## What Was Built

- **ResolvePinPositionsOp** -- Pydantic schema for the resolve_pin_positions operation with target_file (H-01 validated) and optional ref filter (max_length=16)
- **PinResolver** -- Standalone class that parses a .kicad_sch file, resolves absolute pin coordinates for every component, handling multi-unit ICs, named pins, and rotation transforms
- **Executor handler** -- `@register_schematic("resolve_pin_positions")` registered in executor.py, dispatches to PinResolver with optional ref filtering
- **14 tests** -- Full TDD cycle (RED: 8ad971d, GREEN: 3c97649), covering all 8 behavioral requirements from the plan plus schema validation edge cases and threat model mitigations

## Key Implementation Details

### Unit-Aware Lib Symbol Indexing

The core challenge was multi-unit ICs. KiCad stores pins under sub-symbol names like `"CD4066BE_1_1"` (unit 1, body style 1), `"CD4066BE_2_1"` (unit 2), `"CD4066BE_5_1"` (unit 5/power). The `_build_unit_index()` method parses these naming conventions and builds a `(lib_id, unit) -> pins` lookup that correctly maps each placed symbol instance to its specific unit's pins.

### Pin Position Calculation

Reuses the same rotation math from `schematic_graph._parse_symbol_pins()`:
1. Rotate pin offset by symbol angle: `rot_px = px * cos(sa) - py * sin(sa)`
2. Add to symbol position for body: `body = (sx + rot_px, sy + rot_py)`
3. Extend by pin length in combined direction: `wire = body + pl * (cos(pa+sa), sin(pa+sa))`

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create ResolvePinPositionsOp schema and PinResolver with tests | 8ad971d, 3c97649 | _schema_schematic_routing.py, pin_resolver.py, test_pin_resolver.py |
| 2 | Register handler in executor and wire into Operation union | afcb29e | schema.py, executor.py |

## Verification Results

```
14 passed in 0.52s  (tests/test_pin_resolver.py)
8 passed in 0.47s   (tests/test_executor_ops.py -- no regressions)
Schema import OK    (python -c "from kicad_agent.ops.schema import ResolvePinPositionsOp")
```

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED

- All 3 created files verified on disk
- All 3 commits verified in git log (8ad971d, 3c97649, afcb29e)
- No stubs found (no TODO, FIXME, placeholder patterns)
- No new threat surface beyond plan's threat_model
