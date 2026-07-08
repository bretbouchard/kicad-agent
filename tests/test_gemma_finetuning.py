"""Tests for Phase 84: Gemma 4 12B fine-tuning pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_gap_training_data import (
    _VISION_CATEGORIES,
    format_gemma_chatml,
    parse_gemma_chatml,
)


# ---------------------------------------------------------------------------
# TestGemmaChatMLFormat
# ---------------------------------------------------------------------------


class TestGemmaChatMLFormat:
    """Gemma ChatML formatting and parsing."""

    def test_format_produces_start_of_turn(self) -> None:
        _, text = format_gemma_chatml("sys", "user msg", "asst msg")
        assert "<start_of_turn>system\n" in text
        assert "<start_of_turn>user\n" in text
        assert "<start_of_turn>model\n" in text
        assert "<end_of_turn>" in text

    def test_format_maps_assistant_to_model(self) -> None:
        _, text = format_gemma_chatml("sys", "q", "a")
        assert "<start_of_turn>model\n" in text
        assert "<start_of_turn>assistant\n" not in text

    def test_parse_roundtrip(self) -> None:
        system = "You are a PCB expert."
        user = "Analyze this board."
        assistant = "The board has 50 components."
        _, text = format_gemma_chatml(system, user, assistant)

        parsed = parse_gemma_chatml(text)
        assert parsed is not None
        assert len(parsed) == 3
        assert parsed[0]["role"] == "system"
        assert parsed[0]["content"] == system
        assert parsed[1]["role"] == "user"
        assert parsed[1]["content"] == user
        assert parsed[2]["role"] == "assistant"
        assert parsed[2]["content"] == assistant

    def test_parse_normalizes_model_to_assistant(self) -> None:
        text = "<start_of_turn>system\nsys<end_of_turn>\n<start_of_turn>user\nq<end_of_turn>\n<start_of_turn>model\na<end_of_turn>"
        parsed = parse_gemma_chatml(text)
        assert parsed is not None
        assert parsed[2]["role"] == "assistant"

    def test_qwen_format_not_confused(self) -> None:
        """Qwen format tokens are not parsed by Gemma parser."""
        text = "<|im_start|>system\nsys<|im_end|>\n<|im_start|>user\nq<|im_end|>"
        parsed = parse_gemma_chatml(text)
        assert parsed is None


# ---------------------------------------------------------------------------
# TestGapTrainingDataGeneration
# ---------------------------------------------------------------------------


class TestGapTrainingDataGeneration:
    """Training data generation from TaskGenerator."""

    def test_vision_only_filter(self, tmp_path: Path) -> None:
        """Only vision-category tasks are included when vision_only=True."""
        from generate_gap_training_data import generate_from_benchmark_tasks

        count = generate_from_benchmark_tasks(tmp_path, n_seeds=1, vision_only=True)
        assert count > 0

        train_path = tmp_path / "train.jsonl"
        assert train_path.exists()
        with open(train_path, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line.strip())
                assert record["task_type"] in {
                    "routing_feasibility", "clearance_diagnosis",
                    "net_completion", "drc_fix_selection", "unrouted_cause",
                }

    def test_train_val_split(self, tmp_path: Path) -> None:
        """Train/val split has correct ratio."""
        from generate_gap_training_data import generate_from_benchmark_tasks

        generate_from_benchmark_tasks(tmp_path, n_seeds=3, vision_only=True)

        train_path = tmp_path / "train.jsonl"
        val_path = tmp_path / "val.jsonl"
        assert train_path.exists()
        assert val_path.exists()

        with open(train_path, encoding="utf-8") as f:
            train_count = sum(1 for _ in f)
        with open(val_path, encoding="utf-8") as f:
            val_count = sum(1 for _ in f)

        total = train_count + val_count
        assert val_count == max(1, int(total * 0.1))
        assert train_count + val_count == total

    def test_examples_have_required_fields(self, tmp_path: Path) -> None:
        """Each example has messages, text, task_type, task_id."""
        from generate_gap_training_data import generate_from_benchmark_tasks

        generate_from_benchmark_tasks(tmp_path, n_seeds=1, vision_only=True)

        with open(tmp_path / "train.jsonl", encoding="utf-8") as f:
            record = json.loads(f.readline().strip())

        assert "messages" in record
        assert "text" in record
        assert "task_type" in record
        assert "task_id" in record
        assert "difficulty" in record
        assert "seed" in record
        assert len(record["messages"]) >= 3

    def test_text_uses_gemma_format(self, tmp_path: Path) -> None:
        """Generated text field uses Gemma ChatML format."""
        from generate_gap_training_data import generate_from_benchmark_tasks

        generate_from_benchmark_tasks(tmp_path, n_seeds=1, vision_only=True)

        with open(tmp_path / "train.jsonl", encoding="utf-8") as f:
            record = json.loads(f.readline().strip())

        assert "<start_of_turn>" in record["text"]
        assert "<end_of_turn>" in record["text"]
        assert "<|im_start|>" not in record["text"]

    def test_5000_plus_with_default_seeds(self, tmp_path: Path) -> None:
        """50 seeds produce >= 5000 vision examples (MODEL-01)."""
        from generate_gap_training_data import generate_from_benchmark_tasks

        total = generate_from_benchmark_tasks(tmp_path, n_seeds=50, vision_only=True)
        assert total >= 5000, f"Expected >= 5000, got {total}"

    def test_vision_categories_set(self) -> None:
        """_VISION_CATEGORIES includes expected categories, excludes text-only."""
        assert "routing_feasibility" in _VISION_CATEGORIES
        assert "clearance_diagnosis" in _VISION_CATEGORIES
        assert "net_completion" in _VISION_CATEGORIES
        assert "drc_fix_selection" in _VISION_CATEGORIES
        assert "unrouted_cause" in _VISION_CATEGORIES
        assert "coordinate_proximity" not in _VISION_CATEGORIES


# ---------------------------------------------------------------------------
# TestGemmaFineTunedAdapter
# ---------------------------------------------------------------------------


class TestGemmaFineTunedAdapter:
    """GemmaFineTunedAdapter protocol compliance."""

    def test_name_includes_fine_tuned(self, tmp_path: Path) -> None:
        from evaluate_gemma_adapter import GemmaFineTunedAdapter

        adapter = GemmaFineTunedAdapter(adapter_dir=tmp_path)
        assert "Fine-Tuned" in adapter.name

    def test_supports_vision(self, tmp_path: Path) -> None:
        from evaluate_gemma_adapter import GemmaFineTunedAdapter

        adapter = GemmaFineTunedAdapter(adapter_dir=tmp_path)
        assert adapter.supports_vision is True

    def test_satisfies_model_adapter_protocol(self, tmp_path: Path) -> None:
        """Has name, supports_vision, and run_task interface."""
        from evaluate_gemma_adapter import GemmaFineTunedAdapter

        adapter = GemmaFineTunedAdapter(adapter_dir=tmp_path)
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "supports_vision")
        assert hasattr(adapter, "run_task")
        assert callable(adapter.run_task)


# ---------------------------------------------------------------------------
# TestLocalLLMGemmaIntegration
# ---------------------------------------------------------------------------


class TestLocalLLMGemmaIntegration:
    """LocalLLMClient Gemma format detection."""

    def test_gemma_format_detection(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        client = LocalLLMClient(model="ggml-org/gemma-4-12B-it-Q4_K_M")
        assert client._is_gemma_model() is True

    def test_qwen_format_unchanged(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        client = LocalLLMClient(model="Qwen/Qwen2.5-0.5B-Instruct")
        assert client._is_gemma_model() is False

    def test_gemma_format_output(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        text = LocalLLMClient._format_gemma_chatml(messages)
        assert "<start_of_turn>system\n" in text
        assert "<start_of_turn>model\n" in text
        assert "<start_of_turn>assistant\n" not in text
        assert "<|im_start|>" not in text

    def test_qwen_format_output(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        text = LocalLLMClient._format_qwen_chatml(messages)
        assert "<|im_start|>" in text
        assert "<|im_end|>" in text
        assert "<start_of_turn>" not in text

    def test_format_messages_dispatches_correctly(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]

        gemma_client = LocalLLMClient(model="gemma-4-12b")
        qwen_client = LocalLLMClient(model="Qwen/Qwen2.5-0.5B-Instruct")

        gemma_text = gemma_client._format_messages(messages)
        qwen_text = qwen_client._format_messages(messages)

        assert "<start_of_turn>" in gemma_text
        assert "<|im_start|>" in qwen_text

    def test_extract_response_gemma(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        client = LocalLLMClient(model="gemma-4-12b")
        response = "prefix<start_of_turn>model\nanswer text<end_of_turn>"
        assert client._extract_response(response) == "answer text"

    def test_extract_response_qwen(self) -> None:
        from kicad_agent.llm.local_client import LocalLLMClient

        client = LocalLLMClient(model="Qwen/Qwen2.5-0.5B-Instruct")
        response = "prefix<|im_start|>assistant\nanswer text<|im_end|>"
        assert client._extract_response(response) == "answer text"
