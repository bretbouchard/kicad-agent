"""GRPO training loop using ReST with group-relative advantage weighting.

Phase 21: Formalizes the scripts/train_grpo_mlx.py ReST implementation into
a proper module. The loop generates N chains per sample, scores them with
the reward model, computes group-relative advantages, filters to high-reward
samples, and re-trains the policy via SFT on filtered data.

Usage:
    from kicad_agent.training.grpo_trainer import GRPOLoopTrainer, run_grpo_training
    from kicad_agent.training.grpo_config import GRPOTrainingConfig

    config = GRPOTrainingConfig(n_iterations=3)
    trainer = GRPOLoopTrainer(config)
    weights = trainer.compute_advantage_weights([0.1, 0.3, 0.5, 0.9])
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


class GRPOLoopTrainer:
    """GRPO training loop using ReST with group-relative advantage weighting.

    Training cycle per iteration:
      1. Load policy model (base + current LoRA adapter)
      2. Sample prompts from training data
      3. Generate group_size completions per prompt
      4. Score completions with reward model
      5. Compute group-relative advantages per prompt
      6. Filter to top-K by advantage (PPO-clip weighting)
      7. Apply KL divergence penalty to downweight completions far from reference
      8. Re-train (SFT) on filtered, advantage-weighted data
      9. Save updated adapter
    """

    def __init__(self, config: Any):
        """Initialize GRPO loop trainer.

        Args:
            config: GRPOTrainingConfig instance.
        """
        self.config = config
        self._rng = random.Random(config.seed)

    def compute_advantage_weights(
        self,
        scores: list[float],
        kl_penalty: float = 0.0,
    ) -> list[float]:
        """Compute advantage weights from raw scores with KL penalty.

        Group-relative advantage: (score - mean) / (std + eps)
        Clipped by PPO range: clip(advantage, -clip_range, clip_range)
        KL penalty applied: weight = clip(advantage) - kl_coefficient * kl_penalty

        Args:
            scores: Raw reward scores for a group.
            kl_penalty: KL divergence penalty (same for all in group).

        Returns:
            Advantage weights, one per score.
        """
        eps = 1e-8
        if not scores:
            return []

        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / max(len(scores), 1)
        std = math.sqrt(variance) + eps
        raw_advantages = [(s - mean) / std for s in scores]

        # PPO clip
        clip_range = self.config.clip_range
        clipped = [max(-clip_range, min(clip_range, a)) for a in raw_advantages]

        # KL penalty
        penalized = [a - self.config.kl_coefficient * kl_penalty for a in clipped]

        # Convert to positive weights (shift so minimum is >= 0, then normalize)
        min_weight = min(penalized) if penalized else 0.0
        shifted = [w - min_weight + eps for w in penalized]
        total = sum(shifted)
        if total > eps:
            weights = [w / total * len(scores) for w in shifted]
        else:
            weights = [1.0] * len(scores)
        return weights

    def compute_kl_penalty(
        self,
        policy_logprobs: list[float],
        ref_logprobs: list[float],
    ) -> float:
        """Compute KL divergence between policy and reference distributions.

        KL(p || q) = sum(p * (log(p) - log(q)))

        Args:
            policy_logprobs: Log probabilities from policy model.
            ref_logprobs: Log probabilities from reference model.

        Returns:
            Non-negative KL divergence scalar.
        """
        if not policy_logprobs or not ref_logprobs:
            return 0.0

        kl = 0.0
        for p_lp, r_lp in zip(policy_logprobs, ref_logprobs):
            p_prob = math.exp(p_lp)
            r_prob = math.exp(r_lp)
            if p_prob > 1e-10 and r_prob > 1e-10:
                kl += p_prob * (p_lp - r_lp)
        return max(0.0, kl)

    def filter_by_advantages(
        self,
        prompt_completions: list[dict],
    ) -> list[dict]:
        """Filter completions using advantage-weighted selection.

        For each prompt group, compute advantages and keep top filter_top_k fraction.

        Args:
            prompt_completions: Groups of scored completions per prompt.
                Each dict has 'prompt' and 'completions' (list of {text, score}).

        Returns:
            Filtered list of {messages, advantage_weight} dicts.
        """
        filtered: list[dict] = []
        top_k = self.config.filter_top_k

        for group in prompt_completions:
            completions = group["completions"]
            if not completions:
                continue

            scores = [c["score"] for c in completions]
            weights = self.compute_advantage_weights(scores)

            # Pair completions with their weights and sort by weight descending
            paired = list(zip(completions, weights))
            paired.sort(key=lambda x: x[1], reverse=True)

            # Keep top-K fraction
            keep_n = max(1, int(len(paired) * top_k))
            for comp, weight in paired[:keep_n]:
                # Build ChatML messages
                messages = [
                    {"role": "user", "content": group["prompt"]},
                    {"role": "assistant", "content": comp["text"]},
                ]
                filtered.append({
                    "messages": messages,
                    "advantage_weight": weight,
                })

        return filtered

    @staticmethod
    def build_chatml_prompt(messages: list[dict]) -> str:
        """Format messages as ChatML prompt string for mlx-lm generation.

        Args:
            messages: List of {role, content} dicts.

        Returns:
            ChatML-formatted string.
        """
        parts = []
        for msg in messages:
            parts.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    @staticmethod
    def parse_chatml(text: str) -> list[dict] | None:
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

    def load_prompts(self, data_path: Path, max_prompts: int = 0) -> list[dict]:
        """Load ChatML prompts from JSONL training data.

        Args:
            data_path: Path to JSONL file with ChatML "text" field.
            max_prompts: Maximum prompts to load (0 = all).

        Returns:
            List of {messages, original_response} dicts.
        """
        prompts: list[dict] = []
        with open(data_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                text = record.get("text", "")
                messages = self.parse_chatml(text)
                if messages and len(messages) >= 2:
                    prompt_msgs = [
                        m for m in messages if m["role"] in ("system", "user")
                    ]
                    if len(prompt_msgs) >= 2:
                        prompts.append({
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

    def run_iteration(
        self,
        iteration: int,
        prompts: list[dict],
        current_adapter: str,
    ) -> dict:
        """Execute one GRPO iteration: generate, score, filter, retrain.

        Args:
            iteration: Current iteration number (1-indexed).
            prompts: Sampled prompts for this iteration.
            current_adapter: Path to current LoRA adapter directory.

        Returns:
            Iteration metrics dict.
        """
        # Lazy imports for mlx (not required at module level)
        from kicad_agent.training.reward_model import RewardModel, predict_reward

        config = self.config

        # Load reward model
        reward_model = RewardModel.load_trained(config.reward_model_dir)

        # Load policy model with current adapter
        try:
            import mlx.core as mx
            from mlx_lm import load as mlx_load

            model, tokenizer = mlx_load(config.model_name, adapter_path=current_adapter)
        except ImportError:
            return {
                "iteration": iteration,
                "error": "mlx-lm not available",
                "generated": 0,
                "kept": 0,
            }

        # Generate and score
        filtered_samples: list[dict] = []
        total_generated = 0
        total_kept = 0
        all_scores: list[float] = []

        for prompt_data in prompts:
            prompt_msgs = prompt_data["messages"]
            prompt_str = self.build_chatml_prompt(prompt_msgs)

            # Generate completions (mlx-lm)
            completions = self._generate_completions(
                model, tokenizer, prompt_str,
                n=config.group_size,
                max_tokens=config.max_gen_tokens,
                temperature=config.gen_temperature,
            )

            # Score completions
            scored: list[tuple[str, float]] = []
            for comp in completions:
                if len(comp) < 20:
                    continue
                pred = predict_reward(reward_model, comp)
                score = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
                scored.append((comp, score))
                all_scores.append(score)

            if not scored:
                continue

            total_generated += len(scored)

            # Compute advantage weights
            scores_only = [s for _, s in scored]
            weights = self.compute_advantage_weights(scores_only)

            # Filter top-K by weight
            paired = list(zip(scored, weights))
            paired.sort(key=lambda x: x[1], reverse=True)
            keep_n = max(1, int(len(paired) * config.filter_top_k))

            for (comp, score), weight in paired[:keep_n]:
                messages = list(prompt_msgs) + [
                    {"role": "assistant", "content": comp}
                ]
                filtered_samples.append({
                    "messages": messages,
                    "advantage_weight": weight,
                })
                total_kept += 1

        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

        # Re-train on filtered data
        if filtered_samples:
            self._retrain_on_filtered(
                model, tokenizer, filtered_samples, config, iteration,
            )

        return {
            "iteration": iteration,
            "generated": total_generated,
            "kept": total_kept,
            "avg_score": avg_score,
        }

    @staticmethod
    def _generate_completions(
        model: Any,
        tokenizer: Any,
        prompt_str: str,
        n: int,
        max_tokens: int = 512,
        temperature: float = 0.8,
    ) -> list[str]:
        """Generate N completions for a prompt using mlx-lm.

        Args:
            model: mlx-lm model.
            tokenizer: mlx-lm tokenizer.
            prompt_str: ChatML-formatted prompt string.
            n: Number of completions to generate.
            max_tokens: Maximum tokens per completion.
            temperature: Sampling temperature.

        Returns:
            List of generated completion strings.
        """
        import mlx.core as mx
        from mlx_lm import generate

        def temp_sampler(logits):
            return mx.random.categorical(logits * (1.0 / max(temperature, 1e-8)))

        completions = []
        for _ in range(n):
            response = generate(
                model, tokenizer,
                prompt=prompt_str,
                max_tokens=max_tokens,
                sampler=temp_sampler,
                verbose=False,
            )
            # Extract assistant response
            if "<|im_start|>assistant" in prompt_str:
                prefix = prompt_str.rstrip("<|im_start|>assistant\n")
                assistant_part = response
                if response.startswith(prefix):
                    assistant_part = response[len(prefix):]
                completions.append(assistant_part.strip())
            else:
                completions.append(response.strip())
        return completions

    @staticmethod
    def _retrain_on_filtered(
        model: Any,
        tokenizer: Any,
        filtered_samples: list[dict],
        config: Any,
        iteration: int,
    ) -> None:
        """Re-train model on filtered advantage-weighted data via SFT.

        Args:
            model: mlx-lm model.
            tokenizer: mlx-lm tokenizer.
            filtered_samples: Filtered samples with advantage weights.
            config: GRPOTrainingConfig.
            iteration: Current iteration number.
        """
        import json

        import mlx.core as mx
        from mlx.optimizers import AdamW
        from mlx_lm.tuner import datasets, train as tuner_train
        from mlx_lm.tuner.trainer import TrainingArgs

        iter_output = Path(config.output_dir) / f"iter_{iteration}"
        iter_output.mkdir(parents=True, exist_ok=True)

        # Split for train/val
        import random as _random

        rng = _random.Random(config.seed + iteration)
        samples_copy = list(filtered_samples)
        rng.shuffle(samples_copy)
        val_count = min(50, len(samples_copy) // 10)
        train_samples = samples_copy[val_count:]
        val_samples = samples_copy[:val_count]

        train_dataset = datasets.CacheDataset(
            datasets.ChatDataset(train_samples, tokenizer, mask_prompt=True)
        )
        val_dataset = datasets.CacheDataset(
            datasets.ChatDataset(val_samples, tokenizer, mask_prompt=True)
        )

        training_args = TrainingArgs(
            batch_size=config.batch_size,
            iters=config.sft_iters_per_round,
            val_batches=min(25, max(1, len(val_samples) // config.batch_size)),
            steps_per_report=50,
            steps_per_eval=config.sft_iters_per_round + 1,
            steps_per_save=config.sft_iters_per_round + 1,
            max_seq_length=config.max_seq_length,
            adapter_file=str(iter_output / "adapters.safetensors"),
        )

        optimizer = AdamW(learning_rate=config.learning_rate, weight_decay=0.01)

        model.train()
        tuner_train(
            model=model,
            optimizer=optimizer,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            args=training_args,
        )

        # Save adapter
        adapter_file = iter_output / "adapters.safetensors"
        model.save_weights(str(adapter_file))

        # Save adapter_config.json
        lora_meta = {
            "num_layers": config.lora_layers,
            "lora_parameters": {
                "rank": config.lora_rank,
                "scale": config.lora_scale,
                "dropout": 0.0,
                "keys": [
                    "self_attn.q_proj", "self_attn.k_proj",
                    "self_attn.v_proj", "self_attn.o_proj",
                ],
            },
        }
        with open(iter_output / "adapter_config.json", "w") as f:
            json.dump(lora_meta, f, indent=2)


def run_grpo_training(config: Any = None) -> dict:
    """Run full GRPO training loop.

    Args:
        config: Training configuration. Uses defaults if None.

    Returns:
        Dict with iteration metrics and final adapter path.
    """
    from kicad_agent.training.grpo_config import GRPOTrainingConfig

    if config is None:
        config = GRPOTrainingConfig()

    trainer = GRPOLoopTrainer(config)
    all_metrics: list[dict] = []
    current_adapter = config.adapter_path

    # Load prompts
    prompts = trainer.load_prompts(
        Path(config.train_data_path),
        max_prompts=config.max_prompts_per_iter,
    )

    for iteration in range(1, config.n_iterations + 1):
        iter_prompts = trainer._rng.sample(
            prompts, min(config.max_prompts_per_iter, len(prompts))
        )
        metrics = trainer.run_iteration(
            iteration=iteration,
            prompts=iter_prompts,
            current_adapter=current_adapter,
        )
        all_metrics.append(metrics)

        if "error" not in metrics:
            current_adapter = str(
                Path(config.output_dir) / f"iter_{iteration}"
            )

    return {
        "final_adapter": current_adapter,
        "iteration_metrics": all_metrics,
        "total_iterations": config.n_iterations,
    }
