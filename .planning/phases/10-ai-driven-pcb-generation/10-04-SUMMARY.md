---
phase: 10-ai-driven-pcb-generation
plan: 04
subsystem: generation
tags: [intent-schema, template-generator, pcb-creation, schematic-creation, kiutils]
dependency_graph:
  requires: [10-01, 10-03]
  provides: [GenerationIntent, generate_board, generate_schematic, intent_to_operations]
  affects: []
tech_stack:
  added: [kiutils-Board-create_new, kiutils-Schematic-create_new, kiutils-Symbol]
  patterns: [template-method, discriminated-union-operations, round-trip-validation]
key_files:
  created:
    - src/kicad_agent/generation/__init__.py
    - src/kicad_agent/generation/intent.py
    - src/kicad_agent/generation/template_board.py
    - src/kicad_agent/generation/template_schematic.py
    - tests/test_generation_intent.py
    - tests/test_template_board.py
    - tests/test_template_schematic.py
  modified: []
decisions:
  - Lazy imports in __init__.py to support incremental package construction
  - ComponentSpec allows '?' in references for KiCad auto-annotation convention
  - Stub lib_symbols used for schematic generation when actual library files unavailable
  - Empty schematics are valid (no round-trip content check for zero-component designs)
  - Auto-placement uses grid-based distribution with 5mm margin from board edges
metrics:
  duration: 11 min
  completed: "2026-05-23"
  tasks: 2
  tests: 25
  files_created: 7
---

# Phase 10 Plan 04: GenerationIntent Schema and Template Board Generator Summary

GenerationIntent Pydantic schema converts high-level design parameters to structured Operation sequences; template generators create valid .kicad_pcb and .kicad_sch files from scratch using kiutils.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | GenerationIntent schema and operation converter | bf3fd00 | generation/__init__.py, generation/intent.py, tests/test_generation_intent.py |
| 2 | Template board and schematic generators | f697c0a | generation/template_board.py, generation/template_schematic.py, tests/test_template_board.py, tests/test_template_schematic.py |

## What Was Built

### Task 1: GenerationIntent Schema

The `GenerationIntent` Pydantic model serves as the structured contract between an LLM and the operation execution pipeline. Sub-models include:

- **BoardSpec**: Physical board parameters (width, height, layers, thickness, edge connector)
- **ComponentSpec**: Component placement with library_id, reference, value, position, footprint
- **NetSpec**: Net connections with name and REF.PIN pin descriptors
- **PowerSpec**: Power net requirements

The `intent_to_operations()` function converts a validated GenerationIntent into a list of existing Operation objects (AddComponentOp, AddNetOp, AddPowerOp) that flow through the standard Transaction-wrapped executor pipeline.

### Task 2: Template Generators

**Board generator** (`template_board.py`): Creates valid .kicad_pcb files using the same `Board.create_new()` + `to_file()` pattern proven in maze_generator.py. Includes board outline on Edge.Cuts, component footprint placement with auto-grid, net definitions, and round-trip validation.

**Schematic generator** (`template_schematic.py`): Creates valid .kicad_sch files with embedded lib_symbols (minimal stubs when actual libraries unavailable), component symbol instances with auto-spacing, power symbols, and round-trip validation.

## Verification

All verification commands pass:

1. `python3 -m pytest tests/test_generation_intent.py tests/test_template_board.py tests/test_template_schematic.py -x -q` -- 25 passing
2. `python3 -c "from kicad_agent.generation import GenerationIntent, generate_board, generate_schematic"` -- imports work
3. `python3 -c "from kicad_agent.generation.intent import GenerationIntent, intent_to_operations; i = GenerationIntent(name='test', power=PowerSpec(nets=[])); print(intent_to_operations(i))"` -- empty intent produces empty ops
4. Full test suite: 774 passed, 6 pre-existing failures (unchanged), 1 skipped

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical] Safe identifier pattern needed `?` for auto-references**
- **Found during:** Task 1 test execution
- **Issue:** KiCad uses `R?`, `C?`, `U?` for unannotated component references, but the safe identifier validator rejected `?`
- **Fix:** Added `?` to the allowed character pattern in `_SAFE_ID_PATTERN`
- **Files modified:** src/kicad_agent/generation/intent.py
- **Commit:** bf3fd00

**2. [Rule 3 - Blocking] kiutils API differences from assumed signatures**
- **Found during:** Task 2 test execution
- **Issue:** kiutils Symbol constructor does not accept `libId` keyword; Property constructor does not accept `x, y, angle` directly; SchematicSymbol.properties is a list, not a dict; Schematic has `graphicalItems` (not `graphicItems`); titleBlock is None on new schematics
- **Fix:** Updated all constructors and property access patterns to match actual kiutils 1.4.8 API
- **Files modified:** src/kicad_agent/generation/template_schematic.py
- **Commit:** f697c0a

**3. [Rule 3 - Blocking] Default PowerSpec includes GND and +3V3**
- **Found during:** Task 1 test execution
- **Issue:** Tests expecting empty operations from minimal intents got 2 extra power ops from default PowerSpec
- **Fix:** Updated tests to explicitly set `power=PowerSpec(nets=[])` when testing specific operation categories
- **Files modified:** tests/test_generation_intent.py
- **Commit:** bf3fd00

**4. [Rule 3 - Blocking] Eager imports in __init__.py fail before template modules exist**
- **Found during:** Task 1 initial import
- **Issue:** __init__.py imported template_board and template_schematic at module level, which didn't exist yet during incremental build
- **Fix:** Used `__getattr__` for lazy imports of template modules
- **Files modified:** src/kicad_agent/generation/__init__.py
- **Commit:** bf3fd00

## Test Coverage

| Suite | Tests | Status |
|-------|-------|--------|
| test_generation_intent.py | 14 | All passing |
| test_template_board.py | 6 | All passing |
| test_template_schematic.py | 5 | All passing |
| **Total** | **25** | **All passing** |

## Threat Model Mitigations

| Threat | Mitigation | Status |
|--------|------------|--------|
| T-10-12 (DoS via component list) | ComponentSpec capped at 500, NetSpec at 200 | Implemented |
| T-10-13 (Tampering via library_id) | Safe identifier regex validation | Implemented |
| T-10-14 (DoS via auto-placement) | Grid placement is O(n), bounded by caps | Accepted |

## Self-Check

- [x] src/kicad_agent/generation/__init__.py exists
- [x] src/kicad_agent/generation/intent.py exists
- [x] src/kicad_agent/generation/template_board.py exists
- [x] src/kicad_agent/generation/template_schematic.py exists
- [x] tests/test_generation_intent.py exists
- [x] tests/test_template_board.py exists
- [x] tests/test_template_schematic.py exists
- [x] Commit bf3fd00 exists
- [x] Commit f697c0a exists
