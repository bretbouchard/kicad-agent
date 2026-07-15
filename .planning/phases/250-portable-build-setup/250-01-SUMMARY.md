# Phase 250 — Portable Build Setup Summary

**Date:** 2026-07-15
**Plan:** 250-01-PLAN.md
**Status:** COMPLETE

## What shipped

- `scripts/setup_local.py` — portable build setup script
  - Detects canonical Volta v2 adapter across known locations
  - Creates `volta-12b-v2` symlink at repo root
  - Optional `--download` flag for HF fetch
  - `--verify` mode for environment-only checks
  - Verifies Python >=3.11, kicad-cli presence, symlink validity

## Search order

1. `/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2` (Storage mount, legacy name)
2. `/Volumes/Storage/models/kicad-agent/adapters/volta-pcb-adapter-v2` (Storage mount, canonical)
3. `~/Library/Application Support/VoltaPCB/models/volta-pcb-adapter-v2/` (app cache)
4. `~/.cache/huggingface/hub/bretbouchard--volta-pcb-adapter-v2/` (HF cache)
5. Optional HuggingFace download (with `--download`)

## Verification

```
[1/3] Verifying environment...
  python: OK (3.11.11)
  kicad-cli: OK (/usr/local/bin/kicad-cli)
  adapter-symlink: OK -> /Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2
```

## Use cases covered

| Scenario | Behavior |
|----------|----------|
| Bret's Mac mini (Storage mounted) | Detects adapter, creates symlink |
| Fresh CI runner (no Storage) | Falls through to HF cache, then prompts `--download` |
| Teammate with adapter in app cache | Detects app cache path |
| Air-gapped machine | Detects cached adapter if pre-staged, else fails gracefully |
| Bret's laptop vs Mac mini | Same script works on both |

## Compliance

- Symlink creates if missing ✓
- Symlink updates if stale ✓
- HF download optional (off by default) ✓
- Verify-only mode supported ✓
- Exit codes reflect success/failure ✓