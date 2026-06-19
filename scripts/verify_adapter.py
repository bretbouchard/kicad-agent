#!/usr/bin/env python3
"""Verify a trained KiCad vision LoRA adapter loads and runs locally via mlx-vlm.

Tests cross-platform PEFT compatibility: adapter trained on CUDA (Vast.ai)
loads on Apple Silicon (MPS) via mlx-vlm.

Usage:
    python scripts/verify_adapter.py \
        --adapter-path /Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v1 \
        --test-image training_output/vision_data/images/sample_000000.png

Prerequisites:
    - mlx-vlm installed (pip install mlx-vlm==0.6.3)
    - HF_TOKEN set for gated Gemma 4 model access
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify trained KiCad vision LoRA adapter via mlx-vlm inference.",
    )
    parser.add_argument(
        "--adapter-path",
        type=Path,
        required=True,
        help="Path to trained adapter directory (adapters.safetensors)",
    )
    parser.add_argument(
        "--test-image",
        type=Path,
        required=True,
        help="Path to test image (PNG) for inference",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=(
            "Analyze this PCB layout. What components do you see? "
            "Identify component placement and routing patterns."
        ),
        help="Inference prompt",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Maximum tokens to generate",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default="google/gemma-4-12b-it",
        help="Base model ID (must match training)",
    )
    args = parser.parse_args()

    # Validate paths
    if not args.adapter_path.exists():
        print(f"Error: adapter path not found: {args.adapter_path}", file=sys.stderr)
        return 1
    adapter_weights = args.adapter_path / "adapters.safetensors"
    if not adapter_weights.exists():
        print(f"Error: adapter weights not found: {adapter_weights}", file=sys.stderr)
        return 1
    if not args.test_image.exists():
        print(f"Error: test image not found: {args.test_image}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("KiCad Vision Adapter Verification")
    print("=" * 60)
    print(f"  Adapter: {args.adapter_path}")
    print(f"  Image:   {args.test_image}")
    print(f"  Model:   {args.model_id}")
    print(f"  Prompt:  {args.prompt[:80]}...")
    print()

    # Load model with adapter
    print("Loading model + adapter (this may take a few minutes)...")
    try:
        from mlx_vlm import load, generate
    except ImportError as exc:
        print(f"\nError: mlx-vlm not installed: {exc}", file=sys.stderr)
        print("Install with: pip install mlx-vlm==0.6.3", file=sys.stderr)
        print(
            "Or use spectral-primitives venv:",
            file=sys.stderr,
        )
        print(
            "  /Users/bretbouchard/apps/spectral-primitives/.venv-brew/bin/python3",
            file=sys.stderr,
        )
        return 1

    try:
        model, processor = load(
            str(args.model_id),
            adapter_path=str(args.adapter_path),
        )
    except Exception as exc:
        print(f"\nError loading model: {exc}", file=sys.stderr)
        return 1

    print("Model loaded successfully.")

    # Run inference
    print(f"\nRunning inference on {args.test_image.name}...")
    try:
        output = generate(
            model,
            processor,
            image=str(args.test_image),
            prompt=args.prompt,
            max_tokens=args.max_tokens,
        )
    except Exception as exc:
        print(f"\nError during inference: {exc}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("INFERENCE OUTPUT")
    print("=" * 60)
    print(output)
    print("=" * 60)

    # Check output quality indicators
    has_coordinates = (
        "<point" in output.lower()
        or "x,y" in output.lower()
        or "coordinate" in output.lower()
    )
    has_content = len(output.strip()) > 50

    print(f"\nVerification Results:")
    print(f"  Output length: {len(output)} chars")
    print(f"  Contains coordinate notation: {has_coordinates}")
    print(f"  Meaningful content (>50 chars): {has_content}")

    if has_content:
        print("\nPASS: Adapter loaded and produced output.")
        return 0
    else:
        print("\nWARNING: Output is very short. Adapter may need more training.")
        return 0  # Still return 0 — the adapter loaded, which is the primary check (D-16)


if __name__ == "__main__":
    sys.exit(main())
