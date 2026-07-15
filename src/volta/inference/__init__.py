"""Inference module -- GRPO model reasoning engine with best-of-N selection.

Usage:
    from volta.inference import generate_analysis, InferenceWrapper

    result = generate_analysis("path/to/board.kicad_pcb")
    print(result.chain_text)
    print(f"Score: {result.composite_score:.3f}")
"""

from __future__ import annotations

from volta.inference.wrapper import InferenceWrapper, generate_analysis
from volta.inference.best_of_n import ScoredChain, best_of_n_select
from volta.inference.evaluator import EvaluationReport, run_e2e_evaluation
from volta.inference.confidence_scorer import InferenceConfidence, compute_confidence

__all__ = [
    "InferenceWrapper",
    "generate_analysis",
    "ScoredChain",
    "best_of_n_select",
    "EvaluationReport",
    "run_e2e_evaluation",
    "InferenceConfidence",
    "compute_confidence",
]
