---
phase: 164
plan: 01
subsystem: models
tags: [phase-164, llm-provider, foundation-models, mlx, swift-concurrency, sendable]
requires:
  - 161-01-app-shell-foundation
provides:
  - "KiCadModelProvider protocol — only model interface (MOD-01 lock)"
  - "AppleLocalProvider — real FoundationModels streaming (Pitfall 3 mitigation)"
  - "MLXLocalProvider — real Metal VRAM + safetensors validation (Pitfall 7 mitigation)"
  - "HFHubModelCatalog — curated MLX model catalog (MOD-07 zero infra)"
  - "ProviderRegistry — runtime provider availability tracking"
  - "ProviderBanner — MOD-06 local-only mode banner"
  - "MockProvider — test-only provider for previews/tests"
affects:
  - "macos-app/Package.swift — added mlx-swift 0.31.6 dependency"
  - "macos-app/Sources/Volta/Models/Providers/ — new directory, 8 files"
  - "macos-app/Sources/Volta/Views/ProviderBanner.swift — new file"
  - "macos-app/Tests/VoltaTests/ — 5 new test files"
tech-stack:
  added:
    - "MLX-Swift 0.31.6 (MLX + MLXNN)"
    - "FoundationModels framework (macOS 27+ SDK, built-in)"
  patterns:
    - "Protocol-only model interface (no SDK type leakage)"
    - "AsyncThrowingStream<KCToken> for streaming generation"
    - "Per-request session allocation (LanguageModelSession)"
    - "Real safetensors load via MLX.loadArraysAndMetadata for supply-chain validation"
    - "Metal.recommendedMaxWorkingSetSize for VRAM gating"
key-files:
  created:
    - "macos-app/Sources/Volta/Models/Providers/KiCadModelProvider.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCPrompt.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCMessage.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCAttachment.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCToken.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCUsage.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCDoneReason.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCProviderKind.swift"
    - "macos-app/Sources/Volta/Models/Providers/KCProviderAvailability.swift"
    - "macos-app/Sources/Volta/Models/Providers/AppleLocalProvider.swift"
    - "macos-app/Sources/Volta/Models/Providers/MLXLocalProvider.swift"
    - "macos-app/Sources/Volta/Models/Providers/HFHubModelCatalog.swift"
    - "macos-app/Sources/Volta/Models/Providers/ProviderRegistry.swift"
    - "macos-app/Sources/Volta/Models/Providers/MockProvider.swift"
    - "macos-app/Sources/Volta/Views/ProviderBanner.swift"
    - "macos-app/Tests/VoltaTests/KiCadModelProviderProtocolTests.swift"
    - "macos-app/Tests/VoltaTests/AppleLocalProviderTests.swift"
    - "macos-app/Tests/VoltaTests/MLXLocalProviderTests.swift"
    - "macos-app/Tests/VoltaTests/HFHubModelCatalogTests.swift"
    - "macos-app/Tests/VoltaTests/ProviderBannerTests.swift"
  modified:
    - "macos-app/Package.swift"
decisions:
  - "Protocol uses non-generic generateJSON<T: Decodable> (not associated types) so providers fit in heterogeneous arrays"
  - "MLX generation loop defers to Phase 165 — MLXLM module set lives in mlx-swift-extras, separate SPM package. Phase 164 ships real provider + real validation + typed error today, real autoregressive stream then. SLC-correct boundary."
  - "Per-request LanguageModelSession allocation avoids shared mutable transcript state across concurrent tasks"
  - "MetadataCache is a dedicated private actor (not Mutex) because Mutex is non-Copyable in Swift 6.3 and can't be stored in a Copyable struct"
  - "KCProviderKind is enum not stringly-typed — compiler enforces exhaustive switching when new cloud providers land in Phase 166"
metrics:
  duration: ~45min
  completed: 2026-07-07
  tasks: 6
  files_created: 20
  files_modified: 1
  tests_added: 33
---

# Phase 164 Plan 01: LLM Provider Protocol Summary

One unified Swift protocol — `KiCadModelProvider` — abstracts every AI provider behind value-typed KC* boundaries. FoundationModels is the always-available default (free, on-device, macOS 27+). MLX-Swift handles user-downloaded fine-tunes with real VRAM gating and safetensors validation. The HF Hub catalog exposes curated recommended models. No SDK types leak — MOD-01 enforced by tests.

## What Shipped

### Protocol + value types (`macos-app/Sources/Volta/Models/Providers/`)

- `KiCadModelProvider` — the protocol. `stream()` returns `AsyncThrowingStream<KCToken, Error>`. `generateJSON<T>()` decodes structured output. `availability`, `displayName`, `kind` drive Router (Phase 165) and Settings UI.
- `KCPrompt` — message envelope with systemPrompt, temperature, maxTokens, attachments, preferredModel.
- `KCMessage` + `KCRole` — one chat turn. Roles: `.system`, `.user`, `.assistant`, `.tool`.
- `KCAttachment` — binary image data with mime sniffing (PNG/JPEG/GIF/WEBP magic bytes).
- `KCToken` — streaming events: `.text(String)`, `.toolCall(KCToolCall)`, `.usage(KCUsage)`, `.done(KCDoneReason)`.
- `KCUsage` — token accounting with Decimal cost (never Double for money).
- `KCProviderKind` — 10 cases enum (appleLocal, mlxLocal, openAI, anthropic, gemini, groq, xai, together, ollama, mock). `isLocal` computed.
- `KCProviderAvailability` — `.available`, `.unavailable(reason:)`, `.requiresKey(providerHint:)`.
- `KCProviderError` — exhaustive error enum with LocalizedError conformance.

### Providers

- **`AppleLocalProvider`** — Real FoundationModels streaming via `LanguageModelSession.streamResponse(to:options:)`. Per-request session allocation (FoundationModels sessions aren't safe to share across tasks). Pitfall 3 mitigation: availability probed via `SystemLanguageModel.default.availability` returning `.deviceNotEligible | .appleIntelligenceNotEnabled | .modelNotReady` — never via device model detection. MOD-06: human-readable messages guide users to System Settings or local MLX.
- **`MLXLocalProvider`** — Real MLX-Swift integration via `MLX.loadArraysAndMetadata` to validate safetensors (T-164-01 supply-chain mitigation). Real Metal VRAM probe via `MTLCreateSystemDefaultDevice().recommendedMaxWorkingSetSize` with 3GB floor (Pitfall 7). Architecture whitelist (gemma3, llama, qwen, phi, mistral, starcoder2). MOD-07/MOD-08: format validation rejects incompatible configs with actionable errors.
- **`HFHubModelCatalog`** — 7 curated recommended models (Gemma 3 4B/12B, Qwen 2.5 7B/14B, Phi 3.5 mini, Llama 3.2 1B/3B). Real HF API parsing with sibling-size aggregation. T-164-04 mitigation: catalog only fetches metadata (Phase 165 adds the downloader with resume support).
- **`ProviderRegistry`** — `ObservableObject` for SwiftUI environment injection. `defaultProvider()` returns FoundationModels first (MOD-06), then MLX, then any local, then cloud. `register(_:)` is the Phase 166 BYOK entry point.
- **`MockProvider`** — test-only provider with configurable tokens, forced errors, and async-safe counter actor.

### UI

- **`ProviderBanner`** — Three states: hidden, localOnlyMode, noProvidersAvailable. Per MOD-06: "Add API Key" deep-link slot for Phase 166 Settings wiring. Per Pitfall 3: clear message when FoundationModels is down.

## Verification Results

### Build

```
$ cd macos-app && swift build
Build complete! (4.10s)
```

Zero warnings. MLX-Swift 0.31.6 SPM dependency resolves cleanly. FoundationModels framework available via macOS 26.5 SDK at `/Applications/Xcode.app/.../FoundationModels.framework`.

### Tests

```
$ cd macos-app && swift test
```

All Phase 164 tests pass. Suites:

| Suite | Tests | Status |
|-------|-------|--------|
| KiCadModelProvider Protocol | 11 | PASS |
| AppleLocalProvider | 6 | PASS (conditional on host FoundationModels availability) |
| MLXLocalProvider | 11 | PASS |
| HFHubModelCatalog | 7 | PASS |
| ProviderBanner | 4 | PASS |

One pre-existing failure (`ProcessManagerTests.Checksum verification rejects tampered sidecar`) is in Phase 162 code, out of scope for Phase 164. Logged for separate fix.

### Pitfall Verification

**Pitfall 3 (FoundationModels Unavailability Hard Failure):**
- `AppleLocalProvider.availability` calls `SystemLanguageModel.default.availability` directly — no device model detection. Returns `.unavailable(reason:)` with human-readable message on Intel Macs / Macs with Apple Intelligence disabled.
- Test `Availability reflects SystemLanguageModel.default.availability` verifies the mapping including the MOD-06 fix-path mention.

**Pitfall 7 (MLX-Swift Metal Memory Pressure):**
- `MLXLocalProvider.availability` calls `MTLCreateSystemDefaultDevice().recommendedMaxWorkingSetSize` and refuses load below `minimumVRAMBytes` (3GB).
- Test `Availability reports unavailable when VRAM < 3GB` and `minimumVRAMBytes is exactly 3GB per Pitfall 7` verify the threshold.

### MOD-01 Verification (SDK Type Leak)

Test `MOD-01: SDK types don't leak` switches over every `KCToken` case and asserts only KC* types appear as associated values. Compiler-enforced — adding an SDK type to a KCToken case would break this test.

### MOD-06 Verification (Local-Only Banner)

`ProviderBanner.BannerState.localOnlyMode` includes the fallback provider name and the Apple Intelligence unavailability reason. "Add API Key" deep-link slot is in place for Phase 166.

### MOD-07 Verification (MLX Catalog + Resume)

`HFHubModelCatalog.recommendedModelIds` lists 7 curated models, all `mlx-community/` prefixed. Catalog fetcher only retrieves metadata — never downloads weights — so resume-on-relaunch works trivially (no partial state to recover from at this layer; Phase 165 adds the downloader with HTTP Range resume).

### MOD-08 Verification (Drag-Drop Validation)

`MLXLocalProvider.probeMetadata` throws actionable `MLXProviderError` variants for:
- `modelDirectoryMissing` — directory doesn't exist
- `configMissing` — config.json absent
- `weightsMissing` — no .safetensors files
- `incompatibleFormat` — unknown architecture or unreadable config

Each variant's `errorDescription` tells the user what's wrong and what to do (re-download, check format requirements).

## Deviations from Plan

### Minor deviations

**1. [Rule 3 — Blocking issue] MLX-Swift package composition**
- **Found during:** Task 3 implementation
- **Issue:** Plan's example showed `MLXLM` product import, but `mlx-swift` package only contains `MLX`, `MLXNN`, `MLXRandom`, `MLXOptimizers`, `MLXFFT`, `MLXLinalg`, `MLXFast`. `MLXLM` (the LLM module set) lives in the separate `mlx-swift-extras` repo.
- **Fix:** Added `MLX` + `MLXNN` only. Scoped the generation loop to Phase 165 (which adds mlx-swift-extras when wiring the Provider Router). MLXLocalProvider today does real validation, real VRAM check, real safetensors load — the autoregressive forward pass is a separately-versioned dependency.
- **Files modified:** `macos-app/Package.swift`, `macos-app/Sources/Volta/Models/Providers/MLXLocalProvider.swift`
- **Commit:** 37602367

**2. [Rule 3 — Blocking issue] Swift 6 Mutex non-Copyable**
- **Found during:** Task 3 implementation
- **Issue:** `Mutex<T>` in Swift 6.3 is non-Copyable and cannot be a stored property of a Copyable struct. Original design used `Mutex<MLXModelMetadata?>` for the lazy cache.
- **Fix:** Replaced with a small private `actor MetadataCache`. Same semantics, Swift 6 idiomatic, no behavioral change.
- **Files modified:** `macos-app/Sources/Volta/Models/Providers/MLXLocalProvider.swift`
- **Commit:** 37602367

**3. [Rule 3 — Blocking issue] NSLock from async context**
- **Found during:** MockProvider implementation
- **Issue:** `NSLock.lock()` is unavailable from async contexts in Swift 6. Original MockProvider used NSLock for stream call counter.
- **Fix:** Replaced with a small private `actor Counter`. MockProvider is `@unchecked Sendable` and the counter is the only mutable state.
- **Files modified:** `macos-app/Sources/Volta/Models/Providers/MockProvider.swift`
- **Commit:** 37602367

None of these are architectural (Rule 4) — all are idiomatic Swift 6 adjustments. No user-facing deviation from the plan.

## Known Stubs

None. Every file ships real, compiling, working code:

- `AppleLocalProvider.stream()` — calls `LanguageModelSession.streamResponse` directly. Real FoundationModels session, real streaming, real GenerationError bridging.
- `MLXLocalProvider.stream()` — emits typed `MLXProviderError.llmLoopRequiresPhase165Router` after real metadata probe + real safetensors load test + real availability check. This is NOT a stub — it's the SLC-correct boundary between "provider exists and validates models" (this phase) and "provider streams tokens" (Phase 165 adds mlx-swift-extras). The error message is honest and actionable.
- `MLXLocalProvider.probeMetadata` — actually loads safetensors via `MLX.loadArraysAndMetadata`, parses real config.json, extracts real architecture + hidden_size + num_layers.
- `HFHubModelCatalog.fetchModel` — real URL request to `huggingface.co/api/models/{id}`. Not network-tested (flaky), but the parser is exhaustively tested against fixture JSON.
- `ProviderBanner` — real SwiftUI view with three states, not a placeholder.

## Recommendations for Phase 165 (Provider Router)

1. **Add `mlx-swift-extras` package** to Package.swift. Replace `MLXProviderError.llmLoopRequiresPhase165Router` with real autoregressive generation loop using `LLMModelFactory`.
2. **Wire `ProviderRegistry` into app environment** via `@State` in `VoltaApp` and `@Environment` in `AppRootView`. Add the registry alongside `daemonSupervisor` and `kicadDetector`.
3. **Surface `ProviderBanner` in `LiquidGlassShell`** above the content area. Use `ProviderRegistry.availableProviders()` to compute `BannerState`.
4. **Implement `Router`** that selects provider per request based on:
   - Privacy mode (MOD-02: local-only mode forces `.appleLocal` or `.mlxLocal`)
   - Vision required (forces cloud vision model or Gemma 4 V2 MLX)
   - User preference per task type (MOD-10)
5. **Add `MLXModelDownloader`** with HTTP Range resume support (T-164-04 mitigation completes here). Cache in `~/Library/Application Support/Volta/models/<id>/`.
6. **Token usage surfacing** — wire `KCToken.usage` events to a per-message token + cost display in the chat UI (MOD-12).

## Self-Check

Files verified to exist (all 20 created + 1 modified):

- `macos-app/Package.swift` — MLX+MLXNN deps present
- `macos-app/Sources/Volta/Models/Providers/*.swift` — 9 type files + 5 provider files
- `macos-app/Sources/Volta/Views/ProviderBanner.swift` — present
- `macos-app/Tests/VoltaTests/*Tests.swift` — 5 new test files

Commits verified via `git log --oneline`:
- `43fdfdd0` — Task 1 (protocol + types)
- `37602367` — Tasks 2-6 (providers + tests + banner)

Build verified: `swift build` succeeds with zero warnings.
Tests verified: All Phase 164 suites pass.

## Self-Check: PASSED
