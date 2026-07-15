"""Tests for parallel chain generation in InferenceWrapper.

Task 1 of plan 79-05: Parallel inference, confidence scoring, and real-world
training data support.

RED phase -- these tests define the expected behavior. They will fail until
the implementation is added in GREEN phase.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from concurrent.futures import ThreadPoolExecutor

import pytest

from volta.inference.best_of_n import ScoredChain


def _make_wrapper(n_best: int = 4, max_workers: int = 4) -> "InferenceWrapper":
    """Create an InferenceWrapper with mocked internals for testing."""
    from volta.inference.wrapper import InferenceWrapper

    wrapper = InferenceWrapper.__new__(InferenceWrapper)
    wrapper._model_name = "test-model"
    wrapper._adapter_dir = None
    wrapper._reward_model_dir = Path("/tmp/test-reward")
    wrapper._n_best = n_best
    wrapper._max_tokens = 128
    wrapper._temperature = 0.7
    wrapper._device = "cpu"
    wrapper._max_workers = max_workers
    wrapper._llm_client = MagicMock()
    wrapper._reward_model = MagicMock()
    wrapper._models_loaded = True
    wrapper._knowledge_manager = None
    return wrapper


def _make_pcb_file(tmp_path: Path) -> Path:
    """Create a minimal .kicad_pcb file and mock the parser."""
    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018) (generator pcbnew))")
    return pcb_file


# ---------------------------------------------------------------------------
# Test 1: Parallel completion faster than sequential
# ---------------------------------------------------------------------------


def test_parallel_completion_faster_than_sequential(tmp_path: Path) -> None:
    """analyze() with n_best=4 completes faster than 4x single chain time."""
    pcb_file = _make_pcb_file(tmp_path)
    wrapper = _make_wrapper(n_best=4, max_workers=4)

    chain_delay = 0.1  # 100ms per chain

    def slow_generate(messages):
        time.sleep(chain_delay)
        return f"chain-{threading.current_thread().ident}", chain_delay

    wrapper._generate_chain = slow_generate

    # Mock the parser
    mock_board = MagicMock()
    mock_board.footprints = [MagicMock()]
    mock_board.nets = [MagicMock()]
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    # Mock reward model scoring
    from volta.training.reward_model import PredictedReward
    wrapper._reward_model = MagicMock()
    wrapper._llm_client = MagicMock()

    def mock_predict(model, text):
        return PredictedReward(format_score=0.8, quality_score=0.7, accuracy_score=0.9)

    with patch("volta.parser.pcb_parser.parse_pcb", return_value=mock_result), \
         patch("volta.inference.best_of_n.predict_reward", side_effect=mock_predict), \
         patch("volta.training.reward_model.predict_reward", side_effect=mock_predict):
        start = time.monotonic()
        result = wrapper.analyze(pcb_file)
        elapsed = time.monotonic() - start

    # Parallel should be significantly faster than 4 * 0.1s = 0.4s sequential
    # Allow generous margin -- parallel should be under 0.3s
    assert elapsed < 0.35, f"Parallel took {elapsed:.2f}s, expected < 0.35s"
    assert isinstance(result, ScoredChain)


# ---------------------------------------------------------------------------
# Test 2: All N chains generated
# ---------------------------------------------------------------------------


def test_all_n_chains_generated(tmp_path: Path) -> None:
    """analyze() generates exactly n_best chains."""
    pcb_file = _make_pcb_file(tmp_path)
    wrapper = _make_wrapper(n_best=4, max_workers=4)

    generated_chains: list[str] = []

    def tracking_generate(messages):
        chain = f"chain-{len(generated_chains)}"
        generated_chains.append(chain)
        return chain, 0.01

    wrapper._generate_chain = tracking_generate

    mock_board = MagicMock()
    mock_board.footprints = []
    mock_board.nets = []
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    def mock_predict(model, text):
        return MagicMock(format_score=0.7, quality_score=0.7, accuracy_score=0.7)

    with patch("volta.parser.pcb_parser.parse_pcb", return_value=mock_result), \
         patch("volta.inference.best_of_n.predict_reward", side_effect=mock_predict), \
         patch("volta.training.reward_model.predict_reward", side_effect=mock_predict):
        wrapper.analyze(pcb_file)

    assert len(generated_chains) == 4, f"Expected 4 chains, got {len(generated_chains)}"


# ---------------------------------------------------------------------------
# Test 3: Best-of-N returns highest composite score
# ---------------------------------------------------------------------------


def test_best_of_n_returns_highest_score(tmp_path: Path) -> None:
    """Best-of-N selection returns the chain with the highest composite score."""
    pcb_file = _make_pcb_file(tmp_path)
    wrapper = _make_wrapper(n_best=3, max_workers=3)

    chain_outputs = [
        ("low-score-chain", 0.01),
        ("high-score-chain", 0.01),
        ("mid-score-chain", 0.01),
    ]
    chain_idx = [0]

    def multi_generate(messages):
        idx = chain_idx[0]
        chain_idx[0] += 1
        return chain_outputs[idx]

    wrapper._generate_chain = multi_generate

    mock_board = MagicMock()
    mock_board.footprints = []
    mock_board.nets = []
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    scores = [0.5, 0.95, 0.7]
    # predict_reward is called per chain in both confidence scoring and best-of-N
    # (2 calls per chain). Cycle through scores to ensure consistent per-chain scoring.
    score_idx = [0]

    def mock_predict(model, text):
        s = scores[score_idx[0] % len(scores)]
        score_idx[0] += 1
        return MagicMock(format_score=s, quality_score=s, accuracy_score=s)

    with patch("volta.parser.pcb_parser.parse_pcb", return_value=mock_result), \
         patch("volta.inference.best_of_n.predict_reward", side_effect=mock_predict), \
         patch("volta.training.reward_model.predict_reward", side_effect=mock_predict):
        result = wrapper.analyze(pcb_file)

    assert "high-score-chain" in result.chain_text
    assert result.composite_score >= 0.9


# ---------------------------------------------------------------------------
# Test 4: n_best=1 returns single chain (no executor overhead)
# ---------------------------------------------------------------------------


def test_n_best_1_single_chain(tmp_path: Path) -> None:
    """Parallel generation with n_best=1 returns single chain without executor."""
    pcb_file = _make_pcb_file(tmp_path)
    wrapper = _make_wrapper(n_best=1, max_workers=1)

    call_count = [0]

    def single_generate(messages):
        call_count[0] += 1
        return "only-chain", 0.01

    wrapper._generate_chain = single_generate

    mock_board = MagicMock()
    mock_board.footprints = []
    mock_board.nets = []
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    def mock_predict(model, text):
        return MagicMock(format_score=0.8, quality_score=0.8, accuracy_score=0.8)

    with patch("volta.parser.pcb_parser.parse_pcb", return_value=mock_result), \
         patch("volta.inference.best_of_n.predict_reward", side_effect=mock_predict), \
         patch("volta.training.reward_model.predict_reward", side_effect=mock_predict):
        result = wrapper.analyze(pcb_file)

    assert call_count[0] == 1
    assert isinstance(result, ScoredChain)


# ---------------------------------------------------------------------------
# Test 5: Thread safety -- shared read-only weights, independent activations
# ---------------------------------------------------------------------------


def test_thread_safety_shared_model(tmp_path: Path) -> None:
    """Parallel generation shares model weights (read-only) with per-thread activations."""
    pcb_file = _make_pcb_file(tmp_path)
    wrapper = _make_wrapper(n_best=4, max_workers=4)

    thread_ids: set[int] = set()
    lock = threading.Lock()

    def thread_aware_generate(messages):
        tid = threading.current_thread().ident
        with lock:
            thread_ids.add(tid)
        time.sleep(0.05)
        return f"chain-from-{tid}", 0.05

    wrapper._generate_chain = thread_aware_generate

    mock_board = MagicMock()
    mock_board.footprints = []
    mock_board.nets = []
    mock_result = MagicMock()
    mock_result.kiutils_obj = mock_board
    mock_result.raw_content = "(kicad_pcb)"

    def mock_predict(model, text):
        return MagicMock(format_score=0.8, quality_score=0.8, accuracy_score=0.8)

    with patch("volta.parser.pcb_parser.parse_pcb", return_value=mock_result), \
         patch("volta.inference.best_of_n.predict_reward", side_effect=mock_predict), \
         patch("volta.training.reward_model.predict_reward", side_effect=mock_predict):
        result = wrapper.analyze(pcb_file)

    # With 4 max_workers and 4 chains, multiple threads should have been used
    assert len(thread_ids) >= 2, f"Expected multiple threads, got {len(thread_ids)}"


# ---------------------------------------------------------------------------
# Test 6: LocalLLMClient.unload_model() releases model and tokenizer
# ---------------------------------------------------------------------------


def test_unload_model_releases_references() -> None:
    """unload_model() sets model and tokenizer to None."""
    from volta.llm.local_client import LocalLLMClient

    client = LocalLLMClient(model="test-model", adapter_dir=None)
    # Simulate loaded state
    client._model = MagicMock()
    client._tokenizer = MagicMock()

    assert client._model is not None
    assert client._tokenizer is not None

    client.unload_model()

    assert client._model is None
    assert client._tokenizer is None


# ---------------------------------------------------------------------------
# Test 7: After unload, next chat() call reloads model (lazy reload)
# ---------------------------------------------------------------------------


def test_chat_after_unload_reloads_model() -> None:
    """After unload_model(), chat() triggers lazy reload via _ensure_loaded()."""
    from volta.llm.local_client import LocalLLMClient

    client = LocalLLMClient(model="test-model", adapter_dir=None)
    # Start with model loaded
    client._model = MagicMock()
    client._tokenizer = MagicMock()

    # Unload
    client.unload_model()
    assert client._model is None

    # Mock _ensure_loaded to set a new model
    new_model = MagicMock()
    new_tokenizer = MagicMock()

    original_ensure = client._ensure_loaded
    def mock_ensure():
        client._model = new_model
        client._tokenizer = new_tokenizer

    with patch.object(client, "_ensure_loaded", side_effect=mock_ensure), \
         patch("mlx_lm.generate", return_value="reloaded response"):
        result = client.chat([{"role": "user", "content": "test"}])

    assert client._model is new_model
    assert client._tokenizer is new_tokenizer


# ---------------------------------------------------------------------------
# Test 8: n_best=0 raises ValueError
# ---------------------------------------------------------------------------


def test_n_best_zero_raises_value_error() -> None:
    """n_best=0 raises ValueError (existing behavior preserved)."""
    from volta.inference.wrapper import InferenceWrapper

    with pytest.raises(ValueError, match="n_best must be between"):
        InferenceWrapper(n_best=0)


# ---------------------------------------------------------------------------
# Test 9: max_workers defaults to min(n_best, 4)
# ---------------------------------------------------------------------------


def test_max_workers_default_bound() -> None:
    """max_workers defaults to min(n_best, 4)."""
    from volta.inference.wrapper import InferenceWrapper

    # n_best=8 -> max_workers should be 4 (capped)
    wrapper = InferenceWrapper(n_best=8)
    assert wrapper._max_workers == 4

    # n_best=2 -> max_workers should be 2
    wrapper2 = InferenceWrapper(n_best=2)
    assert wrapper2._max_workers == 2
