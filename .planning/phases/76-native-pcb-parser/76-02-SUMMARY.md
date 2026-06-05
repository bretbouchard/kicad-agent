---
phase: "76-native-pcb-parser"
plan: "02"
subsystem: ir
tags: [pcb, parser, native, adapter, kiutils-fallback, pcb_ir, executor]

# Dependency graph
requires:
  - phase: "76-01"
    provides: [NativeBoard, NativeParser, NativeNet, NativeFootprint, NativePad, NativeGraphicItem, _NativePosition]
provides:
  - PcbIR with NativeBoard adapter and kiutils fallback (from_native classmethod)
  - Executor using NativeParser for PCB read path with kiutils serialization
  - 41 integration tests for native adapter, fallback, and CRITICAL-2 consumers
affects: [pcb_ops, spatial/board_outline, spatial/layer_stackup, generation/template_board, export/general]

# Tech tracking
tech-stack:
  added: []
  patterns: ["_is_native branching pattern", "from_native classmethod for NativeBoard PcbIR", "dual-parser executor pattern"]

key-files:
  created:
    - tests/test_pcb_native_adapter.py
  modified:
    - src/kicad_agent/ir/pcb_ir.py
    - src/kicad_agent/ops/executor.py

key-decisions:
  - "D-76-02-1: Executor uses dual-parser approach -- native for reads, kiutils for serialization -- to achieve zero regression while making native the default read path"
  - "D-76-02-2: _is_native property on PcbIR for branching mutation methods between NativeNet/NativePad and kiutils Net/pad"
  - "D-76-02-3: UUID map requirement relaxed for native path (NativeBoard preserves UUIDs automatically via raw_content)"

patterns-established:
  - "_is_native branching: PcbIR methods check self._is_native to select NativeBoard vs kiutils code paths"
  - "from_native classmethod: Creates PcbIR from NativeBoard without UUID map"
  - "Dual-parser executor: Always parse with kiutils for serialization, optionally augment with native parser for reads"

requirements-completed: ["#43"]

# Metrics
started: 2026-06-05T05:53:23Z
completed: 2026-06-05T06:02:27Z
duration: 9m
duration_minutes: 9
commits: 1
files_modified: 3
---

# Phase 76 Plan 02: Wire NativeParser into PcbIR and Executor Summary

**PcbIR NativeBoard adapter with _is_native branching for all mutation/query methods, executor dual-parser pattern (native reads + kiutils serialization), and 41 integration tests with zero regression.**

## Performance

- **Duration:** 9m
- **Started:** 2026-06-05T05:53:23Z
- **Completed:** 2026-06-05T06:02:27Z
- **Tasks:** 1
- **Commits:** 1
- **Files modified:** 3

## Accomplishments
- PcbIR.from_native() creates NativeBoard-backed IR without UUID map requirement
- All 8 PcbIR methods (add_net, remove_net, rename_net, swap_footprint, get_net_pads, get_footprint_pads, get_board_bounds, extract_netlist) handle both NativeBoard and kiutils Board
- Executor._execute_pcb uses NativeParser for read path via _try_native_parse() with Exception catch per CRITICAL-1
- 41 integration tests covering native path, kiutils fallback, CRITICAL-2 external consumers, board_outline duck-typing
- All 73 existing PCB + handler tests pass with zero regression

## Task Commits

1. **Task 1: Add NativeBoard adapter to PcbIR and wire NativeParser into executor** - `a044f10` (feat)

## Files Created/Modified
- `src/kicad_agent/ir/pcb_ir.py` - Added _native_board field, _is_native property, from_native() classmethod, native branching in all mutation/query methods (936 lines, +135)
- `src/kicad_agent/ops/executor.py` - Added _try_native_parse() static method, dual-parser logic in _execute_pcb (always kiutils for serialization, native for reads)
- `tests/test_pcb_native_adapter.py` - 41 tests across 7 test classes: construction, properties, net mutations, footprint queries, board queries, kiutils fallback, CRITICAL-2 consumers, board_outline duck-typing, mutation tracking (451 lines)

## Decisions Made

1. **Dual-parser executor pattern (D-76-02-1):** The executor always parses with kiutils for serialization support (serialize_pcb calls kiutils_obj.to_file()). NativeParser is tried additionally for the PcbIR read path. This avoids the NativeBoard serialization gap while still making native the default read path. The alternative (native-only path with raw_content write-back) would require all handlers to be native-aware and was deferred.

2. **_is_native branching (D-76-02-2):** A boolean property on PcbIR that determines which code path to use. NativeBoard has different attribute names (lib_id vs libId, net_name vs pad.net.name, position tuple vs Position object). Branching at the method level keeps each path simple and avoids complex adapter wrappers.

3. **UUID map relaxation (D-76-02-3):** When PcbIR is created via from_native(), no UUID map is required because NativeParser preserves UUIDs in raw_content (no kiutils round-trip = no UUID loss). The __post_init__ check only enforces UUID map when _native_board is None.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test assertion for net number off by one**
- **Found during:** Task 1 (test execution)
- **Issue:** Test asserted net.number == 80 but Arduino Mega has 79 nets (0-78), so max+1 = 79
- **Fix:** Changed assertion to net.number == 79
- **Files modified:** tests/test_pcb_native_adapter.py
- **Committed in:** a044f10

**2. [Rule 1 - Bug] Executor serialization crash with NativeBoard**
- **Found during:** Task 1 (regression testing)
- **Issue:** When executor used native parser as sole parser, serialize_pcb() called NativeBoard.to_file() which doesn't exist (AttributeError)
- **Fix:** Changed executor to dual-parser approach: always parse with kiutils for serialization, optionally augment with native parser for PcbIR read path. Added _try_native_parse() static method replacing _parse_pcb_native_or_kiutils().
- **Files modified:** src/kicad_agent/ops/executor.py
- **Committed in:** a044f10

**3. [Rule 1 - Bug] Test referenced renamed method**
- **Found during:** Task 1 (test execution)
- **Issue:** test_executor_fallback_on_native_failure referenced _parse_pcb_native_or_kiutils which was renamed to _try_native_parse
- **Fix:** Updated test to call _try_native_parse() and assert None return on failure
- **Files modified:** tests/test_pcb_native_adapter.py
- **Committed in:** a044f10

---

**Total deviations:** 3 auto-fixed (all Rule 1 - Bug)
**Impact on plan:** All auto-fixes necessary for correctness. No scope creep. The dual-parser approach (deviation #2) is the most significant -- it changes the executor strategy from "native replaces kiutils" to "native augments kiutils" for zero-regression migration.

## Issues Encountered

- NativeBoard has no to_file() method, making it unsuitable as a drop-in replacement for kiutils Board in the serialization path. Resolved by keeping kiutils parse_result for serialization while using NativeBoard for reads through PcbIR.
- Test ordering sensitivity with IR registry when mixing native and kiutils PcbIR creation in the same test session. Not a bug -- the _clear_ir_registry fixture handles this correctly.

## Known Stubs

None -- all PcbIR methods have complete native and kiutils code paths. The NativeStackup.layers list is a placeholder (full stackup parsing deferred to future phase), but this is documented in the 76-01 SUMMARY and intentional.

## Threat Flags

None -- no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries beyond those in the threat model. The _try_native_parse() method reads files from disk (same as existing parse_pcb) and the Exception catch is per the threat model's T-76-06 mitigation.

## Self-Check: PASSED

- `src/kicad_agent/ir/pcb_ir.py`: FOUND
- `src/kicad_agent/ops/executor.py`: FOUND
- `tests/test_pcb_native_adapter.py`: FOUND
- Commit `a044f10`: FOUND
- 41 adapter tests: PASSED
- 73 total tests (adapter + pcb_ops + handler): PASSED
