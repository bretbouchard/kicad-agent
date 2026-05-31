---
phase: 39-schematic-intelligence
plan: 01
subsystem: schematic-intelligence
tags: [net-extraction, schematic-graph, union-find, topology, pydantic, kicad-sch]

# Dependency graph
requires:
  - phase: 38-schematic-routing
    provides: SchematicGraph wire/pin/label parsing, netlist_parser, trace_endpoint_to_net
provides:
  - extract_nets operation returning complete net topology
  - ExtractNetsOp schema for LLM-to-tool contract
  - Union-find based wire connectivity grouping
  - Mid-point pin-on-wire-segment detection
affects: [39-02, 39-03, net-intelligence, erc-root-cause]

# Tech tracking
tech-stack:
  added: []
  patterns: [union-find for connectivity, multi-pin position map, mid-point wire detection]

key-files:
  created:
    - src/kicad_agent/ops/_schema_schematic_intel.py
    - src/kicad_agent/schematic_routing/net_extractor.py
    - tests/test_net_extractor.py
  modified:
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
    - src/kicad_agent/schematic_routing/__init__.py
    - tests/test_code_quality.py
    - tests/test_mcp/test_edit_server.py

key-decisions:
  - "pin_pos_map uses list[PinPosition] per position to handle multiple pins at same coordinates"
  - "Mid-point connectivity: pins on wire segments (not just endpoints) are unioned into the net"
  - "Wire-only components (no pins, no labels) still create net entries for completeness"
  - "Auto-names use Net_N pattern for unnamed nets"

patterns-established:
  - "Schematic intelligence schemas in _schema_schematic_intel.py (extends with DetectNetConflictsOp, SuggestNetNamesOp)"
  - "Union-find pattern for connected-component grouping of schematic positions"
  - "Multi-pin position indexing: dict[Pos, list[PinPosition]] to handle overlapping pin coordinates"

requirements-completed: [SCH-INTEL-01]

# Metrics
duration: 23min
completed: 2026-05-31
---

# Phase 39 Plan 01: Net Extraction Summary

**extract_nets operation building complete net topology from SchematicGraph using union-find wire connectivity, label resolution, and optional netlist cross-reference**

## Performance

- **Duration:** 23 min
- **Started:** 2026-05-31T22:24:42Z
- **Completed:** 2026-05-31T22:47:50Z
- **Tasks:** 1 (TDD: RED -> GREEN)
- **Files modified:** 8

## Accomplishments
- ExtractNetsOp schema with op_type discriminator, target_file, include_positions, netlist_path fields
- extract_nets() function using union-find for wire-connected component grouping
- Global/local/hierarchical label resolution to net names
- Auto-generated Net_N naming for unnamed wire groups
- Optional netlist pin_index cross-reference for additional name resolution
- Mid-point pin-on-wire-segment detection for KiCad-style connectivity
- Handler registered as @register_schematic("extract_nets") in executor
- 13 tests covering all specified behaviors

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ExtractNetsOp schema, net_extractor module, handler, and tests** - `da125c9` (feat)

_Note: Single TDD commit encompassing RED (failing tests) and GREEN (implementation) phases_

## Files Created/Modified
- `src/kicad_agent/ops/_schema_schematic_intel.py` - ExtractNetsOp Pydantic schema (new)
- `src/kicad_agent/schematic_routing/net_extractor.py` - extract_nets() with union-find algorithm (new)
- `tests/test_net_extractor.py` - 13 tests: schema, empty, labels, unnamed, multi-pin, stats, netlist (new)
- `src/kicad_agent/ops/schema.py` - Added ExtractNetsOp to Operation union and __all__
- `src/kicad_agent/ops/executor.py` - Registered @register_schematic("extract_nets") handler
- `src/kicad_agent/schematic_routing/__init__.py` - Added extract_nets export
- `tests/test_code_quality.py` - Updated schema sub-module count 14 -> 16
- `tests/test_mcp/test_edit_server.py` - Updated operation tool count 74 -> 81, total 81 -> 88

## Decisions Made
- Used list[PinPosition] per position in pin_pos_map because KiCad components (e.g., resistors at angle 0) can have multiple pins at identical wire-connection coordinates -- a single-value dict would silently drop pins
- Added _point_on_segment() helper for mid-point connectivity: in KiCad, a pin touching a wire segment at any point (not just endpoints) is electrically connected
- Wire-only components (no pins, no labels) are included as nets per the plan's must_have: "Unnamed nets are grouped by wire connectivity even without labels"

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pin_pos_map overwriting pins at shared positions**
- **Found during:** Task 1 (test_netlist_resolves_net_names failed)
- **Issue:** pin_pos_map used dict[Pos, PinPosition] -- when two pins share the same wire-connection coordinate (common for resistors), the second overwrites the first
- **Fix:** Changed to dict[Pos, list[PinPosition]] with setdefault/append pattern, updated all consumers
- **Files modified:** src/kicad_agent/schematic_routing/net_extractor.py
- **Verification:** All 13 tests pass including netlist cross-reference test

**2. [Rule 1 - Bug] Added mid-point wire segment connectivity**
- **Found during:** Task 1 (test_netlist_resolves_net_names failed -- pin at wire midpoint not connected)
- **Issue:** Union-find only connected wire endpoints, but KiCad considers any pin on a wire segment as connected, not just those at endpoints
- **Fix:** Added _point_on_segment() helper and Step 2b that unions any position lying on a wire segment with the segment's endpoints
- **Files modified:** src/kicad_agent/schematic_routing/net_extractor.py
- **Verification:** All 13 tests pass

**3. [Rule 3 - Blocking] Updated test count constants for Phase 38+39 additions**
- **Found during:** Task 1 (test_code_quality.py and test_mcp tests failed)
- **Issue:** Phase 38 added _schema_schematic_routing.py and Phase 39 added _schema_schematic_intel.py, but count assertions were stale (14 sub-modules, 74 tools)
- **Fix:** Updated: schema sub-modules 14 -> 16, operation tools 74 -> 81, total tools 81 -> 88
- **Files modified:** tests/test_code_quality.py, tests/test_mcp/test_edit_server.py
- **Verification:** Full test suite passes (863+ tests)

---

**Total deviations:** 3 auto-fixed (2 bug, 1 blocking)
**Impact on plan:** All auto-fixes necessary for correctness. Pin deduplication and mid-point connectivity are fundamental to net extraction accuracy. Count updates are mechanical maintenance.

## Issues Encountered
- Test fixture positioning required careful calculation of pin wire-connection points relative to symbol origin and rotation angle to ensure pins align with wire segments

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- extract_nets operation complete and callable via OperationExecutor
- Ready for Plan 39-02 (detect_net_conflicts) which depends on extract_nets for topology analysis
- Ready for Plan 39-03 (suggest_net_names) which depends on extract_nets for unnamed net identification

---
*Phase: 39-schematic-intelligence*
*Completed: 2026-05-31*

## Self-Check: PASSED

- All 3 created files found on disk
- Commit da125c9 found in git history
- All 13 tests pass
