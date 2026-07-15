"""Unit tests for D-04 anti-hack caps (Plan 01 Task 2).

Three caps implement D-04 (Phase 107 RESEARCH.md §6):
  - CompactnessCap: penalize infinite-spread layouts (tanh smoothing)
  - CrossingsFloorCap: penalize suspiciously low crossing counts (over-routing)
  - AlignmentJitter: ±amplitude_mm perturbation (data augmentation, not penalty)
"""
from __future__ import annotations

import math
import random
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from volta.training.rewards.anti_hack import (
    AlignmentJitter,
    CompactnessCap,
    CrossingsFloorCap,
)
from volta.training.rewards.cap_inputs import CapInputs


# ---------------------------------------------------------------------------
# CompactnessCap (D-04 cap 1: infinite-spread penalty)
# ---------------------------------------------------------------------------


def test_compactness_at_threshold_returns_one() -> None:
    """Test 1: ratio=2.0 at threshold -> 1.0 (no penalty)."""
    cap = CompactnessCap(threshold_ratio=2.0)
    inputs = CapInputs(bounding_box_mm2=5000.0, component_footprint_area_mm2=2500.0, crossing_count=5)
    assert cap.penalty(inputs) == pytest.approx(1.0)


def test_compactness_compact_layout_returns_one() -> None:
    """Test 2: ratio=1.0 (compact) -> 1.0 (no penalty)."""
    cap = CompactnessCap(threshold_ratio=2.0)
    inputs = CapInputs(bounding_box_mm2=2500.0, component_footprint_area_mm2=2500.0, crossing_count=5)
    assert cap.penalty(inputs) == pytest.approx(1.0)


def test_compactness_ratio_three_returns_penalty_in_expected_band() -> None:
    """Test 3: ratio=3.0 -> penalty multiplier in [0.3, 0.7]."""
    cap = CompactnessCap(threshold_ratio=2.0)
    inputs = CapInputs(bounding_box_mm2=7500.0, component_footprint_area_mm2=2500.0, crossing_count=5)
    mult = cap.penalty(inputs)
    assert 0.3 <= mult <= 0.7, f"ratio=3.0 multiplier {mult} not in [0.3, 0.7]"


def test_compactness_ratio_ten_returns_severe_penalty() -> None:
    """Test 4: ratio=10.0 -> multiplier <= 0.2 (severe, asymptotic)."""
    cap = CompactnessCap(threshold_ratio=2.0)
    inputs = CapInputs(
        bounding_box_mm2=25000.0, component_footprint_area_mm2=2500.0, crossing_count=5,
    )
    mult = cap.penalty(inputs)
    assert mult <= 0.2, f"ratio=10.0 multiplier {mult} not <= 0.2"


def test_compactness_penalty_monotonically_decreasing() -> None:
    """Test 5: more spread = more penalty (monotonic decrease)."""
    cap = CompactnessCap(threshold_ratio=2.0)
    prev = 1.0
    for ratio in [2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 20.0]:
        inputs = CapInputs(
            bounding_box_mm2=ratio * 1000.0,
            component_footprint_area_mm2=1000.0,
            crossing_count=5,
        )
        mult = cap.penalty(inputs)
        assert mult <= prev + 1e-9, f"penalty not monotonic at ratio={ratio}"
        prev = mult


def test_compactness_zero_footprint_does_not_crash() -> None:
    """Test 6: footprint_mm2=0 guarded by max(footprint, 1.0)."""
    cap = CompactnessCap(threshold_ratio=2.0)
    inputs = CapInputs(bounding_box_mm2=5000.0, component_footprint_area_mm2=0.0, crossing_count=5)
    # Should not raise; should return a severe penalty (ratio is huge under the guard)
    mult = cap.penalty(inputs)
    assert isinstance(mult, float)
    assert 0.0 < mult <= 1.0


# ---------------------------------------------------------------------------
# CrossingsFloorCap (D-04 cap 2: over-routing penalty)
# ---------------------------------------------------------------------------


def test_crossings_floor_zero_crossings_returns_floor_multiplier() -> None:
    """Test 7: crossing_count=0 -> 0.3 (suspicious, over-routing)."""
    cap = CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3)
    inputs = CapInputs(bounding_box_mm2=100.0, component_footprint_area_mm2=50.0, crossing_count=0)
    assert cap.penalty(inputs) == pytest.approx(0.3)


def test_crossings_floor_at_min_returns_one() -> None:
    """Test 8: crossing_count=1 (at floor) -> 1.0 (no penalty)."""
    cap = CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3)
    inputs = CapInputs(bounding_box_mm2=100.0, component_footprint_area_mm2=50.0, crossing_count=1)
    assert cap.penalty(inputs) == pytest.approx(1.0)


def test_crossings_floor_above_min_returns_one() -> None:
    """Test 9: crossing_count=10 (above floor) -> 1.0 (no penalty)."""
    cap = CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3)
    inputs = CapInputs(bounding_box_mm2=100.0, component_footprint_area_mm2=50.0, crossing_count=10)
    assert cap.penalty(inputs) == pytest.approx(1.0)


def test_crossings_floor_negative_count_raises_valueerror() -> None:
    """Test 10: crossing_count=-1 invalid input -> ValueError."""
    cap = CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3)
    inputs = CapInputs(bounding_box_mm2=100.0, component_footprint_area_mm2=50.0, crossing_count=-1)
    with pytest.raises(ValueError):
        cap.penalty(inputs)


# ---------------------------------------------------------------------------
# AlignmentJitter (D-04 cap 3: data-augmentation perturbation)
# ---------------------------------------------------------------------------


def test_jitter_perturb_coord_in_expected_band() -> None:
    """Test 11: perturb_coord(50.0) -> value in [49.9, 50.1] (±0.1mm)."""
    jitter = AlignmentJitter(amplitude_mm=0.1)
    rng = random.Random(42)
    val = jitter.perturb_coord(50.0, rng)
    assert 49.9 <= val <= 50.1, f"perturbed value {val} outside [49.9, 50.1]"


def test_jitter_same_seed_produces_same_perturbation() -> None:
    """Test 12: deterministic — same seed -> same output."""
    jitter = AlignmentJitter(amplitude_mm=0.1)
    rng1 = random.Random(123)
    rng2 = random.Random(123)
    assert jitter.perturb_coord(100.0, rng1) == pytest.approx(jitter.perturb_coord(100.0, rng2))


def test_jitter_different_seeds_produce_different_perturbations() -> None:
    """Test 13: different seeds -> different outputs (statistical, with mocks)."""
    jitter = AlignmentJitter(amplitude_mm=0.1)
    rng1 = random.Random(1)
    rng2 = random.Random(2)
    val1 = jitter.perturb_coord(100.0, rng1)
    val2 = jitter.perturb_coord(100.0, rng2)
    assert val1 != val2, "different seeds produced same perturbation (RNG not propagating)"


def test_jitter_pure_function_same_input_same_output() -> None:
    """Test 14: pure — calling twice with same input + same rng state -> same output."""
    jitter = AlignmentJitter(amplitude_mm=0.1)
    rng = random.Random(999)
    # Save state
    state = rng.getstate()
    val1 = jitter.perturb_coord(75.0, rng)
    rng.setstate(state)
    val2 = jitter.perturb_coord(75.0, rng)
    assert val1 == val2


# ---------------------------------------------------------------------------
# Phase 100 CR-01: all caps frozen
# ---------------------------------------------------------------------------


def test_caps_are_frozen_dataclasses() -> None:
    """Phase 100 CR-01: cap classes must be frozen."""
    with pytest.raises(FrozenInstanceError):
        cap = CompactnessCap(threshold_ratio=2.0)
        cap.threshold_ratio = 5.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        cap = CrossingsFloorCap(min_crossings=1)
        cap.min_crossings = 5  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        jitter = AlignmentJitter(amplitude_mm=0.1)
        jitter.amplitude_mm = 0.5  # type: ignore[misc]
