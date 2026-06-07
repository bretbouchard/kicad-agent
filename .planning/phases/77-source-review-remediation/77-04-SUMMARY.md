---
phase: 77-source-review-remediation
plan: 04
subsystem: schematic-routing
tags: [kicad, schematic-routing, wire-router, erc, bug-fix, grid-snap]

# Dependency graph
requires:
  - phase: 77-source-review-remediation
    provides: BUGS.md with R-BUG-001 through R-BUG-008 findings
provides:
  - Fixed schematic_routing subsystem: power_unit_placer, schematic_graph, batch_executor, wire_router, collision_detector, __init__
  - L-shaped routing implementation (was disabled)
  - Grid-snapped wire coordinates
  - Hierarchical sheet pin support
  - 24 new tests for modified modules
affects: [schematic-routing, wire-routing, ERC-parsing, hierarchical-designs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Depth-tracked paren matching for KiCad (schematic ...) block boundaries
    - Unit-aware pin index building from lib_symbols sub-symbol naming conventions
    - Grid snapping via round(value / grid) * grid for coordinate alignment

key-files:
  created:
    - tests/test_power_unit_placer.py
    - tests/test_wire_router.py
  modified:
    - src/kicad_agent/schematic_routing/power_unit_placer.py
    - src/kicad_agent/schematic_routing/schematic_graph.py
    - src/kicad_agent/schematic_routing/batch_executor.py
    - src/kicad_agent/schematic_routing/wire_router.py
    - src/kicad_agent/schematic_routing/collision_detector.py
    - src/kicad_agent/schematic_routing/__init__.py
    - tests/test_collision_detector.py
    - tests/test_schematic_graph.py

key-decisions:
  - "Use depth tracking from (schematic opening paren instead of rfind() for block boundary detection"
  - "Parse unit numbers from symbol instances for per-unit pin resolution in schematic_graph"
  - "Auto-detect ERC coordinate scale from first violation value instead of hardcoded mm/100"
  - "Implement L-shape routing with two fixes: extend to corner + new segment to target"
  - "Parse sheet_pin entries as hierarchical labels for cross-sheet connectivity"

patterns-established:
  - "Depth-tracking for KiCad S-expression block boundaries: find opening paren, count depth to 0"
  - "Unit-aware lib_symbols lookup: build (base, unit) index, resolve with 4-strategy fallback"

requirements-completed: []

# Metrics
started: 2026-06-07T05:09:13Z
completed: 2026-06-07T05:23:00Z
duration: 14m
duration_minutes: 14
commits: 8
files_modified: 10
---

# Phase 77 Plan 04: Schematic Routing Bug Remediation Summary

**Fixed 8 critical/high bugs in kicad-agent schematic_routing subsystem: power unit placement, multi-unit pin resolution, block boundary detection, grid snapping, netlist parsing, ERC scaling, hierarchical sheet pins, and L-shaped routing**

## Performance

- **Duration:** 14m
- **Started:** 2026-06-07T05:09:13Z
- **Completed:** 2026-06-07T05:23:00Z
- **Tasks:** 8
- **Commits:** 8 (atomic task commits)
- **Files modified:** 10

## Accomplishments

- Fixed power_unit_placer inserting power units OUTSIDE the (schematic ...) block (R-BUG-001) -- root cause of persistent missing_power_pin ERC violations
- Fixed multi-unit IC pin resolution returning ALL pins instead of unit-specific pins (R-BUG-002) -- CD4066BE, TL072, NE5532 all affected
- Fixed batch_executor new_segment insertion using rfind(")") which found wrong block boundary (R-BUG-003)
- Added grid snapping to wire router endpoints to prevent endpoint_off_grid ERC violations (R-BUG-004)
- Fixed collision_detector netlist parser to handle KiCad 10 quoted code values like (code "1") (R-BUG-005)
- Auto-detected ERC coordinate scale instead of hardcoded mm/100 assumption (R-BUG-006)
- Added hierarchical sheet pin parsing for cross-sheet connectivity in multi-sheet designs (R-BUG-007)
- Implemented L-shaped routing (was disabled with `pass`) for non-same-axis violations (R-BUG-008)

## Task Commits

Each task was committed atomically:

1. **Task 1: R-BUG-001 power_unit_placer insertion point** - `0f87a1f` (fix)
2. **Task 2: R-BUG-002 multi-unit pin resolution** - `9ae3e1b` (fix)
3. **Task 3: R-BUG-003 batch_executor insertion point** - `55da0f7` (fix)
4. **Task 4: R-BUG-004 grid snapping** - `093d7a5` (fix)
5. **Task 5: R-BUG-005 KiCad 10 netlist format** - `dace378` (fix)
6. **Task 6: R-BUG-006 ERC scale auto-detection** - `cda4862` (fix)
7. **Task 7: R-BUG-007 hierarchical sheet pins** - `ec94e19` (fix)
8. **Task 8: R-BUG-008 L-shaped routing** - `b5b7ac4` (fix)

## Files Created/Modified

- `src/kicad_agent/schematic_routing/power_unit_placer.py` - Added _find_schematic_block_end() for correct insertion point
- `src/kicad_agent/schematic_routing/schematic_graph.py` - Added _build_unit_index(), _resolve_unit_pins(), sheet pin parsing
- `src/kicad_agent/schematic_routing/batch_executor.py` - Added _find_schematic_insertion_point() for correct insertion
- `src/kicad_agent/schematic_routing/wire_router.py` - Added _snap_to_grid(), L-shaped routing, removed duplicate function
- `src/kicad_agent/schematic_routing/collision_detector.py` - Fixed netlist regex for quoted code values
- `src/kicad_agent/schematic_routing/__init__.py` - Auto-detect ERC coordinate scale
- `tests/test_power_unit_placer.py` - 7 new tests for schematic block end detection
- `tests/test_wire_router.py` - 12 new tests for grid snap, same-axis, L-shape routing
- `tests/test_collision_detector.py` - 1 new test for KiCad 10 quoted code format
- `tests/test_schematic_graph.py` - 4 new tests for hierarchical sheet pin parsing

## Decisions Made

- **Depth tracking over rfind()**: Both power_unit_placer and batch_executor used rfind(")") to find the schematic block end, but this finds the (kicad_sch ...) closing paren instead of (schematic ...). Replaced with depth tracking from the (schematic opening paren.
- **Unit-aware pin resolution in schematic_graph**: Ported pin_resolver's _build_unit_index pattern into schematic_graph.py to fix multi-unit IC pin resolution. The old code returned ALL pins from all units.
- **Grid snapping via round(value/grid)*grid**: Used simple integer rounding after division instead of round() to avoid banker's rounding issues (e.g., 59.69/2.54=23.5 rounds to 24 instead of 23).
- **ERC scale auto-detection**: Instead of hardcoded *100, detect from first violation value. Values >500 are assumed already in schematic coordinates.
- **L-shape as two fixes**: Implement L-shaped routing as extend (dangling -> corner) + new_segment (corner -> target), reusing existing batch_executor infrastructure.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed duplicate _snap_to_grid function**
- **Found during:** Task 8 (R-BUG-008 L-shaped routing)
- **Issue:** wire_router.py had two _snap_to_grid functions with different signatures (float vs tuple). The second shadowed the first, causing TypeError when called with float args.
- **Fix:** Removed the tuple version (line 181-191), kept the float version (line 40).
- **Files modified:** src/kicad_agent/schematic_routing/wire_router.py
- **Committed in:** `b5b7ac4` (part of R-BUG-008 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Dead code removal, no scope creep.

## Issues Encountered

- Test assertions for grid snapping needed on-grid values (99.06=39*2.54 instead of 100.0) since grid snapping is now correctly applied to all coordinates.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Schematic routing subsystem is significantly more robust for channel strip and hierarchical designs
- L-shaped routing enables fixing non-same-axis ERC violations (majority of violations in dense analog layouts)
- Hierarchical sheet pin support enables cross-sheet net tracing for 15-sheet channel strip designs
- Remaining schematic_routing bugs from BUGS.md: P-BUG-001 through P-BUG-005 (parser subsystem), S-BUG-001 through S-BUG-005 (serializer), O-BUG-001 through O-BUG-008 (ops/execution), V-BUG-001 through V-BUG-003 (validation)

## Self-Check: PASSED

All commits verified:
- `0f87a1f` R-BUG-001: FOUND
- `9ae3e1b` R-BUG-002: FOUND
- `55da0f7` R-BUG-003: FOUND
- `093d7a5` R-BUG-004: FOUND
- `dace378` R-BUG-005: FOUND
- `cda4862` R-BUG-006: FOUND
- `ec94e19` R-BUG-007: FOUND
- `b5b7ac4` R-BUG-008: FOUND

All created test files verified:
- FOUND: tests/test_power_unit_placer.py
- FOUND: tests/test_wire_router.py

All 115 tests pass (91 original + 24 new).

---
*Phase: 77-source-review-remediation*
*Completed: 2026-06-07*
