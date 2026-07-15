"""Tests for O-BUG-011: PreAnalysisGate singleton sharing.

Validates that batch_executor and execution.py use the same
PreAnalysisGate instance.
"""
from __future__ import annotations

import pytest

from volta.ops.execution import get_pre_analysis_gate
from volta.ops.batch_executor import _get_pre_analysis_gate


class TestPreAnalysisGateSingletonOBUG011:
    """O-BUG-011: Single PreAnalysisGate instance across execution paths."""

    def test_batch_uses_same_instance_as_execution(self):
        """batch_executor._get_pre_analysis_gate returns same object as execution.get_pre_analysis_gate."""
        gate_a = get_pre_analysis_gate()
        gate_b = _get_pre_analysis_gate()

        assert gate_a is gate_b, (
            "batch_executor and execution.py must use the same PreAnalysisGate instance"
        )

    def test_execution_gate_is_singleton(self):
        """Repeated calls to get_pre_analysis_gate return same object."""
        gate_a = get_pre_analysis_gate()
        gate_b = get_pre_analysis_gate()

        assert gate_a is gate_b

    def test_batch_gate_is_singleton(self):
        """Repeated calls to _get_pre_analysis_gate return same object."""
        gate_a = _get_pre_analysis_gate()
        gate_b = _get_pre_analysis_gate()

        assert gate_a is gate_b
