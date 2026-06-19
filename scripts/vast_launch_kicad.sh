#!/usr/bin/env bash
# Vast.ai Gemma 4 LoRA Training — KiCad Vision Launch Script
# Adapted from spectral-primitives vast_launch.sh
#
# Prerequisites:
#   1. Vast.ai account with $5+ balance (https://vast.ai/create)
#   2. vast.ai CLI installed: pip install vastai
#   3. HF_TOKEN environment variable set (for gated Gemma 4 access)
#
# Usage:
#   export HF_TOKEN=hf_xxxxx
#   bash scripts/vast_launch_kicad.sh
#
# Cost estimate: RTX 3090 at $0.13/hr, ~3-4hr training = ~$0.40-0.55 total

set -euo pipefail

# --- Configuration ---
GPU_NAME="RTX_3090"          # Cheapest option with 24GB VRAM (sufficient)
MAX_PRICE="0.20"             # $/hr — don't overpay
IMAGE="pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel"
DATASET_KAGGLE=""            # Empty — use SCP upload instead of Kaggle
MAX_STEPS=400
OUTPUT_DIR="/workspace/kicad-vision-lora-adapter"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Vast.ai KiCad Vision LoRA Training Setup ===${NC}"

# --- Check prerequisites ---
if ! command -v vastai &> /dev/null; then
    echo "ERROR: vastai CLI not found. Install with: pip install vastai"
    exit 1
fi

if [ -z "${HF_TOKEN:-}" ]; then
    echo -e "${YELLOW}WARNING: HF_TOKEN not set. Gated model access may fail.${NC}"
    echo "  Set with: export HF_TOKEN=hf_xxxxx"
fi

# --- Step 1: Search for available GPU ---
echo -e "\n${GREEN}[1/5] Searching for ${GPU_NAME} instances...${NC}"
SEARCH_JSON=$(vastai search offers "gpu_name=${GPU_NAME} num_gpus=1 dph<${MAX_PRICE} cuda_max_good>=12.0" --limit 1 --on-demand --raw 2>/dev/null)

if [ -z "$SEARCH_JSON" ] || [ "$SEARCH_JSON" = "[]" ]; then
    echo "No ${GPU_NAME} under \$${MAX_PRICE}/hr found. Try:"
    echo "  - Increase MAX_PRICE in the script"
    echo "  - Try 'RTX_4090' (faster, ~\$0.34/hr)"
    echo "  - Run: vastai search offers 'gpu_name=RTX_3090 dph<0.30'"
    exit 1
fi

# Parse JSON with python (more reliable than jq which may not be installed)
OFFER_INFO=$(echo "$SEARCH_JSON" | python3 -c "
import sys, json
offers = json.load(sys.stdin)
if not offers:
    sys.exit(1)
o = offers[0]
print(f\"{o['id']}|{o.get('dph_total', o.get('dph', '?'))}|{o.get('machine_id', '?')}|{o.get('cuda_max_good', '?')}\")
")

if [ $? -ne 0 ] || [ -z "$OFFER_INFO" ]; then
    echo "ERROR parsing search results. Raw output:"
    echo "$SEARCH_JSON" | head -5
    exit 1
fi

OFFER_ID=$(echo "$OFFER_INFO" | cut -d'|' -f1)
DPH=$(echo "$OFFER_INFO" | cut -d'|' -f2)
MACH_ID=$(echo "$OFFER_INFO" | cut -d'|' -f3)
echo "  Found: offer ${OFFER_ID} at \$${DPH}/hr"

# --- Step 2: Create instance ---
echo -e "\n${GREEN}[2/5] Creating instance...${NC}"
CREATE_RESULT=$(vastai create instance "$OFFER_ID" \
    --image "$IMAGE" \
    --disk 50 \
    --ssh \
    --label "kicad-vision-lora-train" \
    2>&1)

echo "  $CREATE_RESULT"
INSTANCE_ID=$(echo "$CREATE_RESULT" | python3 -c "import sys,json; d=json.loads(sys.stdin.read().replace(\"Started. \",\"\")); print(d.get('new_id', d.get('new_contract', '')))" 2>/dev/null)

if [ -z "$INSTANCE_ID" ] || ! [[ "$INSTANCE_ID" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Instance creation failed. Output above."
    exit 1
fi

echo "  Instance ID: ${INSTANCE_ID}"
echo "  SSH port will be assigned — wait for ready state..."

# --- Step 3: Wait for instance to be ready ---
echo -e "\n${GREEN}[3/5] Waiting for instance to start...${NC}"
for i in $(seq 1 30); do
    # Use --json flag to get machine-readable output
    INSTANCE_JSON=$(vastai show instances --json 2>/dev/null)
    STATE=$(echo "$INSTANCE_JSON" | python3 -c "
import sys, json
instances = json.loads(sys.stdin.read()) if sys.stdin.read() else []
for inst in instances:
    if inst.get('id') == $INSTANCE_ID:
        print(inst.get('actual_status', ''))
        break
" 2>/dev/null || echo "")

    if [ "$STATE" = "running" ]; then
        echo "  Instance is running!"
        break
    fi
    if [ "$STATE" = "error" ]; then
        echo "ERROR: Instance failed to start. Check: vastai show instances $INSTANCE_ID"
        vastai destroy instance "$INSTANCE_ID" 2>/dev/null || true
        exit 1
    fi
    echo "  State: ${STATE:-unknown} (waiting...)"
    sleep 10
done

# Get SSH details via scp-url command (most reliable method)
SCP_URL=$(vastai scp-url "$INSTANCE_ID" 2>/dev/null)
if [ -n "$SCP_URL" ]; then
    # scp-url returns: scp://root@host:port/
    SSH_HOST=$(echo "$SCP_URL" | sed 's|scp://root@||' | cut -d':' -f1)
    SSH_PORT=$(echo "$SCP_URL" | sed 's|scp://root@||' | cut -d':' -f2 | cut -d'/' -f1)
else
    # Fallback: parse from JSON
    INSTANCE_JSON=$(vastai show instances --json 2>/dev/null)
    SSH_HOST=$(echo "$INSTANCE_JSON" | python3 -c "
import sys, json
instances = json.loads(sys.stdin.read()) if sys.stdin.read() else []
for inst in instances:
    if inst.get('id') == $INSTANCE_ID:
        print(inst.get('public_ipaddr', ''))
        break
" 2>/dev/null)
    SSH_PORT=$(echo "$INSTANCE_JSON" | python3 -c "
import sys, json
instances = json.loads(sys.stdin.read()) if sys.stdin.read() else []
for inst in instances:
    if inst.get('id') == $INSTANCE_ID:
        print(inst.get('ssh_port', ''))
        break
" 2>/dev/null)
fi

if [ -z "$SSH_HOST" ] || [ -z "$SSH_PORT" ]; then
    echo "ERROR: Could not get SSH details. Instance may not be ready."
    echo "  Check manually: vastai show instance $INSTANCE_ID"
    echo "  Or: vastai scp-url $INSTANCE_ID"
    exit 1
fi

echo "  SSH: ${SSH_HOST}:${SSH_PORT}"

# --- Step 4: Upload training script + dataset ---
echo -e "\n${GREEN}[4/5] Uploading files...${NC}"

# Upload training script
vastai scp scripts/vast_train_kicad.py "${INSTANCE_ID}:/workspace/vast_train_kicad.py"
echo "  Training script uploaded."

# Upload KiCad vision dataset via SCP
echo -e "${GREEN}Uploading KiCad vision dataset via SCP...${NC}"
vastai scp -r training_output/unified_vision_data/ "${INSTANCE_ID}:/workspace/unified_vision_data/"
echo "  Dataset uploaded."

# --- Step 5: Start training ---
echo -e "\n${GREEN}[5/5] Starting training...${NC}"
echo -e "${YELLOW}=== TRAINING IS RUNNING ===${NC}"
echo "  Monitor with:  vastai ssh ${INSTANCE_ID} -- tail -f /workspace/nohup.out"
echo "  Stop training:  vastai destroy instance ${INSTANCE_ID}"
echo "  Cost so far:   vastai show instances ${INSTANCE_ID}"
echo ""
echo "Estimated cost: ~\$0.40-0.55 for ${MAX_STEPS} steps on ${GPU_NAME}"
echo -e "${YELLOW}===========================${NC}"

# Run training in background with nohup so SSH disconnect doesn't kill it
vastai ssh "$INSTANCE_ID" -- bash -c "
    set -e
    cd /workspace
    export HF_TOKEN=${HF_TOKEN:-}

    # Install deps (transformers from GitHub for gemma4_unified support)
    pip install -q git+https://github.com/huggingface/transformers.git \\
        peft>=0.15.0 bitsandbytes>=0.45.0 accelerate>=1.3.0 \\
        trl==1.5.1 datasets>=3.0.0 sentencepiece protobuf

    echo 'Dependencies installed. Starting training...'
    echo '---' | tee /workspace/nohup.out

    nohup python vast_train_kicad.py \\
        --dataset_path /workspace/unified_vision_data/train \\
        --output_dir ${OUTPUT_DIR} \\
        --max_steps ${MAX_STEPS} \\
        --heartbeat_interval 300 \\
        >> /workspace/nohup.out 2>&1 &

    echo \"Training PID: \\\$!\"
    echo 'Training started. Run: tail -f /workspace/nohup.out'
"

echo -e "\n${GREEN}Instance running. Training started in background.${NC}"
echo ""
echo "Useful commands:"
echo "  vastai ssh ${INSTANCE_ID} -- tail -f /workspace/nohup.out    # Watch training"
echo "  vastai ssh ${INSTANCE_ID} -- cat /workspace/kicad-vision-lora-adapter/training_progress.json  # Check progress"
echo "  vastai show instances ${INSTANCE_ID}                           # Check cost/time"
echo ""
echo "When training finishes, download the adapter:"
echo "  vastai scp -r ${INSTANCE_ID}:/workspace/kicad-vision-lora-adapter/ ./output/kicad_vision_adapter_vast/"
echo ""
echo "Then destroy the instance to stop billing:"
echo "  vastai destroy instance ${INSTANCE_ID}"
