"""Tests for Vision Benchmark (Plan 04)."""

from __future__ import annotations

import pytest
from pathlib import Path

from kicad_agent.evaluation.vision_benchmark import VisionBenchmarkResult


class TestVisionBenchmarkResult:
    """Benchmark result dataclass tests."""

    def test_fields(self):
        result = VisionBenchmarkResult(
            total_tasks=10,
            gemma_correct=8,
            gemma_total_time=30.0,
            qwen_correct=7,
            qwen_total_time=15.0,
            gemma_accuracy=0.8,
            qwen_accuracy=0.7,
            accuracy_delta=14.285714,
            per_task_results=[],
        )
        assert result.total_tasks == 10
        assert result.gemma_accuracy == 0.8
        assert result.qwen_accuracy == 0.7
        assert result.accuracy_delta > 0  # Gemma is better

    def test_frozen(self):
        result = VisionBenchmarkResult(
            total_tasks=0, gemma_correct=0, gemma_total_time=0.0,
            qwen_correct=0, qwen_total_time=0.0,
            gemma_accuracy=0.0, qwen_accuracy=0.0, accuracy_delta=0.0,
            per_task_results=[],
        )
        with pytest.raises(AttributeError):
            result.gemma_correct = 99

    def test_zero_tasks(self):
        result = VisionBenchmarkResult(
            total_tasks=0, gemma_correct=0, gemma_total_time=0.0,
            qwen_correct=0, qwen_total_time=0.0,
            gemma_accuracy=0.0, qwen_accuracy=0.0, accuracy_delta=0.0,
            per_task_results=[],
        )
        assert result.gemma_accuracy == 0.0
        assert result.accuracy_delta == 0.0
