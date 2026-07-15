---
phase: 245
type: research
status: complete
gathered: 2026-07-14
source: manual (SDK roadmap parser broken, skipping gsd-phase-researcher)
---

# Phase 245 Research — Wire Volta v2 LoRA adapter

## Why research was skipped

The `gsd-sdk roadmap` parser is broken (returns only 2 phases and
mis-numbers Phase 245 as 235), so the formal `gsd-phase-researcher`
agent invocation was bypassed. All decisions are locked in
`245-CONTEXT.md`, the source-of-truth files have been read directly,
and the technical scope is narrow enough that a separate research
pass would duplicate context.

## Technical decisions

### HuggingFace upload

- `huggingface-cli` is the canonical upload path. Two-step:
  1. `huggingface-cli repo create bretbouchard/volta-pcb-adapter-v2 --type model --private`
  2. `huggingface-cli upload bretbouchard/volta-pcb-adapter-v2 /Volumes/Storage/models/volta/adapters/volta-12b-v2/ .`
- Auth: `huggingface-cli login` reads token from keychain or `HF_TOKEN` env var
- Resumable: yes (built into huggingface_hub)
- Bandwidth: ~5 GB; expect ~2-15 min depending on uplink

### MLX Swift inference

- The existing `MLXLocalProvider` is a placeholder gated by `#if canImport(MLXLLM)`
- MLX's `MLXLLM` framework provides `LLMModelFactory` for base model loading
- For LoRA, MLX uses `Module` patching: load adapter weights, cast each
  `Linear` to `LoRALinear`, fill in `loraA`/`loraB` from the safetensors
- The exact API depends on MLX's current `MLXLLM` version; verify at
  compile time, fall back to direct `MLXArray` manipulation if needed

### Failure guard pattern

- `ModelDownloader.fetchFileList` returns 404 for non-existent repo
  vs. HTTP error for network. Distinguish these explicitly.
- The current `LocalModelManager.scanAndRegister` sets
  `hasLocalModel = false; showDownloadSheet = true` and returns.
  For the v2 case, we want to know WHY it's not there:
  - Repo doesn't exist (404) → "Adapter not published" state
  - Network error (timeout) → "Network unreachable, retry" state
  - Repo exists but no adapter file → "Repo corrupt" state
- This needs an enum `LocalModelStatus` rather than just `hasLocalModel: Bool`

### Test strategy

- The 5 GB model can't be loaded in CI. Tests must:
  - Verify path resolution (`ModelDownloader.adapterDirectory` returns the v2 path)
  - Verify download failure handling (mock URLSession → 404 → failure state)
  - Verify the v1 path is gone (`grep -rn "volta-pcb-adapter-v1" Sources/` → 0 hits)
- End-to-end inference is verified manually (the 19.2h training already proved
  the model works; the wiring just needs to not break it)

## v1 -> v2 differences that matter

| Concern | v1 | v2 | Risk |
|---------|----|----|------|
| Adapter repo | `bretbouchard/volta-pcb-adapter-v1` | `bretbouchard/volta-pcb-adapter-v2` | Swap one string |
| Base model | gemma-4-12b-it-4bit | gemma-4-12b-it-4bit (unchanged) | None |
| Sandbox path | `volta-pcb-adapter-v1/` | `volta-pcb-adapter-v2/` | Swap path string |
| `isAdapterPresent` check | `adapters.safetensors` | `adapter_model.safetensors` | **Bug** - v1 used `adapters.safetensors` (with "s"). v2 uses PEFT-standard `adapter_model.safetensors`. The check in ModelDownloader.swift:127 looks for `adapters.safetensors` which doesn't exist in v2! |
| MLX adapter loading | (assumed) PEFT-style | PEFT-style (rank 64) | Verify MLXLLM supports it |

**Critical finding**: `ModelDownloader.isAdapterPresent` checks for
`adapters.safetensors` (with an "s"). The v2 adapter (PEFT-standard) is
`adapter_model.safetensors` (no "s", with underscore). The check will
return false even after a successful v2 download, so `LocalModelManager`
won't register the provider. **This must be fixed in the plan.**

## Out of scope (deferred to other phases)

- MLX binding verification (compile-check only; full e2e in eval harness phase)
- Eval harness (separate phase)
- Gap closure (separate phase)
- Multi-LoRA runtime (Phase 246+)
- iOS adapter (separate training job)

---

*Phase: 245-wire-volta-v2-adapter*
*Research complete: 2026-07-14*
</content>
