---
phase: 02-operation-schema-and-ir-layer
plan: 03
subsystem: ir-layer, serializer
tags: [transaction, rollback, snapshot, normalizer, deterministic, fcntl, symlink-protection]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: ParseResult, UUIDMap, parsers, serializers for all file types
  - plan: 02-02
    provides: BaseIR, SchematicIR, PcbIR, SymbolLibIR, FootprintIR
provides:
  - Transaction class with file-level snapshots, commit, rollback, auto-rollback
  - TransactionResult frozen dataclass for immutable results
  - normalize_kicad_output function with string-aware scientific notation fix and whitespace normalization
affects: [04-mutation-operations, 05-graph-analysis, 06-cross-file]

# Tech tracking
tech-stack:
  added: [fcntl]
  patterns: [context-manager-transaction, file-locking, string-aware-tokenization, idempotent-normalizer]

key-files:
  created:
    - src/kicad_agent/ir/transaction.py
    - src/kicad_agent/serializer/normalizer.py
    - tests/test_transaction.py
    - tests/test_normalizer.py
  modified:
    - src/kicad_agent/ir/__init__.py
    - src/kicad_agent/serializer/__init__.py

key-decisions:
  - "Symlink check must happen BEFORE resolve() because resolve() follows symlinks on macOS"
  - "String-aware tokenization for sci-notation fix: state machine splits quoted/unquoted segments (Council M-01)"
  - "Normalizer starts with two rules (sci-notation + whitespace); more rules added incrementally in later phases"
  - "D-11 (property ordering) and D-14 (byte-identical) deferred to later phases as aspirational targets"

patterns-established:
  - "Transaction context manager: __enter__ snapshots via shutil.copy2, __exit__ auto-rollback on exception"
  - "File locking: fcntl.LOCK_EX | fcntl.LOCK_NB for non-blocking exclusive lock via .lck file"
  - "Normalizer pipeline: normalize_kicad_output calls composable rules in sequence, each rule preserves idempotency"

requirements-completed: [FND-07, FND-08]

# Metrics
duration: 7min
completed: 2026-05-18
---

# Phase 2 Plan 03: Transaction Engine and Output Normalizer Summary

**File-level transactions with auto-rollback and deterministic serialization normalizer**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-18T06:17:44Z
- **Completed:** 2026-05-18T06:24:47Z
- **Tasks:** 2
- **Files modified:** 6 (2 source + 2 test + 2 barrel exports)

## Accomplishments
- Transaction class provides file-level snapshots with auto-rollback on exception (D-08, D-09, D-10)
- Security hardening: symlink TOCTOU protection (H-02), restricted snapshot permissions 0o600 (H-03), concurrent modification guard via fcntl locking (H-04)
- Normalizer with string-aware scientific notation fix (Council M-01) and whitespace normalization
- Normalizer is deterministic and idempotent: same input always produces same output
- Integration test validates full parse -> IR -> Transaction -> modify -> serialize -> normalize -> commit pipeline
- All 119 tests pass (48 Phase 1 + 20 Plan 02-01 + 18 Plan 02-02 + 19 transaction + 14 normalizer)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create transaction engine with file-level snapshots** - `57b4ea8` (feat)
2. **Task 2: Create KiCad output normalizer** - `aee3bbb` (feat)
3. **Barrel export updates** - `b9cd5dd` (chore)

## Files Created/Modified
- `src/kicad_agent/ir/transaction.py` - Transaction class with snapshot/commit/rollback, fcntl locking, symlink protection
- `src/kicad_agent/serializer/normalizer.py` - normalize_kicad_output with string-aware sci-notation fix and whitespace normalization
- `tests/test_transaction.py` - 19 tests across 7 test classes (snapshot, commit, rollback, auto-rollback, errors, security, logs)
- `tests/test_normalizer.py` - 14 tests across 5 test classes (sci-notation, whitespace, determinism, round-trip, integration)
- `src/kicad_agent/ir/__init__.py` - Added Transaction, TransactionResult exports
- `src/kicad_agent/serializer/__init__.py` - Added normalize_kicad_output export

## Decisions Made
- Symlink check must happen BEFORE resolve() because Path.resolve() follows symlinks on macOS, making is_symlink() return False on the resolved path
- String-aware tokenization for scientific notation: state machine splits content into quoted and unquoted segments, regex only applied to unquoted segments (Council M-01)
- Normalizer starts with two rules (scientific notation + whitespace); D-11 (property ordering) and D-14 (byte-identical output) deferred to later phases as aspirational targets per plan scope note
- File locking uses fcntl.LOCK_EX | fcntl.LOCK_NB (non-blocking) to fail fast on concurrent access

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Symlink check after resolve() always returns False**
- **Found during:** Task 1 (test_symlink_target_rejected failed)
- **Issue:** Path.resolve() follows symlinks on macOS, so is_symlink() on the resolved path returns False even for symlink inputs
- **Fix:** Moved is_symlink() check to BEFORE resolve() in __init__, checking the user-provided path first
- **Files modified:** src/kicad_agent/ir/transaction.py
- **Verification:** test_symlink_target_rejected passes
- **Committed in:** 57b4ea8 (Task 1)

**2. [Rule 1 - Bug] Broken caplog test in TestTransactionSecurity**
- **Found during:** Task 1 (test_auto_rollback_logs_warning failed with TypeError)
- **Issue:** Used pytest.warns(None) which raises TypeError; manual MemoryHandler approach was overly complex
- **Fix:** Removed broken test from TestTransactionSecurity, kept proper caplog-based version in TestTransactionSecurityLogs
- **Files modified:** tests/test_transaction.py
- **Verification:** All 19 transaction tests pass
- **Committed in:** 57b4ea8 (Task 1)

**3. [Rule 3 - Blocking] Missing logging import in test_transaction.py**
- **Found during:** Task 1 (NameError: name 'logging' is not defined)
- **Issue:** TestTransactionSecurityLogs.test_auto_rollback_logs_warning uses logging.WARNING but logging was not imported
- **Fix:** Added `import logging` to test file imports
- **Files modified:** tests/test_transaction.py
- **Verification:** All 19 transaction tests pass
- **Committed in:** 57b4ea8 (Task 1)

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All auto-fixes corrected test infrastructure issues. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 complete: all 3 plans (operation schema, IR layer, transaction + normalizer) executed
- Transaction engine ready for Phase 4 (mutation operations) to wrap IR mutations
- Normalizer ready for incremental rule addition in later phases
- All 119 tests pass with no regressions

---
*Phase: 02-operation-schema-and-ir-layer*
*Completed: 2026-05-18*

## Self-Check: PASSED

- [x] All 4 created files exist
- [x] Commit 57b4ea8 exists (Task 1: feat)
- [x] Commit aee3bbb exists (Task 2: feat)
- [x] Commit b9cd5dd exists (chore: barrel exports)
- [x] All 119 tests pass (48 Phase 1 + 20 Plan 02-01 + 18 Plan 02-02 + 19 transaction + 14 normalizer)
