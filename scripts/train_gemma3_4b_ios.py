#!/usr/bin/env python3
"""Gemma 3 4B LoRA training for Volta PCB on iPhone/iPad.

Trains a rank-32 LoRA adapter on the SKiDL + circuit design corpus.
The 4B model is small enough to run on iPhone 15 Pro+ / iPad Pro M-series
(~2.5 GB in 4-bit MLX quantization).

Base model: mlx-community/gemma-3-4b-it-4bit (HuggingFace)
Training data: training_output/sft_prepared/train.jsonl (108K examples)
Output: ~50 MB adapter uploaded to HuggingFace

Usage on Vast.ai RTX 4090:
    pip install torch transformers peft trl datasets
    python train_gemma3_4b_ios.py --max_steps 2000
    python train_gemma3_4b_ios.py --max_steps 2000 --dataset_path /workspace/train.jsonl

Total cost: ~$2 (3 hours on RTX 4090)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainerCallback
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer, SFTConfig
from datasets import Dataset


def load_training_data(path: str) -> Dataset:
    """Load JSONL training data."""
    rows = []
    with open(path) as f:
        for line in f:
            row = json.loads(line.strip())
            # Convert messages list to text format for SFTTrainer
            if "messages" in row:
                messages = row["messages"]
                if isinstance(messages, str):
                    messages = eval(messages)  # JSON-encoded list
                text = ""
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "system":
                        text += f"<|system|>\n{content}\n"
                    elif role == "user":
                        text += f"<|user|>\n{content}\n"
                    elif role == "assistant":
                        text += f"<|assistant|>\n{content}\n"
                text += "<|end|>\n"
                rows.append({"text": text, "source": row.get("source", "")})
            elif "text" in row:
                rows.append(row)

    print(f"Loaded {len(rows)} training examples", flush=True)
    return Dataset.from_list(rows)


def main():
    parser = argparse.ArgumentParser(description="Gemma 3 4B LoRA for Volta PCB iOS")
    parser.add_argument("--model_id", type=str, default="google/gemma-3-4b-it",
                        help="Base model (HuggingFace ID)")
    parser.add_argument("--dataset_path", type=str,
                        default="training_output/sft_prepared/train.jsonl",
                        help="Path to JSONL training data")
    parser.add_argument("--output_dir", type=str, default="output/volta-ios-4b-adapter",
                        help="Output directory for adapter")
    parser.add_argument("--max_steps", type=int, default=2000)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--grad_accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora_rank", type=int, default=32)
    parser.add_argument("--lora_alpha", type=int, default=64)
    parser.add_argument("--push_to_hub", action="store_true",
                        help="Upload adapter to HuggingFace after training")
    parser.add_argument("--hub_repo", type=str, default="bretbouchard/volta-pcb-ios-4b-adapter",
                        help="HuggingFace repo name")
    args = parser.parse_args()

    print("=" * 60)
    print("Volta PCB iOS — Gemma 3 4B LoRA Training")
    print("=" * 60)
    print(f"Base model:    {args.model_id}")
    print(f"Dataset:       {args.dataset_path}")
    print(f"LoRA rank:     {args.lora_rank}")
    print(f"LoRA alpha:    {args.lora_alpha}")
    print(f"Max steps:     {args.max_steps}")
    print(f"Batch size:    {args.batch_size} x {args.grad_accum} accum")
    print(f"Learning rate: {args.lr}")
    print(f"Output:        {args.output_dir}")
    print("=" * 60)

    # Load tokenizer
    print("\nLoading tokenizer...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load model with 4-bit quantization (RTX 4090 has 24GB VRAM)
    print("Loading model with 4-bit quantization...", flush=True)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False

    # Apply LoRA
    print("Applying LoRA adapter...", flush=True)
    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Load training data
    print("\nLoading training data...", flush=True)
    dataset = load_training_data(args.dataset_path)
    print(f"Dataset: {len(dataset)} examples", flush=True)

    # Training config
    sft_config = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=1,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        max_steps=args.max_steps,
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
        max_seq_length=2048,
    )

    # Trainer
    trainer = SFTTrainer(
        model=model,
        args=sft_config,
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
    print("Saving adapter...", flush=True)
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    # Print final stats
    train_loss = trainer.state.log_history[-1].get("train_loss", "?") if trainer.state.log_history else "?"
    print(f"\nFinal training loss: {train_loss}")
    print(f"Adapter saved to: {args.output_dir}")

    # Count adapter parameters
    adapter_params = sum(
        p.numel() for n, p in model.named_parameters()
        if "lora" in n.lower()
    )
    print(f"LoRA parameters: {adapter_params:,} ({adapter_params * 4 / 1024 / 1024:.1f} MB in float32)")

    if args.push_to_hub:
        print(f"\nUploading to HuggingFace: {args.hub_repo}")
        trainer.model.push_to_hub(args.hub_repo)
        tokenizer.push_to_hub(args.hub_repo)
        print(f"Upload complete: https://huggingface.co/{args.hub_repo}")

    print("\n✅ Done. Convert to MLX format and upload for iOS distribution:")
    print(f"   python scripts/convert_peft_to_mlx.py --input {args.output_dir} --output {args.output_dir}_mlx")


if __name__ == "__main__":
    main()
