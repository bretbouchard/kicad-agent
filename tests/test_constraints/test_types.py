"""Tests for PCBConstraint type hierarchy and ConstraintType enum.

CP-02: PCBConstraint frozen dataclass hierarchy with typed subtypes.
"""

import pytest
from pydantic import ValidationError

from kicad_agent.constraints.types import (
    ClearanceConstraint,
    ConstraintType,
    DecouplingConstraint,
    DifferentialPairConstraint,
    ImpedanceConstraint,
    PCBConstraint,
    ThermalConstraint,
)


class TestPCBConstraintBase:
    """Test PCBConstraint base model behavior."""

    def test_base_model_rejects_direct_instantiation(self):
        """PCBConstraint must not be instantiated directly -- abstract base."""
        with pytest.raises(ValidationError, match="abstract"):
            PCBConstraint(
                constraint_type=ConstraintType.CLEARANCE,
                net_names=("CLK+",),
                source_rule="test",
                confidence=0.9,
                rationale="test",
            )

    def test_isinstance_returns_true_for_all_subclasses(self):
        """All 5 subclasses should be instances of PCBConstraint."""
        dp = DifferentialPairConstraint(
            net_names=("D+", "D-"),
            source_rule="diff_pair",
            confidence=0.9,
            rationale="USB differential pair",
            gap_mm=0.1,
            width_mm=0.15,
        )
        cl = ClearanceConstraint(
            net_names=("CLK+", "CLK-"),
            source_rule="clearance_extractor",
            confidence=0.8,
            rationale="Clock clearance",
            min_clearance_mm=0.2,
        )
        imp = ImpedanceConstraint(
            net_names=("USB_DP", "USB_DN"),
            source_rule="impedance_extractor",
            confidence=0.85,
            rationale="USB impedance",
            target_impedance_ohm=90.0,
            trace_width_mm=0.15,
        )
        dec = DecouplingConstraint(
            net_names=("VCC",),
            source_rule="decoupling_extractor",
            confidence=0.75,
            rationale="Decoupling",
            ic_ref="U1",
            cap_ref="C1",
            max_distance_mm=2.0,
        )
        therm = ThermalConstraint(
            net_names=(),
            source_rule="thermal_extractor",
            confidence=0.7,
            rationale="Thermal relief",
            component_refs=("U2",),
            max_junction_temp_c=125.0,
        )
        for constraint in (dp, cl, imp, dec, therm):
            assert isinstance(constraint, PCBConstraint)


class TestConstraintType:
    """Test ConstraintType enum."""

    def test_has_exactly_five_members(self):
        """ConstraintType must have 5 members matching subclass names."""
        members = set(ConstraintType)
        expected = {
            ConstraintType.DIFFERENTIAL_PAIR,
            ConstraintType.CLEARANCE,
            ConstraintType.IMPEDANCE,
            ConstraintType.DECOUPLING,
            ConstraintType.THERMAL,
        }
        assert members == expected
        assert len(members) == 5


class TestDifferentialPairConstraint:
    """Test DifferentialPairConstraint subclass."""

    def test_valid_construction(self):
        """DifferentialPairConstraint with valid fields constructs correctly."""
        c = DifferentialPairConstraint(
            net_names=("D+", "D-"),
            source_rule="diff_pair",
            confidence=0.9,
            component_refs=("U1",),
            rationale="USB differential pair",
            gap_mm=0.1,
            width_mm=0.15,
            length_match_tolerance_mm=0.5,
        )
        assert c.constraint_type == ConstraintType.DIFFERENTIAL_PAIR
        assert c.gap_mm == 0.1
        assert c.width_mm == 0.15
        assert c.length_match_tolerance_mm == 0.5
        assert c.net_names == ("D+", "D-")
        assert c.confidence == 0.9

    def test_frozen_model(self):
        """DifferentialPairConstraint is immutable."""
        c = DifferentialPairConstraint(
            net_names=("D+", "D-"),
            source_rule="diff_pair",
            confidence=0.9,
            rationale="USB",
            gap_mm=0.1,
            width_mm=0.15,
        )
        with pytest.raises(ValidationError):
            c.gap_mm = 0.2


class TestClearanceConstraint:
    """Test ClearanceConstraint subclass."""

    def test_valid_construction(self):
        c = ClearanceConstraint(
            net_names=("CLK+", "CLK-"),
            source_rule="clearance_extractor",
            confidence=0.85,
            rationale="Clock pair clearance",
            min_clearance_mm=0.15,
        )
        assert c.constraint_type == ConstraintType.CLEARANCE
        assert c.min_clearance_mm == 0.15
        assert c.layer_constraint == "copper"
        assert c.net_class_name == ""

    def test_rejects_negative_clearance(self):
        """min_clearance_mm must be > 0."""
        with pytest.raises(ValidationError):
            ClearanceConstraint(
                net_names=("CLK+",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                min_clearance_mm=-0.1,
            )

    def test_rejects_zero_clearance(self):
        """min_clearance_mm must be > 0."""
        with pytest.raises(ValidationError):
            ClearanceConstraint(
                net_names=("CLK+",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                min_clearance_mm=0.0,
            )


class TestImpedanceConstraint:
    """Test ImpedanceConstraint subclass."""

    def test_valid_construction(self):
        c = ImpedanceConstraint(
            net_names=("USB_DP", "USB_DN"),
            source_rule="impedance_extractor",
            confidence=0.85,
            rationale="USB 90-ohm impedance",
            target_impedance_ohm=90.0,
            trace_width_mm=0.15,
        )
        assert c.constraint_type == ConstraintType.IMPEDANCE
        assert c.target_impedance_ohm == 90.0
        assert c.trace_width_mm == 0.15
        assert c.layer == "F.Cu"

    def test_rejects_non_positive_impedance(self):
        """target_impedance_ohm must be > 0."""
        with pytest.raises(ValidationError):
            ImpedanceConstraint(
                net_names=("USB_DP",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                target_impedance_ohm=0.0,
                trace_width_mm=0.15,
            )

    def test_rejects_non_positive_trace_width(self):
        """trace_width_mm must be > 0."""
        with pytest.raises(ValidationError):
            ImpedanceConstraint(
                net_names=("USB_DP",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                target_impedance_ohm=90.0,
                trace_width_mm=-0.1,
            )


class TestDecouplingConstraint:
    """Test DecouplingConstraint subclass."""

    def test_valid_construction(self):
        c = DecouplingConstraint(
            net_names=("VCC",),
            source_rule="decoupling_extractor",
            confidence=0.75,
            rationale="IC decoupling",
            ic_ref="U1",
            cap_ref="C1",
            max_distance_mm=2.0,
            priority="critical",
        )
        assert c.constraint_type == ConstraintType.DECOUPLING
        assert c.ic_ref == "U1"
        assert c.cap_ref == "C1"
        assert c.max_distance_mm == 2.0
        assert c.priority == "critical"

    def test_rejects_non_positive_distance(self):
        """max_distance_mm must be > 0."""
        with pytest.raises(ValidationError):
            DecouplingConstraint(
                net_names=("VCC",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                ic_ref="U1",
                cap_ref="C1",
                max_distance_mm=0.0,
            )

    def test_rejects_invalid_priority(self):
        """priority must be one of 'critical', 'high', 'normal'."""
        with pytest.raises(ValidationError):
            DecouplingConstraint(
                net_names=("VCC",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                ic_ref="U1",
                cap_ref="C1",
                max_distance_mm=2.0,
                priority="urgent",
            )

    def test_default_priority_is_normal(self):
        c = DecouplingConstraint(
            net_names=("VCC",),
            source_rule="test",
            confidence=0.5,
            rationale="test",
            ic_ref="U1",
            cap_ref="C1",
            max_distance_mm=2.0,
        )
        assert c.priority == "normal"


class TestThermalConstraint:
    """Test ThermalConstraint subclass."""

    def test_valid_construction(self):
        c = ThermalConstraint(
            net_names=(),
            source_rule="thermal_extractor",
            confidence=0.7,
            rationale="Power regulator thermal",
            component_refs=("U2",),
            max_junction_temp_c=125.0,
            thermal_resistance_c_per_w=5.0,
            heat_dissipation_w=1.5,
        )
        assert c.constraint_type == ConstraintType.THERMAL
        assert c.max_junction_temp_c == 125.0
        assert c.thermal_resistance_c_per_w == 5.0
        assert c.heat_dissipation_w == 1.5

    def test_rejects_non_positive_junction_temp(self):
        """max_junction_temp_c must be > 0."""
        with pytest.raises(ValidationError):
            ThermalConstraint(
                net_names=(),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                max_junction_temp_c=0.0,
            )

    def test_allows_zero_thermal_resistance(self):
        """thermal_resistance_c_per_w can be 0 (ge=0)."""
        c = ThermalConstraint(
            net_names=(),
            source_rule="test",
            confidence=0.5,
            rationale="test",
            max_junction_temp_c=100.0,
            thermal_resistance_c_per_w=0.0,
        )
        assert c.thermal_resistance_c_per_w == 0.0

    def test_allows_zero_heat_dissipation(self):
        """heat_dissipation_w can be 0 (ge=0)."""
        c = ThermalConstraint(
            net_names=(),
            source_rule="test",
            confidence=0.5,
            rationale="test",
            max_junction_temp_c=100.0,
            heat_dissipation_w=0.0,
        )
        assert c.heat_dissipation_w == 0.0

    def test_confidence_range_validation(self):
        """confidence must be 0.0-1.0."""
        with pytest.raises(ValidationError):
            ThermalConstraint(
                net_names=(),
                source_rule="test",
                confidence=1.5,
                rationale="test",
                max_junction_temp_c=100.0,
            )
