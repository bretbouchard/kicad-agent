"""Tests for analysis intent and review modules."""

import pytest

from volta.analysis.intent_inference import IntentInferrer, InferenceResult
from volta.analysis.intent_schemas import DesignGoal, DesignIntent, SubcircuitIntent
from volta.analysis.design_review import (
    DesignFinding,
    DesignReview,
    DesignReviewer,
    ReviewCategory,
    ReviewSeverity,
)


class TestIntentInferrer:
    """Tests for IntentInferrer."""

    def test_creation(self):
        """IntentInferrer can be created."""
        inferrer = IntentInferrer()
        assert inferrer is not None


class TestInferenceResult:
    """Tests for InferenceResult."""

    def test_import(self):
        """InferenceResult is importable."""
        assert InferenceResult is not None


class TestDesignGoal:
    """Tests for DesignGoal enum."""

    def test_values(self):
        """DesignGoal has expected values."""
        values = [v.value for v in DesignGoal]
        assert len(values) >= 5
        assert any("audio" in v.lower() for v in values)


class TestDesignIntent:
    """Tests for DesignIntent."""

    def test_import(self):
        """DesignIntent is importable."""
        assert DesignIntent is not None


class TestDesignReviewer:
    """Tests for DesignReviewer."""

    def test_creation(self):
        """DesignReviewer can be created."""
        reviewer = DesignReviewer()
        assert reviewer is not None


class TestDesignFinding:
    """Tests for DesignFinding."""

    def test_import(self):
        """DesignFinding is importable."""
        assert DesignFinding is not None


class TestDesignReview:
    """Tests for DesignReview."""

    def test_import(self):
        """DesignReview is importable."""
        assert DesignReview is not None


class TestReviewSeverity:
    """Tests for ReviewSeverity enum."""

    def test_values(self):
        """ReviewSeverity has expected values."""
        values = [v for v in ReviewSeverity]
        assert len(values) >= 4


class TestReviewCategory:
    """Tests for ReviewCategory enum."""

    def test_values(self):
        """ReviewCategory has expected values."""
        values = [v for v in ReviewCategory]
        assert len(values) >= 3
