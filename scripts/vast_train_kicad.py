#!/usr/bin/env python3
"""Standalone Gemma 4 12B LoRA training script for KiCad vision (Vast.ai / CUDA).

Trains on unified KiCad vision dataset (maze spatial reasoning + PCB analysis).
Adapted from spectral-primitives vast_train_gemma4.py.

Usage:
    python vast_train_kicad.py --dataset_path /workspace/unified_vision_data/train
    python vast_train_kicad.py --dataset_path /workspace/unified_vision_data/train --max_steps 400

Environment:
    HF_TOKEN — HuggingFace token for gated model access (optional but recommended)
"""

import argparse
import glob
import json
import os
import shutil
import sys
import time
from pathlib import Path

import torch
from transformers import (
    AutoModelForMultimodalLM,
    AutoProcessor,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainerCallback,
)
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer, SFTConfig
from datasets import load_from_disk


class HeartbeatCallback(TrainerCallback):
    """Periodic progress logging for long training runs."""

    def __init__(self, interval_seconds: int = 300, progress_file: str | None = None):
        self.interval = interval_seconds
        self.progress_file = progress_file
        self._last_print = time.time()
        self._start_time = time.time()
        self._last_loss: float | None = None

    def on_log(self, args, state, control, logs=None, **kwargs):
        self._last_loss = logs.get("loss") if logs else self._last_loss
        now = time.time()
        if now - self._last_print >= self.interval:
            elapsed = now - self._start_time
            steps_done = state.global_step
            steps_total = state.max_steps
            pct = 100 * steps_done / steps_total if steps_total else 0
            eta = (elapsed / steps_done) * (steps_total - steps_done) if steps_done > 0 else 0
            loss_str = f"{self._last_loss:.4f}" if self._last_loss else "N/A"
            print(
                f"\n[HEARTBEAT] step {steps_done}/{steps_total} ({pct:.0f}%) | "
                f"loss: {loss_str} | elapsed: {elapsed / 3600:.1f}h | ETA: {eta / 3600:.1f}h",
                flush=True,
            )
            if self.progress_file:
                data = {
                    "global_step": steps_done,
                    "max_steps": steps_total,
                    "loss": self._last_loss,
                    "elapsed_s": elapsed,
                    "eta_s": eta,
                    "pct": round(pct, 1),
                    "timestamp": time.time(),
                }
                tmp = self.progress_file + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self.progress_file)
            self._last_print = now


def dequantize_vision_encoder(model):
    """Dequantize vision encoder from 4-bit to bfloat16 for stable training."""
    base = model
    while hasattr(base, "module"):
        base = base.module

    vision = None
    if hasattr(base, "model") and hasattr(base.model, "embed_vision"):
        vision = base.model.embed_vision
    elif hasattr(base, "embed_vision"):
        vision = base.embed_vision

    if vision is None:
        print("WARNING: Could not find embed_vision module — skipping dequantize", flush=True)
        return

    count = 0
    for name, module in vision.named_modules():
        if isinstance(module, torch.nn.Linear) and hasattr(module.weight, "dequantize"):
            module.weight = torch.nn.Parameter(module.weight.dequantize())
            count += 1
    print(f"Dequantized {count} vision encoder linear layer(s) to bfloat16", flush=True)


class Gemma4VisionCollator:
    """Custom data collator for Gemma 4 multimodal SFT."""

    def __init__(self, processor, max_seq_length=2048, compute_dtype=torch.bfloat16):
        self.processor = processor
        self.max_seq_length = max_seq_length
        self.compute_dtype = compute_dtype

    @staticmethod
    def _to_row_format(examples):
        if isinstance(examples, dict):
            keys = list(examples.keys())
            n_rows = len(examples[keys[0]])
            return [{k: examples[k][i] for k in keys} for i in range(n_rows)]
        return examples

    def __call__(self, examples):
        examples = self._to_row_format(examples)
        texts, images_per_sample = [], []
        from PIL import Image as PILImage
        for ex in examples:
            # Carry ALL images for this sample (not just images[0]).
            # Multimodal examples may have multiple images (e.g. SCH + PCB).
            sample_images = []
            for img in ex.get("images", []):
                if img is None:
                    continue
                if img.mode != "RGB":
                    img = img.convert("RGB")
                sample_images.append(img)

            # Phase 106: text-only rows have empty images. Inject a small white
            # placeholder AND add an <|image|> token to the first user message
            # so the processor doesn't raise "0 image tokens, 1 image" mismatch.
            text_only_inject = not sample_images
            if text_only_inject:
                sample_images = [PILImage.new("RGB", (224, 224), (255, 255, 255))]
            images_per_sample.append(sample_images)

            template_messages = []
            user_msg_idx = 0
            img_idx = 0
            for msg in ex["messages"]:
                template_content = []
                has_image_part = False
                for part in msg.get("content", []):
                    if part.get("type") == "image":
                        # Use next available image (cycle if more tokens than images)
                        url = sample_images[img_idx % len(sample_images)] if sample_images else None
                        if url is not None:
                            template_content.append({"type": "image", "url": url})
                            img_idx += 1
                            has_image_part = True
                    elif part.get("type") == "text":
                        template_content.append({"type": "text", "text": part["text"]})
                # Text-only injection: add image token to first user message
                if (text_only_inject
                        and not has_image_part
                        and msg["role"] == "user"
                        and user_msg_idx == 0):
                    template_content.insert(0, {"type": "image", "url": sample_images[0]})
                if msg["role"] == "user":
                    user_msg_idx += 1
                template_messages.append({"role": msg["role"], "content": template_content})

            text = self.processor.apply_chat_template(
                template_messages, tokenize=False, add_generation_prompt=False
            )
            texts.append(text)

        batch = self.processor(
            text=texts,
            images=images_per_sample,
            padding=True,
            truncation=True,
            max_length=self.max_seq_length,
            return_tensors="pt",
        )
        if "pixel_values" in batch and batch["pixel_values"].dtype != self.compute_dtype:
            batch["pixel_values"] = batch["pixel_values"].to(self.compute_dtype)
        batch["labels"] = batch["input_ids"].clone()
        return batch


def find_latest_checkpoint(output_dir: str) -> str | None:
    """Find the checkpoint directory with the highest step number."""
    checkpoints = glob.glob(os.path.join(output_dir, "checkpoint-*"))
    if not checkpoints:
        return None
    best, best_step = None, -1
    for cp in checkpoints:
        try:
            step = int(cp.split("checkpoint-")[-1])
            if step > best_step:
                best_step, best = step, cp
        except ValueError:
            continue
    return best


def main():
    p = argparse.ArgumentParser(description="Gemma 4 LoRA training for KiCad vision (Vast.ai / CUDA)")
    p.add_argument("--dataset_path", type=str, required=True,
                   help="Path to unified KiCad vision dataset (HuggingFace save_to_disk format)")
    p.add_argument("--output_dir", type=str, default="/workspace/kicad-vision-lora-adapter",
                   help="Output directory for adapter checkpoints")
    p.add_argument("--model_id", type=str, default="google/gemma-4-12b-it",
                   help="HuggingFace model ID")
    p.add_argument("--lora_rank", type=int, default=16)
    p.add_argument("--lora_alpha", type=int, default=32)
    p.add_argument("--lora_target_modules", nargs="+",
                   default=["q_proj", "k_proj", "v_proj", "o_proj"])
    p.add_argument("--max_steps", type=int, default=400)
    p.add_argument("--learning_rate", type=float, default=1e-5)
    p.add_argument("--batch_size", type=int, default=1)
    p.add_argument("--gradient_accumulation_steps", type=int, default=8)
    p.add_argument("--max_seq_length", type=int, default=2048)
    p.add_argument("--warmup_ratio", type=float, default=0.1)
    p.add_argument("--logging_steps", type=int, default=5)
    p.add_argument("--save_steps", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--heartbeat_interval", type=int, default=300)
    args = p.parse_args()

    effective_batch = args.batch_size * args.gradient_accumulation_steps
    hf_token = os.environ.get("HF_TOKEN", "")

    print("=" * 60, flush=True)
    print("GEMMA 4 LORA TRAINING — Vast.ai / CUDA", flush=True)
    print("=" * 60, flush=True)
    print(f"Model:          {args.model_id}", flush=True)
    print(f"Steps:          {args.max_steps}", flush=True)
    print(f"Effective batch: {effective_batch} ({args.batch_size} x {args.gradient_accumulation_steps})", flush=True)
    print(f"LoRA rank:      {args.lora_rank}", flush=True)
    print(f"Output:         {args.output_dir}", flush=True)
    print(f"HF_TOKEN:       {'configured' if hf_token else 'NOT SET — gated models may fail'}", flush=True)
    print(f"CUDA available: {torch.cuda.is_available()}", flush=True)
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            mem = getattr(props, "total_memory", getattr(props, "total_mem", 0)) / 1e9
            print(f"  GPU {i}: {torch.cuda.get_device_name(i)} ({mem:.1f} GB)", flush=True)
    print("=" * 60, flush=True)

    # GPU guard
    if not torch.cuda.is_available():
        print("ERROR: No CUDA GPU detected!", flush=True)
        sys.exit(1)

    # [1/7] Processor + tokenizer
    print("\n[1/7] Loading processor + tokenizer...", flush=True)
    processor = AutoProcessor.from_pretrained(
        args.model_id, trust_remote_code=True, token=hf_token or None
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_id, trust_remote_code=True, token=hf_token or None
    )
    pt = getattr(processor, "tokenizer", None)
    if pt is None:
        processor.tokenizer = tokenizer
    else:
        tokenizer = pt
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    print("  Done.", flush=True)

    # [2/7] Model
    print("[2/7] Loading model (4-bit quantization)...", flush=True)
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
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"  Params: {total:,} | Trainable: {trainable:,} ({100 * trainable / total:.4f}%)", flush=True)

    # [3/7] LoRA
    print("[3/7] Applying LoRA...", flush=True)
    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        target_modules=args.lora_target_modules,
        lora_dropout=0.0,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    trainable_after = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  LoRA trainable: {trainable_after:,}", flush=True)

    # [4/7] Dataset
    print("[4/7] Loading dataset...", flush=True)
    ds_path = Path(args.dataset_path)
    # Three modes: local arrow dir, local parquet files, or HF Hub path
    if ds_path.is_dir() and (ds_path / "dataset_info.json").exists():
        dataset = load_from_disk(str(ds_path))
        if hasattr(dataset, "get"):
            dataset = dataset.get("train", dataset)
    elif ds_path.is_dir() and any(ds_path.glob("*.parquet")):
        # Local parquet directory
        from datasets import load_dataset
        print(f"  Loading local parquet from: {ds_path}", flush=True)
        dataset = load_dataset("parquet", data_files=str(ds_path / "*.parquet"), split="train")
    elif "/" in args.dataset_path and not ds_path.exists():
        from datasets import load_dataset
        print(f"  Loading from HF Hub: {args.dataset_path}", flush=True)
        dataset = load_dataset(args.dataset_path, token=os.environ.get("HF_TOKEN"))
        if hasattr(dataset, "get"):
            dataset = dataset.get("train", dataset)
    else:
        if not ds_path.exists():
            print(f"ERROR: Dataset not found at {args.dataset_path}", flush=True)
            sys.exit(1)
        dataset = load_from_disk(str(ds_path))
        if hasattr(dataset, "get"):
            dataset = dataset.get("train", dataset)
        if not ds_path.exists():
            print(f"ERROR: Dataset not found at {args.dataset_path}", flush=True)
            sys.exit(1)
        dataset = load_from_disk(str(ds_path))
        if hasattr(dataset, "get"):
            dataset = dataset.get("train", dataset)
    print(f"  Samples: {len(dataset)}", flush=True)

    # [5/7] Collator
    print("[5/7] Creating collator...", flush=True)
    collator = Gemma4VisionCollator(processor, max_seq_length=args.max_seq_length)
    test_batch = collator(dataset[:2])
    print(f"  Test batch OK — input_ids: {test_batch['input_ids'].shape}", flush=True)

    # [6/7] Trainer
    print("[6/7] Creating trainer...", flush=True)
    checkpoint = find_latest_checkpoint(args.output_dir)
    if checkpoint:
        print(f"  RESUMING from {checkpoint}", flush=True)
    else:
        print("  Starting fresh", flush=True)

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
        save_total_limit=2,
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
        callbacks=[
            HeartbeatCallback(
                interval_seconds=args.heartbeat_interval,
                progress_file=os.path.join(args.output_dir, "training_progress.json"),
            )
        ],
    )

    # [7/7] Train
    print(f"\n[7/7] Training — {args.max_steps} steps, heartbeat every {args.heartbeat_interval}s", flush=True)
    train_result = trainer.train(resume_from_checkpoint=checkpoint)

    print(f"\n{'=' * 60}", flush=True)
    print(f"TRAINING COMPLETE", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"  Steps:    {train_result.global_step}", flush=True)
    print(f"  Loss:     {train_result.training_loss:.6f}", flush=True)

    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"  Adapter saved to: {args.output_dir}", flush=True)

    # Verify saved files
    adapter_files = list(Path(args.output_dir).glob("adapter_*"))
    print(f"  Files: {len(adapter_files)}", flush=True)
    for f in sorted(adapter_files):
        size_mb = f.stat().st_size / 1e6
        print(f"    {f.name}: {size_mb:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
