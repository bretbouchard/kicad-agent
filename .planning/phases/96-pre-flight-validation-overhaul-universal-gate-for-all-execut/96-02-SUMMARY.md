---
phase: 96-pre-flight-validation-overhaul-universal-gate-for-all-execut
plan: 02
subsystem: execution-pipeline
tags: [batch-executor, transaction, lock, hardening, silent-failure, pre-flight-gate]
dependency_graph:
  requires: ["96-01"]
  provides: ["stop-and-rollback-batch", "cumulative-ir-tracking", "lock-error"]
  affects: ["batch_executor", "execution", "transaction"]
tech_stack:
  added: []
  patterns: ["stop-and-rollback", "cumulative-ir-reparse", "dual-parse-path", "loud-failure-logging"]
key_files:
  created: []
  modified:
    - src/kicad_agent/ops/batch_executor.py
    - src/kicad_agent/ir/base.py
    - src/kicad_agent/ir/transaction.py
    - src/kicad_agent/ops/execution.py
    - src/kicad_agent/ops/repair_wires.py
    - src/kicad_agent/ops/persistent_undo.py
    - tests/test_batch_executor.py
    - tests/test_transaction.py
decisions: []
metrics:
  duration: "8m"
  completed_date: "2026-06-17"
---

# Phase 96 Plan 02: Silent Failure Hardening Summary

Harden silent failure modes across the execution pipeline. Batch executor stops and rolls back on individual op failure (no more partial mutation corruption). Batch tracks cumulative IR state by re-parsing after each mutation using both native and kiutils parse paths. Batch Phase 1 pre-check runs gate for ALL file types. Transaction cleanup logs failures loudly. Lock file creation raises LockError on write failure only. Repair and undo modules log failures instead of silently continuing.

## Changes Made

### Task 1: Batch stop-and-rollback, cumulative IR, universal gate (D-03, D-08, H-03, H-04)

**batch_executor.py:**
- Added `BatchOpFailedError` exception class with `__cause__` chaining (L-02 fix)
- Removed `.kicad_sch`-only guard from Phase 1 pre-check gate -- now runs for ALL file types (H-04 fix)
- Replaced silent exception swallowing in Phase 3 loop with `raise BatchOpFailedError(...) from e` -- triggers Transaction auto-rollback (D-08)
- Added cumulative IR re-parse after each successful mutation using dual path: try native parser first, fall back to kiutils (H-03 fix)
- Added per-op pre-flight gate check against current (possibly mutated) IR (D-03)
- Multi-file batch failure rolls back all committed files from pre_contents snapshots
- 31 tests pass (20 existing + 11 new: TestBatchRollback, TestCumulativeIR, TestBatchPhase1Gate)

**base.py (Rule 1 - Bug fix):**
- Added `_deregister_ir()` function to remove ParseResult id from IR registry
- Fixed Python id reuse bug: when cumulative IR re-parsing creates new SchematicIR objects, old ParseResults get GC'd and Python reuses their memory addresses, causing spurious "already has an IR wrapper" errors from the one-IR-per-ParseResult guard

### Task 2: Hardening -- transaction cleanup, lock errors, repair/undo logging (D-09, D-10, D-11, M-02)

**transaction.py:**
- `_cleanup_snapshot()`: Split `except (FileNotFoundError, OSError)` into separate handlers -- `FileNotFoundError` passes silently, `OSError` logs at WARNING (D-09 fix)

**execution.py:**
- Added `LockError` class (RuntimeError subclass) for lock file creation failures
- Lock file WRITE failure (site 2) now raises `LockError` with `from e` chaining (D-10 fix)
- Lock file READ failure (site 1) remains soft warning with `"<unreadable>"` fallback (M-02 preserved)

**repair_wires.py:**
- NetPositionIndex build failure upgraded from `logger.debug` to `logger.warning` with exception details (D-11 fix)

**persistent_undo.py:**
- Entry load failure upgraded from `logger.debug` to `logger.warning` with entry filename and "data may be incomplete" message (D-11 fix)

**tests/test_transaction.py:**
- Added `TestTransactionCleanupLogging` (3 tests): unlink FileNotFoundError, rmdir OSError logged, rmdir FileNotFoundError
- Added `TestLockError` (4 tests): write failure raises, chains original, read remains soft, read fallback to unreadable
- Added `TestSilentFailureHardening` (2 tests): repair_wires NetPositionIndex warning, persistent_undo entry load warning
- 28 transaction tests pass

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed IR registry guard spurious errors on cumulative re-parse**
- Found during: Task 1 -- Phase 3 cumulative IR re-parse with 100 ops
- Issue: Python GC reuses freed ParseResult memory addresses. After ~13 re-parses, a new ParseResult gets the same `id()` as a previously GC'd one, triggering the one-IR-per-ParseResult guard erroneously.
- Fix: Added `_deregister_ir()` to `ir/base.py` that removes the old ParseResult id from the registry before creating a fresh re-parse
- Files modified: `src/kicad_agent/ir/base.py`, `src/kicad_agent/ops/batch_executor.py`
- Commit: ca85a81

**2. [Rule 3 - Blocking] AtomicOperation fcntl lock conflict with per-file Transactions**
- Found during: Task 1 -- multi-file batch tests failing with `BlockingIOError: Resource temporarily unavailable`
- Issue: Plan specified wrapping multi-file batch Phase 3 in `AtomicOperation`, but `AtomicOperation` opens its own per-file `Transaction` contexts with fcntl locks. The inner `_run_phase3` loop also opens `Transaction` contexts, causing fcntl lock conflicts.
- Fix: Removed `AtomicOperation` wrapper for multi-file batches. Instead, use manual rollback from `pre_contents` snapshots for multi-file failure cases. Single-file batches use per-file `Transaction` as before.
- Files modified: `src/kicad_agent/ops/batch_executor.py`

**3. [Rule 1 - Bug] O-BUG-009 partial failure behavior changed by D-08 design**
- Found during: Task 1 -- existing TestOBUG009PartialFailure tests expected partial success
- Issue: D-08 explicitly replaces the old O-BUG-009 behavior (continue on failure) with stop-and-rollback. The old tests needed updating to reflect the new design intent.
- Fix: Updated test assertions to verify stop-and-rollback behavior instead of partial success
- Files modified: `tests/test_batch_executor.py`

**4. [Rule 3 - Blocking] PCB test fixture and PCB handler mismatch**
- Found during: Task 1 -- PCB tests using `validate_refs` op which has no PCB handler
- Issue: `validate_refs` only exists for schematic handlers, not PCB. Tests needed a valid PCB op type.
- Fix: Changed PCB tests to use `add_net` op which has a PCB handler
- Files modified: `tests/test_batch_executor.py`

**5. [Rule 3 - Blocking] PersistentUndoStack test directory name mismatch**
- Found during: Task 2 -- persistent_undo test failing silently
- Issue: Test created undo directory as `.kicad_agent` (underscore) but PersistentUndoStack uses `.kicad-agent` (hyphen) via the `_UNDO_DIR_NAME` constant
- Fix: Changed test directory construction to match constant name
- Files modified: `tests/test_transaction.py`

## Threat Flags

No new threat surface introduced beyond what the plan's threat model already documented (T-96-05: LockError on read-only dirs is catchable; T-96-06: Rollback is safe).

## Known Stubs

None -- all implementations are complete and wired.

## Self-Check: PASSED
