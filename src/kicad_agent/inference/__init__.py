"""Inference module -- GRPO model reasoning engine with best-of-N selection.

Usage:
    from kicad_agent.inference import generate_analysis, InferenceWrapper

    result = generate_analysis("path/to/board.kicad_pcb")
    print(result.chain_text)
    print(f"Score: {result.composite_score:.3f}")
"""

from __future__ import annotations

from kicad_agent.inference.wrapper import InferenceWrapper, generate_analysis
from kicad_agent.inference.best_of_n import ScoredChain, best_of_n_select
from kicad_agent.inference.evaluator import EvaluationReport, run_e2e_evaluation
from kicad_agent.inference.confidence_scorer import InferenceConfidence, compute_confidence

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
