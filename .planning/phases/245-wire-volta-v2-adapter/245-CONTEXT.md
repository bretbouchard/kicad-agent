---
phase: 245
type: context
status: complete
gathered: 2026-07-14
source: manual
---

# Phase 245 Context — Wire Volta v2 LoRA adapter into macOS app + publish to HF

## Phase Boundary

Replace the `MLXLocalProvider` placeholder with real PEFT inference on
`google/gemma-4-12b-it`, publish the trained adapter to HuggingFace, and
flip the v1→v2 swap gate. End result: first-time users see the download
sheet pull the v2 adapter (not v1) and inference generates real PCB output.

## Locked Decisions

### Adapter source
- **HF repo**: `bretbouchard/volta-pcb-adapter-v2` (does not exist yet — must be created)
- **Source of truth (canonical)**: `/Volumes/Storage/models/volta/adapters/volta-12b-v2/`
  - 5.0 GB, SHA256 `cbc121ccdc43cf9b8f29ca20bdd2837bee196d6cf76bc2491d07de74b6f150ab`
  - 39 files: final adapter, 3 checkpoints (2000/2500/3000), tokenizer, configs
  - 656 bfloat16 LoRA tensors across 48 layers × 7 target modules (q/k/v/o/gate/up/down_proj)
  - v_proj is intentionally missing on layers 5/11/17/23/29/35/41/47 (every 6th layer — gemma-4 hybrid attention pattern)
- **Training metrics**: step 3000/3000, loss 0.0288, accuracy 98.66%, 48.5M tokens
- **Training adapter_config.json**: rank=64, alpha=128, dropout=0.05, peft_type=LORA, task_type=CAUSAL_LM

### v1 → v2 swap
- **Remove v1 entirely**: no smoke-test fallback, no v1 download path
- The current `ModelDownloader.swift:65` returns `bretbouchard/volta-pcb-adapter-v1` for macOS — change to `bretbouchard/volta-pcb-adapter-v2`
- Sandbox install path changes from `volta-pcb-adapter-v1/` → `volta-pcb-adapter-v2/`

### Failure guard (P0)
- If HF repo is down or 404s, `ModelDownloadView` must show a clear
  "Volta v2 adapter unavailable" state, not silently fall back
- Specifically: replace the silent `hasLocalModel = false` with an explicit
  "Download failed: {error}" state showing the user the failure + retry button
- No automatic fallback to a previous version

### Inference architecture
- `MLXLocalProvider` (already present, `#if canImport(MLXLLM)`) — fill in the
  real implementation. Adapter path comes from `ModelDownloader.adapterDirectory`
- The base model is `mlx-community/gemma-4-12b-it-4bit` (already in code)
- Adapter loaded via `PeftModel.from_pretrained(base, adapterPath)` (Python daemon side; Swift invokes via XPC/subprocess)
- Preserves Phase 175 streaming contract + Phase 241 E2E test invariants

### Bridge to existing pipeline
- `ProviderRegistry` resolves the local provider as the default
- `KiCadModelRouter` picks the local provider unless the user selects cloud
- Streaming tokens flow through the existing `AsyncStream<TokenChunk>` contract

## Canonical References (downstream agents must read)

### Source-of-truth files
- `macos-app/Sources/Volta/Models/LocalModelManager.swift` — current `scanAndRegister()`, where `MLXLocalProvider` is registered. Lines 36-70.
- `macos-app/Sources/Volta/Models/ModelDownloader.swift` — current v1 wire-up. Line 65 = the swap gate.
- `macos-app/Sources/Volta/Views/Settings/ModelDownloadView.swift` — download sheet UI; needs the failure-state branch.
- `macos-app/Sources/Volta/Models/MLXLocalProvider.swift` — placeholder, needs real PEFT inference
- `macos-app/Sources/Volta/Models/ProviderRegistry.swift` — provider registration; new local model name

### Tests that must keep passing
- `macos-app/Tests/VoltaTests/StreamingChatE2ETests.swift` (Phase 241) — streaming invariants
- `macos-app/Tests/VoltaTests/OnboardingFlowTests.swift` (Phase 242) — onboarding
- `macos-app/Tests/VoltaTests/ImageAttachmentPipelineTests.swift` (Phase 239) — attachment pipeline

### Reference patterns
- `python/daemon/...` — Python daemon's PEFT loading code (if exists) — patterns to mirror in Swift's MLX binding
- `output/volta-pcb-adapter-v2-upload/adapter_config.json` — the source config the Swift code must match

## Specific Ideas

- After uploading to HF, verify by hitting `https://huggingface.co/api/models/bretbouchard/volta-pcb-adapter-v2` and confirming the file list includes `adapter_model.safetensors`
- Use `huggingface-cli upload bretbouchard/volta-pcb-adapter-v2 /Volumes/Storage/models/volta/adapters/volta-12b-v2/` (CLI handles resumable multi-GB upload)
- For the Swift test side, add a `LocalModelLoadTests` that verifies the
  download path resolution + failure-state presentation, without actually
  requiring the 5 GB model to be present
- MLX Swift binding: the `#if canImport(MLXLLM)` guard means we can ship the
  Swift code that references MLX without it being available in CI; tests
  use the path-resolution layer only

## Deferred Ideas

- **Vision adapter (`kicad-vision-v2-peft`)** — separate model, different
  serving path. Not in this phase.
- **iOS adapter** (`bretbouchard/volta-pcb-ios-4b-adapter`) — separate training
  job, different file. Not in this phase.
- **Multi-LoRA runtime** (load 2+ adapters, route per request) — Phase 246+
- **A/B testing v1 vs v2** in the download sheet — explicitly rejected;
  v1 is being deleted from the catalog

---

*Phase: 245-wire-volta-v2-adapter*
*Context gathered: 2026-07-14 via manual scope (decisions are locked by user)*
</content>
</invoke>