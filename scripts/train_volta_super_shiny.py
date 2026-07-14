#!/usr/bin/env python3
"""Volta PCB Super Shiny Training — unified 12B + 4B adapter training.

Trains both models on the full combined dataset:
  - 108K SFT prepared (spatial reasoning + PCB analysis)
  - 5.6K SchGen SKiDL pairs (NL→SKiDL code generation)
  - 550 real PCB pairs (real-world circuits)
  Total: ~115K examples

12B adapter (Mac):
  - google/gemma-4-12b-it, rank 64, 3000 steps
  - ~$3 on RTX 4090, ~5 hours
  - Output: ~1GB adapter → bretbouchard/volta-pcb-adapter-v2

4B adapter (iOS/iPad):
  - google/gemma-3-4b-it, rank 32, 2000 steps
  - ~$2 on RTX 4090, ~3 hours
  - Output: ~50MB adapter → bretbouchard/volta-pcb-ios-4b-adapter

Usage on Vast.ai RTX 4090:
  pip install torch transformers peft trl datasets
  python train_volta_super_shiny.py --model 12b
  python train_volta_super_shiny.py --model 4b
  python train_volta_super_shiny.py --model both
"""

import argparse
import inspect
import json
import os
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer, SFTConfig
from datasets import Dataset


def build_sft_config(max_seq_length: int, **kwargs) -> SFTConfig:
    """Build SFTConfig across TRL versions.

    Newer TRL releases renamed max_seq_length to max_length. Keep both paths so
    remote Vast images can use their installed package version without a script
    edit.
    """
    params = dict(kwargs)
    signature = inspect.signature(SFTConfig)
    if "max_length" in signature.parameters:
        params["max_length"] = max_seq_length
    else:
        params["max_seq_length"] = max_seq_length
    return SFTConfig(**params)


def load_combined_dataset() -> Dataset:
    """Load and combine all training data into one unified dataset."""
    rows = []
    sources = {}

    def add_messages(messages_text, source_name):
        if isinstance(messages_text, str):
            import ast
            try:
                msgs = ast.literal_eval(messages_text)
            except:
                msgs = json.loads(messages_text)
        else:
            msgs = messages_text

        text = ""
        for msg in msgs:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                text += f"<|system|>\n{content}\n"
            elif role == "user":
                text += f"<|user|>\n{content}\n"
            elif role == "assistant":
                text += f"<|assistant|>\n{content}\n"
        text += "<|end|>\n"
        rows.append({"text": text, "source": source_name})
        sources[source_name] = sources.get(source_name, 0) + 1

    # 1. SchGen SKiDL pairs (NL → SKiDL) — highest priority for app
    skidl_path = Path("/Volumes/Storage/schgen/converted/synthetic_skidl.jsonl")
    if not skidl_path.exists():
        skidl_path = Path("training_output/sft_prepared/train.jsonl")
    if skidl_path.exists():
        with open(skidl_path) as f:
            for line in f:
                d = json.loads(line.strip())
                add_messages(d.get("messages", "[]"), "skidl_nl")

    # 2. SFT prepared (spatial reasoning + PCB analysis)
    sft_path = Path("training_output/sft_prepared/train.jsonl")
    if sft_path.exists():
        with open(sft_path) as f:
            for line in f:
                d = json.loads(line.strip())
                add_messages(d.get("messages", "[]"), "sft_spatial")

    # 3. Real PCB pairs
    real_path = Path("training_output/real_pcb_560/train.jsonl")
    if real_path.exists():
        with open(real_path) as f:
            for line in f:
                d = json.loads(line.strip())
                add_messages(d.get("messages", "[]"), "real_pcb")

    print(f"\nDataset summary:", flush=True)
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {src}: {count:,} examples", flush=True)
    print(f"  TOTAL: {len(rows):,} examples\n", flush=True)

    return Dataset.from_list(rows)


def train_model(
    model_id: str,
    output_dir: str,
    hub_repo: str,
    lora_rank: int,
    lora_alpha: int,
    max_steps: int,
    max_seq_length: int,
    dataset: Dataset,
):
    """Train one model with LoRA."""
    print(f"\n{'='*60}", flush=True)
    print(f"Training: {model_id}", flush=True)
    print(f"  LoRA rank:  {lora_rank}", flush=True)
    print(f"  LoRA alpha: {lora_alpha}", flush=True)
    print(f"  Max steps:  {max_steps}", flush=True)
    print(f"  Seq length:  {max_seq_length}", flush=True)
    print(f"  Output:     {output_dir}", flush=True)
    print(f"  Hub repo:   {hub_repo}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # Tokenizer
    print("Loading tokenizer...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Model with 4-bit quantization
    print("Loading model (4-bit)...", flush=True)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False

    # LoRA
    print("Applying LoRA...", flush=True)
    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Training config
    config = build_sft_config(
        max_seq_length=max_seq_length,
        output_dir=output_dir,
        num_train_epochs=1,
        # 24GB GPUs (RTX 4090) OOM on the fp32 chunked CE matmul at batch=4,
        # seq=4096. Keep effective batch=16 via grad_accum but reduce peak.
        per_device_train_batch_size=1,
        gradient_accumulation_steps=16,
        learning_rate=2e-4,
        max_steps=max_steps,
        warmup_steps=100,
        logging_steps=10,
        save_steps=500,
        save_total_limit=3,
        bf16=True,
        gradient_checkpointing=True,
        optim="adamw_torch",
        lr_scheduler_type="cosine",
        report_to="none",
        dataset_text_field="text",
    )

    # Trainer
    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=dataset,
        processing_class=tokenizer,
    )

    # Train
    print("\nStarting training...", flush=True)
    start = time.time()
    trainer.train()
    elapsed = time.time() - start

    # Save
    print(f"\nTraining complete in {elapsed/3600:.1f} hours", flush=True)
    trainer.model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # Stats
    if trainer.state.log_history:
        train_loss = trainer.state.log_history[-1].get("train_loss", "?")
        print(f"Final training loss: {train_loss}", flush=True)

    adapter_params = sum(
        p.numel() for n, p in model.named_parameters() if "lora" in n.lower()
    )
    print(f"LoRA parameters: {adapter_params:,} ({adapter_params * 4 / 1024 / 1024:.1f} MB)", flush=True)

    # Upload
    print(f"\nUploading to HuggingFace: {hub_repo}", flush=True)
    trainer.model.push_to_hub(hub_repo)
    tokenizer.push_to_hub(hub_repo)
    print(f"✅ Upload complete: https://huggingface.co/{hub_repo}", flush=True)

    return train_loss


def main():
    parser = argparse.ArgumentParser(description="Volta PCB Super Shiny Training")
    parser.add_argument("--model", choices=["12b", "4b", "both"], default="both",
                        help="Which model to train")
    parser.add_argument("--push_to_hub", action="store_true", default=True,
                        help="Upload adapters to HuggingFace")
    args = parser.parse_args()

    print("=" * 60)
    print("VOLTA PCB — SUPER SHINY TRAINING")
    print("=" * 60)

    # Load combined dataset once
    print("\nLoading combined dataset...", flush=True)
    dataset = load_combined_dataset()

    results = {}

    if args.model in ("12b", "both"):
        loss = train_model(
            model_id="google/gemma-4-12b-it",
            output_dir="output/volta-12b-v2",
            hub_repo="bretbouchard/volta-pcb-adapter-v2",
            lora_rank=64,
            lora_alpha=128,
            max_steps=3000,
            max_seq_length=4096,
            dataset=dataset,
        )
        results["12b"] = loss

    if args.model in ("4b", "both"):
        loss = train_model(
            model_id="google/gemma-3-4b-it",
            output_dir="output/volta-4b-ios",
            hub_repo="bretbouchard/volta-pcb-ios-4b-adapter",
            lora_rank=32,
            lora_alpha=64,
            max_steps=2000,
            max_seq_length=2048,
            dataset=dataset,
        )
        results["4b"] = loss

    print(f"\n{'='*60}")
    print("TRAINING COMPLETE")
    print(f"{'='*60}")
    for model, loss in results.items():
        print(f"  {model}: loss={loss}")

    print("\nNext steps:")
    if "12b" in results:
        print("  12B: Convert to MLX and update ModelDownloader")
        print("    python scripts/convert_peft_to_mlx.py --input output/volta-12b-v2")
    if "4b" in results:
        print("  4B: Convert to MLX and update ModelDownloader")
        print("    python scripts/convert_peft_to_mlx.py --input output/volta-4b-ios")


if __name__ == "__main__":
    main()
