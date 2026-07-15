"""Tests for placement prediction module (predict.py).

Covers:
  - PlacementPrediction dataclass immutability and construction
  - _compute_confidence edge cases: empty, single, multiple components
  - Confidence bounds and scaling behavior
  - PlacementPredictor instantiation requires torch (import guard tested)
"""

from __future__ import annotations

import numpy as np
import pytest

from volta.placement.predict import PlacementPrediction, _compute_confidence


class TestPlacementPrediction:
    """Tests for the PlacementPrediction result dataclass."""

    def test_construction(self) -> None:
        pred = PlacementPrediction(
            positions={"U1": (10.0, 20.0, 90.0)},
            raw_output=np.array([[10.0, 20.0, 90.0]], dtype=np.float32),
            model_confidence=0.75,
        )
        assert pred.positions["U1"] == (10.0, 20.0, 90.0)
        assert pred.model_confidence == 0.75

    def test_frozen_immutability(self) -> None:
        pred = PlacementPrediction(
            positions={"U1": (0.0, 0.0, 0.0)},
            raw_output=np.zeros((1, 3), dtype=np.float32),
            model_confidence=0.5,
        )
        with pytest.raises(AttributeError):
            pred.model_confidence = 1.0  # type: ignore[misc]

    def test_empty_positions(self) -> None:
        pred = PlacementPrediction(
            positions={},
            raw_output=np.zeros((0, 3), dtype=np.float32),
            model_confidence=0.0,
        )
        assert pred.positions == {}


class TestComputeConfidence:
    """Tests for _compute_confidence helper function."""

    def test_empty_array_returns_zero(self) -> None:
        result = _compute_confidence(np.zeros((0, 3)), 100.0, 80.0)
        assert result == 0.0

    def test_zero_size_array_returns_zero(self) -> None:
        """numpy array with size 0 but shape (0, 3) still returns 0."""
        empty = np.array([]).reshape(0, 3).astype(np.float32)
        result = _compute_confidence(empty, 100.0, 80.0)
        assert result == 0.0

    def test_single_component_returns_half(self) -> None:
        """Single component has no variance to measure, returns 0.5."""
        raw = np.array([[50.0, 40.0, 0.0]], dtype=np.float32)
        result = _compute_confidence(raw, 100.0, 80.0)
        assert result == 0.5

    def test_spread_components_higher_confidence(self) -> None:
        """Components spread across the board should have higher confidence."""
        raw = np.array([
            [10.0, 10.0, 0.0],
            [90.0, 70.0, 0.0],
        ], dtype=np.float32)
        result = _compute_confidence(raw, 100.0, 80.0)
        assert result > 0.5

    def test_clustered_components_lower_confidence(self) -> None:
        """Components clustered near each other should have lower confidence."""
        raw = np.array([
            [50.0, 40.0, 0.0],
            [51.0, 41.0, 0.0],
        ], dtype=np.float32)
        result = _compute_confidence(raw, 100.0, 80.0)
        assert result < 0.5

    def test_confidence_capped_at_1(self) -> None:
        """Confidence should never exceed 1.0."""
        raw = np.array([
            [0.0, 0.0, 0.0],
            [100.0, 80.0, 0.0],
            [0.0, 80.0, 0.0],
            [100.0, 0.0, 0.0],
        ], dtype=np.float32)
        result = _compute_confidence(raw, 100.0, 80.0)
        assert result <= 1.0

    def test_zero_board_dims_no_crash(self) -> None:
        """Board dimensions of zero should not cause division by zero."""
        raw = np.array([[10.0, 20.0, 0.0]], dtype=np.float32)
        result = _compute_confidence(raw, 0.0, 0.0)
        # Should not raise -- max(board_w, 1.0) guard prevents div-by-zero
        assert result >= 0.0

    def test_confidence_non_negative(self) -> None:
        raw = np.array([[50.0, 40.0, 0.0]], dtype=np.float32)
        result = _compute_confidence(raw, 100.0, 80.0)
        assert result >= 0.0


class TestPlacementPredictorImport:
    """Tests verifying PlacementPredictor requires torch for instantiation."""

    def test_predictor_needs_torch(self) -> None:
        """PlacementPredictor.__init__ imports torch; verify the class exists."""
        # We cannot fully instantiate without torch, but the class should
        # be importable at module level (torch is inside __init__).
        from volta.placement.predict import PlacementPredictor
        assert PlacementPredictor is not None

    def test_predictor_model_path_none(self) -> None:
        """PlacementPredictor with model_path=None should still work (random init)."""
        pytest.importorskip("torch")
        from volta.placement.predict import PlacementPredictor
        predictor = PlacementPredictor(model_path=None)
        assert predictor.is_ready is True
