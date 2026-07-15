"""Tests for inference confidence scoring (InferenceConfidence).

Task 2 Part A & B of plan 79-05: Confidence scorer for AI outputs and
wiring confidence into ScoredChain/analyze().
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1: compute_confidence returns InferenceConfidence with all fields
# ---------------------------------------------------------------------------


def test_compute_confidence_returns_all_fields() -> None:
    """compute_confidence() returns InferenceConfidence with agreement_ratio,
    score_variance, n_chains, and overall fields."""
    from volta.inference.confidence_scorer import compute_confidence

    result = compute_confidence([0.5, 0.7, 0.6])

    assert hasattr(result, "agreement_ratio")
    assert hasattr(result, "score_variance")
    assert hasattr(result, "n_chains")
    assert hasattr(result, "overall")
    assert result.n_chains == 3
    assert 0.0 <= result.agreement_ratio <= 1.0
    assert 0.0 <= result.overall <= 1.0


# ---------------------------------------------------------------------------
# Test 2: Identical scores -> agreement_ratio=1.0, variance=0.0
# ---------------------------------------------------------------------------


def test_identical_scores_high_agreement() -> None:
    """When all chains score identically, agreement_ratio is 1.0 and variance is 0.0."""
    from volta.inference.confidence_scorer import compute_confidence

    result = compute_confidence([0.8, 0.8, 0.8, 0.8])

    assert result.agreement_ratio == 1.0
    assert result.score_variance == 0.0
    assert result.overall == 1.0


# ---------------------------------------------------------------------------
# Test 3: Different scores -> agreement_ratio < 1.0, variance > 0.0
# ---------------------------------------------------------------------------


def test_different_scores_lower_agreement() -> None:
    """When chains score differently, agreement_ratio < 1.0 and variance > 0.0."""
    from volta.inference.confidence_scorer import compute_confidence

    result = compute_confidence([0.2, 0.5, 0.9])

    assert result.agreement_ratio < 1.0
    assert result.score_variance > 0.0


# ---------------------------------------------------------------------------
# Test 4: Single chain -> agreement_ratio=1.0
# ---------------------------------------------------------------------------


def test_single_chain_high_agreement() -> None:
    """compute_confidence() with single chain returns agreement_ratio=1.0."""
    from volta.inference.confidence_scorer import compute_confidence

    result = compute_confidence([0.75])

    assert result.agreement_ratio == 1.0
    assert result.score_variance == 0.0
    assert result.n_chains == 1


# ---------------------------------------------------------------------------
# Test 5: Empty chains raises ValueError
# ---------------------------------------------------------------------------


def test_empty_chains_raises_value_error() -> None:
    """compute_confidence() with empty list raises ValueError."""
    from volta.inference.confidence_scorer import compute_confidence

    with pytest.raises(ValueError, match="scores"):
        compute_confidence([])


# ---------------------------------------------------------------------------
# Test 6: ScoredChain gains confidence field when analyze() returns
# ---------------------------------------------------------------------------


def test_analyze_returns_confidence(tmp_path: Path) -> None:
    """analyze() attaches InferenceConfidence to the returned ScoredChain."""
    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018) (generator pcbnew))")

    mock_board = MagicMock()
    mock_board.footprints = [MagicMock()]
    mock_board.nets = [MagicMock()]
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    def mock_predict(model, text):
        from volta.training.reward_model import PredictedReward
        return PredictedReward(format_score=0.8, quality_score=0.7, accuracy_score=0.9)

    with patch("volta.parser.pcb_parser.parse_pcb", return_value=mock_result), \
         patch("volta.inference.best_of_n.predict_reward", side_effect=mock_predict), \
         patch("volta.training.reward_model.predict_reward", side_effect=mock_predict):
        from volta.inference.wrapper import InferenceWrapper
        wrapper = InferenceWrapper.__new__(InferenceWrapper)
        wrapper._model_name = "test"
        wrapper._adapter_dir = None
        wrapper._reward_model_dir = Path("/tmp/test")
        wrapper._n_best = 3
        wrapper._max_tokens = 128
        wrapper._temperature = 0.7
        wrapper._device = "cpu"
        wrapper._max_workers = 3
        wrapper._llm_client = MagicMock()
        wrapper._reward_model = MagicMock()
        wrapper._models_loaded = True
        wrapper._knowledge_manager = None

        chain_idx = [0]
        def fake_generate(messages):
            chain_idx[0] += 1
            return f"chain-{chain_idx[0]}", 0.01
        wrapper._generate_chain = fake_generate

        result = wrapper.analyze(pcb_file)

    # ScoredChain should have a confidence field
    assert hasattr(result, "confidence"), "ScoredChain should have confidence field"
    assert result.confidence is not None
    assert result.confidence.n_chains == 3


# ---------------------------------------------------------------------------
# Test 7: ScoredChain confidence field default is None for backward compat
# ---------------------------------------------------------------------------


def test_scored_chain_confidence_default_none() -> None:
    """ScoredChain.confidence defaults to None for backward compatibility."""
    from volta.inference.best_of_n import ScoredChain

    chain = ScoredChain(
        chain_text="test",
        format_score=0.8,
        quality_score=0.7,
        accuracy_score=0.6,
        composite_score=0.7,
    )
    assert chain.confidence is None
