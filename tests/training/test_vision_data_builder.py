"""Tests for Vision Data Builder (Plan 02)."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kicad_agent.training.vision_data_builder import (
    VisionDataRow,
    _extract_assistant_text,
    _row_to_hf_format,
)


class TestExtractAssistantText:
    """ChatML assistant text extraction tests."""

    def test_chatml_format(self):
        sample = {
            "text": "<|im_start|>system\nYou are a PCB expert<|im_end|>\n"
                   "<|im_start|>user\nAnalyze this PCB<|im_end|>\n"
                   "<|im_start|>assistant\n<operation>wire_net</operation>\n"
                   "<|im_end|>",
        }
        result = _extract_assistant_text(sample)
        assert result == "<operation>wire_net</operation>"

    def test_plain_text_fallback(self):
        sample = {"text": "Just plain text output"}
        result = _extract_assistant_text(sample)
        assert result == "Just plain text output"

    def test_empty_text(self):
        sample = {"text": ""}
        result = _extract_assistant_text(sample)
        assert result == ""

    def test_no_text_field(self):
        sample = {}
        result = _extract_assistant_text(sample)
        assert result == ""


class TestRowToHFFormat:
    """HuggingFace dataset format conversion tests."""

    def test_basic_conversion(self):
        row = VisionDataRow(
            image_path=Path("/tmp/images/sample_000000.png"),
            messages=[
                {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "prompt"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "response"}]},
            ],
            task_type="board_analysis",
            source_file="/path/to/board.kicad_pcb",
        )
        hf = _row_to_hf_format(row)
        assert hf["images"] == ["images/sample_000000.png"]
        assert len(hf["messages"]) == 2
        assert hf["messages"][0]["role"] == "user"
        assert hf["messages"][0]["content"][0]["type"] == "image"
        assert hf["task_type"] == "board_analysis"

    def test_relative_image_path(self):
        row = VisionDataRow(
            image_path=Path("/some/deep/path/images/sample_000042.png"),
            messages=[],
            task_type="routing",
            source_file="board.kicad_pcb",
        )
        hf = _row_to_hf_format(row)
        assert hf["images"] == ["images/sample_000042.png"]


class TestVisionDataRow:
    """VisionDataRow dataclass tests."""

    def test_fields(self):
        row = VisionDataRow(
            image_path=Path("test.png"),
            messages=[{"role": "user", "content": "test"}],
            task_type="test",
            source_file="test.kicad_pcb",
        )
        assert row.image_path == Path("test.png")
        assert row.task_type == "test"
