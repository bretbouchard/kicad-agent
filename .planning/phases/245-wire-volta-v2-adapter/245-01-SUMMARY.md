# Phase 245 Plan 01: Wire Volta v2 LoRA adapter + publish to HF

One-shot execution successfully shipped the Volta v2 LoRA adapter to HuggingFace and wired it into the macOS app.

## Completed Tasks

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Publish adapter to HF | 942dcf0 | UPLOADED-TO-HF.md |
| 2 | Flip ModelDownloader to v2 | 942dcf0 | ModelDownloader.swift |
| 3 | Replace hasLocalModel Bool with LocalModelStatus enum | 942dcf0 | LocalModelStatus.swift, LocalModelManager.swift, ModelDownloadView.swift |
| 4 | Implement MLXLocalProvider with local model display name | 942dcf0 | MLXLocalProvider.swift |
| 5 | Add tests for v2 path resolution and failure states | 942dcf0 | LocalModelPathTests.swift, LocalModelFailureTests.swift |

## Acceptance Criteria Results

| Criteria | Status |
| -------- | ------ |
| HF repo `bretbouchard/volta-pcb-adapter-v2` exists with `adapter_model.safetensors` | PASSED |
| `ModelDownloader.adapterRepo` returns `bretbouchard/volta-pcb-adapter-v2` (macOS) | PASSED |
| No v1 references (`volta-pcb-adapter-v1`, `adapters.safetensors`) in Sources/ | PASSED |
| `isAdapterPresent` checks for `adapter_model.safetensors` | PASSED |
| iOS branch unchanged (returns `volta-pcb-ios-4b-adapter`) | PASSED |
| `LocalModelStatus` enum with 5 cases exists | PASSED |
| `DownloadFailureReason` enum with user-facing messages exists | PASSED |
| `ModelDownloadError.adapterNotFound` case exists | PASSED |
| `FailureBanner` and `AdapterNotPublishedBanner` views exist | PASSED |
| `MLXLocalProvider.displayName` returns "Volta PCB v2 (Local, MLX)" | PASSED |
| `swift build` exits 0 | PASSED |
| `swift test --filter "LocalModel.*Tests"` - 6 tests pass | PASSED |
| Existing tests (OnboardingFlowTests, ImageAttachmentPipelineTests, ChatPipelineE2ETests) pass | PASSED |

## Key Files Modified

- `macos-app/Sources/KiCadAgent/Models/ModelDownloader.swift` - v1→v2 adapter swap, fixed isAdapterPresent bug
- `macos-app/Sources/KiCadAgent/Models/LocalModelManager.swift` - state enum migration
- `macos-app/Sources/KiCadAgent/Models/LocalModelStatus.swift` - NEW: lifecycle state enum
- `macos-app/Sources/KiCadAgent/Models/Providers/MLXLocalProvider.swift` - displayName update
- `macos-app/Sources/KiCadAgent/Views/Settings/ModelDownloadView.swift` - failure state UI
- `macos-app/Tests/KiCadAgentTests/LocalModelPathTests.swift` - NEW: 4 path resolution tests
- `macos-app/Tests/KiCadAgentTests/LocalModelFailureTests.swift` - NEW: 2 failure state tests

## Key Decisions

1. **Adapter naming convention**: Used v2 PEFT-standard `adapter_model.safetensors` instead of v1's `adapters.safetensors`
2. **LocalModelStatus vs Bool**: Replaced `hasLocalModel: Bool` with enum to capture distinct failure states
3. **MLXLoRA loading**: Current implementation uses MLXLLM's `ModelAdapterFactory`; added error handling for load failures with fallback to base model
4. **Test approach**: Tests create temporary directories with minimal valid files to test the logic without requiring actual model downloads

## Deviations from Plan

None - plan executed exactly as written.

## Commit

`942dcf0` - feat(245-01): wire Volta v2 adapter and add failure state handling