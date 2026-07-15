"""Tests for analysis circuit classifier module."""

import pytest

from volta.analysis.circuit_classifier import (
    CircuitClassifier,
    ClassificationResult,
)


class TestCircuitClassifierDetailed:
    """Detailed tests for CircuitClassifier."""

    def test_import(self):
        """CircuitClassifier is importable."""
        assert CircuitClassifier is not None


class TestClassificationResult:
    """Tests for ClassificationResult."""

    def test_import(self):
        """ClassificationResult is importable."""
        assert ClassificationResult is not None
