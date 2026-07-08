#!/usr/bin/env python3
"""Evaluate fine-tuned Gemma 4 12B adapter on spatial benchmark.

Loads the base Gemma model + LoRA adapter, runs the full spatial
benchmark, and compares against baseline scores.

Usage:
    python3 scripts/evaluate_gemma_adapter.py
    python3 scripts/evaluate_gemma_adapter.py --adapter training_output/gemma_sft
    python3 scripts/evaluate_gemma_adapter.py --quick 20
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_GEMMA_MODEL_ID = "ggml-org/gemma-4-12B-it-Q4_K_M"


class GemmaFineTunedAdapter:
    """Gemma 4 12B with a fine-tuned LoRA adapter.

    Extends the base GemmaVisionAdapter pattern with adapter loading.
    Uses mlx-lm's load() with adapter_path for LoRA fusion.
    """

    _SYSTEM_PROMPT = (
        "You are a PCB design expert with vision capabilities. "
        "Analyze the provided PCB render and answer spatial reasoning "
        "questions. For numeric answers, respond with just the number. "
        "For yes/no questions, respond with 'yes' or 'no'. "
        "For fix selection, respond with 'Fix N: <description>'. "
        "For path questions, describe waypoints as (x, y) coordinates."
    )

    def __init__(
        self,
        adapter_dir: Path,
        model_id: str = _GEMMA_MODEL_ID,
        max_tokens: int = 256,
        temperature: float = 0.1,
    ) -> None:
        self._adapter_dir = adapter_dir
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._model: Any = None
        self._tokenizer: Any = None
        self._loaded = False

    @property
    def name(self) -> str:
        return f"Gemma 4 12B Fine-Tuned ({self._adapter_dir})"

    @property
    def supports_vision(self) -> bool:
        return True

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        adapter_path = str(self._adapter_dir) if self._adapter_dir.exists() else None
        from mlx_lm import load

        self._model, self._tokenizer = load(
            self._model_id,
            adapter_path=adapter_path,
        )
        self._loaded = True

    def run_task(self, task: Any) -> str:
        """Run a spatial reasoning task."""
        self._ensure_loaded()

        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": task.question},
        ]

        # Format as Gemma ChatML.
        prompt_parts = []
        for msg in messages:
            prompt_parts.append(f"<start_of_turn>{msg['role']}\n{msg['content']}<end_of_turn>")
        prompt_parts.append("<start_of_turn>model\n")
        prompt = "\n".join(prompt_parts)

        import mlx.core as mx
        from mlx_lm import generate

        if self._temperature > 0:
            def sampler(logits):
                return mx.random.categorical(logits * (1.0 / max(self._temperature, 1e-8)))
        else:
            def sampler(logits):
                return mx.argmax(logits, axis=-1)

        response = generate(
            self._model, self._tokenizer,
            prompt=prompt,
            max_tokens=self._max_tokens,
            sampler=sampler,
            verbose=False,
        )

        # Extract model response.
        marker = "<start_of_turn>model\n"
        if marker in response:
            idx = response.index(marker) + len(marker)
            return response[idx:].strip()
        return response.strip()


def evaluate_adapter(
    adapter_dir: Path,
    seed: int = 42,
    quick: int | None = None,
    output_path: Path | None = None,
) -> Any:
    """Evaluate a fine-tuned adapter on the spatial benchmark.

    Args:
        adapter_dir: Directory containing adapters.safetensors.
        seed: Random seed for task generation.
        quick: If set, only run this many tasks.
        output_path: Optional path to write markdown report.

    Returns:
        BenchmarkReport with results.
    """
    from kicad_agent.analysis.benchmark_runner import BenchmarkRunner
    from kicad_agent.analysis.spatial_benchmark import TaskGenerator

    if not (adapter_dir / "adapters.safetensors").exists():
        raise FileNotFoundError(
            f"Adapter not found at {adapter_dir / 'adapters.safetensors'}. "
            f"Run train_gemma_sft_mlx.py first."
        )

    adapter = GemmaFineTunedAdapter(adapter_dir=adapter_dir)

    # Generate tasks.
    gen = TaskGenerator(seed=seed)
    tasks = gen.generate_all()
    vision_tasks = [t for t in tasks if t.input_type == "vision"]
    if quick is not None:
        vision_tasks = vision_tasks[:quick]

    print(f"Evaluating fine-tuned Gemma on {len(vision_tasks)} vision tasks...")
    runner = BenchmarkRunner(adapters=[adapter], seed=seed)
    report = runner.run(tasks=vision_tasks)

    # Check success criteria.
    criteria = check_success_criteria(report)

    print(f"\n{'=' * 60}")
    print(f"Fine-Tuned Gemma 4 12B Results")
    print(f"{'=' * 60}")
    for score in report.category_scores:
        print(f"  {score.category}: {score.accuracy:.1%}")

    print(f"\nSuccess Criteria:")
    all_pass = True
    for criterion, passed in criteria.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {criterion}: {status}")
        if not passed:
            all_pass = False

    print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILED'}")

    if output_path:
        _write_eval_report(report, criteria, output_path)
        print(f"Report written to {output_path}")

    return report


def check_success_criteria(report: Any) -> dict[str, bool]:
    """Check if the fine-tuned model meets success criteria.

    Args:
        report: BenchmarkReport from evaluation.

    Returns:
        Dict mapping criterion name to pass/fail boolean.
    """
    criteria: dict[str, bool] = {}

    # Overall accuracy >= 70%.
    total_correct = sum(s.correct for s in report.category_scores)
    total_tasks = sum(s.total for s in report.category_scores)
    overall = total_correct / total_tasks if total_tasks > 0 else 0.0
    criteria["overall >= 70%"] = overall >= 0.70

    # Vision categories > 0% (vs Qwen's 0% baseline).
    vision_categories = {
        "routing_feasibility", "clearance_diagnosis",
        "drc_fix_selection", "unrouted_cause",
    }
    for score in report.category_scores:
        if score.category in vision_categories:
            criteria[f"{score.category} > 0%"] = score.accuracy > 0.0

    return criteria


def _write_eval_report(
    report: Any,
    criteria: dict[str, bool],
    path: Path,
) -> None:
    """Write evaluation report to markdown."""
    lines = [
        "# Fine-Tuned Gemma 4 12B Evaluation",
        "",
        "## Results",
        "",
        "| Category | Accuracy | Tasks | Avg Latency |",
        "|----------|----------|-------|-------------|",
    ]
    for score in report.category_scores:
        lines.append(
            f"| {score.category} | {score.accuracy:.1%} | {score.total} | {score.avg_latency_ms:.0f}ms |"
        )

    lines.extend([
        "",
        "## Success Criteria",
        "",
    ])
    for criterion, passed in criteria.items():
        status = "PASS" if passed else "FAIL"
        lines.append(f"- **{criterion}:** {status}")

    lines.extend([
        "",
        f"**Total tasks:** {report.total_tasks}",
        f"**Duration:** {report.total_duration_s:.1f}s",
        "",
    ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate fine-tuned Gemma 4 12B adapter.",
    )
    parser.add_argument("--adapter", type=Path, default=Path("training_output/gemma_sft"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quick", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        evaluate_adapter(
            adapter_dir=args.adapter,
            seed=args.seed,
            quick=args.quick,
            output_path=args.output,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
