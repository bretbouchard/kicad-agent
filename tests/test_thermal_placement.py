"""Tests for thermal-aware placement: ThermalProfile, compute_thermal_separation, apply_thermal_constraints.

Validates:
- ThermalProfile dataclass stores reference, power, temp, clearance fields
- compute_thermal_separation calculates distance from profiles with power scaling
- Distance heuristic fallback when profiles missing
- apply_thermal_constraints generates exclusion zones from thermal profiles
- Graceful fallback with logging when no thermal data provided
- Thermal penalty proportional to power_dissipation_watts
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from volta.placement.footprint_geometry import ComponentGeometry
from volta.placement.thermal import (
    _DEFAULT_THERMAL_MARGIN_MM,
    _POWER_SCALING_FACTOR,
    ThermalProfile,
    apply_thermal_constraints,
    compute_thermal_separation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thermal_profile(
    ref: str = "U1",
    power_w: float = 1.0,
    max_temp: float = 85.0,
    clearance_mm: float = 5.0,
) -> ThermalProfile:
    """Build a ThermalProfile fixture."""
    return ThermalProfile(
        reference=ref,
        power_dissipation_watts=power_w,
        max_temp_celsius=max_temp,
        required_clearance_mm=clearance_mm,
    )


def _make_geometry(
    ref: str = "U1",
    width: float = 5.0,
    height: float = 5.0,
) -> ComponentGeometry:
    """Build a ComponentGeometry fixture."""
    return ComponentGeometry(
        reference=ref,
        width_mm=width,
        height_mm=height,
        pad_positions=(),
        thermal_area_mm2=width * height,
        centroid_offset=(0.0, 0.0),
    )


# ---------------------------------------------------------------------------
# ThermalProfile dataclass tests
# ---------------------------------------------------------------------------


class TestThermalProfile:
    """ThermalProfile dataclass stores all required fields."""

    def test_fields_stored(self):
        """ThermalProfile stores reference, power, max_temp, clearance."""
        profile = _make_thermal_profile("U1", power_w=2.5, max_temp=125.0, clearance_mm=8.0)

        assert profile.reference == "U1"
        assert profile.power_dissipation_watts == 2.5
        assert profile.max_temp_celsius == 125.0
        assert profile.required_clearance_mm == 8.0

    def test_frozen(self):
        """ThermalProfile is immutable (frozen dataclass)."""
        profile = _make_thermal_profile()

        with pytest.raises(AttributeError):
            profile.reference = "U2"  # type: ignore[misc]

    def test_default_clearance(self):
        """Default clearance is 5.0mm."""
        profile = ThermalProfile(
            reference="U1",
            power_dissipation_watts=1.0,
            max_temp_celsius=85.0,
        )
        assert profile.required_clearance_mm == 5.0


# ---------------------------------------------------------------------------
# compute_thermal_separation tests
# ---------------------------------------------------------------------------


class TestComputeThermalSeparation:
    """compute_thermal_separation returns min distance based on profiles."""

    def test_both_profiles_returns_margin_with_power(self):
        """With both profiles, separation = max(clearance) + scaling * total_power."""
        prof_a = _make_thermal_profile("U1", power_w=2.0, clearance_mm=5.0)
        prof_b = _make_thermal_profile("U2", power_w=3.0, clearance_mm=8.0)

        result = compute_thermal_separation(prof_a, prof_b)

        # max(5.0, 8.0) + 0.5 * (2.0 + 3.0) = 8.0 + 2.5 = 10.5
        expected = 8.0 + _POWER_SCALING_FACTOR * (2.0 + 3.0)
        assert result == pytest.approx(expected)

    def test_one_profile_returns_single_margin(self):
        """With only one profile, uses its clearance + power scaling."""
        prof_a = _make_thermal_profile("U1", power_w=4.0, clearance_mm=6.0)

        result = compute_thermal_separation(prof_a, None)

        # 6.0 + 0.5 * 4.0 = 8.0
        expected = 6.0 + _POWER_SCALING_FACTOR * 4.0
        assert result == pytest.approx(expected)

    def test_neither_profile_returns_default(self):
        """With neither profile, returns default thermal margin."""
        result = compute_thermal_separation(None, None)

        assert result == _DEFAULT_THERMAL_MARGIN_MM

    def test_higher_power_larger_separation(self):
        """Higher power dissipation produces larger separation distance."""
        low_power = _make_thermal_profile("U1", power_w=1.0, clearance_mm=5.0)
        high_power = _make_thermal_profile("U2", power_w=10.0, clearance_mm=5.0)

        low_sep = compute_thermal_separation(low_power, None)
        high_sep = compute_thermal_separation(high_power, None)

        assert high_sep > low_sep

    def test_power_scaling_is_proportional(self):
        """Separation increase is proportional to power_dissipation_watts."""
        prof_1w = _make_thermal_profile("U1", power_w=1.0, clearance_mm=5.0)
        prof_5w = _make_thermal_profile("U2", power_w=5.0, clearance_mm=5.0)

        sep_1w = compute_thermal_separation(prof_1w, None)
        sep_5w = compute_thermal_separation(prof_5w, None)

        # Difference should be proportional to power difference
        diff = sep_5w - sep_1w
        expected_diff = _POWER_SCALING_FACTOR * (5.0 - 1.0)
        assert diff == pytest.approx(expected_diff)


# ---------------------------------------------------------------------------
# apply_thermal_constraints tests
# ---------------------------------------------------------------------------


class TestApplyThermalConstraints:
    """apply_thermal_constraints generates exclusion zones from thermal profiles."""

    def test_with_profiles_creates_zones(self):
        """Thermal profiles with positions create exclusion zones."""
        profiles = [
            _make_thermal_profile("U1", power_w=5.0, clearance_mm=5.0),
        ]
        positions = {"U1": (50.0, 40.0, 0.0)}

        zones = apply_thermal_constraints(positions, None, profiles)

        assert len(zones) == 1
        x1, y1, x2, y2 = zones[0]
        # Center should be around (50, 40)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        assert center_x == pytest.approx(50.0)
        assert center_y == pytest.approx(40.0)

    def test_with_geometry_expands_zone(self):
        """Exclusion zone expands by component geometry (width/2, height/2)."""
        profiles = [
            _make_thermal_profile("U1", power_w=1.0, clearance_mm=3.0),
        ]
        geometry = {"U1": _make_geometry("U1", width=10.0, height=6.0)}
        positions = {"U1": (50.0, 40.0, 0.0)}

        zones = apply_thermal_constraints(positions, geometry, profiles)

        assert len(zones) == 1
        x1, y1, x2, y2 = zones[0]
        # Radius = clearance + power_scaling * power = 3.0 + 0.5*1.0 = 3.5
        # Expanded by width/2=5.0, height/2=3.0
        radius = 3.0 + _POWER_SCALING_FACTOR * 1.0
        expected_x1 = 50.0 - radius - 5.0  # 50 - 3.5 - 5.0 = 41.5
        expected_x2 = 50.0 + radius + 5.0  # 50 + 3.5 + 5.0 = 58.5
        expected_y1 = 40.0 - radius - 3.0  # 40 - 3.5 - 3.0 = 33.5
        expected_y2 = 40.0 + radius + 3.0  # 40 + 3.5 + 3.0 = 46.5

        assert x1 == pytest.approx(expected_x1)
        assert x2 == pytest.approx(expected_x2)
        assert y1 == pytest.approx(expected_y1)
        assert y2 == pytest.approx(expected_y2)

    def test_empty_profiles_returns_empty(self):
        """Empty profiles list returns empty exclusion zones."""
        positions = {"U1": (50.0, 40.0, 0.0)}

        zones = apply_thermal_constraints(positions, None, [])

        assert zones == []

    def test_none_profiles_logs_fallback(self, caplog):
        """None thermal_profiles logs INFO fallback message and returns empty."""
        positions = {"U1": (50.0, 40.0, 0.0)}

        with caplog.at_level(logging.INFO, logger="volta.placement.thermal"):
            zones = apply_thermal_constraints(positions, None, None)

        assert zones == []
        assert "No thermal profiles provided" in caplog.text
        assert "distance heuristic fallback" in caplog.text

    def test_multiple_profiles_multiple_zones(self):
        """Multiple thermal profiles produce multiple exclusion zones."""
        profiles = [
            _make_thermal_profile("U1", power_w=2.0),
            _make_thermal_profile("U2", power_w=3.0),
            _make_thermal_profile("U3", power_w=1.0),
        ]
        positions = {
            "U1": (20.0, 20.0, 0.0),
            "U2": (50.0, 50.0, 0.0),
            "U3": (80.0, 30.0, 0.0),
        }

        zones = apply_thermal_constraints(positions, None, profiles)

        assert len(zones) == 3

    def test_profile_without_position_skipped(self):
        """Thermal profile with no matching position is skipped."""
        profiles = [
            _make_thermal_profile("U1", power_w=2.0),
            _make_thermal_profile("U99", power_w=5.0),  # Not in positions
        ]
        positions = {"U1": (50.0, 40.0, 0.0)}

        zones = apply_thermal_constraints(positions, None, profiles)

        assert len(zones) == 1

    def test_zone_count_logged(self, caplog):
        """Number of thermal exclusion zones is logged at INFO level."""
        profiles = [
            _make_thermal_profile("U1", power_w=2.0),
            _make_thermal_profile("U2", power_w=3.0),
        ]
        positions = {
            "U1": (20.0, 20.0, 0.0),
            "U2": (50.0, 50.0, 0.0),
        }

        with caplog.at_level(logging.INFO, logger="volta.placement.thermal"):
            zones = apply_thermal_constraints(positions, None, profiles)

        assert len(zones) == 2
        assert "2" in caplog.text
        assert "thermal exclusion zone" in caplog.text

    def test_higher_power_larger_zone(self):
        """Higher power dissipation produces larger exclusion zone radius."""
        profiles_low = [_make_thermal_profile("U1", power_w=1.0, clearance_mm=5.0)]
        profiles_high = [_make_thermal_profile("U1", power_w=10.0, clearance_mm=5.0)]
        positions = {"U1": (50.0, 40.0, 0.0)}

        zones_low = apply_thermal_constraints(positions, None, profiles_low)
        zones_high = apply_thermal_constraints(positions, None, profiles_high)

        # Higher power should produce wider zone
        low_width = zones_low[0][2] - zones_low[0][0]
        high_width = zones_high[0][2] - zones_high[0][0]
        assert high_width > low_width
