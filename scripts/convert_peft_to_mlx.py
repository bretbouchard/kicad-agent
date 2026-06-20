#!/usr/bin/env python3
"""Convert a PEFT LoRA adapter (trained with PyTorch/CUDA) to mlx-vlm format.

Converts adapter_model.safetensors (PEFT) to adapters.safetensors (mlx) and
rewrites adapter_config.json with mlx-compatible fields.

Usage:
    python scripts/convert_peft_to_mlx.py \
        --input /Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v1 \
        --output /Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v1-mlx

The adapter trained on Vast.ai (CUDA/PEFT) uses:
  - adapter_model.safetensors with keys like:
    base_model.model.model.language_model.layers.{i}.self_attn.{proj}.lora_A.weight
    base_model.model.model.language_model.layers.{i}.mlp.{proj}.lora_A.weight  (V2+)
  - adapter_config.json with PEFT fields (peft_type, r, lora_alpha, target_modules)

mlx-vlm expects:
  - adapters.safetensors with keys like:
    layers.{i}.self_attn.{proj}.lora_a / lora_b
    layers.{i}.mlp.{proj}.lora_a / lora_b  (V2+)
  - adapter_config.json with mlx fields (fine_tune_type, num_layers, lora_parameters)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import mlx.core as mx
    import numpy as np
except ImportError:
    print("Error: mlx not installed. pip install mlx", file=sys.stderr)
    sys.exit(1)


def convert_weights(input_path: Path, output_path: Path) -> dict[str, list[str]]:
    """Convert PEFT weights to mlx format using numpy (no torch needed).

    PEFT key pattern:
      base_model.model.model.language_model.layers.{N}.self_attn.{proj}.lora_A.weight
      base_model.model.model.language_model.layers.{N}.mlp.{proj}.lora_A.weight  (V2+)

    mlx key pattern:
      layers.{N}.self_attn.{proj}.lora_a
      layers.{N}.mlp.{proj}.lora_a  (V2+)

    Shape differences:
      PEFT lora_A: (r, in_dims)  -> mlx lora_a: (in_dims, r)  [transposed]
      PEFT lora_B: (out_dims, r)  -> mlx lora_b: (r, out_dims) [same]
    """
    src_file = input_path / "adapter_model.safetensors"
    if not src_file.exists():
        src_file = input_path / "adapters.safetensors"
    if not src_file.exists():
        print(f"Error: No adapter weights found in {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load weights using torch (handles bfloat16) then convert to numpy
    from safetensors.torch import load_file as load_torch_safetensors
    torch_weights = load_torch_safetensors(str(src_file))

    numpy_weights = {}
    target_modules = set()

    for key, tensor in torch_weights.items():
        # Convert to float32 numpy array (handles bfloat16 via torch)
        tensor = tensor.float().detach().cpu().numpy()
        # Parse PEFT key — handle both self_attn and mlp modules
        m = re.match(
            r"base_model\.model\.model\.language_model\.layers\.(\d+)\.(\w+)\.(\w+)\.lora_([AB])\.weight",
            key,
        )
        if not m:
            print(f"  Skipping unexpected key: {key}", file=sys.stderr)
            continue

        layer_num = int(m.group(1))
        block = m.group(2)  # "self_attn" or "mlp"
        proj = m.group(3)
        ab = m.group(4).lower()  # 'a' or 'b'
        target_modules.add(proj)

        # Build mlx key
        mlx_key = f"layers.{layer_num}.{block}.{proj}.lora_{ab}"

        # Convert: lora_A needs transpose (PEFT is (r, in), mlx is (in, r))
        if ab == "a":
            tensor = tensor.T

        numpy_weights[mlx_key] = tensor

    # Save using numpy safetensors backend
    from safetensors.numpy import save_file as save_numpy_safetensors
    out_file = output_path / "adapters.safetensors"
    save_numpy_safetensors(numpy_weights, str(out_file))

    print(f"  Converted {len(numpy_weights)} weights -> {out_file}")
    return {"target_modules": sorted(target_modules), "num_keys": len(numpy_weights)}


def convert_config(input_path: Path, output_path: Path, weight_info: dict) -> None:
    """Read PEFT config, write mlx config."""
    src = input_path / "adapter_config.json"
    with open(src) as f:
        peft_config = json.load(f)

    r = peft_config.get("r", 16)
    alpha = peft_config.get("lora_alpha", 32)
    scale = alpha / r if r > 0 else 1.0
    target_modules = peft_config.get("target_modules", ["q_proj", "k_proj", "v_proj", "o_proj"])
    num_layers = 48  # Gemma 4 12B has 48 transformer layers

    mlx_config = {
        "fine_tune_type": "lora",
        "num_layers": num_layers,
        "lora_parameters": {
            "rank": r,
            "scale": scale,
            "dropout": peft_config.get("lora_dropout", 0.0),
            "keys": target_modules,
        },
        "base_model_name_or_path": peft_config.get("base_model_name_or_path", "google/gemma-4-12b-it"),
        "peft_type": "LORA",
        "r": r,
        "lora_alpha": alpha,
        "target_modules": target_modules,
        "task_type": "CAUSAL_LM",
    }

    out_file = output_path / "adapter_config.json"
    with open(out_file, "w") as f:
        json.dump(mlx_config, f, indent=2)

    print(f"  Config: rank={r}, alpha={alpha}, scale={scale}, layers={num_layers}")
    print(f"  Saved: {out_file}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert PEFT LoRA adapter to mlx-vlm format.")
    parser.add_argument("--input", type=Path, required=True, help="Input PEFT adapter directory")
    parser.add_argument("--output", type=Path, required=True, help="Output mlx adapter directory")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input path not found: {args.input}", file=sys.stderr)
        return 1

    print(f"Converting PEFT adapter -> mlx format")
    print(f"  Input:  {args.input}")
    print(f"  Output: {args.output}")

    args.output.mkdir(parents=True, exist_ok=True)

    weight_info = convert_weights(args.input, args.output)
    convert_config(args.input, args.output, weight_info)

    print("\nDone. Verify with:")
    print(f"  python scripts/verify_adapter.py --adapter-path {args.output} --test-image <image.png>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
