---
phase: 246
type: context
status: pending-planning
gathered: 2026-07-15
source: manual
---

# Phase 246 Context — Python eval harness for Volta v2

## Phase Boundary

Build a Python eval harness that loads `bretbouchard/volta-pcb-adapter-v2` directly
(via `peft + transformers`) and measures PCB generation quality against a held-out
test set. The macOS app's `MLXLocalProvider` is a separate code path — this harness
exercises the same adapter weights through the Python inference stack so we can
measure quality independently of the Swift/MLX binding.

## Locked Decisions (preliminary)

- **Stack**: Python 3.11, peft 0.19.1, transformers 5.13.x, torch 2.12.x
- **Base model**: `google/gemma-4-12b-it` (4-bit quantized via bitsandbytes to fit in 24GB GPU)
- **Adapter source**: `bretbouchard/volta-pcb-adapter-v2` from HuggingFace (just published in Phase 245)
- **Test set**: carve out 50-sample holdout from the Phase 234A corpus (or define a fresh 50-intent set if the corpus is too domain-specific)
- **Scoring dimensions**:
  1. **ERC pass rate**: 0 errors when run through `skidl 2.2.3` ERC
  2. **Syntactic correctness**: output parses as valid Python (SKiDL) or valid netlist
  3. **Schema completeness**: contains all components required for the intent (matched against gold reference)
  4. **Reference fidelity**: BLEU-4 + ROUGE-L vs gold reference output
- **Output**: `output/volta-v2-eval-report.json` (per-sample) + `output/volta-v2-eval-summary.md` (aggregate)
- **Pass gate**: aggregate score ≥ baseline (TBD; Phase 230 v2 metrics on training data set the floor)

## Canonical References (downstream agents must read)

- `macos-app/Sources/KiCadAgent/Models/Providers/MLXLocalProvider.swift` — the Swift-side invocation pattern (for prompt format reference)
- `/Volumes/Storage/models/kicad-agent/adapters/volta-12b-v2/adapter_config.json` — PEFT config (rank, alpha, target_modules)
- `.planning/phases/234a-corpus-and-driver/234a-CONTEXT.md` — corpus structure (if using it as test set)
- `python/daemon/...` — existing Python-side inference patterns if they exist

## Specific Ideas

- Use `transformers.pipeline("text-generation", model=base, ...)` + `PeftModel.from_pretrained(...)` to apply the LoRA at inference time
- Eval framework: lightweight — no need for `lm-eval-harness`; a 200-line Python script with 4 metric functions is sufficient
- GPU: any 24GB+ CUDA card. Vast.ai or Lambda Labs for ad-hoc runs ($0.50-$2/hr)
- CI integration: optional — run on every adapter publish (HF webhook) or on a daily schedule

## Out of scope (deferred)

- MLX-side eval (the macOS app's actual inference path) — separate harness, would need an M-series Mac
- Held-out test set creation from scratch (we reuse the 234A corpus or carve a holdout)
- LLM-as-judge metrics (could add in a future iteration)

## Open Questions

1. **What scoring threshold counts as "pass"?** Phase 230 training metrics (loss 0.0288, acc 98.66% on training data) don't directly map to held-out generation quality. Need to define a baseline.
2. **50 samples or more?** Bigger test set = more confidence but slower. 50 is a starting point.
3. **Local GPU or Vast.ai?** Vast.ai is cheaper for ad-hoc but adds setup overhead. Local A100/RTX4090 if available.

---

*Phase: 246-volta-v2-eval-harness*
*Context gathered: 2026-07-15 — pending detailed planning*
