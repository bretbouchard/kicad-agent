---
phase: 02-operation-schema-and-ir-layer
plan: 02
subsystem: ir-layer
tags: [kiutils, dataclass, mutation-tracking, ir-wrappers, registry]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: ParseResult, UUIDMap, parsers for all file types
provides:
  - BaseIR with mutation tracking, dirty flag, mutation log, one-IR-per-ParseResult registry
  - SchematicIR wrapping kiutils Schematic with component access
  - PcbIR wrapping kiutils Board with footprints, nets, trace_items access
  - SymbolLibIR wrapping kiutils SymbolLib with symbols access
  - FootprintIR wrapping kiutils Footprint with pads, fp_lines, fp_text access
affects: [02-03-transaction, 04-mutation-operations]

# Tech tracking
tech-stack:
  added: []
  patterns: [thin-wrapper-ir, mutation-tracking, id-registry, log-cap-eviction]

key-files:
  created:
    - src/kicad_agent/ir/__init__.py
    - src/kicad_agent/ir/base.py
    - src/kicad_agent/ir/schematic_ir.py
    - src/kicad_agent/ir/pcb_ir.py
    - src/kicad_agent/ir/symbol_lib_ir.py
    - src/kicad_agent/ir/footprint_ir.py
    - tests/test_ir_layer.py
  modified: []

key-decisions:
  - "Used set[int] with id() for registry instead of WeakSet (dataclass IR instances are unhashable)"
  - "Replaced Board.segments/vias with Board.trace_items (kiutils uses traceItems not segments/vias)"
  - "FootprintIR.fp_text filters graphicItems by FpText isinstance (no textItems attribute on kiutils Footprint)"
  - "Added _clear_registry() for test isolation to prevent id() collisions between tests"

patterns-established:
  - "Thin IR wrapper: dataclass extending BaseIR, __post_init__ validates file_type, properties expose kiutils fields"
  - "Mutation tracking: _record_mutation(description, details) appends to log and sets dirty flag"
  - "Registry enforcement: one-IR-per-ParseResult via module-level set of id() values"

requirements-completed: [OPS-03]

# Metrics
duration: 10min
completed: 2026-05-18
---

# Phase 2 Plan 02: IR Layer Summary

**IR layer with BaseIR mutation tracking and four file-type wrappers over kiutils parsed objects**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-18T05:56:56Z
- **Completed:** 2026-05-18T06:07:35Z
- **Tasks:** 2
- **Files modified:** 7 (6 source + 1 test)

## Accomplishments
- BaseIR provides mutation tracking with dirty flag, mutation log (capped at 1000 entries), and one-IR-per-ParseResult registry enforcement
- Four file-type IR wrappers (SchematicIR, PcbIR, SymbolLibIR, FootprintIR) wrap kiutils objects with typed access
- 18 comprehensive tests covering mutation tracking, registry enforcement, file-type validation, and component access against real KiCad fixtures
- All 86 tests pass (48 Phase 1 + 20 Plan 02-01 + 18 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create IR base class and file-type IR wrappers** - `c40cd9d` (feat)
2. **Task 2: Create IR layer test suite** - `dcd67a8` (test)

## Files Created/Modified
- `src/kicad_agent/ir/__init__.py` - Barrel exports for SchematicIR, PcbIR, SymbolLibIR, FootprintIR
- `src/kicad_agent/ir/base.py` - BaseIR with mutation tracking, registry enforcement, log cap
- `src/kicad_agent/ir/schematic_ir.py` - SchematicIR with components, get_component_by_ref
- `src/kicad_agent/ir/pcb_ir.py` - PcbIR with footprints, nets, trace_items (requires UUID map)
- `src/kicad_agent/ir/symbol_lib_ir.py` - SymbolLibIR with symbols access
- `src/kicad_agent/ir/footprint_ir.py` - FootprintIR with pads, fp_lines, fp_text (requires UUID map)
- `tests/test_ir_layer.py` - 18 tests across 6 test classes

## Decisions Made
- Used `set[int]` with `id()` for the registry instead of `WeakSet` because dataclass instances with mutable fields (like `_mutation_log: list`) are unhashable
- Replaced `Board.segments`/`Board.vias` with `Board.trace_items` since kiutils Board does not have separate `segments`/`vias` attributes -- traces are in `traceItems`
- `FootprintIR.fp_text` filters `graphicItems` by `isinstance(item, FpText)` since kiutils Footprint has no separate `textItems` attribute

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] WeakSet import and unhashable dataclass**
- **Found during:** Task 1 (verification)
- **Issue:** `WeakSet` is in `weakref`, not `typing`. Even after fixing the import, `WeakSet.add()` fails because dataclass with mutable `list` field is unhashable.
- **Fix:** Replaced `WeakSet` with `set[int]` tracking `id(parse_result)` values. Added `_clear_registry()` for test cleanup.
- **Files modified:** src/kicad_agent/ir/base.py, tests/test_ir_layer.py
- **Verification:** All IR classes instantiate correctly; duplicate registry raises RuntimeError
- **Committed in:** c40cd9d (Task 1)

**2. [Rule 1 - Bug] Board.segments and Board.vias do not exist**
- **Found during:** Task 1 (verification)
- **Issue:** Plan specified `segments` and `vias` properties on PcbIR, but kiutils Board has `traceItems` instead of separate `segments`/`vias` attributes.
- **Fix:** Replaced `segments` and `vias` properties with single `trace_items` property returning `board.traceItems`.
- **Files modified:** src/kicad_agent/ir/pcb_ir.py
- **Verification:** PcbIR instantiates and `trace_items` returns correct list
- **Committed in:** c40cd9d (Task 1)

**3. [Rule 1 - Bug] Footprint.textItems does not exist**
- **Found during:** Task 1 (verification)
- **Issue:** Plan specified `fp_text` returning `kiutils_obj.textItems`, but kiutils Footprint has no `textItems` attribute. Text items are mixed into `graphicItems` as `FpText` instances.
- **Fix:** `fp_text` now filters `graphicItems` by `isinstance(item, FpText)` using `kiutils.items.fpitems.FpText`.
- **Files modified:** src/kicad_agent/ir/footprint_ir.py
- **Verification:** FootprintIR.fp_text returns 1 FpText item from MountingHole fixture
- **Committed in:** c40cd9d (Task 1)

**4. [Rule 3 - Blocking] Registry id() collisions in tests**
- **Found during:** Task 2 (full suite run)
- **Issue:** Module-level `_ir_registry` set persists across tests; Python can reuse `id()` values when previous ParseResult objects are garbage collected, causing false duplicate errors.
- **Fix:** Added `_clear_registry()` function to base.py and `autouse` pytest fixture in test_ir_layer.py that clears registry before/after each test.
- **Files modified:** src/kicad_agent/ir/base.py, tests/test_ir_layer.py
- **Verification:** Full test suite (86 tests) passes reliably
- **Committed in:** dcd67a8 (Task 2)

---

**Total deviations:** 4 auto-fixed (3 bugs, 1 blocking)
**Impact on plan:** All auto-fixes corrected kiutils API mismatches between plan and actual library. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- IR layer ready for Plan 03 (Transaction engine) to wrap IR mutations in file-level snapshots
- Mutation tracking infrastructure in place for Phase 4 (mutation operations)
- All IR classes tested against real KiCad fixtures with 18 tests

---
*Phase: 02-operation-schema-and-ir-layer*
*Completed: 2026-05-18*

## Self-Check: PASSED

- [x] All 7 created files exist
- [x] Commit c40cd9d exists (Task 1: feat)
- [x] Commit dcd67a8 exists (Task 2: test)
- [x] All 86 tests pass (48 Phase 1 + 20 Plan 02-01 + 18 Plan 02-02)
