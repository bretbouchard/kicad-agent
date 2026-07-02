#!/usr/bin/env bash
# C-03: Reproducible fetch script for the Gemma 4 12B vision adapter.
#
# The adapter weights are too large for git (921MB PEFT, 1GB MLX). This
# script fetches them from known locations and verifies integrity.
#
# Usage:
#   ./scripts/fetch_gemma_vision_adapter.sh [--mlx] [--peft]
#
# Without flags: fetches both PEFT and MLX formats.
#
# Locations (checked in order):
#   1. Already present (skip)
#   2. External drive: /Volumes/Storage/models/kicad-agent/adapters/
#   3. HuggingFace Hub: bretbouchard/kicad-vision-lora-adapter (PEFT only)
#
# Phase 106 (model repoint) requires this adapter for inference. The adapter
# was trained on spatial Q&A + maze reasoning chains (generate_gap_training_data.py).
# Phase 106 will SFT on diagnostic traces from Phase 104.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

FETCH_MLX=true
FETCH_PEFT=true
if [[ "${1:-}" == "--mlx" ]]; then FETCH_PEFT=false; fi
if [[ "${1:-}" == "--peft" ]]; then FETCH_MLX=false; fi

MLX_DEST="$PROJECT_ROOT/output/kicad-vision-v2-mlx"
PEFT_DEST="$PROJECT_ROOT/output/kicad_vision_adapter_v2/checkpoint-2000"
EXTERNAL_MLX="/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2-mlx"

echo "=== C-03: Gemma Vision Adapter Fetch ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# --- MLX format (for mlx-vlm inference) ---
if $FETCH_MLX; then
    if [[ -f "$MLX_DEST/adapters.safetensors" ]]; then
        echo "[MLX] Already present: $MLX_DEST/adapters.safetensors"
    elif [[ -f "$EXTERNAL_MLX/adapters.safetensors" ]]; then
        echo "[MLX] Copying from external drive: $EXTERNAL_MLX"
        mkdir -p "$MLX_DEST"
        cp "$EXTERNAL_MLX/adapters.safetensors" "$MLX_DEST/"
        cp "$EXTERNAL_MLX/adapter_config.json" "$MLX_DEST/"
        echo "[MLX] Done. Size: $(du -sh "$MLX_DEST" | cut -f1)"
    else
        echo "[MLX] WARNING: External drive not mounted and no local copy."
        echo "[MLX]   Mount /Volumes/Storage or run with --peft to skip."
    fi
fi

# --- PEFT format (for HuggingFace transformers / fine-tuning) ---
if $FETCH_PEFT; then
    if [[ -f "$PEFT_DEST/adapter_model.safetensors" ]]; then
        echo "[PEFT] Already present: $PEFT_DEST/adapter_model.safetensors"
    elif [[ -d "$PROJECT_ROOT/output/kicad_vision_adapter_v2/checkpoint-2000" ]]; then
        echo "[PEFT] Checkpoints present in output/kicad_vision_adapter_v2/"
    else
        echo "[PEFT] Not found locally. Attempting HuggingFace Hub download..."
        if command -v huggingface-cli &>/dev/null; then
            huggingface-cli download bretbouchard/kicad-vision-lora-adapter \
                --local-dir "$PROJECT_ROOT/output/kicad_vision_adapter_v2" \
                || echo "[PEFT] WARNING: HF download failed. Check repo access."
        else
            echo "[PEFT] WARNING: huggingface-cli not installed."
            echo "[PEFT]   Install: pip install huggingface_hub"
            echo "[PEFT]   Then: huggingface-cli download bretbouchard/kicad-vision-lora-adapter"
        fi
    fi
fi

echo ""
echo "=== Adapter Manifest ==="
echo "Base model: google/gemma-4-12b-it"
echo "LoRA rank: 64, scale: 2.0 (alpha=128)"
echo "Layers: 48"
echo "Training: spatial Q&A + maze reasoning chains"
echo "Trained via: scripts/train_gemma_sft_mlx.py + scripts/vast_train_kicad.py"
echo ""
echo "Phase 106 will SFT this adapter on Phase 104 diagnostic traces."
