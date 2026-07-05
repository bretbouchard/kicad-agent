#!/bin/bash
# Launch Vast.ai A100 training for Gemma 4 12B multi-skill adapter.
#
# Usage:
#   bash scripts/training/vast_launch_multiskill.sh
#
# Prerequisites:
#   - vastai CLI installed
#   - HF_TOKEN exported (for gated Gemma access)
#   - Vast credit ($5 minimum)
#   - Dataset at /Volumes/Storage/schgen/unified_v2/manifest.jsonl

set -euo pipefail

# Config
GPU_NAME="${GPU_NAME:-RTX_4090}"  # or A100 for faster training
MAX_PRICE="${MAX_PRICE:-0.40}"
IMAGE="pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel"
DISK=80
MAX_STEPS="${MAX_STEPS:-2000}"
OUTPUT_DIR="/workspace/multiskill_adapter"
MANIFEST="/Volumes/Storage/schgen/unified_v2/manifest.jsonl"
IMAGE_ROOT="/workspace/images"

echo "=== Vast.ai Multi-Skill Training Launch ==="
echo "GPU: $GPU_NAME, Max price: \$$MAX_PRICE/hr, Steps: $MAX_STEPS"
echo ""

# Step 1: Search for instance
echo "[1/7] Searching for $GPU_NAME offers..."
OFFER_JSON=$(vastai search offers "gpu_name=${GPU_NAME} num_gpus=1 dph<${MAX_PRICE} cuda_max_good>=12.0" --limit 5 --raw 2>/dev/null)
OFFER_ID=$(echo "$OFFER_JSON" | python3 -c "
import json, sys
offers = json.load(sys.stdin)
if offers:
    # Pick cheapest
    offers.sort(key=lambda x: x.get('dph_total', 999))
    print(offers[0]['id'])
" 2>/dev/null)

if [ -z "$OFFER_ID" ]; then
    echo "ERROR: No suitable offers found. Try increasing MAX_PRICE."
    exit 1
fi
echo "  Selected offer: $OFFER_ID"

# Step 2: Create instance
echo "[2/7] Creating instance..."
CREATE_OUTPUT=$(vastai create instance "$OFFER_ID" --image "$IMAGE" --disk "$DISK" --ssh --label "kicad-multiskill-train" --raw 2>&1)
INSTANCE_ID=$(echo "$CREATE_OUTPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('new_contract', ''))
except: print('')
" 2>/dev/null)

if [ -z "$INSTANCE_ID" ]; then
    echo "ERROR: Failed to create instance."
    echo "$CREATE_OUTPUT"
    exit 1
fi
echo "  Instance: $INSTANCE_ID"

# Step 3: Wait for ready
echo "[3/7] Waiting for instance to be ready..."
for i in $(seq 1 30); do
    STATUS=$(vastai show instance "$INSTANCE_ID" --raw 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('actual_status', ''))
except: print('')
" 2>/dev/null)
    if [ "$STATUS" = "running" ]; then
        echo "  Ready!"
        break
    fi
    echo "  Status: $STATUS (attempt $i/30)..."
    sleep 10
done

if [ "$STATUS" != "running" ]; then
    echo "ERROR: Instance failed to start."
    exit 1
fi

# Get SSH info
SSH_ADDR=$(vastai show instance "$INSTANCE_ID" --raw 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data.get('public_ipaddr', ''))
" 2>/dev/null)
SSH_PORT=$(vastai show instance "$INSTANCE_ID" --raw 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(int(data.get('ports', {}).get('22/tcp', [{}])[0].get('HostPort', 22)))
" 2>/dev/null)
echo "  SSH: ssh root@${SSH_ADDR} -p ${SSH_PORT}"

# Step 4: Upload files
echo "[4/7] Uploading training script..."
vastai scp "$INSTANCE_ID" scripts/training/vast_train_multiskill.py:/workspace/ 2>/dev/null

echo "[5/7] Uploading dataset manifest..."
vastai scp "$INSTANCE_ID" /Volumes/Storage/schgen/unified_v2/manifest.jsonl:/workspace/manifest.jsonl 2>/dev/null

echo "[6/7] Uploading images (this may take a while)..."
# Upload the image directories
for img_dir in \
    "/Volumes/Storage/schgen/our_corpus/multimodal_data" \
    "/Volumes/Storage/schgen/legibility_data/images" \
    "/Volumes/Storage/schgen/placement_data_v2/images" \
    "/Volumes/Storage/schgen/diagnostic_vision_data/images" \
    "/Volumes/Storage/schgen/strategy_data_v2/images"; do
    if [ -d "$img_dir" ]; then
        echo "  Uploading $(basename $img_dir)..."
        vastai scp -r "$INSTANCE_ID" "$img_dir:/workspace/images/" 2>/dev/null || echo "  (some images may have failed)"
    fi
done

# Step 7: Install deps and launch training
echo "[7/7] Installing deps and launching training..."
vastai ssh "$INSTANCE_ID" -- bash -c "
    pip install -q 'git+https://github.com/huggingface/transformers.git' peft>=0.15.0 bitsandbytes>=0.45.0 accelerate trl==1.5.1 datasets sentencepiece protobuf pillow 2>&1 | tail -5
    echo '=== Starting training ==='
    nohup python3 /workspace/vast_train_multiskill.py \
        --manifest /workspace/manifest.jsonl \
        --image_root /workspace/images \
        --output_dir $OUTPUT_DIR \
        --max_steps $MAX_STEPS \
        --lora_rank 64 \
        --lora_alpha 128 \
        >> /workspace/nohup.out 2>&1 &
    echo 'Training launched. Monitor with:'
    echo '  vastai ssh $INSTANCE_ID -- tail -f /workspace/nohup.out'
    echo '  vastai ssh $INSTANCE_ID -- cat $OUTPUT_DIR/training_progress.json'
"

echo ""
echo "=== LAUNCHED ==="
echo "Instance: $INSTANCE_ID"
echo "Monitor:  vastai ssh $INSTANCE_ID -- tail -f /workspace/nohup.out"
echo "Destroy:  vastai destroy instance $INSTANCE_ID"
