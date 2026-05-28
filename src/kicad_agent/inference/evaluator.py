"""End-to-end evaluation of the inference pipeline.

Runs the full pipeline (PCB parse -> prompt -> N-chain generation ->
reward scoring -> best selection) across test files and produces
an EvaluationReport with aggregate quality metrics.

Usage:
    from kicad_agent.inference.evaluator import run_e2e_evaluation

    report = run_e2e_evaluation(["board1.kicad_pcb", "board2.kicad_pcb"])
    print(report.to_text())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from kicad_agent.inference.best_of_n import ScoredChain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationReport:
    """End-to-end evaluation report for the inference pipeline.

    Attributes:
        n_test_files: Number of test files evaluated.
        avg_latency_s: Mean generation time per chain in seconds.
        avg_composite_score: Mean composite score across all best chains.
        avg_format_score: Mean format score.
        avg_quality_score: Mean quality score.
        avg_accuracy_score: Mean accuracy score.
        best_of_n_improvement: Percentage improvement of best-of-N over
            single-sample mean.
        single_sample_mean: Mean composite score of single-chain generation.
        best_of_n_mean: Mean composite score of best-of-N selection.
        per_file_results: Tuple of per-file evaluation details.
    """

    n_test_files: int
    avg_latency_s: float
    avg_composite_score: float
    avg_format_score: float
    avg_quality_score: float
    avg_accuracy_score: float
    best_of_n_improvement: float  # percentage
    single_sample_mean: float
    best_of_n_mean: float
    per_file_results: tuple[dict, ...]

    def to_text(self) -> str:
        """Human-readable evaluation summary."""
        lines = [
            "=== Inference Pipeline Evaluation Report ===",
            "",
            f"Test files evaluated: {self.n_test_files}",
            f"Average latency: {self.avg_latency_s:.2f}s",
            "",
            "--- Score Averages ---",
            f"  Composite: {self.avg_composite_score:.3f}",
            f"  Format:    {self.avg_format_score:.3f}",
            f"  Quality:   {self.avg_quality_score:.3f}",
            f"  Accuracy:  {self.avg_accuracy_score:.3f}",
            "",
            "--- Best-of-N Improvement ---",
            f"  Single-sample mean: {self.single_sample_mean:.3f}",
            f"  Best-of-N mean:     {self.best_of_n_mean:.3f}",
            f"  Improvement:        {self.best_of_n_improvement:.1f}%",
        ]

        if self.per_file_results:
            lines.append("")
            lines.append("--- Per-File Results ---")
            for i, result in enumerate(self.per_file_results, 1):
                file_name = result.get("file", "unknown")
                score = result.get("composite_score", 0.0)
                latency = result.get("latency_s", 0.0)
                lines.append(
                    f"  {i}. {file_name}: score={score:.3f}, latency={latency:.2f}s"
                )

        return "\n".join(lines)


def run_e2e_evaluation(
    test_files: list[str | Path],
    model: str | None = None,
    adapter_dir: str | Path | None = None,
    reward_model_dir: str | Path | None = None,
    n_best: int = 4,
    n_single: int = 1,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    device: str = "auto",
) -> EvaluationReport:
    """Run end-to-end evaluation on test files.

    For each test file:
      1. Generate 1 chain (single-sample baseline)
      2. Generate N chains and select best (best-of-N)
      3. Compare improvement

    Args:
        test_files: List of .kicad_pcb or .kicad_sch file paths.
        model: Base model identifier.
        adapter_dir: LoRA adapter directory.
        reward_model_dir: Reward model directory.
        n_best: Best-of-N count (default: 4).
        n_single: Single-sample count for baseline (default: 1).
        max_tokens: Max tokens per chain.
        temperature: Sampling temperature.
        device: Device for reward model.

    Returns:
        EvaluationReport with aggregate metrics.
    """
    if not test_files:
        return EvaluationReport(
            n_test_files=0,
            avg_latency_s=0.0,
            avg_composite_score=0.0,
            avg_format_score=0.0,
            avg_quality_score=0.0,
            avg_accuracy_score=0.0,
            best_of_n_improvement=0.0,
            single_sample_mean=0.0,
            best_of_n_mean=0.0,
            per_file_results=(),
        )

    from kicad_agent.inference.wrapper import InferenceWrapper

    single_scores: list[float] = []
    best_scores: list[float] = []
    single_format_scores: list[float] = []
    single_quality_scores: list[float] = []
    single_accuracy_scores: list[float] = []
    best_format_scores: list[float] = []
    best_quality_scores: list[float] = []
    best_accuracy_scores: list[float] = []
    latencies: list[float] = []
    per_file: list[dict] = []

    for file_path in test_files:
        path = Path(file_path)

        # Skip missing files gracefully
        if not path.exists():
            logger.warning("Skipping missing test file: %s", path)
            continue

        # Single-sample baseline
        single_wrapper = InferenceWrapper(
            model=model,
            adapter_dir=adapter_dir,
            reward_model_dir=reward_model_dir,
            n_best=n_single,
            max_tokens=max_tokens,
            temperature=temperature,
            device=device,
        )

        try:
            single_result: ScoredChain = single_wrapper.analyze(str(path))
            single_scores.append(single_result.composite_score)
            single_format_scores.append(single_result.format_score)
            single_quality_scores.append(single_result.quality_score)
            single_accuracy_scores.append(single_result.accuracy_score)
        except Exception as exc:
            logger.warning("Single-sample evaluation failed for %s: %s", path, exc)
            continue

        # Best-of-N evaluation
        best_wrapper = InferenceWrapper(
            model=model,
            adapter_dir=adapter_dir,
            reward_model_dir=reward_model_dir,
            n_best=n_best,
            max_tokens=max_tokens,
            temperature=temperature,
            device=device,
        )

        try:
            best_result: ScoredChain = best_wrapper.analyze(str(path))
            best_scores.append(best_result.composite_score)
            best_format_scores.append(best_result.format_score)
            best_quality_scores.append(best_result.quality_score)
            best_accuracy_scores.append(best_result.accuracy_score)
            latencies.append(best_result.generation_time_s)

            per_file.append({
                "file": str(path),
                "composite_score": best_result.composite_score,
                "format_score": best_result.format_score,
                "quality_score": best_result.quality_score,
                "accuracy_score": best_result.accuracy_score,
                "latency_s": best_result.generation_time_s,
            })
        except Exception as exc:
            logger.warning("Best-of-N evaluation failed for %s: %s", path, exc)
            # Remove the single-sample score too for consistency
            if single_scores:
                single_scores.pop()
                single_format_scores.pop()
                single_quality_scores.pop()
                single_accuracy_scores.pop()

    if not single_scores:
        # No files could be evaluated
        return EvaluationReport(
            n_test_files=0,
            avg_latency_s=0.0,
            avg_composite_score=0.0,
            avg_format_score=0.0,
            avg_quality_score=0.0,
            avg_accuracy_score=0.0,
            best_of_n_improvement=0.0,
            single_sample_mean=0.0,
            best_of_n_mean=0.0,
            per_file_results=(),
        )

    single_mean = sum(single_scores) / len(single_scores)
    best_mean = sum(best_scores) / len(best_scores)

    if single_mean > 0:
        improvement = (best_mean - single_mean) / single_mean * 100.0
    else:
        improvement = 0.0

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    return EvaluationReport(
        n_test_files=len(single_scores),
        avg_latency_s=avg_latency,
        avg_composite_score=sum(best_scores) / len(best_scores),
        avg_format_score=sum(best_format_scores) / len(best_format_scores),
        avg_quality_score=sum(best_quality_scores) / len(best_quality_scores),
        avg_accuracy_score=sum(best_accuracy_scores) / len(best_accuracy_scores),
        best_of_n_improvement=improvement,
        single_sample_mean=single_mean,
        best_of_n_mean=best_mean,
        per_file_results=tuple(per_file),
    )
