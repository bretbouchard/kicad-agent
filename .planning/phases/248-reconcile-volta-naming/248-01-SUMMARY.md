# Phase 248 — Naming Reconciliation Summary

**Date:** 2026-07-15
**Plan:** 248-01-PLAN.md
**Status:** COMPLETE

## What shipped

- Symlink `volta-12b-v2 → /Volumes/Storage/models/volta/adapters/kicad-vision-v2` verified intact
- Adapter config verified against Phase 245 spec
- Canonical paths documented in `CLAUDE.md`

## Adapter verification

| Property | Spec (Phase 245) | Actual | Match |
|----------|------------------|--------|-------|
| base_model_name_or_path | google/gemma-4-12b-it | google/gemma-4-12b-it | OK |
| r (LoRA rank) | 64 | 64 | OK |
| lora_alpha | 128 | 128 | OK |
| target_modules | 7 modules | ['gate_proj', 'up_proj', 'down_proj', 'q_proj', 'k_proj', 'o_proj', 'v_proj'] | OK |
| peft_type | LORA | LORA | OK |
| task_type | CAUSAL_LM | CAUSAL_LM | OK |

## Canonical paths

| Use case | Path |
|----------|------|
| Repo symlink | `volta-12b-v2` (in repo root) |
| Storage target | `/Volumes/Storage/models/volta/adapters/kicad-vision-v2` |
| HuggingFace repo | `bretbouchard/volta-pcb-adapter-v2` |
| App local cache | `~/Library/Application Support/VoltaPCB/models/volta-pcb-adapter-v2/` |

## Naming reconciliation

- **Storage file name:** `kicad-vision-v2` (legacy, kept for compatibility)
- **App/HF name:** `volta-pcb-adapter-v2` (canonical)
- **Symlink:** `volta-12b-v2` (repo-friendly alias)

All three refer to the same trained adapter (verified by adapter_config.json
matching Phase 245 spec).

## Compliance

- Symlink resolves ✓
- Adapter config matches spec ✓
- CLAUDE.md updated with canonical paths ✓