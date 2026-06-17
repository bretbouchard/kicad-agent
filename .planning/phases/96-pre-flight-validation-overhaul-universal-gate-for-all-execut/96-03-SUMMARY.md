---
phase: 96-pre-flight-validation-overhaul-universal-gate-for-all-execut
plan: 03
subsystem: validation
tags: [write-verification, content-validation, extension-validation, force-removal, net-resolution]

# Dependency graph
requires:
  - phase: 96-01
    provides: "_VALID_KICAD_EXTENSIONS defined in pre_analysis.py"
provides:
  - "Force flag removed from PCB transfer handler (D-12)"
  - "Hardcoded net 1 replaced with regex-extracted net ID (D-13, H-05)"
  - "SHA-256 write verification in commit_raw_content (D-14)"
  - "Cross-file extension validation using shared constant (D-15, M-03)"
  - "Content header validation in create_file.py (D-16)"
affects: [cross-file-operations, pcb-transfer, raw-writer, file-creation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SHA-256 hash comparison for write verification"
    - "Regex extraction from existing content for net ID resolution"
    - "Content header validation gate before file writes"

key-files:
  created:
    - tests/test_pcb_transfer.py
    - tests/test_pcb_ir_write_verify.py
    - tests/test_create_file.py
    - tests/test_execution.py
  modified:
    - src/kicad_agent/ops/handlers/pcb_transfer.py
    - src/kicad_agent/ops/pcb_raw_writer.py
    - src/kicad_agent/ir/pcb_ir.py
    - src/kicad_agent/ops/pre_analysis.py
    - src/kicad_agent/ops/execution.py
    - src/kicad_agent/ops/create_file.py
    - tests/test_pcb_raw_writer.py

key-decisions:
  - "D-12: Force flag removed entirely -- production handlers must never bypass validation gates"
  - "D-13/H-05: Net ID extracted from existing content via regex, NOT added as IR parameter to @staticmethod (preserves API contract)"
  - "D-14: SHA-256 read-back verification catches filesystem-level corruption after atomic_write"
  - "D-15/M-03: _VALID_KICAD_EXTENSIONS defined once in pre_analysis.py, imported by execution.py (not duplicated)"
  - "D-16: Content validation only applied to KiCad S-expression writes via _atomic_write, not to JSON project files or kiutils to_file() calls"

patterns-established:
  - "Write-verify pattern: compute hash before write, read back after, compare SHA-256"
  - "Regex-before-substitute pattern: extract existing value from content, reuse in replacement"

requirements-completed: []

# Metrics
started: 2026-06-17T09:26:40Z
completed: 2026-06-17T09:34:19Z
duration: 7m
duration_minutes: 7
commits: 2
files_modified: 11
---

# Phase 96 Plan 03: Structural Fragility Fixes Summary

**Eliminated five structural fragilities: force bypass removal, hardcoded net replacement, write verification, cross-file extension validation, and content header validation.**

## Performance

- **Duration:** 7m
- **Started:** 2026-06-17T09:26:40Z
- **Completed:** 2026-06-17T09:34:19Z
- **Tasks:** 2
- **Commits:** 2 (atomic task commits)
- **Files modified:** 11

## Accomplishments
- Removed force flag bypass from `handle_update_from_schematic` -- validation gates now always run with no escape hatch (D-12)
- Replaced hardcoded net 1 in `modify_zone_field` with regex-extracted net ID from existing content, preserving the `@staticmethod` signature with 4 params (D-13, H-05)
- Added SHA-256 read-back verification to `commit_raw_content()` that raises IOError on hash mismatch (D-14)
- Added cross-file extension validation rejecting non-KiCad file extensions using shared `_VALID_KICAD_EXTENSIONS` from `pre_analysis.py` (D-15, M-03)
- Added content header validation in `create_file.py` that rejects non-KiCad S-expression content before writing (D-16)
- 31 new tests covering all five structural fix paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove force flag, fix hardcoded net via regex extraction, add write verification** - `463f46b` (fix)
2. **Task 2: Cross-file path validation and create_file content validation** - `f83abd6` (fix)

## Files Created/Modified

### Created
- `tests/test_pcb_transfer.py` - 4 tests verifying force flag removal from production handlers
- `tests/test_pcb_ir_write_verify.py` - 3 tests verifying SHA-256 write verification in commit_raw_content
- `tests/test_create_file.py` - 12 tests verifying content header validation rejects non-KiCad content
- `tests/test_execution.py` - 9 tests verifying cross-file extension validation and M-03 import

### Modified
- `src/kicad_agent/ops/handlers/pcb_transfer.py` - Removed force parameter from handle_update_from_schematic, removed force bypass branch
- `src/kicad_agent/ops/pcb_raw_writer.py` - Replaced hardcoded net 1 with regex-extracted existing net ID in modify_zone_field
- `src/kicad_agent/ir/pcb_ir.py` - Added hashlib import, added SHA-256 read-back verification to commit_raw_content
- `src/kicad_agent/ops/pre_analysis.py` - Added _VALID_KICAD_EXTENSIONS frozenset as single source of truth
- `src/kicad_agent/ops/execution.py` - Imported _VALID_KICAD_EXTENSIONS from pre_analysis.py, added extension check in execute_cross_file
- `src/kicad_agent/ops/create_file.py` - Added _VALID_KICAD_HEADERS and _validate_kicad_content, called before KiCad S-expression writes
- `tests/test_pcb_raw_writer.py` - Added 3 tests for modify_zone_field net resolution (D-13, H-05)

## Decisions Made

- **Force removal scope**: Only `handle_update_from_schematic` had a force parameter. Removed it entirely -- there is no CLI-only escape hatch for gate validation. This is intentional: production handlers must always validate.
- **Net ID extraction approach**: Used regex extraction from existing zone content (`r'\(net\s+(\d+)\s+"[^"]*"\)'`) rather than adding an `ir` parameter to the `@staticmethod`. This preserves the pure content-manipulation API contract (4 params: content, zone_uuid, field, value).
- **Content validation scope**: Applied `_validate_kicad_content` only to `_atomic_write` calls in `create_schematic` and `create_footprint`. Did not apply to `create_pcb` or `create_symbol` which use kiutils `to_file()` (generates valid content by construction). Did not apply to `create_project` which writes JSON.
- **M-03 defined proactively**: Plan 96-01 (which was supposed to define `_VALID_KICAD_EXTENSIONS`) has not executed yet. Defined the constant in `pre_analysis.py` now so execution.py can import it, establishing the single source of truth that 96-01 would have created.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

No new threat surface introduced. All changes are defensive hardening:
- Write verification (D-14) is a mitigation for T-96-07 (Integrity)
- Net ID extraction (D-13) is a mitigation for T-96-08 (Tampering)
- Content header validation (D-16) is a mitigation for T-96-09 (Spoofing)

## Self-Check: PASSED

- [x] `463f46b` commit exists
- [x] `f83abd6` commit exists
- [x] `tests/test_pcb_transfer.py` created
- [x] `tests/test_pcb_ir_write_verify.py` created
- [x] `tests/test_create_file.py` created
- [x] `tests/test_execution.py` created
- [x] 64 tests passing (33 existing + 31 new), zero regression
