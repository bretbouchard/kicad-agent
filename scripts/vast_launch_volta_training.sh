#!/usr/bin/env bash
# Volta PCB — Vast.ai Training Launch Script
#
# Provisions a GPU instance, uploads the combined training corpus, installs
# dependencies, and starts the 12B + 4B adapter training run in the background.
#
# Usage:
#   export HF_TOKEN=hf_xxxxx
#   bash scripts/vast_launch_volta_training.sh
#
# If HF_TOKEN is not exported, the script will use the local HuggingFace CLI
# token at ~/.cache/huggingface/token when present.

set -euo pipefail

GPU_NAME="${GPU_NAME:-RTX_4090}"
MAX_PRICE="${MAX_PRICE:-0.60}"
IMAGE="${IMAGE:-pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel}"
MIN_CUDA="${MIN_CUDA:-12.4}"
DISK="${DISK:-80}"
LABEL="${LABEL:-volta-pcb-adapter-train}"
LOG_PATH="/workspace/volta_training.log"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v vastai >/dev/null 2>&1; then
    echo "ERROR: vastai CLI not found. Install with: pip install vastai"
    exit 1
fi

if [ -z "${HF_TOKEN:-}" ] && [ -s "$HOME/.cache/huggingface/token" ]; then
    HF_TOKEN="$(<"$HOME/.cache/huggingface/token")"
    export HF_TOKEN
fi

if [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: HF_TOKEN is not set and no HuggingFace token file was found."
    exit 1
fi

required_files=(
    "scripts/train_volta_super_shiny.py"
    "training_output/sft_prepared/train.jsonl"
    "training_output/real_pcb_560/train.jsonl"
    "/Volumes/Storage/schgen/converted/synthetic_skidl.jsonl"
    "scripts/convert_peft_to_mlx.py"
)

for path in "${required_files[@]}"; do
    if [ ! -s "$path" ]; then
        echo "ERROR: required file missing or empty: $path"
        exit 1
    fi
done

echo "=== Volta PCB Training — Vast.ai Launch ==="
echo "GPU: ${GPU_NAME}, max price: \$${MAX_PRICE}/hr, disk: ${DISK}GB, CUDA >= ${MIN_CUDA}"

echo "[1/6] Searching for ${GPU_NAME} offers..."
OFFER_JSON="$(vastai search offers \
    "gpu_name=${GPU_NAME} num_gpus=1 rentable=True" \
    --limit 20 --storage "$DISK" --on-demand --raw 2>/dev/null)"

if [ -z "$OFFER_JSON" ] || [ "$OFFER_JSON" = "[]" ]; then
    echo "No ${GPU_NAME} offers found. Trying any >=20GB VRAM GPU..."
    OFFER_JSON="$(vastai search offers \
        "gpu_ram>=20 num_gpus=1 rentable=True" \
        --limit 20 --storage "$DISK" --on-demand --raw 2>/dev/null)"
fi

OFFER_INFO="$(echo "$OFFER_JSON" | MAX_PRICE="$MAX_PRICE" MIN_CUDA="$MIN_CUDA" python3 -c '
import json, sys
from os import environ

offers = json.load(sys.stdin)
if not offers:
    sys.exit(1)

max_price = float(environ["MAX_PRICE"])
min_cuda = float(environ["MIN_CUDA"])
filtered = []
for offer in offers:
    price = float(offer.get("dph_total", offer.get("dph", 999)))
    cuda = float(offer.get("cuda_max_good", offer.get("cuda_vers", 0)) or 0)
    verification = offer.get("verification", "")
    if price <= max_price and cuda >= min_cuda and verification == "verified" and offer.get("disk_space", 0) >= 100:
        filtered.append(offer)

if not filtered:
    for offer in offers:
        price = float(offer.get("dph_total", offer.get("dph", 999)))
        cuda = float(offer.get("cuda_max_good", offer.get("cuda_vers", 0)) or 0)
        if price <= max_price and cuda >= min_cuda and offer.get("disk_space", 0) >= 100:
            filtered.append(offer)

if not filtered:
    sys.exit(1)

offers = filtered
offers.sort(key=lambda o: o.get("dph_total", o.get("dph", 999)))
o = offers[0]
print("{}|{}|{}".format(o["id"], o.get("gpu_name", "?"), o.get("dph_total", o.get("dph", "?"))))
' 2>/dev/null || true)"

if [ -z "$OFFER_INFO" ]; then
    echo "ERROR: no suitable Vast.ai offers found."
    exit 1
fi

OFFER_ID="${OFFER_INFO%%|*}"
OFFER_REST="${OFFER_INFO#*|}"
OFFER_GPU="${OFFER_REST%%|*}"
OFFER_PRICE="${OFFER_REST#*|}"
echo "  Selected offer ${OFFER_ID}: ${OFFER_GPU} at \$${OFFER_PRICE}/hr"

echo "[2/6] Creating instance..."
CREATE_OUTPUT="$(vastai create instance "$OFFER_ID" \
    --image "$IMAGE" \
    --disk "$DISK" \
    --ssh \
    --label "$LABEL" \
    --env "-e HF_TOKEN=${HF_TOKEN}" \
    --raw 2>&1)"

INSTANCE_ID="$(echo "$CREATE_OUTPUT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("new_contract", ""))
except Exception:
    print("")
' 2>/dev/null)"

if [ -z "$INSTANCE_ID" ]; then
    echo "ERROR: instance creation failed."
    echo "$CREATE_OUTPUT"
    exit 1
fi
echo "  Instance: ${INSTANCE_ID}"

cleanup_hint() {
    echo "Destroy instance to stop billing: vastai destroy instance ${INSTANCE_ID}"
}
trap cleanup_hint ERR

echo "[3/6] Waiting for instance to run..."
STATUS=""
for i in $(seq 1 60); do
    STATUS="$(vastai show instance "$INSTANCE_ID" --raw 2>/dev/null | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("actual_status", ""))
except Exception:
    print("")
' 2>/dev/null)"

    if [ "$STATUS" = "running" ]; then
        echo "  Instance is running."
        break
    fi

    if [ "$STATUS" = "error" ]; then
        echo "ERROR: instance entered error state."
        exit 1
    fi

    INSTANCE_STATE="$(vastai show instance "$INSTANCE_ID" --raw 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print("{}|{}".format(data.get("cur_state", ""), data.get("intended_status", "")))
except Exception:
    print("|")
' 2>/dev/null)"
    if [ "$STATUS" = "loading" ] && [ "$INSTANCE_STATE" = "stopped|stopped" ]; then
        echo "ERROR: instance is stuck loading while stopped."
        echo "Destroy instance to stop billing: vastai destroy instance ${INSTANCE_ID}"
        exit 1
    fi

    echo "  Status: ${STATUS:-unknown} (${i}/60)"
    sleep 10
done

if [ "$STATUS" != "running" ]; then
    echo "ERROR: instance did not reach running state."
    exit 1
fi

SSH_URL="$(vastai ssh-url "$INSTANCE_ID" | tail -n 1)"
if [[ ! "$SSH_URL" =~ ^ssh://root@.+:[0-9]+$ ]]; then
    echo "ERROR: could not resolve SSH URL: ${SSH_URL}"
    exit 1
fi

SSH_TARGET="${SSH_URL#ssh://}"
SSH_HOSTPORT="${SSH_TARGET#root@}"
SSH_HOST="${SSH_HOSTPORT%:*}"
SSH_PORT="${SSH_HOSTPORT##*:}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p "$SSH_PORT")

echo "  SSH: root@${SSH_HOST}:${SSH_PORT}"
echo "  Waiting for SSH..."
for i in $(seq 1 60); do
    if ssh "${SSH_OPTS[@]}" "root@${SSH_HOST}" "true" >/dev/null 2>&1; then
        echo "  SSH ready."
        break
    fi
    if [ "$i" = "60" ]; then
        echo "ERROR: SSH did not become ready."
        exit 1
    fi
    sleep 10
done

echo "  Writing HuggingFace token to remote environment..."
printf '%s' "$HF_TOKEN" | ssh "${SSH_OPTS[@]}" "root@${SSH_HOST}" \
    "umask 077 && cat > /workspace/.hf_token"

echo "  Checking GPU/CUDA health..."
ssh "${SSH_OPTS[@]}" "root@${SSH_HOST}" "bash -s" <<'REMOTE'
set -euo pipefail
echo "--- nvidia-smi ---"
nvidia-smi
echo "--- torch cuda preflight ---"
python - <<'PY'
import os
import sys
import torch

print(f"torch={torch.__version__}")
print(f"torch_cuda={torch.version.cuda}")
print(f"cuda_available={torch.cuda.is_available()}")
if not torch.cuda.is_available():
    sys.exit("ERROR: torch cannot access CUDA on this instance.")
print(f"device_count={torch.cuda.device_count()}")
print(f"device_0={torch.cuda.get_device_name(0)}")
PY
test -s /workspace/.hf_token
REMOTE

echo "[4/6] Preparing remote workspace..."
ssh "${SSH_OPTS[@]}" "root@${SSH_HOST}" \
    "mkdir -p /workspace/training_output/sft_prepared /workspace/training_output/real_pcb_560 /Volumes/Storage/schgen/converted /workspace/scripts"

echo "[5/6] Uploading training files..."
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    scripts/train_volta_super_shiny.py "root@${SSH_HOST}:/workspace/train_volta_super_shiny.py"
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    scripts/convert_peft_to_mlx.py "root@${SSH_HOST}:/workspace/scripts/convert_peft_to_mlx.py"
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    training_output/sft_prepared/train.jsonl "root@${SSH_HOST}:/workspace/training_output/sft_prepared/train.jsonl"
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    training_output/real_pcb_560/train.jsonl "root@${SSH_HOST}:/workspace/training_output/real_pcb_560/train.jsonl"
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    /Volumes/Storage/schgen/converted/synthetic_skidl.jsonl "root@${SSH_HOST}:/Volumes/Storage/schgen/converted/synthetic_skidl.jsonl"

echo "[6/6] Installing dependencies and starting training..."
ssh "${SSH_OPTS[@]}" "root@${SSH_HOST}" "bash -s" <<'REMOTE'
set -euo pipefail
cd /workspace
export HF_TOKEN="$(cat /workspace/.hf_token)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
# HuggingFace Xet chunked download hangs indefinitely on some Vast
# instances (xet_client spins on CAS retries that never resolve).
# Disabling Xet forces plain HTTPS, which downloads cleanly here.
export HF_HUB_DISABLE_XET=1
export HF_HUB_ENABLE_HF_TRANSFER=0
export HF_HUB_DOWNLOAD_TIMEOUT=300
# RTX 4090 (24GB) is tight for 12B + LoRA r=64 + seq 4096 + fp32 chunked CE.
# expandable_segments reduces CUDA fragmentation (the original OOM cause was
# reserved-but-unallocated memory, not peak working set).
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
python -m pip install -q --upgrade pip
python -m pip install -q transformers peft trl datasets bitsandbytes accelerate sentencepiece protobuf huggingface_hub
echo "Dependencies installed at $(date -u)." > /workspace/volta_training_launch.log
nohup python /workspace/train_volta_super_shiny.py --model both > /workspace/volta_training.log 2>&1 &
echo "$!" > /workspace/volta_training.pid
echo "Training PID: $(cat /workspace/volta_training.pid)" >> /workspace/volta_training_launch.log
REMOTE

trap - ERR

echo ""
echo "=== Training launched ==="
echo "Instance: ${INSTANCE_ID}"
echo "Log: ${LOG_PATH}"
echo "Monitor:"
echo "  ssh -p ${SSH_PORT} root@${SSH_HOST} 'tail -f ${LOG_PATH}'"
echo "Status:"
echo "  vastai show instance ${INSTANCE_ID}"
echo "Destroy:"
echo "  vastai destroy instance ${INSTANCE_ID}"
