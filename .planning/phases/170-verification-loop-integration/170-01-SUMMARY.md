---
phase: 170-verification-loop-integration
plan: 01
subsystem: governance
tags: [governance, verification, rollback, obdurate-runtime, track-c]
requires:
  - 169-01
provides:
  - "Swift VerificationLoop orchestrating checkpoint → preCheck → execute → postCheck → restore"
  - "Daemon kicad.pre_check / kicad.post_check / kicad.snapshot / kicad.restore MCP methods"
  - "snapshot.py atomic per-file snapshot/restore with path-traversal defense"
affects:
  - "macos-app/Sources/Volta/MCP/MCPClient.swift (governedCall rewired)"
  - "macos-app/Sources/Volta/Governance/GovernedCall.swift (Governance holds verificationLoop)"
tech-stack:
  added: []
  patterns:
    - "Atomic per-file snapshot+restore via tempfile + os.replace"
    - "Content-addressed blob dedup within one snapshot"
    - "@MainActor class subclassing for test override of gates"
    - "Daemon RPC handlers wrapping existing validation_gates.py infrastructure"
key-files:
  created:
    - macos-app/Sources/Volta/Governance/PreOpGate.swift
    - macos-app/Sources/Volta/Governance/PostOpGate.swift
    - macos-app/Sources/Volta/Governance/Rollback.swift
    - macos-app/Sources/Volta/Governance/VerificationLoop.swift
    - macos-app/daemon/snapshot.py
    - macos-app/Tests/VoltaTests/Governance/PreOpGateTests.swift
    - macos-app/Tests/VoltaTests/Governance/PostOpGateTests.swift
    - macos-app/Tests/VoltaTests/Governance/RollbackTests.swift
    - macos-app/Tests/VoltaTests/Governance/VerificationLoopTests.swift
    - macos-app/daemon/tests/test_snapshot.py
    - macos-app/daemon/tests/test_verification_handlers.py
  modified:
    - macos-app/Sources/Volta/Governance/GovernedCall.swift
    - macos-app/Sources/Volta/MCP/MCPClient.swift
    - macos-app/daemon/handlers.py
decisions:
  - "Gates are @MainActor to share MCPClient's actor isolation, avoiding [String: Any] sendability crossings"
  - "PreOpGate short-circuits for read-only ops (no daemon round-trip — they cannot mutate state)"
  - "Snapshot failures are non-fatal: op proceeds but loses rollback; post-op failure then surfaces as .failed without restore"
  - "PostOpGate composes: failed deterministic → .failed; indeterminate → .indeterminate; passed + LLM no → .failed (semantic veto)"
  - "snapshot.py uses tempfile.mkstemp in target parent dir for atomic per-file restore via os.replace"
  - "Path-traversal defense (T-170-06): refuse '..' segments + optional base_dir containment check"
metrics:
  duration: ~2h
  completed: 2026-07-08
  tasks: 3
  files_created: 11
  files_modified: 3
  swift_tests_added: 50
  python_tests_added: 26
requirements: [GOV-03, GOV-04, GOV-05]
---

# Phase 170 Plan 01: Verification Loop Integration Summary

Implemented Swift-side verification pipeline (PreOpGate → execute → PostOpGate) with file-snapshot auto-rollback wired through four new daemon MCP handlers; closes Track C Governance for GOV-03, GOV-04, GOV-05.

## What Shipped

### Swift (Governance module)

**PreOpGate.swift** (`@MainActor`, ~190 lines)
- Validates intent matches op + will achieve goal (GOV-03)
- Local sanity check: rejects empty op names immediately
- Read-only ops short-circuit (allow) — no daemon round-trip needed since they can't mutate files
- Mutating ops call daemon `kicad.pre_check`
- Returns `PreOpDecision {allow, warn, block}` with reasons + per-check outcome map

**PostOpGate.swift** (`@MainActor`, ~210 lines)
- Deterministic check: delegates to daemon `kicad.post_check` which runs ERC on `.kicad_sch` files and DRC on `.kicad_pcb` files via existing `validation/erc_drc.py`
- Semantic check: optional `SemanticJudge` protocol — brief LLM "did this achieve intent?" call. `NoSemanticJudge` default returns nil (indeterminate) so deterministic check still runs
- Decision composition: failed deterministic → `.failed`; indeterminate → `.indeterminate`; passed + LLM no → `.failed` (semantic veto)
- Returns `PostOpDecision {passed, failed, indeterminate}` with raw ERC/DRC summaries + failures list

**Rollback.swift** (`@MainActor`, ~180 lines)
- `checkpoint(files:)` calls daemon `kicad.snapshot`, returns `Checkpoint` with snapshot_id
- `restore(checkpoint:)` calls daemon `kicad.restore` with snapshot_id, returns `RestoreResult {restored, removed, skipped}`
- Sentinel IDs handle no-client test mode (`__no_client__`) and empty file lists (`__empty__`)
- Path-traversal defense inherits from daemon's snapshot.py

**VerificationLoop.swift** (`@MainActor`, ~170 lines)
- Single `run(intent:args:executor:)` method
- Pipeline: checkpoint (skip if no files) → preOpGate.check → execute (caller closure) → postOpGate.verify → rollback.restore if `.failed`
- Returns `VerificationOutcome` with status, pre/post results, checkpointId, restore summary, per-stage timings
- Status: `.passed`, `.failed`, `.blocked`, `.executionFailed`, `.indeterminate`
- Snapshot failure is non-fatal: op proceeds but loses rollback safety; journal records it

**MCPClient.swift `governedCall` rewired**
- After IntentGate → DriftDetector → StateMachine → EscalationLadder checks pass, the VerificationLoop runs the actual op call
- Outcome status maps to journal `result_status`:
  - `.passed` → `success`
  - `.indeterminate` → `success` (verification `nil`)
  - `.blocked` → `rejected` (pre-op gate failure)
  - `.executionFailed` → `failed` + escalation
  - `.failed` → `rolled_back` + escalation + auto-learn failure
- `journalExtended` enriches result_summary with snapshot_id prefix, restore counts, stage timings

### Python Daemon

**snapshot.py** (~190 lines)
- `Snapshot.create(files, base_dir=None)` captures content-addressed blobs
- Defense-in-depth: refuses any path with `..` segments; optional `base_dir` containment check
- Manifest records `{path: {exists: bool, sha256: str|None}}` — missing files become "remove-on-restore"
- `Snapshot.restore()` atomic per-file: `tempfile.mkstemp` in target parent → `os.replace`
- Deduplication: identical content across multiple files in one snapshot shares one blob
- `Snapshot.close()` removes snapshot dir

**handlers.py additions** (~270 lines)
- `kicad.pre_check` — op_known + file_type_ok (kicad suffixes only) + args_present (mutating ops require target_file); path traversal blocked
- `kicad.post_check` — runs `run_erc` on .kicad_sch files, `run_drc` on .kicad_pcb files via lazy import; aggregates per-file results; returns decision + failures
- `kicad.snapshot` — wraps `Snapshot.create`, stashes on `ctx._verification_snapshots` dict by UUID
- `kicad.restore` — looks up snapshot by id, calls `Snapshot.restore()`, cleans up dir

### Tests

**Python (26 tests, all pass)**
- `test_snapshot.py`: capture/restore roundtrip, removes op-created files, idempotent skip, path traversal `..` rejection, base_dir containment, deduplication, cleanup, non-regular file rejection
- `test_verification_handlers.py`: pre_check happy path + dotdot block + suffix check + missing op_type, post_check returns decisions, snapshot/restore roundtrip + unknown id + traversal + base_dir enforcement

**Swift (50+ tests across 4 suites, all pass)**
- `PreOpGateTests`: empty op blocks, read-only short-circuit, no-client warns, decode allow/block/unknown/non-dict, shouldExecute matrix
- `PostOpGateTests`: read-only skip, no daemon indeterminate, semantic judge composition, toCodable helpers, isPassed matrix
- `RollbackTests`: empty files sentinel, no-client placeholder, sentinel stability, Checkpoint equality, RestoreResult affectedCount, RollbackError descriptions
- `VerificationLoopTests`: happy path, block stops execution, failed triggers rollback, indeterminate commits, executor throws, read-only skips checkpoint, empty target files, stage timings

Full Swift suite: **211 tests pass**, `swift build` clean. Daemon suite: **195 pass** (14 pre-existing pytest-asyncio environmental failures, not caused by Phase 170).

## Verification

| Criterion | Result |
|-----------|--------|
| Pre-op Intent Gate validates op + file types | `kicad.pre_check` returns decision + reasons; PreOpGate decodes and short-circuits read-only |
| Post-op gate runs deterministic + semantic checks | `kicad.post_check` aggregates ERC/DRC; PostOpGate composes with optional LLM judge |
| Auto-rollback via PersistentUndoStack-style snapshot | `kicad.snapshot`/`kicad.restore` + snapshot.py atomic per-file restore |
| All phases logged to OpJournal with fsync | `journalExtended` records snapshot_id + restore counts + stage timings |
| Failures surfaced as user decisions | GovernedCallError.intentRejected on `.blocked`; journal `rolled_back` status on `.failed` |

## Threat Model Coverage

| Threat | Mitigation Shipped |
|--------|-------------------|
| T-170-01 (spoofing via path traversal) | PreOpGate + snapshot.py refuse `..` segments; daemon validates kicad suffixes only |
| T-170-02 (verification bypass) | VerificationLoop is mandatory path through `governedCall`; no skip flag |
| T-170-03 (repudiation) | Every checkpoint / restore / verification failure journaled with snapshot_id |
| T-170-05 (DoS via slow verification) | Inherits MCPClient 30s timeout; per-file ERC/DRC runs serially with per-file error tolerance |
| T-170-06 (file rollback traversal) | snapshot.py base_dir containment check + `..` rejection defense-in-depth |

## Deviations from Plan

None — plan executed exactly as written. Three tasks (PreOpGate, PostOpGate, Rollback+VerificationLoop) delivered as one atomic commit since they share types and the VerificationLoop can't be tested in isolation without all three gates.

## Integration Notes for Phase 173

Phase 173 (GSD Conversation Engine) consumes the verification loop via:
- `MCPClient.governedCall(...)` — already wired, returns `GovernedCallResult<T>` with the full VerificationOutcome in the journal entry
- `Governance.shared.verificationLoop` — direct access for non-MCP-driven flows (e.g. file-only mutations from the GSD engine)
- `VerificationOutcome.stageTimingsMs` — useful for the Pipeline View (PIPE-02) to show per-stage duration
- `outcome.restore` non-nil → trigger user decision prompt "Verification failed, rolled back. Retry?" (GSD-07)

The `SemanticJudge` protocol is intentionally minimal (3 fields: intent, op, result → Bool?). Phase 173 can wire it to the KiCadModelProvider router; Phase 170 ships `NoSemanticJudge` as the default so deterministic checks run independently.

## Self-Check: PASSED

Created files verified present:
- macos-app/Sources/Volta/Governance/PreOpGate.swift ✓
- macos-app/Sources/Volta/Governance/PostOpGate.swift ✓
- macos-app/Sources/Volta/Governance/Rollback.swift ✓
- macos-app/Sources/Volta/Governance/VerificationLoop.swift ✓
- macos-app/daemon/snapshot.py ✓
- 4 Swift test files + 2 Python test files ✓

Modified files verified:
- macos-app/Sources/Volta/Governance/GovernedCall.swift ✓
- macos-app/Sources/Volta/MCP/MCPClient.swift ✓
- macos-app/daemon/handlers.py ✓

Commit verified: `7b367635 feat(governance): phase 170 verification loop` ✓
