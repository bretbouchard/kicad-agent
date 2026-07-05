#!/usr/bin/env python3
"""Vast.ai training script for Gemma 4 12B multi-skill LoRA.

Reads a JSONL manifest with image PATHS (not inline images) and lazy-loads
images during training. This avoids the 14GB RAM blowup of loading all images
at once.

Manifest format (one JSON per line):
  {
    "system": "...",
    "user": "...",
    "assistant": "...",
    "task_type": "nl_to_skidl_with_image",
    "source_file": "corpus/...",
    "image_paths": ["/workspace/images/foo.png", "/workspace/images/bar.png"],
    "has_images": true
  }

Usage (on Vast instance):
    python3 vast_train_multiskill.py \
        --manifest /workspace/unified_v2/manifest.jsonl \
        --output_dir /workspace/multiskill_adapter \
        --max_steps 2000
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import torch
from torch.utils.data import Dataset
from PIL import Image as PILImage
from transformers import (
    AutoProcessor,
    AutoTokenizer,
    AutoModelForMultimodalLM,
    BitsAndBytesConfig,
)
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer, SFTConfig


class JSONLManifestDataset(Dataset):
    """Lazy-loading dataset from a JSONL manifest with image paths."""

    def __init__(self, manifest_path: str, image_root: str = ""):
        self.image_root = image_root
        self.examples = []
        with open(manifest_path) as f:
            for line in f:
                self.examples.append(json.loads(line))
        print(f"  Loaded {len(self.examples)} examples from manifest", flush=True)

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]

        # Load images lazily
        images = []
        for path in ex.get("image_paths", []):
            full_path = os.path.join(self.image_root, path) if self.image_root else path
            try:
                img = PILImage.open(full_path)
                img.load()
                images.append(img.convert("RGB"))
            except Exception:
                pass  # Skip broken images — text-only fallback

        return {
            "images": images,
            "system": ex.get("system", ""),
            "user": ex.get("user", ""),
            "assistant": ex.get("assistant", ""),
            "task_type": ex.get("task_type", "unknown"),
            "has_images": len(images) > 0,
        }


class MultiskillCollator:
    """Collator that handles both text-only and multimodal examples."""

    def __init__(self, processor, tokenizer, max_seq_length=2048):
        self.processor = processor
        self.tokenizer = tokenizer
        self.max_seq_length = max_seq_length
        # White placeholder for text-only examples
        self._placeholder = None

    def _get_placeholder(self):
        if self._placeholder is None:
            self._placeholder = PILImage.new("RGB", (224, 224), (255, 255, 255))
        return self._placeholder

    def __call__(self, batch):
        processed = []

        for ex in batch:
            system = ex["system"]
            user = ex["user"]
            assistant = ex["assistant"]
            images = ex["images"] if ex["has_images"] else [self._get_placeholder()]

            # Build messages in the format Gemma expects
            messages = [
                {"role": "system", "content": [{"type": "text", "text": system}]},
            ]

            # User message: images first, then text
            user_content = []
            if ex["has_images"]:
                for _ in images:
                    user_content.append({"type": "image"})
            user_content.append({"type": "text", "text": user})
            messages.append({"role": "user", "content": user_content})

            # Assistant message
            messages.append({"role": "assistant", "content": [{"type": "text", "text": assistant}]})

            # Apply chat template
            try:
                text = self.processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=False,
                )
                # Process with images
                result = self.processor(
                    text=text,
                    images=images if ex["has_images"] else [self._get_placeholder()],
                    return_tensors="pt",
                    truncation=True,
                    max_length=self.max_seq_length,
                )
                processed.append(result)
            except Exception as e:
                # Fallback: text-only processing
                try:
                    text = self.processor.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=False,
                    )
                    result = self.processor(
                        text=text,
                        images=[self._get_placeholder()],
                        return_tensors="pt",
                        truncation=True,
                        max_length=self.max_seq_length,
                    )
                    processed.append(result)
                except Exception:
                    pass  # Skip this example

        if not processed:
            # Return empty batch (shouldn't happen)
            return {"input_ids": torch.tensor([[0]]), "labels": torch.tensor([[-100]])}

        # Pad and stack
        input_ids = [p["input_ids"].squeeze(0) for p in processed]
        attention_mask = [p["attention_mask"].squeeze(0) for p in processed]
        pixel_values = [p.get("pixel_values", torch.zeros(1, 3, 224, 224)) for p in processed]

        # Pad to max length in batch
        max_len = max(t.size(0) for t in input_ids)
        padded_ids = []
        padded_mask = []
        labels = []

        for ids, mask in zip(input_ids, attention_mask):
            pad_len = max_len - ids.size(0)
            padded_ids.append(torch.cat([ids, torch.zeros(pad_len, dtype=ids.dtype)]))
            padded_mask.append(torch.cat([mask, torch.zeros(pad_len, dtype=mask.dtype)]))
            # Labels: mask padding with -100
            label = ids.clone()
            label = torch.cat([label, torch.full((pad_len,), -100, dtype=label.dtype)])
            labels.append(label)

        return {
            "input_ids": torch.stack(padded_ids),
            "attention_mask": torch.stack(padded_mask),
            "labels": torch.stack(labels),
            "pixel_values": torch.cat(pixel_values, dim=0)[:len(processed)],
        }


class HeartbeatCallback:
    """Logs training progress periodically."""

    def __init__(self, interval_seconds=300, progress_file="training_progress.json"):
        self.interval = interval_seconds
        self.progress_file = progress_file
        self.last_log = 0

    def __call__(self, args, state, control, **kwargs):
        # This is called via the callback protocol
        pass

    def on_step_end(self, args, state, control, **kwargs):
        now = time.time()
        if now - self.last_log >= self.interval:
            self.last_log = now
            progress = {
                "step": state.global_step,
                "max_steps": state.max_steps,
                "loss": state.log_history[-1].get("loss", "?") if state.log_history else "?",
                "epoch": state.epoch,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            print(f"[heartbeat] {json.dumps(progress)}", flush=True)
            try:
                with open(self.progress_file, "w") as f:
                    json.dump(progress, f, indent=2)
            except Exception:
                pass


def dequantize_vision_encoder(model):
    """Convert 4-bit vision encoder to bfloat16 for training stability."""
    vision_encoder = getattr(model, "embed_vision", None)
    if vision_encoder is None:
        # Try other attribute names
        for attr in dir(model):
            if "vision" in attr.lower() and "embed" in attr.lower():
                vision_encoder = getattr(model, attr)
                break
    if vision_encoder is None:
        print("  WARN: Could not find vision encoder to dequantize", flush=True)
        return

    count = 0
    for module in vision_encoder.modules():
        if hasattr(module, "weight") and hasattr(module.weight, "dequantize"):
            module.weight = torch.nn.Parameter(module.weight.dequantize().to(torch.bfloat16))
            count += 1
    print(f"  Dequantized {count} vision encoder layers", flush=True)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="Path to manifest.jsonl")
    parser.add_argument("--image_root", default="", help="Root dir for relative image paths")
    parser.add_argument("--output_dir", default="/workspace/multiskill_adapter")
    parser.add_argument("--model_id", default="google/gemma-4-12b-it")
    parser.add_argument("--lora_rank", type=int, default=64)
    parser.add_argument("--lora_alpha", type=int, default=128)
    parser.add_argument("--lora_target_modules", nargs="+",
                        default=["q_proj", "k_proj", "v_proj", "o_proj",
                                 "gate_proj", "up_proj", "down_proj"])
    parser.add_argument("--max_steps", type=int, default=2000)
    parser.add_argument("--learning_rate", type=float, default=1e-5)
    parser.add_argument("--batch_size", type=int, default=1)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=8)
    parser.add_argument("--max_seq_length", type=int, default=2048)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--save_steps", type=int, default=100)
    parser.add_argument("--logging_steps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("=" * 60, flush=True)
    print("Gemma 4 12B Multi-Skill Training", flush=True)
    print("=" * 60, flush=True)
    print(f"Manifest:       {args.manifest}", flush=True)
    print(f"Output:         {args.output_dir}", flush=True)
    print(f"LoRA rank:      {args.lora_rank}", flush=True)
    print(f"Max steps:      {args.max_steps}", flush=True)
    print(f"CUDA:           {torch.cuda.is_available()}", flush=True)
    if torch.cuda.is_available():
        print(f"GPU:            {torch.cuda.get_device_name(0)}", flush=True)
    print("=" * 60, flush=True)

    # [1] Processor + tokenizer
    print("\n[1/6] Loading processor...", flush=True)
    hf_token = os.environ.get("HF_TOKEN", "")
    processor = AutoProcessor.from_pretrained(
        args.model_id, trust_remote_code=True, token=hf_token or None,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_id, trust_remote_code=True, token=hf_token or None,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    print("  Done.", flush=True)

    # [2] Model
    print("[2/6] Loading model (4-bit)...", flush=True)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model_id,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        dtype=torch.bfloat16,
        token=hf_token or None,
    )
    dequantize_vision_encoder(model)
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    print("  Done.", flush=True)

    # [3] LoRA
    print("[3/6] Applying LoRA...", flush=True)
    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        target_modules=args.lora_target_modules,
        lora_dropout=0.0,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Trainable: {trainable:,} params", flush=True)

    # [4] Dataset
    print("[4/6] Loading dataset...", flush=True)
    dataset = JSONLManifestDataset(args.manifest, args.image_root)
    print(f"  {len(dataset)} examples", flush=True)

    # [5] Collator
    print("[5/6] Creating collator...", flush=True)
    collator = MultiskillCollator(processor, tokenizer, max_seq_length=args.max_seq_length)
    print("  Done.", flush=True)

    # [6] Train
    print("[6/6] Training...", flush=True)
    os.makedirs(args.output_dir, exist_ok=True)

    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=1,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_steps=int(args.max_steps * args.warmup_ratio),
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=3,
        bf16=True,
        gradient_checkpointing=True,
        optim="adamw_torch_fused",
        report_to="none",
        seed=args.seed,
        remove_unused_columns=False,
        dataset_kwargs={"skip_prepare_dataset": True},
        max_length=args.max_seq_length,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=collator,
        processing_class=processor,
    )

    train_result = trainer.train()

    # Save
    print(f"\n{'='*60}", flush=True)
    print(f"TRAINING COMPLETE", flush=True)
    print(f"  Steps: {train_result.global_step}", flush=True)
    print(f"  Loss:  {train_result.training_loss:.6f}", flush=True)
    print(f"{'='*60}", flush=True)

    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"Adapter saved to: {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
