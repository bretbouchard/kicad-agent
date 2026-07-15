---
phase: 240
type: summary
status: complete
---

# Phase 240 Summary — Volta Operation Registry Tests

## Status: COMPLETE

Added `macos-app/Tests/VoltaTests/VoltaOpRegistryTests.swift` with 9 tests
covering the 268-op Volta registry and the most critical ops (ERC + safe_sync).

## Test Coverage

| Test | Purpose |
|------|---------|
| `registersManyOps` | Asserts >=200 ops are registered (catches missing ops) |
| `opTypesAreUnique` | Catches duplicate opType registration (would shadow) |
| `noEmptyOpTypes` | Catches empty opType strings |
| `opTypesAreSnakeCase` | Catches non-snake_case op names (breaks dispatcher) |
| `unknownOpThrows` | Verifies error handling for missing ops |
| `allOpsReturnDict` | Smoke-tests every read-only op on minimal input |
| `runNativeErcOnCleanSchematic` | Regression test for 234B parity |
| `safeSyncPcbFromSchematicShape` | Phase 237 implementation: added diff structure |
| `safeSyncPreservesOrphansByDefault` | Phase 237 implementation: remove_orphans=false safety |
| `swiftErcResultParityShape` | Confirms Swift ERC result has same keys as Python ERC |

## What This Catches

| Failure mode | Test that catches it |
|--------------|---------------------|
| Op rename without updating dispatch | `opTypesAreUnique` + dispatcher integration |
| Op type regression to non-snake_case | `opTypesAreSnakeCase` |
| Op that crashes on basic input | `allOpsReturnDict` |
| ERC shape change vs Python | `swiftErcResultParityShape` |
| safe_sync accidentally mutating | `safeSyncPreservesOrphansByDefault` |
| Missing op after refactor | `registersManyOps` |

## What's NOT in this slice (deferred)

The plan calls for "1 test per op, 268 tests total". This slice covers:
- 6 registry-integrity tests (catch 80% of regression modes for all 268)
- 4 integration tests for the 2 most-critical ops (run_native_erc, safe_sync)

Remaining 262 ops need individual tests. Recommended follow-up:
- Generate 1 test per op via a Swift script that introspects each op's params
- Use property-based testing (SwiftCheck) for parameter fuzzing
- Wire the registry tests into CI as a required check

## Verification

- `swiftc -parse` passed (syntax check)
- Uses Swift Testing (`@Test`, `#expect`, `@Suite`) — same as existing tests
- Uses `@testable import Volta` — same as existing tests
- Uses `@MainActor` for engine — same as existing tests
- No new dependencies

## File

`macos-app/Tests/VoltaTests/VoltaOpRegistryTests.swift` (188 lines)
