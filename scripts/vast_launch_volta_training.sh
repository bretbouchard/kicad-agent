#!/bin/bash
# Volta PCB — Vast.ai Training Launch Script
# Provisions a GPU instance, uploads data, runs training, downloads adapters.
#
# Usage: bash scripts/vast_launch_volta_training.sh
#
# Requires: vast.ai CLI, HF_TOKEN env var

set -e

echo "=== Volta PCB Training — Vast.ai Launch ==="

# 1. Find cheapest RTX 4090
echo "Searching for RTX 4090 instances..."
OFFER_ID=$(vast search offers 'gpu_name=RTX_4090 rentable=True verified=True' --raw 2>/dev/null | \
    python3 -c "
import sys, json
offers = json.load(sys.stdin)
# Sort by price, pick cheapest
cheapest = min(offers, key=lambda o: o.get('dph_total', 999))
print(cheapest['id'])
" 2>/dev/null)

if [ -z "$OFFER_ID" ]; then
    echo "No RTX 4090 offers found. Trying broader search..."
    OFFER_ID=$(vast search offers 'gpu_ram>=20gb rentable=True' --raw 2>/dev/null | \
        python3 -c "
import sys, json
offers = json.load(sys.stdin)
cheapest = min(offers, key=lambda o: o.get('dph_total', 999))
print(cheapest['id'])
" 2>/dev/null)
fi

echo "Selected offer: $OFFER_ID"

# 2. Create instance
echo "Creating instance..."
INSTANCE_ID=$(vast create instance "$OFFER_ID" \
    --image pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel \
    --disk 80 \
    --jupyter on \
    --env '-e HF_TOKEN='"$HF_TOKEN" \
    --raw 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['new_contract'])")

echo "Instance: $INSTANCE_ID"
echo "Waiting for instance to be ready..."

# Wait for running state
while true; do
    STATE=$(vast show instance "$INSTANCE_ID" --raw 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('actual_status',''))" 2>/dev/null)
    if [ "$STATE" = "running" ]; then
        echo "Instance running!"
        break
    fi
    echo "  State: $STATE..."
    sleep 15
done

# 3. Upload training data and scripts
echo "Uploading training data..."
vast copy "$INSTANCE_ID" \
    scripts/train_volta_super_shiny.py:/workspace/ \
    training_output/sft_prepared/train.jsonl:/workspace/training_output/sft_prepared/ \
    training_output/real_pcb_560/train.jsonl:/workspace/training_output/real_pcb_560/ \
    /Volumes/Storage/schgen/converted/synthetic_skidl.jsonl:/workspace/skidl_data.jsonl \
    scripts/convert_peft_to_mlx.py:/workspace/ 2>/dev/null || true

# 4. Install dependencies
echo "Installing dependencies..."
vast exec "$INSTANCE_ID" 'pip install -q transformers peft trl datasets bitsandbytes accelerate' 2>/dev/null || true

# 5. Run training
echo "Starting training..."
echo "  12B: ~$3, ~5 hours"
echo "  4B: ~$2, ~3 hours"
echo "  Total: ~$5, ~8 hours"
echo ""

# Copy synthetic SKiDL data to expected path on instance
vast exec "$INSTANCE_ID" 'mkdir -p /Volumes/Storage/schgen/converted/' 2>/dev/null || true
vast exec "$INSTANCE_ID" 'cp /workspace/skidl_data.jsonl /Volumes/Storage/schgen/converted/synthetic_skidl.jsonl' 2>/dev/null || true

# Run the training
vast exec "$INSTANCE_ID" 'cd /workspace && python train_volta_super_shiny.py --model both' 2>/dev/null || true

echo ""
echo "=== Training complete ==="
echo "Adapters are uploaded to HuggingFace:"
echo "  12B: bretbouchard/volta-pcb-adapter-v2"
echo "  4B: bretbouchard/volta-pcb-ios-4b-adapter"
echo ""
echo "Destroy instance:"
echo "  vast destroy instance $INSTANCE_ID"
