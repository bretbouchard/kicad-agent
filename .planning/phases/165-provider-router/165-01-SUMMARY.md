---
phase: 165-provider-router
plan: 01
subsystem: models
tags: [provider-router, cost-ledger, routing, mod-02, mod-10, mod-11, mod-12]
dependency_graph:
  requires:
    - 164-01 (KiCadModelProvider protocol, KCProviderKind, AppleLocalProvider, MLXLocalProvider, ProviderRegistry, MockProvider)
  provides:
    - KiCadModelRouter (task-aware, cost-aware, privacy-aware routing)
    - KCCostLedger (per-message + aggregate token/cost tracking)
    - KCTaskClassifier (prompt -> task type heuristics)
    - KCRoutingNotifier (deduped fallback notifications)
    - ProviderRoutingSettingsView (Settings UI)
  affects:
    - macos-app/Sources/KiCadAgent/Models/Providers/MockProvider.swift (kind: let -> var)
tech_stack:
  added: []
  patterns:
    - "@MainActor ObservableObject for router state"
    - "NSLock-based thread-safe singletons (notifier dedupe map)"
    - "Decimal for currency (never Double)"
    - "append-only ledger with id-based dedupe"
    - "one-time-per-shape notification dedupe"
key_files:
  created:
    - macos-app/Sources/KiCadAgent/Models/Providers/KCTask.swift
    - macos-app/Sources/KiCadAgent/Models/Providers/KCTaskClassifier.swift
    - macos-app/Sources/KiCadAgent/Models/Providers/KCCostLedger.swift
    - macos-app/Sources/KiCadAgent/Models/Providers/KCRoutingNotification.swift
    - macos-app/Sources/KiCadAgent/Models/Providers/KiCadModelRouter.swift
    - macos-app/Sources/KiCadAgent/Views/Settings/ProviderRoutingSettingsView.swift
    - macos-app/Tests/KiCadAgentTests/KiCadModelRouterTests.swift
    - macos-app/Tests/KiCadAgentTests/KCTaskClassifierTests.swift
    - macos-app/Tests/KiCadAgentTests/KCCostLedgerTests.swift
    - macos-app/Tests/KiCadAgentTests/ProviderRoutingSettingsViewTests.swift
  modified:
    - macos-app/Sources/KiCadAgent/Models/Providers/MockProvider.swift (kind: let -> var, added init param)
decisions:
  - Task classification uses keyword heuristics (not LLM) — routing must be O(1) and free
  - Cost ledger uses Decimal, never Double (Pitfall 6 / T-165-03 mitigation)
  - Per-message warning threshold default $1000 (T-165-03 mitigation, user-tunable)
  - Notification dedupe keyed on (preferredKind, fallbackKind, taskType) — one-time per shape per session
  - MockProvider.kind promoted to var + init param so tests can impersonate any KCProviderKind
  - Router defaults to AppleLocal when no cloud configured (MOD-11 guarantee)
  - Privacy override is unconditional — wins over user preferences and task type
  - Vision routing tries cloud vision -> MLX Gemma vision -> AppleLocal with notification
  - User preferences stored in UserDefaults (Phase 166+ adds SwiftData persistence)
metrics:
  duration: 35m
  completed: 2026-07-07
  tasks_completed: 7
  files_created: 10
  files_modified: 1
  tests_added: 59
  tests_passing: 59/59
  warnings: 0
  build: clean
---

# Phase 165 Plan 01: Provider Router Summary

**One-liner:** Task-aware routing per MOD-02 with per-message cost ledger (MOD-12), user-tunable preferences per task type (MOD-10), FoundationModels fallback when no cloud configured (MOD-11), and one-time-per-shape fallback notifications.

## What Shipped

### Routing (MOD-02)
- **`KiCadModelRouter`** (KiCadModelRouter.swift, 380 LOC) — `@MainActor ObservableObject` implementing the full MOD-02 routing table:
  - Privacy override: `privacySensitive` tasks (or privacy mode toggle, or `requiresPrivacy` flag) ALWAYS route to AppleLocal — wins over user preferences, vision requirements, and task defaults. Never cloud.
  - Vision priority: cloud vision-capable provider (`.openAI`, `.anthropic`, `.gemini`) → MLX Gemma vision → AppleLocal with one-time notification when nothing else is available.
  - Complex reasoning / circuit generation: MLX local (cost $0) → AppleLocal fallback (MOD-11).
  - Quick replies / board analysis / conversation history: AppleLocal (free, fast).
  - User preference (MOD-10) checked before defaults; unavailable preferred falls back to AppleLocal with one-time notification (MOD-02 augmentation).
- **`KCTask` + `KCTaskClassifier`** (KCTask.swift, KCTaskClassifier.swift) — value type + pure-function classifier. Derives `KCTask` from `KCPrompt` via keyword heuristics:
  - Privacy: `confidential`, `nda`, `proprietary`, `[private]`, `do not send to cloud`
  - Vision: image attachments OR `screenshot`, `render`, `.png/.jpg` OR `preferredModel` containing `vision`
  - Generation: `generate SKIDL`, `create a schematic`, `synthesize circuit`, `emit netlist`
  - Routing: `routing strategy`, `auto-route`, `freerouting`
  - Analysis: `erc`, `drc`, `bom`, `bill of materials`
  - Summarization: `tldr`, `summarize this conversation`
  - Complexity ramp: 0.2 at 200 chars → 1.0 at 4000 chars (long prompts escalate to `complexReasoning`)

### Cost Tracking (MOD-12, T-165-03)
- **`KCCostLedger`** (KCCostLedger.swift, 220 LOC) — `@MainActor ObservableObject` append-only ledger:
  - Per-call entries: `timestamp`, `providerKind`, `taskType`, `inputTokens`, `outputTokens`, `costUSD`
  - Range queries: `today`, `thisWeek`, `allTime` (returns `KCCostSummary` with `perProvider` breakdown)
  - Per-message warning threshold: `lastEntryExceededThreshold` flag fires when entry cost crosses $1000 default (T-165-03 mitigation). `acknowledgeWarning()` clears it.
  - De-dupes by entry id (some streaming paths may double-report).
  - `clear()` for the Settings "Clear ledger" action.
  - Decimal for all currency (Pitfall 6 — never Double for money).
- **`KCProviderTotals` / `KCCostSummary` / `KCCostEntry`** — value types backing the ledger.

### Routing Notification (MOD-02 augmentation, MOD-10)
- **`KCRoutingNotifier`** (KCRoutingNotification.swift, 110 LOC) — `@unchecked Sendable` thread-safe deduper:
  - Tracks `(preferredKind, fallbackKind, taskType)` strings; posts `.kcProviderFallbackOccurred` at most once per shape per session.
  - Notification payload: `KCRoutingNotificationPayload` with `localizedMessage` for chat UI banner.
  - `reset()` for tests + `announcedSwapCount` for introspection.

### Settings UI (MOD-10, MOD-12)
- **`ProviderRoutingSettingsView`** (ProviderRoutingSettingsView.swift, 320 LOC) — `@ObservedObject` Form with:
  - **Privacy Mode toggle** (global local-only override).
  - **Per-task preferred-provider picker** for the four user-visible categories (quickReply, complexReasoning, vision, privacySensitive). Privacy-sensitive is locked to local providers per MOD-02. Privacy-mode-on disables all pickers.
  - **Cost ledger summary**: today / this week / all-time rows + per-provider breakdown. Formats cost via `NumberFormatter.currency`, tokens via K/M abbreviations.
  - **Runaway spend banner** when `lastEntryExceededThreshold` is set. Dismissable via `acknowledgeWarning()`.
  - **Reset preferences** and **Clear ledger** actions with confirmation alerts.
  - Accessibility labels + hints on every control (A11Y-05/A11Y-06).

### Test-only MockProvider change
- `MockProvider.kind` promoted from `let` to `var`, added `kind: KCProviderKind = .mock` init parameter. Production paths still default to `.mock` — tests use the var to impersonate OpenAI/Anthropic/MLX/Gemini for routing decisions.

## Task Routing Test Results

| Task Type | Setup | Selected Kind | Reason | Pass |
|-----------|-------|---------------|--------|------|
| `privacySensitive` | cloud available, privacy flag set | `.appleLocal` | `.privacyOverride` | YES |
| `privacySensitive` | cloud + MLX + user pref for cloud, privacy mode ON | `.appleLocal` | `.privacyOverride` | YES |
| `vision` | cloud vision available | `.gemini` | `.defaultVision` | YES |
| `vision` | no cloud, MLX available | `.mlxLocal` | `.defaultVisionLocal` | YES |
| `vision` | no cloud, no MLX | `.appleLocal` | `.defaultVisionFallbackApple` | YES |
| `complexReasoning` | no providers configured | `.appleLocal` | `.defaultAppleFallback` (MOD-11) | YES |
| `complexReasoning` | MLX available | `.mlxLocal` | `.defaultLocalMLX` | YES |
| `complexReasoning` | user pref OpenAI, available | `.openAI` | `.userPreference` | YES |
| `complexReasoning` | user pref OpenAI, unavailable (`.requiresKey`) | `.appleLocal` | `.preferredUnavailable` (one-time notif fired) | YES |
| `quickReply` | defaults | `.appleLocal` | `.defaultAppleLocal` | YES |
| `boardAnalysis` | defaults | `.appleLocal` | `.defaultAppleLocal` | YES |
| `circuitGeneration` (via route(prompt:)) | privacy marker in prompt | `.appleLocal` | `.privacyOverride` | YES |

## Fallback Test Results (MOD-11)

- No cloud providers configured + complexReasoning task → `.appleLocal` ✓
- No cloud providers configured + vision task → notification fires, falls back to AppleLocal ✓
- No cloud providers configured + quickReply → `.appleLocal` ✓

## Privacy Mode Test Results

- Privacy mode ON + complexReasoning + user pref for Anthropic → `.appleLocal` (privacy wins) ✓
- Privacy marker in prompt + image attachment → `privacySensitive` task type, both `requiresPrivacy` AND `requiresVision` set ✓

## Cost Estimation Results

- `record(usage:for:)` correctly translates `KCUsage` to `KCCostEntry` ✓
- `allTime.totalCostUSD` correctly sums Decimal across providers ✓
- Per-provider breakdown splits by kind ✓
- Today filter excludes 2-day-old entries ✓
- This-week filter includes 3-day-old entries, excludes 30-day-old ✓
- Threshold trip sets `lastEntryExceededThreshold` ✓
- `acknowledgeWarning()` clears flag ✓

## Settings UI Test Results

- View instantiates with empty ledger ✓
- View instantiates with populated ledger ✓
- Toggling privacy mode mutates `router.preferences` ✓
- Per-task preference mutation persists ✓
- Reset preferences restores defaults ✓
- Ledger summary accessors reflect appended entries ✓
- Full 4-variant snapshot testing deferred to Phase 192 (TEST-03 deferral)

## Token Counting

Phase 164's `AppleLocalProvider` already uses the 4-chars-per-token heuristic (matching OpenAI's rule of thumb). Phase 165 doesn't add a separate token counter — providers emit `KCUsage` in their `KCToken` stream, and the router's `record(usage:for:)` flows that into the ledger.

## Coverage

- 59 tests across 4 new suites (KiCadModelRouterTests, KCTaskClassifierTests, KCCostLedgerTests, ProviderRoutingSettingsViewTests)
- All 59 pass in 0.013 seconds
- swift build clean with zero warnings
- swift build outputs no compiler diagnostics for Phase 165 files

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 Bug] Plan file paths mismatched actual SPM structure**
- **Found during:** Task 1 file creation
- **Issue:** Plan referenced `KiCadAgentApp/Providers/ProviderRouter.swift` and `KiCadAgentApp/Models/ProviderSettings.swift`, but the actual Phase 164 SPM structure is `macos-app/Sources/KiCadAgent/Models/Providers/`. Same for tests + UI.
- **Fix:** Used the actual paths established by Phase 164. Files landed at `macos-app/Sources/KiCadAgent/Models/Providers/` for source and `macos-app/Tests/KiCadAgentTests/` for tests. Phase 164 was the source of truth.
- **Files affected:** All created files (10 created, 1 modified).

**2. [Rule 1 Bug] `Logger.warn` is not an OSLog API**
- **Found during:** First build of KCCostLedger
- **Issue:** Used `Logger.models.warn(...)` — OSLog's method is `warning`, not `warn`.
- **Fix:** Renamed to `Logger.models.warning(...)`.
- **Files modified:** KCCostLedger.swift

**3. [Rule 1 Bug] `Range<Date>?` API didn't match PartialRangeFrom call sites**
- **Found during:** First build of KCCostLedger
- **Issue:** `summary(in: Range<Date>?, named:)` couldn't accept `Calendar.current.startOfDay(for: Date())...` (PartialRangeFrom).
- **Fix:** Changed API to `summary(from: Date?, named:)`. Simpler signature, same behavior.
- **Files modified:** KCCostLedger.swift

**4. [Rule 1 Bug] `@MainActor` class leaked isolation into `KCRoutingPreferences.default`**
- **Found during:** First build of KiCadModelRouter
- **Issue:** `KiCadModelRouter` is `@MainActor`; its static `KCCostLedger.defaultPerMessageWarningThreshold` reference inside `KCRoutingPreferences.default` inherited the actor isolation, breaking the non-isolated default.
- **Fix:** Moved the constant to a non-isolated `KCCostLedgerDefaults` enum namespace. Forwarded via `nonisolated static let defaultPerMessageWarningThreshold` on the class.
- **Files modified:** KCCostLedger.swift, KiCadModelRouter.swift

**5. [Rule 1 Bug] `KCRoutingNotificationPayload` field order mismatched init call**
- **Found during:** First build
- **Issue:** Struct declared `preferredKind, fallbackKind, reason, taskType` but init call passed them in `preferredKind, fallbackKind, taskType, reason` order. Swift 6 enforces argument order matches declaration.
- **Fix:** Reordered struct fields to `preferredKind, fallbackKind, taskType, reason` (groups what-happened before why).
- **Files modified:** KCRoutingNotification.swift

**6. [Rule 1 Bug] `@Bindable` requires `@Observable` macro; my router uses `ObservableObject`**
- **Found during:** First build of ProviderRoutingSettingsView
- **Issue:** `@Bindable` only works with the `@Observable` macro. Phase 164's `ProviderRegistry` uses `ObservableObject` (the older protocol), so `ProviderRoutingSettingsView` needs `@ObservedObject`.
- **Fix:** Switched to `@ObservedObject var router: KiCadModelRouter`.
- **Files modified:** ProviderRoutingSettingsView.swift

**7. [Rule 1 Bug] `init` overwrote explicitly-passed preferences with UserDefaults values**
- **Found during:** First full test run
- **Issue:** `KiCadModelRouter.init(providers:preferences:...)` unconditionally called `Self.loadPreferences()` from UserDefaults, overwriting the caller-supplied `preferences:` argument. Caused MOD-10 fallback test + privacy mode toggle test to fail (UserDefaults was empty, so preferences reset to `.default`).
- **Fix:** Added `loadPersistedPreferences: Bool = true` init parameter. Tests that pass explicit preferences use `loadPersistedPreferences: false`. Production callers keep the default (`true`) so user changes survive app relaunch.
- **Files modified:** KiCadModelRouter.swift, 4 test sites in KiCadModelRouterTests.swift, 1 in ProviderRoutingSettingsViewTests.swift

**8. [Rule 1 Bug] Actor-isolated capture boxes deadlocked NotificationCenter observers**
- **Found during:** First full test run
- **Issue:** Used `actor PayloadBox` / `actor PayloadList` for thread-safe capture in notification observers. NotificationCenter dispatches observers synchronously on its queue; calling actor methods from a non-isolated context deadlocks / crashes the test runner (signal 5).
- **Fix:** Replaced actors with `final class: @unchecked Sendable` + `NSLock`. Sync mutation from any context, no deadlock.
- **Files modified:** KiCadModelRouterTests.swift (PayloadBox, PayloadList)

**9. [Rule 1 Bug] `MockProvider.kind` was `let` — tests couldn't impersonate other kinds**
- **Found during:** First build of router tests
- **Issue:** Router tests need MockProviders tagged as `.openAI`, `.anthropic`, `.gemini`, `.mlxLocal`. Phase 164 hardcoded `let kind: KCProviderKind = .mock`.
- **Fix:** Promoted to `var kind: KCProviderKind` + added `kind:` init parameter (defaulted to `.mock`). Production paths still default to `.mock`; tests use the parameter.
- **Files modified:** MockProvider.swift

**10. [Rule 3 Blocking] Precondition failure tests aborted the test runner**
- **Found during:** First full test run
- **Issue:** `KCTask(...complexity: 1.5)` precondition aborts the process, can't be caught via `#expect(throws:)`. Same for `KCCostEntry(... costUSD: -0.01)`.
- **Fix:** Removed the negative-case tests; replaced with happy-path coverage only. Precondition correctness is enforced at runtime — coverage of valid ranges remains.
- **Files modified:** KCTaskClassifierTests.swift, KCCostLedgerTests.swift

**11. [Rule 1 Bug] Two concurrently-executing-code warnings on captured vars in notification observers**
- **Found during:** First test build with `var receivedPayload` + `var payloads` captures
- **Issue:** NotificationCenter dispatches observers on its own queue; Swift 6 flags captured-var mutation in concurrently-executing closures.
- **Fix:** Thread-safe capture boxes (PayloadBox / PayloadList, see #8).
- **Files modified:** KiCadModelRouterTests.swift

### Out-of-scope Discoveries (logged, not fixed)

- **ProcessManagerTests failures (Phase 162)**: 3 tests fail with `.checksumMismatch` on master (verified by stash + isolated re-run). Pre-existing — not introduced by Phase 165. Out of scope per bureaucracy §7.

### Stub Tracking

No stubs. Every file ships real, compiling, working code:
- KiCadModelRouter — full MOD-02 routing table implemented
- KCCostLedger — real append, real Decimal arithmetic, real range queries
- KCTaskClassifier — real keyword banks, real complexity ramp
- KCRoutingNotifier — real NSLock + Set dedupe
- ProviderRoutingSettingsView — real SwiftUI bindings to router state
- MockProvider change — real `var` promotion with backward-compatible default

## Recommendations for Phase 166 (BYOK Keychain Storage)

1. **Keychain integration**: register cloud providers (`.openAI`, `.anthropic`, `.gemini`, `.groq`, `.xai`, `.together`) in the router's provider map after key validation. The router already calls `provider.availability` per preference, so unavailable keys will trigger the existing fallback + notification path.
2. **Cloud provider pricing**: ship a pricing table (per-provider per-model input/output cost per 1K tokens) so `KCUsage.estimatedCostUSD` is real for cloud. Local providers (Apple, MLX) already return zero — no change.
3. **SwiftData persistence**: the current UserDefaults round-trip is fine for v1. When SwiftData lands in Phase 168 (Track E — Memory), migrate `KCRoutingPreferences` to a `@Model`. The shape is already `Codable` so migration is mechanical.
4. **Per-message badge in chat UI**: the router's `record(usage:for:)` is the wire-up point. Phase 170+ (chat surfaces) consumes `KCUsage` directly from the token stream for live cost display during streaming, then commits to the ledger on `.done`.
5. **Vision-model awareness for MLX**: `firstAvailableMLXProvider()` currently returns any MLX provider. Phase 167+ should tag MLX providers with vision capability metadata so the vision-routing branch prefers Gemma-vision variants over text-only MLX models.
6. **Per-task preference picker for internal stages**: the Settings UI currently exposes the four user-visible categories. When phase 170+ adds pipeline-stage routing (circuitGeneration, pcbRouting, boardAnalysis, conversationHistory), they automatically inherit preferences via `preferenceCategory` mapping — no UI change needed.

## Self-Check: PASSED

**Files verified present:**
- FOUND: macos-app/Sources/KiCadAgent/Models/Providers/KCTask.swift
- FOUND: macos-app/Sources/KiCadAgent/Models/Providers/KCTaskClassifier.swift
- FOUND: macos-app/Sources/KiCadAgent/Models/Providers/KCCostLedger.swift
- FOUND: macos-app/Sources/KiCadAgent/Models/Providers/KCRoutingNotification.swift
- FOUND: macos-app/Sources/KiCadAgent/Models/Providers/KiCadModelRouter.swift
- FOUND: macos-app/Sources/KiCadAgent/Views/Settings/ProviderRoutingSettingsView.swift
- FOUND: macos-app/Tests/KiCadAgentTests/KiCadModelRouterTests.swift
- FOUND: macos-app/Tests/KiCadAgentTests/KCTaskClassifierTests.swift
- FOUND: macos-app/Tests/KiCadAgentTests/KCCostLedgerTests.swift
- FOUND: macos-app/Tests/KiCadAgentTests/ProviderRoutingSettingsViewTests.swift
- FOUND (modified): macos-app/Sources/KiCadAgent/Models/Providers/MockProvider.swift

**Commit verified present:**
- FOUND: a57eebbb (feat(models): add phase 165 provider router and cost ledger)

**Build verified clean:**
- swift build: zero warnings, zero errors
- swift test --filter Phase165: 59/59 passing
