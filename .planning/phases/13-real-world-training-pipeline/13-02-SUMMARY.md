---
phase: 13-real-world-training-pipeline
plan: 02
subsystem: training
tags: [networkx, graph, schematic, pcb, spatial, json, sha256]

# Dependency graph
requires:
  - phase: 08-visual-primitives
    provides: "spatial extractor (extract_all) and primitives"
  - phase: 05-net-reference-footprint-operations
    provides: "NetGraph connectivity analysis"
  - phase: 02-operation-schema-and-ir-layer
    provides: "SchematicIR, PcbIR, parse_schematic, parse_pcb"
  - phase: 13-01
    provides: "GitHub crawler for downloading schematic+PCB pairs"
provides:
  - "BoardGraphResult frozen dataclass with board graph metadata"
  - "build_board_graph() composing SchematicIR + PcbIR + NetGraph + extract_all"
  - "Unified networkx graph with component nodes and net edges"
  - "Spatial feature attachment (x, y, rotation, bbox) to graph nodes"
  - "SHA256 content hash from raw file bytes for stable dedup"
  - "Graph JSON serialization via node-link-data format"
affects: [13-03, training-data-pipeline, grpo-training]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IR registry cleanup via difference_update to prevent id() collision across sequential calls"

key-files:
  created:
    - src/kicad_agent/training/graph_builder.py
    - tests/test_graph_builder.py
  modified: []

key-decisions:
  - "IR registry entries cleaned up via difference_update after graph construction to allow repeated calls to build_board_graph on the same files"
  - "Board hash computed from raw file bytes (before kiutils parsing) for stable deduplication"
  - "Net edges connect component references (not individual pads) when 2+ components share a net"

patterns-established:
  - "ParseResult registry cleanup: build_board_graph tracks registered IDs and removes them after completion (success or failure)"

requirements-completed: [RW-02, RW-03]

# Metrics
duration: 4min
completed: 2026-05-23
---

# Phase 13 Plan 02: Board Graph Builder Summary

**Unified networkx graph from schematic+PCB pairs with component nodes, net edges, spatial features, and stable SHA256 dedup**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-23T23:44:43Z
- **Completed:** 2026-05-23T23:48:55Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- BoardGraphResult frozen dataclass with 14 fields (all primitives/JSON strings) for safe JSONL serialization
- build_board_graph() composes SchematicIR + PcbIR + NetGraph + extract_all into unified graph pipeline
- Component nodes from schematic with reference, value, footprint attributes
- Net edges connecting components sharing the same net (component-level, not pad-level)
- Spatial attributes (x_mm, y_mm, rotation_deg, bbox_width_mm, bbox_height_mm) from PCB footprints
- SHA256 hash from raw file bytes before kiutils parsing for stable dedup
- Difficulty grading: easy (<10 components), medium (10-50), hard (50+)
- 16 tests passing including real RaspberryPi-uHAT fixture parsing

## Task Commits

Each task was committed atomically:

1. **Task 1: Board graph builder with spatial features and JSON serialization** - `beae776` (feat)

## Files Created/Modified
- `src/kicad_agent/training/graph_builder.py` - Board graph construction from schematic+PCB pairs (BoardGraphResult, build_board_graph)
- `tests/test_graph_builder.py` - 16 tests covering frozen dataclass, error handling, graph roundtrip, spatial features, real fixture parsing

## Decisions Made
- IR registry cleanup via difference_update to prevent id() collision when calling build_board_graph multiple times on the same files (Python can reuse memory addresses for garbage-collected ParseResult objects)
- Board hash from raw bytes (not kiutils serialization) because kiutils output is non-deterministic per STATE.md decision
- Net edges at component level (not pad level) because downstream ML training needs component connectivity, not individual pad connections

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] IR registry cleanup for sequential calls**
- **Found during:** Task 1 (test_board_hash_is_stable)
- **Issue:** BaseIR enforces one-IR-per-ParseResult via a global registry using id(). When build_board_graph is called twice on the same files, Python reuses memory addresses for GC'd ParseResult objects, causing "already has an IR wrapper" errors
- **Fix:** Track registered ParseResult IDs and clean them up via _ir_registry.difference_update() in both success and exception paths
- **Files modified:** src/kicad_agent/training/graph_builder.py
- **Verification:** test_board_hash_is_stable passes (two sequential calls succeed)
- **Committed in:** beae776 (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed -= operator shadowing module-level import**
- **Found during:** Task 1 (test_returns_none_on_invalid_schematic)
- **Issue:** Using `_ir_registry -= _registered_ids` caused UnboundLocalError because Python treats `-=` as local variable assignment, shadowing the module-level import
- **Fix:** Changed to `_ir_registry.difference_update(_registered_ids)` which mutates in-place without creating a local binding
- **Files modified:** src/kicad_agent/training/graph_builder.py
- **Verification:** All tests pass including error-path tests
- **Committed in:** beae776 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking)
**Impact on plan:** Both fixes necessary for correct function execution. No scope creep.

## Issues Encountered
- The one-IR-per-ParseResult registry pattern in BaseIR doesn't account for short-lived IR objects created in utility functions. Solved by cleaning up after graph construction. This is the correct approach because graph_builder only needs IR data temporarily to build the graph, not for ongoing mutation tracking.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Board graph pipeline complete, ready for Plan 13-03 (training data collection and dataset assembly)
- build_board_graph() can be called by the GitHub crawler pipeline (13-01) to transform downloaded file pairs into graph data
- All 953 existing tests still passing (16 new tests added)

## Self-Check: PASSED

- [x] src/kicad_agent/training/graph_builder.py exists
- [x] tests/test_graph_builder.py exists
- [x] Commit beae776 exists in git log
- [x] All 16 new tests passing
- [x] Full test suite: 953 passed, 1 skipped

---
*Phase: 13-real-world-training-pipeline*
*Completed: 2026-05-23*
