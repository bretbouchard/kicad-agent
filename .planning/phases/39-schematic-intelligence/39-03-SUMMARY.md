---
phase: 39-schematic-intelligence
plan: 03
subsystem: schematic-intelligence
tags: [net-naming, power-convention, pin-name-analysis, pydantic, kicad-sch]

# Dependency graph
requires:
  - phase: 39-schematic-intelligence
    provides: extract_nets from Plan 39-01 for net topology data
provides:
  - suggest_net_names operation with five priority levels
  - SuggestNetNamesOp schema for LLM-to-tool contract
  - Power pin name recognition (VCC, GND, VDD, +3V3, -12V, etc.)
  - Component-ref-based naming (U1_SDA, R1_2)
affects: [net-intelligence, erc-root-cause, schematic-generation, net-repair]

# Tech tracking
tech-stack:
  added: []
  patterns: [priority-ordered name resolution, power pin regex matching, passive component detection via lib_id]

key-files:
  created:
    - src/kicad_agent/schematic_routing/net_namer.py
    - tests/test_net_namer.py
  modified:
    - src/kicad_agent/ops/_schema_schematic_intel.py
    - src/kicad_agent/ops/schema.py
    - src/kicad_agent/ops/executor.py
    - src/kicad_agent/schematic_routing/__init__.py
    - tests/test_mcp/test_edit_server.py

key-decisions:
  - "Voltage pattern regex extended to match +3V3 style (digit after V) in addition to +3.3V style"
  - "Power convention check uses pin_name matching only, not lib_id -- SchematicGraph filters out power symbols (# refs)"
  - "Passive components identified by lib_id containing Device:R, Device:C, Device:L"
  - "Fallback naming sorts by ref number then pin_number for deterministic ordering"

patterns-established:
  - "Priority-ordered net name resolution: global_label > hierarchical_label > power_convention > component_ref > fallback"
  - "Confidence levels map 1:1 to naming basis (1.0, 0.9, 0.85, 0.7, 0.5)"

requirements-completed: [SCH-INTEL-03]

# Metrics
duration: 18min
completed: 2026-05-31
---

# Phase 39 Plan 03: Auto-Name Nets Summary

**suggest_net_names operation proposing canonical net names via five priority levels: global labels (1.0), hierarchical labels (0.9), power pin conventions (0.85), IC component refs (0.7), and passive fallbacks (0.5)**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-31T23:02:18Z
- **Completed:** 2026-05-31T23:20:45Z
- **Tasks:** 1 (TDD: RED -> GREEN)
- **Files modified:** 7

## Accomplishments
- SuggestNetNamesOp schema with op_type discriminator, target_file, netlist_path, naming_convention fields
- suggest_net_names() function with five priority-ordered naming levels
- Power pin name detection matching VCC, VDD, VEE, VSS, GND, AGND, DGND, GND_ANALOG, VIN, VOUT and voltage patterns (+3V3, +5V, -12V, +3.3V, +1V8, +2V5)
- Component-ref-based naming producing REF_PIN format (e.g., U1_SDA) with ref_pin_number variant (e.g., U1_Pin5)
- Handler registered as @register_schematic("suggest_net_names") in executor
- 16 tests covering all specified behaviors

## Task Commits

Each task was committed atomically:

1. **Task 1: Add SuggestNetNamesOp schema, net_namer module, handler, and tests** - `329573e` (feat)

_Note: Single TDD commit encompassing RED (failing tests) and GREEN (implementation) phases_

## Files Created/Modified
- `src/kicad_agent/schematic_routing/net_namer.py` - suggest_net_names() with priority-ordered name resolution (new)
- `tests/test_net_namer.py` - 16 tests: schema, global label, hierarchical label, GND, VCC, +3V3, component ref, fallback, naming convention, stats (new)
- `src/kicad_agent/ops/_schema_schematic_intel.py` - SuggestNetNamesOp schema appended after DetectNetConflictsOp
- `src/kicad_agent/ops/schema.py` - Added SuggestNetNamesOp to Operation union and __all__
- `src/kicad_agent/ops/executor.py` - Registered @register_schematic("suggest_net_names") handler
- `src/kicad_agent/schematic_routing/__init__.py` - Added suggest_net_names export
- `tests/test_mcp/test_edit_server.py` - Updated operation tool count 82 -> 83, total 89 -> 90

## Decisions Made
- Extended voltage pattern regex from `r'^[+-]?\d+\.?\d*[Vv]$'` to also match `+3V3`-style patterns (digit after V), since KiCad commonly uses this naming convention
- Power convention detection relies solely on pin_name matching, not lib_id "power:*" -- SchematicGraph filters out power symbols (refs starting with "#") during parsing, so they won't appear in pin lists
- Passive components identified by checking if lib_id contains "Device:R", "Device:C", or "Device:L" -- simple but effective for the standard KiCad library convention
- Fallback naming sorts pins by (ref_number, pin_number) for deterministic output regardless of parse order

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extended voltage pattern regex to match +3V3**
- **Found during:** Task 1 (test_voltage_pattern_recognized failed)
- **Issue:** Plan's regex `r'^[+-]?\d+\.?\d*[Vv]$'` does not match `+3V3` because it expects the string to end with V. KiCad uses both `+3.3V` and `+3V3` conventions.
- **Fix:** Extended regex to `r"^[+-]?\d+(?:\.\d+)?[Vv]\d*$|^[+-]?\d+\.?\d*[Vv]$"` matching both styles
- **Files modified:** src/kicad_agent/schematic_routing/net_namer.py
- **Verification:** All 16 tests pass including test_voltage_pattern_recognized

**2. [Rule 3 - Blocking] Updated operation tool count constants**
- **Found during:** Task 1 (test_mcp tests failed)
- **Issue:** Adding SuggestNetNamesOp increased operation tools from 82 to 83, total from 89 to 90, but count assertions were stale
- **Fix:** Updated operation tools 82 -> 83, total tools 89 -> 90 in test_edit_server.py
- **Files modified:** tests/test_mcp/test_edit_server.py
- **Verification:** All 46 MCP tests pass including test_generates_82_operation_tools and test_total_tool_count

**3. [Rule 1 - Bug] Fixed test fixture pin positioning**
- **Found during:** Task 1 (test_global_label_suggestion_has_pins and test_passive_only_fallback failed)
- **Issue:** Test fixture had resistor R1 at (75,52.54) placing its pins off the wire at y=50; adjusted assertions expected wrong pin number
- **Fix:** Moved R1 to (75,50) so pin 2 wire-connection lands at (75,50) on the wire; corrected assertions to R1_1/R1_Pin1 for deterministic sort order
- **Files modified:** tests/test_net_namer.py
- **Verification:** All 16 tests pass

---

**Total deviations:** 3 auto-fixed (2 bug, 1 blocking)
**Impact on plan:** All auto-fixes necessary for correctness. Voltage regex fix handles real KiCad naming conventions. Count updates are mechanical maintenance.

## Issues Encountered
- None beyond the deviations documented above

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- suggest_net_names operation complete and callable via OperationExecutor
- Phase 39 complete (all 3 plans done): extract_nets, detect_net_conflicts, suggest_net_names
- Ready for Phase 40 (ERC Root Cause: violation classification, root cause diagnosis, enhanced erc_auto_fix)

---
*Phase: 39-schematic-intelligence*
*Completed: 2026-05-31*
