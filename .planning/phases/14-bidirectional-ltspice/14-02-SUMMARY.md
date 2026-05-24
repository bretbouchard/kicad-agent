---
phase: 14-bidirectional-ltspice
plan: 02
subsystem: ltspice
tags: [bidi, asc-writer, kiCad-export, coordinate-transform, spicelib]

# Dependency graph
requires:
  - phase: 14-01
    provides: SymbolMapper, SymbolMappingResult, SymbolMappingType
  - phase: 11-ltspice-integration
    provides: parse_asc(), ASY_STUBS_DIR, LTspiceSchematic types
provides:
  - AscWriter class for KiCad-to-LTspice .asc export
  - CoordinateTransformer for mm-to-internal-unit conversion with Y-axis flip
  - export_schematic_to_asc() convenience function
  - _sanitize_net_name() helper for net label cleaning
  - _rotation_from_kicad() helper for angle/mirror mapping
affects: [14-03, bidirectional-sync]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass-coordinate-transform, direct-list-manipulation-spicelib, path-traversal-validation]

key-files:
  created:
    - src/kicad_agent/ltspice/asc_writer.py
    - tests/test_ltspice_writer.py
  modified:
    - src/kicad_agent/ltspice/__init__.py

key-decisions:
  - "Strip whitespace before leading-slash check in _sanitize_net_name for correct combined input handling"
  - "Direct list manipulation (editor.wires.append, editor.labels.append) instead of add_instruction() due to SpiceLib broken behavior"
  - "Lazy kiutils import only in export_schematic_to_asc() to match project pattern"

patterns-established:
  - "Frozen dataclass for CoordinateTransformer with configurable scale and sheet_height"
  - "tempfile.NamedTemporaryFile for .asc template with finally-block cleanup"
  - "Path traversal protection on output_path (same pattern as asc_parser._validate_path)"

requirements-completed: [BIDI-01, BIDI-03]

# Metrics
duration: 2min
completed: 2026-05-24
---

# Phase 14 Plan 02: KiCad-to-LTspice .asc Writer Summary

**AscWriter with CoordinateTransformer exporting KiCad schematics to valid LTspice .asc files via SpiceLib AscEditor, with Y-axis flip, grid alignment, and round-trip parse validation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-24T00:03:27Z
- **Completed:** 2026-05-24T00:05:47Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- AscWriter converts KiCad schematic symbols, wires, and labels to LTspice .asc format
- CoordinateTransformer flips Y-axis (KiCad down-positive to LTspice up-positive) with 16-unit grid alignment
- 15 integration tests with round-trip validation (export -> parse_asc -> verify)
- Power symbols become FLAG entries (GND -> "0"), net labels strip leading "/"

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CoordinateTransformer and AscWriter core** - `145930e` (feat)
2. **Task 2: Create integration tests for .asc writer with round-trip validation** - `e71167d` (test)

## Files Created/Modified
- `src/kicad_agent/ltspice/asc_writer.py` - AscWriter, CoordinateTransformer, export_schematic_to_asc, _sanitize_net_name, _rotation_from_kicad
- `tests/test_ltspice_writer.py` - 15 tests across 4 test classes (297 lines)
- `src/kicad_agent/ltspice/__init__.py` - Added AscWriter, CoordinateTransformer, export_schematic_to_asc exports

## Decisions Made
- Strip whitespace before leading-slash check in _sanitize_net_name for correct combined input handling (e.g., "  /VCC  ")
- Direct list manipulation for SpiceLib editor (wires.append, labels.append) per research finding that add_instruction() has broken replace-instead-of-append behavior
- Lazy kiutils import only in export_schematic_to_asc() to match project pattern for optional dependencies

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed _sanitize_net_name whitespace ordering**
- **Found during:** Task 2 (test run)
- **Issue:** _sanitize_net_name checked for leading "/" before stripping whitespace, so "  /VCC  " returned "/VCC" instead of "VCC"
- **Fix:** Moved text.strip() before the leading-slash check
- **Files modified:** src/kicad_agent/ltspice/asc_writer.py
- **Verification:** All 15 tests pass including test_slash_and_whitespace_combined
- **Committed in:** e71167d (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor fix necessary for correct net name handling. No scope creep.

## Issues Encountered
None beyond the whitespace ordering bug documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- AscWriter complete, ready for Plan 14-03 (bidirectional synchronization or additional features)
- SymbolMapper + AscWriter form the core export pipeline
- Round-trip validated: export -> parse_asc() -> verify components, flags, wires

## Self-Check: PASSED

All files verified:
- src/kicad_agent/ltspice/asc_writer.py: FOUND
- tests/test_ltspice_writer.py: FOUND
- src/kicad_agent/ltspice/__init__.py: FOUND

All commits verified:
- 145930e: FOUND (feat: AscWriter core)
- e71167d: FOUND (test: integration tests)

---
*Phase: 14-bidirectional-ltspice*
*Completed: 2026-05-24*
