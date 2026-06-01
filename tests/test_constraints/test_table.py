"""Tests for ConstraintParams and ConstraintTable lookup.

CP-04: ConstraintTable maps (SignalIntegrity, NetImportance) to
ConstraintParams via deterministic first-match lookup.
"""

import pytest

from kicad_agent.analysis.net_classifier import NetImportance, SignalIntegrity
from kicad_agent.constraints.table import ConstraintParams, lookup_params


class TestConstraintParams:
    """Test ConstraintParams frozen dataclass."""

    def test_has_positive_defaults(self):
        """All dimension fields should have positive defaults."""
        p = ConstraintParams()
        assert p.clearance_mm > 0
        assert p.trace_width_mm > 0
        assert p.diff_pair_gap_mm > 0
        assert p.via_diameter_mm > 0

    def test_frozen(self):
        """ConstraintParams is immutable (frozen dataclass)."""
        import dataclasses
        p = ConstraintParams()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.clearance_mm = 0.5  # type: ignore[misc]


class TestLookupParams:
    """Test lookup_params deterministic lookup."""

    def test_high_speed_critical_returns_tight_clearance(self):
        """HIGH_SPEED + CRITICAL should return tighter clearance than defaults."""
        result = lookup_params(SignalIntegrity.HIGH_SPEED, NetImportance.CRITICAL)
        assert isinstance(result, ConstraintParams)
        # Tighter than default 0.2mm
        assert result.clearance_mm < ConstraintParams().clearance_mm

    def test_low_frequency_returns_default_or_larger(self):
        """LOW_FREQUENCY + MEDIUM should return default or larger clearance."""
        result = lookup_params(SignalIntegrity.LOW_FREQUENCY, NetImportance.MEDIUM)
        assert isinstance(result, ConstraintParams)
        assert result.clearance_mm >= ConstraintParams().clearance_mm

    def test_unknown_returns_default(self):
        """Unknown combinations return default ConstraintParams."""
        result = lookup_params(SignalIntegrity.UNKNOWN, NetImportance.LOW)
        assert isinstance(result, ConstraintParams)
        # Should be default values
        default = ConstraintParams()
        assert result.clearance_mm == default.clearance_mm
        assert result.trace_width_mm == default.trace_width_mm

    def test_high_speed_critical_tighter_than_low_frequency(self):
        """HIGH_SPEED/CRITICAL should have tighter clearance than LOW_FREQUENCY/MEDIUM."""
        hs = lookup_params(SignalIntegrity.HIGH_SPEED, NetImportance.CRITICAL)
        lf = lookup_params(SignalIntegrity.LOW_FREQUENCY, NetImportance.MEDIUM)
        assert hs.clearance_mm < lf.clearance_mm

    def test_power_integrity_critical_returns_wider_trace(self):
        """POWER_INTEGRITY + CRITICAL should have wider trace width."""
        result = lookup_params(SignalIntegrity.POWER_INTEGRITY, NetImportance.CRITICAL)
        assert isinstance(result, ConstraintParams)
        default = ConstraintParams()
        assert result.trace_width_mm > default.trace_width_mm
