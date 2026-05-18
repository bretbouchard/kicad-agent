---
phase: 01-foundation
plan: 02
subsystem: serializer
tags: [kiutils, uuid, s-expression, round-trip, serialization, validation]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Four KiCad file-type parsers with raw content preservation"
provides:
  - "UUID extraction from raw S-expression content (UUIDMap with parent_type, parent_index, line_number)"
  - "UUID re-injection into kiutils serialized output (sequential structural matching)"
  - "Four file-type serializers (schematic, PCB, symbol lib, footprint) with UUID-aware PCB/footprint"
  - "Two-pass round-trip stability validator proving deterministic serialization"
affects: [03-diff, 04-edit, 05-validate]

# Tech tracking
tech-stack:
  added: []
  patterns: [sequential-uuid-reinjection, two-pass-stability-test, uuid-aware-serialization]

key-files:
  created:
    - src/kicad_agent/parser/uuid_extractor.py
    - src/kicad_agent/serializer/__init__.py
    - src/kicad_agent/serializer/schematic_ser.py
    - src/kicad_agent/serializer/pcb_ser.py
    - src/kicad_agent/serializer/symbol_ser.py
    - src/kicad_agent/serializer/footprint_ser.py
    - src/kicad_agent/serializer/uuid_reinjector.py
    - src/kicad_agent/validation/__init__.py
    - src/kicad_agent/validation/roundtrip.py
    - tests/test_parser/test_uuid_extractor.py
    - tests/test_roundtrip/test_roundtrip_stability.py
  modified: []

key-decisions:
  - "Sequential UUID re-injection: match structural elements in file order and inject UUIDs sequentially, rather than (parent_type, parent_index) lookup which was too fragile"
  - "Combined regex pattern for all structural elements in reinjector (single pass, more maintainable than list of separate patterns)"
  - "UUID format validation (v4 pattern) before injection to mitigate T-01-04 tampering threat"
  - "Two-pass stability test: first pass normalizes, second pass proves determinism"

patterns-established:
  - "Serializer pattern: each serializer takes ParseResult + output_path, delegates to kiutils to_file(), optionally applies UUID re-injection"
  - "Round-trip validation pattern: parse->serialize->parse->serialize->compare (byte-identical second pass proves stability)"
  - "UUID extraction pattern: regex scan of raw content with parent context detection and line tracking"

requirements-completed: [FND-05, FND-06]

# Metrics
duration: 8min
completed: 2026-05-18
---

# Phase 1 Plan 2: UUID Extraction and Round-Trip Stability Summary

**UUID extraction/re-injection layer and four file-type serializers with two-pass round-trip stability validator -- 21 tests proving deterministic serialization across all KiCad file types**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-18T03:36:32Z
- **Completed:** 2026-05-18T03:44:35Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- UUID extraction from raw PCB/footprint content: 305 UUIDs from Arduino_Mega PCB (exceeds 115+ research baseline)
- UUID re-injection via sequential structural matching in kiutils output
- All four file types pass two-pass round-trip stability test (pass1 == pass2 byte-for-byte)
- PCB and footprint UUID counts preserved through extraction/re-injection cycle
- 21 new tests (14 UUID extractor + serializer tests, 7 round-trip stability tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: UUID extractor, reinjector, and serializer package** - `c010c55` (feat)
2. **Task 2: Round-trip stability validator and test suite** - `e141909` (feat)

**Plan metadata:** pending (docs commit after state updates)

## Files Created/Modified
- `src/kicad_agent/parser/uuid_extractor.py` - UUID extraction with UUIDEntry (uuid_value, parent_type, parent_index, line_number) and UUIDMap
- `src/kicad_agent/serializer/__init__.py` - Package exporting all four serializers + reinject_uuids
- `src/kicad_agent/serializer/schematic_ser.py` - Schematic serializer (no UUID handling needed)
- `src/kicad_agent/serializer/pcb_ser.py` - PCB serializer with optional UUIDMap for re-injection
- `src/kicad_agent/serializer/symbol_ser.py` - Symbol library serializer (no UUID handling needed)
- `src/kicad_agent/serializer/footprint_ser.py` - Footprint serializer with optional UUIDMap for re-injection
- `src/kicad_agent/serializer/uuid_reinjector.py` - UUID re-injection via sequential structural element matching
- `src/kicad_agent/validation/__init__.py` - Package exporting round_trip_stable and round_trip_compare
- `src/kicad_agent/validation/roundtrip.py` - Two-pass round-trip validator with RoundTripResult dataclass
- `tests/test_parser/test_uuid_extractor.py` - 14 tests for UUID extraction, re-injection, and all serializers
- `tests/test_roundtrip/test_roundtrip_stability.py` - 7 tests for round-trip stability across all file types

## Decisions Made
- Sequential UUID re-injection instead of (parent_type, parent_index) lookup -- the original plan specified matching by parent_type and parent_index, but testing showed that a single footprint can have many UUIDs (footprint itself, properties, pads, pad properties) making type+index lookup ambiguous. Sequential injection matches the deterministic ordering of structural elements.
- Combined regex pattern in reinjector -- single `_ELEMENT_PATTERN` regex with named groups instead of a list of 15+ separate patterns. More maintainable and processes in a single pass.
- UUID format validation (threat T-01-04) -- UUIDs are validated against v4 pattern before injection to prevent tampering via malformed UUID strings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed UUID re-injection matching strategy**
- **Found during:** Task 1 (UUID extractor and reinjector implementation)
- **Issue:** Original (parent_type, parent_index) lookup failed because a single footprint contains multiple UUIDs at different depths (footprint itself, properties, pads). The parent_index counter was not correctly tracking nested UUIDs.
- **Fix:** Replaced type+index lookup with sequential structural matching -- walk the kiutils output finding all structural elements in order and inject UUIDs sequentially from the map.
- **Files modified:** src/kicad_agent/serializer/uuid_reinjector.py
- **Verification:** All 14 extractor tests and 7 round-trip tests pass; 305 PCB UUIDs extracted and preserved
- **Committed in:** c010c55 (Task 1 commit)

**2. [Rule 1 - Bug] Added fp_* structural element patterns to reinjector**
- **Found during:** Task 1 (footprint serializer test failing)
- **Issue:** Reinjector only matched `gr_*` graphical elements but not `fp_*` elements (fp_circle, fp_text, fp_line, etc.) used inside footprints. UUIDs for these elements were skipped, shifting the UUID sequence.
- **Fix:** Added fp_circle, fp_text, fp_line, fp_arc, fp_poly, fp_rect patterns and consolidated into single combined regex.
- **Files modified:** src/kicad_agent/serializer/uuid_reinjector.py
- **Verification:** Footprint serializer test passes with all UUIDs restored
- **Committed in:** c010c55 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bugs in re-injection strategy)
**Impact on plan:** Both fixes were correctness requirements for the core feature. The sequential matching approach is simpler and more robust than the planned (type, index) lookup. No scope creep.

## Issues Encountered
None beyond the deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Serializer layer complete for all four file types
- Round-trip stability proven for all four file types
- UUID preservation working for PCB and footprint files
- Ready for Plan 01-03 (remaining foundation work)

---
*Phase: 01-foundation*
*Completed: 2026-05-18*
