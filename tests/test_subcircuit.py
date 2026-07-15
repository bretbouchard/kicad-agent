"""Tests for analysis subcircuit modules."""

import pytest

from volta.analysis.subcircuit_detector import SubcircuitDetector, Subcircuit
from volta.analysis.subcircuit_detector import SubcircuitType


class TestSubcircuitDetectorDetailed:
    """Detailed tests for SubcircuitDetector."""

    def test_import(self):
        """SubcircuitDetector is importable."""
        assert SubcircuitDetector is not None

    def test_creation(self):
        """SubcircuitDetector can be created."""
        detector = SubcircuitDetector()
        assert detector is not None


class TestSubcircuitType:
    """Tests for SubcircuitType enum."""

    def test_import(self):
        """SubcircuitType is importable."""
        assert SubcircuitType is not None

    def test_values(self):
        """SubcircuitType has expected values."""
        values = [v for v in SubcircuitType]
        assert len(values) >= 5
