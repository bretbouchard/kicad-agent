---
phase: 241
type: summary
status: complete
---

# Phase 241 Summary — Streaming Chat E2E Test

## Status: COMPLETE

`ChatPipelineE2ETests` ships 11 passing tests covering the streaming
chat pipeline end-to-end:

```
MockProvider → KiCadModelRouter → RouterStreamProvider → chunks
```

The exact gap that allowed the Phase 211 echo bug to ship is now caught
by an automated test.

## What Was Added This Phase

| File | Change |
|------|--------|
| `macos-app/Tests/KiCadAgentTests/ChatPipelineE2ETests.swift` | NEW — 11-test suite |

## Tests (all 11 passing)

| Test | What it catches |
|------|-----------------|
| `echoStripped` | **The regression that started this work** — model echoes user prompt; `stripEcho` removes it from first chunk |
| `paragraphBreakFlushes` | `\n\n` boundary produces a separate chunk |
| `sentenceBoundaryFlushes` | `. ` boundary flushes the buffer |
| `costCallbackFires` | `onUsage` closure called with non-zero `KCUsage` |
| `streamTerminatesCleanly` | `.done(.complete)` triggers `continuation.finish()` (no hang) |
| `loopResponseDeliversFull` | Repeated content delivered; renderer owns collapse (no silent truncation here) |
| `historyIsForwarded` | Multi-turn history is included in the `KCPrompt` (prior assistant turn visible to model) |
| `stripEcho: full-chunk echo` | Unit: full chunk is user prompt → returns "" |
| `stripEcho: prefix echo` | Unit: chunk starts with prompt → returns remainder |
| `stripEcho: no echo` | Unit: chunk doesn't match → unchanged |
| `stripEcho: case-insensitive` | Unit: case differences don't defeat matching |

## Architecture

The test wires a real `MockProvider` (Phase 164) into a real
`KiCadModelRouter`, with `KCRoutingPreferences.preferredProviderPerTask`
set to force routing to `.mock` for every task category. This bypasses
AppleLocal / cloud / privacy fallbacks and gives the test full control
over the token stream.

`RouterStreamProvider.onUsage` is captured via an `actor` for async-safe
introspection. The `PromptCapturingProvider` subclass records the
`KCPrompt` it received so the multi-turn test can assert the history
is intact.

## Fixtures (inline, not JSON)

The plan called for JSON files under `Tests/.../Fixtures/`, but the
SPM test target has no `resources:` declaration in `Package.swift`,
so `Bundle.module` is unavailable. Fixtures are inline `static let`
arrays of `KCToken` — simpler, faster, no bundle gymnastics, and
documents the expected token sequences right next to the tests that
use them.

## What's NOT in this slice (deferred)

- **Renderer-level loop collapse**: tests verify the stream delivers all
  content (no silent truncation in the pipeline). The chat bubble
  view's loop-collapse annotation (`(x5)`) is a separate render concern
  and is covered by the `AppRootViewSnapshotTests` / chat view tests.
- **Real network/provider tests**: per the plan, all tests use mocks.
  Live providers are exercised in the v5 training pipeline
  (Vast.ai Gemma 4) and in manual QA.
- **Bundle.module integration**: not needed; inline fixtures win.

## Pre-existing bugs found and fixed

While running the test build, two pre-existing compile errors in
`VoltaEngineRemaining.swift` from Phase 243 surfaced and were fixed:

1. `SExpr.removingChildren { $0 === wire }` — `SExpr` is a value-type
   enum, not a class. `===` is illegal. Replaced with
   `.list(head, children.filter { $0 != wire })` (Equatable value
   comparison).
2. `typeNode.replaceChildren(with: [SExpr.atom("passive")])` — no such
   method on the value type. Replaced with a root-level rebuild that
   reconstructs only the modified `pin` subtrees, keeping the rest of
   the schematic untouched.

These fixes are required for `swift test` to even reach Phase 241 tests
at all.

## Pre-existing failures NOT fixed in this phase

`VoltaOpRegistryTests` (Phase 240) has 7 pre-existing failures unrelated
to this phase:

- `engine.availableOperations.count → 171` < 200 expected (not 268)
- 1 duplicate `opType` (172 strings, 171 unique)
- `result["ok"]` expectation but actual returns `"clean"`
- `safe_sync_pcb_from_schematic` returns 1 schematic symbol but test
  expects 2
- `safe_sync` added list doesn't include `C1`

These are gaps in the Phase 240 implementation — the test file shipped
but the underlying Volta registry and the NativeERC return shape don't
match the test expectations. Tracked separately; not in Phase 241 scope.

## Verification

```
swift test --filter "ChatPipelineE2ETests"
✔ Test "stripEcho: case-insensitive match" passed
✔ Test "stripEcho: no echo returns the chunk unchanged" passed
✔ Test "stripEcho: full-chunk echo returns empty" passed
✔ Test "stripEcho: prefix echo returns the remainder" passed
✔ Test "Stream terminates with continuation.finish(), not via thrown error" passed
✔ Test "Multi-turn history is forwarded to the provider (prior assistant turn included)" passed
✔ Test "Echo of user prompt is stripped from first chunk" passed
✔ Test "Sentence boundary (. ) flushes a chunk on its own" passed
✔ Test "Paragraph break (\n\n) produces a separate chunk" passed
✔ Test "Loop response delivers all repeated content (no silent truncation)" passed
✔ Test "onUsage fires with non-zero usage after stream completes" passed
✔ Test run with 11 tests in 1 suite passed after 0.063 seconds.
```

Echo regression is now a test case. The bug that started this work
cannot recur silently.
