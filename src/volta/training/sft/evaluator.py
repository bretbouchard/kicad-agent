"""SFT evaluation: compare base vs fine-tuned model on held-out test data.

Generates chains from test prompts using both base and SFT models,
scores them with the reward model, and produces comparison metrics.

Usage:
    from volta.training.sft.evaluator import (
        evaluate_sft_model,
        compare_base_vs_sft,
    )

    result = compare_base_vs_sft(
        adapter_path="training_output/sft_final",
        test_data_path="training_output/sft_prepared/test.jsonl",
        reward_model_dir="training_output/unified",
    )
"""

from __future__ import annotations

import json
from pathlib import Path

from volta.training.reward_model import RewardModel, predict_reward
from volta.training.sft.templates import SYSTEM_PROMPT_SPATIAL


def generate_chain(
    model,
    tokenizer,
    prompt: str,
    max_new_tokens: int = 512,
) -> str:
    """Generate text from the model given a user prompt.

    Formats the prompt as ChatML (system + user messages), tokenizes,
    generates with sampling, and decodes the output.

    Args:
        model: HuggingFace causal LM model (with or without LoRA adapter).
        tokenizer: Corresponding tokenizer.
        prompt: User prompt text.
        max_new_tokens: Maximum tokens to generate.

    Returns:
        Generated text string (assistant response only).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_SPATIAL},
        {"role": "user", "content": prompt},
    ]

    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    import torch

    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.7,
            do_sample=True,
            top_p=0.9,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode only the generated tokens (skip input)
    generated_ids = outputs[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated_ids, skip_special_tokens=True)


def evaluate_sft_model(
    adapter_path: str | None,
    test_samples: list[dict],
    reward_model_dir: str,
    n_samples: int = 50,
) -> dict:
    """Evaluate a model (base or SFT) on test samples using reward model.

    Args:
        adapter_path: Path to LoRA adapter directory. None for base model only.
        test_samples: List of dicts with "messages" field (system/user/assistant).
        reward_model_dir: Directory with trained reward model.
        n_samples: Number of samples to evaluate.

    Returns:
        Dict with avg_reward, avg_format, avg_quality, avg_accuracy, n_samples,
        and sample_outputs (first 5 for inspection).
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "mps" if torch.backends.mps.is_available() else "cpu"

    # Load base model
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-1.5B-Instruct",
        torch_dtype=torch.float16,
        device_map=device,
    )

    # Load adapter if provided
    if adapter_path is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter_path)

    model.eval()

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")
    tokenizer.pad_token = tokenizer.eos_token

    # Load reward model
    reward_model = RewardModel.load_trained(reward_model_dir)

    # Evaluate
    format_scores: list[float] = []
    quality_scores: list[float] = []
    accuracy_scores: list[float] = []
    sample_outputs: list[dict] = []

    samples_to_eval = test_samples[:n_samples]

    for i, sample in enumerate(samples_to_eval):
        messages = sample.get("messages", [])
        if len(messages) < 2:
            continue

        user_prompt = messages[1]["content"]

        try:
            generated = generate_chain(model, tokenizer, user_prompt, max_new_tokens=512)
        except Exception as e:
            generated = f"Generation error: {e}"

        # Score generated chain
        pred = predict_reward(reward_model, generated)
        format_scores.append(pred.format_score)
        quality_scores.append(pred.quality_score)
        accuracy_scores.append(pred.accuracy_score)

        if i < 5:
            sample_outputs.append({
                "prompt": user_prompt[:200],
                "generated": generated[:500],
                "format_score": pred.format_score,
                "quality_score": pred.quality_score,
                "accuracy_score": pred.accuracy_score,
            })

    n = len(format_scores)
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0

    return {
        "avg_reward": round(avg([((f + q + a) / 3.0) for f, q, a in zip(format_scores, quality_scores, accuracy_scores)]), 6),
        "avg_format": round(avg(format_scores), 6),
        "avg_quality": round(avg(quality_scores), 6),
        "avg_accuracy": round(avg(accuracy_scores), 6),
        "n_samples": n,
        "sample_outputs": sample_outputs,
    }


def compare_base_vs_sft(
    adapter_path: str,
    test_data_path: str,
    reward_model_dir: str,
    n_samples: int = 50,
) -> dict:
    """Compare SFT model against base model on test data.

    Args:
        adapter_path: Path to trained LoRA adapter.
        test_data_path: Path to test JSONL with "messages" field.
        reward_model_dir: Directory with trained reward model.
        n_samples: Number of test samples to evaluate.

    Returns:
        Dict with delta metrics and per-model results.
    """
    # Load test data
    test_samples: list[dict] = []
    with open(test_data_path) as f:
        for line in f:
            line = line.strip()
            if line:
                test_samples.append(json.loads(line))

    # Evaluate SFT model
    sft_results = evaluate_sft_model(
        adapter_path=adapter_path,
        test_samples=test_samples,
        reward_model_dir=reward_model_dir,
        n_samples=n_samples,
    )

    # Evaluate base model (no adapter)
    base_results = evaluate_sft_model(
        adapter_path=None,
        test_samples=test_samples,
        reward_model_dir=reward_model_dir,
        n_samples=n_samples,
    )

    return {
        "delta_reward": round(sft_results["avg_reward"] - base_results["avg_reward"], 6),
        "delta_format": round(sft_results["avg_format"] - base_results["avg_format"], 6),
        "delta_quality": round(sft_results["avg_quality"] - base_results["avg_quality"], 6),
        "delta_accuracy": round(sft_results["avg_accuracy"] - base_results["avg_accuracy"], 6),
        "base_results": base_results,
        "sft_results": sft_results,
    }
