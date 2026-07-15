"""GRPO evaluation: discrimination test and multi-model comparison.

Phase 21: Evaluates GRPO-trained models against SFT baseline on held-out
test data. Measures discrimination rate (correct vs corrupted chains)
and per-dimension reward scores.

Usage:
    from volta.training.grpo_evaluator import (
        run_discrimination_test,
        compare_sft_vs_grpo,
        evaluate_grpo_model,
    )
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from volta.training.reward_model import RewardModel, predict_reward


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_chatml_prompts(data_path: str, max_prompts: int = 0) -> list[dict]:
    """Load prompts from ChatML JSONL file.

    Args:
        data_path: Path to JSONL file with ChatML "text" field.
        max_prompts: Maximum prompts to load (0 = all).

    Returns:
        List of {prompt, messages, original_response} dicts.
    """
    prompts: list[dict] = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            text = record.get("text", "")
            messages = _parse_chatml(text)
            if messages and len(messages) >= 2:
                prompt_msgs = [
                    m for m in messages if m["role"] in ("system", "user")
                ]
                if len(prompt_msgs) >= 2:
                    prompts.append({
                        "prompt": messages[-2]["content"] if len(messages) >= 2 else "",
                        "messages": prompt_msgs,
                        "original_response": (
                            messages[-1]["content"]
                            if messages[-1]["role"] == "assistant"
                            else ""
                        ),
                    })
    if max_prompts > 0:
        prompts = prompts[:max_prompts]
    return prompts


def _parse_chatml(text: str) -> list[dict] | None:
    """Parse ChatML text into message dicts.

    Args:
        text: ChatML-formatted text.

    Returns:
        List of {role, content} dicts, or None if parsing fails.
    """
    messages = []
    parts = text.split("<|im_start|>")
    for part in parts:
        if not part.strip():
            continue
        role_end = part.find("\n")
        if role_end < 0:
            continue
        role = part[:role_end].strip()
        content = part[role_end + 1:]
        if content.endswith("<|im_end|>"):
            content = content[: -len("<|im_end|>")]
        content = content.strip()
        if role in ("system", "user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages if len(messages) >= 2 else None


def _build_chatml_prompt(messages: list[dict]) -> str:
    """Format messages as ChatML prompt string for generation.

    Args:
        messages: List of {role, content} dicts.

    Returns:
        ChatML-formatted string ending with assistant start tag.
    """
    parts = []
    for msg in messages:
        parts.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def _generate_text_with_adapter(
    model_name: str,
    adapter_path: str,
    prompt_str: str,
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    """Generate text using model with LoRA adapter via mlx-lm.

    Args:
        model_name: Base model identifier.
        adapter_path: Path to LoRA adapter directory.
        prompt_str: ChatML-formatted prompt.
        max_tokens: Maximum generation tokens.
        temperature: Sampling temperature.

    Returns:
        Generated text string.
    """
    import mlx.core as mx
    from mlx_lm import generate, load

    model, tokenizer = load(model_name, adapter_path=adapter_path)

    def temp_sampler(logits):
        return mx.random.categorical(logits * (1.0 / max(temperature, 1e-8)))

    response = generate(
        model, tokenizer,
        prompt=prompt_str,
        max_tokens=max_tokens,
        sampler=temp_sampler,
        verbose=False,
    )
    # Extract assistant part from response
    if response.startswith(prompt_str.rstrip("<|im_start|>assistant\n")):
        return response[len(prompt_str.rstrip("<|im_start|>assistant\n")):].strip()
    return response.strip()


def _corrupt_text(text: str, rng: random.Random) -> str:
    """Apply text-level corruption to a generated completion.

    Strategies:
      - shuffle_sentences: Randomly reorder sentences
      - wrong_coords: Replace <point x,y> references with wrong values
      - remove_sentences: Remove every other sentence

    Args:
        text: Original text to corrupt.
        rng: Random state for deterministic corruption.

    Returns:
        Corrupted text.
    """
    strategy = rng.choice(["shuffle_sentences", "wrong_coords", "remove_sentences"])

    sentences = [s.strip() for s in re.split(r'[.!?]\s+', text) if s.strip()]

    if strategy == "shuffle_sentences" and len(sentences) > 1:
        rng.shuffle(sentences)
        return ". ".join(sentences)

    if strategy == "wrong_coords":
        def _replace_coord(match: re.Match) -> str:
            x = float(match.group(1)) + rng.uniform(-10, 10)
            y = float(match.group(2)) + rng.uniform(-10, 10)
            return f"<point {x:.1f},{y:.1f}>"
        return re.sub(r"<point\s+(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)>", _replace_coord, text)

    if strategy == "remove_sentences" and len(sentences) > 1:
        kept = [s for i, s in enumerate(sentences) if i % 2 == 0]
        return ". ".join(kept) if kept else text

    return text


def _score_text(reward_model: RewardModel, text: str) -> float:
    """Score text with reward model, returning average of three dimensions.

    Args:
        reward_model: Trained reward model.
        text: Text to score.

    Returns:
        Average score across format, quality, accuracy.
    """
    pred = predict_reward(reward_model, text)
    return (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_grpo_model(
    adapter_path: str,
    test_data_path: str,
    reward_model_dir: str,
    model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
    n_samples: int = 50,
) -> dict:
    """Evaluate a GRPO-trained adapter on test data.

    Loads model with adapter, generates completions for test prompts,
    scores with reward model, and returns aggregate metrics.

    Args:
        adapter_path: Path to LoRA adapter directory.
        test_data_path: Path to test ChatML JSONL file.
        reward_model_dir: Path to trained reward model directory.
        model_name: Base model identifier for mlx-lm.
        n_samples: Number of test samples to evaluate.

    Returns:
        Dict with avg_reward, avg_format, avg_quality, avg_accuracy,
        n_samples, sample_outputs.
    """
    reward_model = RewardModel.load_trained(reward_model_dir)
    prompts = _load_chatml_prompts(test_data_path, max_prompts=n_samples)

    format_scores: list[float] = []
    quality_scores: list[float] = []
    accuracy_scores: list[float] = []
    sample_outputs: list[dict] = []

    for prompt_data in prompts:
        prompt_str = _build_chatml_prompt(prompt_data["messages"])
        generated = _generate_text_with_adapter(
            model_name, adapter_path, prompt_str,
            max_tokens=512, temperature=0.7,
        )
        if len(generated) < 10:
            continue

        pred = predict_reward(reward_model, generated)
        format_scores.append(pred.format_score)
        quality_scores.append(pred.quality_score)
        accuracy_scores.append(pred.accuracy_score)
        sample_outputs.append({
            "prompt": prompt_data["prompt"][:100],
            "generated": generated[:200],
            "format": pred.format_score,
            "quality": pred.quality_score,
            "accuracy": pred.accuracy_score,
        })

    n_evaluated = len(format_scores)
    return {
        "avg_reward": (
            (sum(format_scores) + sum(quality_scores) + sum(accuracy_scores)) / (3 * n_evaluated)
            if n_evaluated > 0
            else 0.0
        ),
        "avg_format": sum(format_scores) / n_evaluated if n_evaluated else 0.0,
        "avg_quality": sum(quality_scores) / n_evaluated if n_evaluated else 0.0,
        "avg_accuracy": sum(accuracy_scores) / n_evaluated if n_evaluated else 0.0,
        "n_samples": n_evaluated,
        "sample_outputs": sample_outputs[:5],  # Keep only first 5 for report size
    }


def run_discrimination_test(
    adapter_path: str,
    reward_model_dir: str,
    test_data_path: str,
    model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
    n_samples: int = 50,
) -> dict:
    """Run discrimination test: correct completions vs corrupted versions.

    For each test prompt, generates a completion, scores it, creates a
    corrupted version, scores that, and checks whether the correct version
    scores higher.

    Args:
        adapter_path: Path to LoRA adapter directory.
        reward_model_dir: Path to trained reward model directory.
        test_data_path: Path to test ChatML JSONL file.
        model_name: Base model identifier for mlx-lm.
        n_samples: Number of test samples.

    Returns:
        Dict with discrimination_rate, n_tested, avg_correct_score,
        avg_corrupted_score, gap, per_sample.
    """
    rng = random.Random(42)
    reward_model = RewardModel.load_trained(reward_model_dir)
    prompts = _load_chatml_prompts(test_data_path, max_prompts=n_samples)

    correct_scores: list[float] = []
    corrupted_scores: list[float] = []
    per_sample: list[dict] = []
    n_correct_wins = 0

    for prompt_data in prompts:
        prompt_str = _build_chatml_prompt(prompt_data["messages"])

        # Generate correct completion
        generated = _generate_text_with_adapter(
            model_name, adapter_path, prompt_str,
            max_tokens=512, temperature=0.7,
        )
        if len(generated) < 10:
            continue

        correct_score = _score_text(reward_model, generated)

        # Create corrupted version
        corrupted = _corrupt_text(generated, rng)
        corrupted_score = _score_text(reward_model, corrupted)

        correct_scores.append(correct_score)
        corrupted_scores.append(corrupted_score)

        if correct_score > corrupted_score:
            n_correct_wins += 1

        per_sample.append({
            "correct_score": correct_score,
            "corrupted_score": corrupted_score,
            "correct_wins": correct_score > corrupted_score,
        })

    n_tested = len(correct_scores)
    discrimination_rate = n_correct_wins / n_tested if n_tested > 0 else 0.0
    avg_correct = sum(correct_scores) / n_tested if n_tested else 0.0
    avg_corrupted = sum(corrupted_scores) / n_tested if n_tested else 0.0

    return {
        "discrimination_rate": discrimination_rate,
        "n_tested": n_tested,
        "avg_correct_score": avg_correct,
        "avg_corrupted_score": avg_corrupted,
        "gap": avg_correct - avg_corrupted,
        "per_sample": per_sample[:10],  # Keep only first 10 for report size
    }


def compare_sft_vs_grpo(
    sft_adapter_path: str,
    grpo_adapter_path: str,
    test_data_path: str,
    reward_model_dir: str,
    model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
    n_samples: int = 50,
) -> dict:
    """Compare SFT and GRPO models on test data.

    Evaluates both adapters, runs discrimination test on GRPO model,
    and computes deltas for all reward dimensions.

    Args:
        sft_adapter_path: Path to SFT adapter directory.
        grpo_adapter_path: Path to GRPO adapter directory.
        test_data_path: Path to test ChatML JSONL file.
        reward_model_dir: Path to trained reward model directory.
        model_name: Base model identifier for mlx-lm.
        n_samples: Number of test samples.

    Returns:
        Dict with sft_results, grpo_results, discrimination, delta keys,
        and grpo_wins_all_dimensions boolean.
    """
    sft_results = evaluate_grpo_model(
        adapter_path=sft_adapter_path,
        test_data_path=test_data_path,
        reward_model_dir=reward_model_dir,
        model_name=model_name,
        n_samples=n_samples,
    )

    grpo_results = evaluate_grpo_model(
        adapter_path=grpo_adapter_path,
        test_data_path=test_data_path,
        reward_model_dir=reward_model_dir,
        model_name=model_name,
        n_samples=n_samples,
    )

    discrimination = run_discrimination_test(
        adapter_path=grpo_adapter_path,
        reward_model_dir=reward_model_dir,
        test_data_path=test_data_path,
        model_name=model_name,
        n_samples=n_samples,
    )

    delta_reward = grpo_results["avg_reward"] - sft_results["avg_reward"]
    delta_format = grpo_results["avg_format"] - sft_results["avg_format"]
    delta_quality = grpo_results["avg_quality"] - sft_results["avg_quality"]
    delta_accuracy = grpo_results["avg_accuracy"] - sft_results["avg_accuracy"]

    grpo_wins = (
        delta_reward > 0
        and delta_format > 0
        and delta_quality > 0
        and delta_accuracy > 0
    )

    return {
        "sft_results": sft_results,
        "grpo_results": grpo_results,
        "discrimination": discrimination,
        "delta_reward": delta_reward,
        "delta_format": delta_format,
        "delta_quality": delta_quality,
        "delta_accuracy": delta_accuracy,
        "grpo_wins_all_dimensions": grpo_wins,
    }
