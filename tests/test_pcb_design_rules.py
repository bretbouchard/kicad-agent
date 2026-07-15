"""Tests for PCB-specific design rules extending DesignRule ABC.

Phase 53-02: ClearanceCheckRule, ImpedanceCheckRule, ThermalProximityRule.
All tests use mock spatial models and constraints -- no Phase 50/51 dependency.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from volta.analysis.design_rule_engine import DesignRuleEngine


# ---------------------------------------------------------------------------
# Mock types for testing (no Phase 50/51 dependency)
# ---------------------------------------------------------------------------


@dataclass
class MockPosition:
    """Mock footprint position with mm coordinates."""
    X: float
    Y: float


@dataclass
class MockFootprint:
    """Mock PCB footprint with position and reference."""
    position: MockPosition
    reference: str


@dataclass
class MockLayerStackup:
    """Mock layer stackup with impedance lookup."""
    _impedance: float | None = 50.0

    def get_impedance(self, layer: str, trace_width: float) -> float | None:
        return self._impedance


@dataclass
class MockSpatialModel:
    """Mock PcbSpatialModel with footprints and optional layer_stackup."""
    footprints: list[MockFootprint]
    layer_stackup: MockLayerStackup | None = None


@dataclass
class MockImpedanceConstraint:
    """Mock impedance constraint with target and net info."""
    target_impedance: float
    layer: str = "F.Cu"
    trace_width: float = 0.2
    net_name: str = "DIFF_P"


@dataclass
class MockThermalConstraint:
    """Mock thermal constraint with source ref and keepout margin."""
    component_ref: str
    keepout_margin: float = 2.0
    thermal_pad: bool = True


# ---------------------------------------------------------------------------
# Tests 1-5: ClearanceCheckRule
# ---------------------------------------------------------------------------


class TestClearanceCheckRule:
    """Tests for PCB_CLEARANCE_01 spatial clearance rule."""

    def test_rule_attributes(self) -> None:
        """Test 1: ClearanceCheckRule has correct class attributes."""
        from volta.validation.pcb_design_rules import ClearanceCheckRule

        rule = ClearanceCheckRule()
        assert rule.name == "PCB_CLEARANCE_01"
        assert rule.category == RuleCategory.LAYOUT
        assert rule.default_severity == RuleSeverity.WARNING
        assert isinstance(rule, DesignRule)

    def test_violation_below_threshold(self) -> None:
        """Test 2: Footprints at 0.1mm (below 0.2mm default) produce 1 violation."""
        from volta.validation.pcb_design_rules import ClearanceCheckRule

        rule = ClearanceCheckRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=0.0, Y=0.0), reference="U1"),
                MockFootprint(position=MockPosition(X=0.1, Y=0.0), reference="U2"),
            ],
        )
        violations = rule.check(None, config={"spatial_model": model})
        assert len(violations) == 1
        assert violations[0].rule_id == "PCB_CLEARANCE_01"
        assert "U1" in violations[0].location
        assert "U2" in violations[0].location

    def test_no_violation_above_threshold(self) -> None:
        """Test 3: Footprints at 0.5mm (above 0.2mm default) produce 0 violations."""
        from volta.validation.pcb_design_rules import ClearanceCheckRule

        rule = ClearanceCheckRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=0.0, Y=0.0), reference="U1"),
                MockFootprint(position=MockPosition(X=0.5, Y=0.0), reference="U2"),
            ],
        )
        violations = rule.check(None, config={"spatial_model": model})
        assert len(violations) == 0

    def test_config_override_threshold(self) -> None:
        """Test 4: config min_clearance_mm=0.5 applies override threshold."""
        from volta.validation.pcb_design_rules import ClearanceCheckRule

        rule = ClearanceCheckRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=0.0, Y=0.0), reference="U1"),
                MockFootprint(position=MockPosition(X=0.3, Y=0.0), reference="U2"),
            ],
        )
        # 0.3mm > 0.2mm default, but < 0.5mm override
        violations = rule.check(None, config={"spatial_model": model, "min_clearance_mm": 0.5})
        assert len(violations) == 1

    def test_spatial_model_none_returns_empty(self) -> None:
        """Test 5: spatial_model=None returns empty list (graceful degradation)."""
        from volta.validation.pcb_design_rules import ClearanceCheckRule

        rule = ClearanceCheckRule()
        violations = rule.check(None, config={"spatial_model": None})
        assert violations == []

    def test_no_config_returns_empty(self) -> None:
        """Test 5b: No config at all returns empty list."""
        from volta.validation.pcb_design_rules import ClearanceCheckRule

        rule = ClearanceCheckRule()
        violations = rule.check(None)
        assert violations == []


# ---------------------------------------------------------------------------
# Tests 6-9: ImpedanceCheckRule
# ---------------------------------------------------------------------------


class TestImpedanceCheckRule:
    """Tests for PCB_IMPEDANCE_01 impedance verification rule."""

    def test_rule_attributes(self) -> None:
        """Test 6: ImpedanceCheckRule has correct class attributes."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        assert rule.name == "PCB_IMPEDANCE_01"
        assert rule.category == RuleCategory.IMPEDANCE
        assert rule.default_severity == RuleSeverity.WARNING
        assert isinstance(rule, DesignRule)

    def test_violation_outside_tolerance(self) -> None:
        """Test 7: Z0=40.0 is outside 50.0 +/- 10%, produces 1 violation."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        model = MockSpatialModel(
            footprints=[],
            layer_stackup=MockLayerStackup(_impedance=40.0),
        )
        constraints = [MockImpedanceConstraint(target_impedance=50.0)]
        violations = rule.check(
            None,
            config={
                "spatial_model": model,
                "constraints": constraints,
            },
        )
        assert len(violations) == 1
        assert violations[0].rule_id == "PCB_IMPEDANCE_01"
        assert "40" in violations[0].description
        assert "50" in violations[0].description

    def test_no_violation_within_tolerance(self) -> None:
        """Test 8: Z0=50.5 is within 50.0 +/- 10%, produces 0 violations."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        model = MockSpatialModel(
            footprints=[],
            layer_stackup=MockLayerStackup(_impedance=50.5),
        )
        constraints = [MockImpedanceConstraint(target_impedance=50.0)]
        violations = rule.check(
            None,
            config={
                "spatial_model": model,
                "constraints": constraints,
            },
        )
        assert len(violations) == 0

    def test_no_constraints_returns_empty(self) -> None:
        """Test 9a: No constraints returns empty list."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        model = MockSpatialModel(
            footprints=[],
            layer_stackup=MockLayerStackup(_impedance=45.0),
        )
        violations = rule.check(
            None,
            config={"spatial_model": model, "constraints": []},
        )
        assert violations == []

    def test_no_layer_stackup_returns_empty(self) -> None:
        """Test 9b: No layer_stackup returns empty list."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        model = MockSpatialModel(footprints=[], layer_stackup=None)
        constraints = [MockImpedanceConstraint(target_impedance=50.0)]
        violations = rule.check(
            None,
            config={"spatial_model": model, "constraints": constraints},
        )
        assert violations == []

    def test_no_spatial_model_returns_empty(self) -> None:
        """Test 9c: spatial_model=None returns empty list."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        violations = rule.check(None, config={"spatial_model": None})
        assert violations == []

    def test_deviation_fraction_override(self) -> None:
        """Test 9d: config deviation_fraction=0.05 narrows tolerance."""
        from volta.validation.pcb_design_rules import ImpedanceCheckRule

        rule = ImpedanceCheckRule()
        model = MockSpatialModel(
            footprints=[],
            layer_stackup=MockLayerStackup(_impedance=47.0),
        )
        constraints = [MockImpedanceConstraint(target_impedance=50.0)]

        # 47.0 is within 10% of 50.0 (range: 45-55) -- no violation at default
        violations_default = rule.check(
            None,
            config={"spatial_model": model, "constraints": constraints},
        )
        assert len(violations_default) == 0

        # 47.0 is outside 5% of 50.0 (range: 47.5-52.5) -- violation at 5%
        violations_narrow = rule.check(
            None,
            config={
                "spatial_model": model,
                "constraints": constraints,
                "deviation_fraction": 0.05,
            },
        )
        assert len(violations_narrow) == 1


# ---------------------------------------------------------------------------
# Tests 10-14: ThermalProximityRule
# ---------------------------------------------------------------------------


class TestThermalProximityRule:
    """Tests for PCB_THERMAL_01 thermal proximity rule."""

    def test_rule_attributes(self) -> None:
        """Test 10: ThermalProximityRule has correct class attributes."""
        from volta.validation.pcb_design_rules import ThermalProximityRule

        rule = ThermalProximityRule()
        assert rule.name == "PCB_THERMAL_01"
        assert rule.category == RuleCategory.THERMAL
        assert rule.default_severity == RuleSeverity.WARNING
        assert isinstance(rule, DesignRule)

    def test_violation_below_keepout(self) -> None:
        """Test 11: Sensitive at (10, 10.5), source at (10, 10), dist=0.5mm < 2.0mm -> violation."""
        from volta.validation.pcb_design_rules import ThermalProximityRule

        rule = ThermalProximityRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=10.0, Y=10.0), reference="U1"),
                MockFootprint(position=MockPosition(X=10.0, Y=10.5), reference="U2"),
            ],
        )
        constraints = [MockThermalConstraint(component_ref="U1")]
        violations = rule.check(
            None,
            config={"spatial_model": model, "constraints": constraints},
        )
        assert len(violations) == 1
        assert violations[0].rule_id == "PCB_THERMAL_01"
        assert "U2" in violations[0].description
        assert "U1" in violations[0].description

    def test_no_violation_above_keepout(self) -> None:
        """Test 12: Sensitive at (10, 15), source at (10, 10), dist=5.0mm > 2.0mm -> no violation."""
        from volta.validation.pcb_design_rules import ThermalProximityRule

        rule = ThermalProximityRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=10.0, Y=10.0), reference="U1"),
                MockFootprint(position=MockPosition(X=10.0, Y=15.0), reference="U2"),
            ],
        )
        constraints = [MockThermalConstraint(component_ref="U1")]
        violations = rule.check(
            None,
            config={"spatial_model": model, "constraints": constraints},
        )
        assert len(violations) == 0

    def test_config_override_keepout(self) -> None:
        """Test 13: config keepout_margin_mm=5.0 applies override."""
        from volta.validation.pcb_design_rules import ThermalProximityRule

        rule = ThermalProximityRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=10.0, Y=10.0), reference="U1"),
                MockFootprint(position=MockPosition(X=10.0, Y=14.0), reference="U2"),
            ],
        )
        constraints = [MockThermalConstraint(component_ref="U1")]
        # Distance 4.0mm > 2.0mm default (no violation), but < 5.0mm override (violation)
        violations = rule.check(
            None,
            config={
                "spatial_model": model,
                "constraints": constraints,
                "keepout_margin_mm": 5.0,
            },
        )
        assert len(violations) == 1

    def test_spatial_model_none_returns_empty(self) -> None:
        """Test 14: spatial_model=None returns empty list."""
        from volta.validation.pcb_design_rules import ThermalProximityRule

        rule = ThermalProximityRule()
        violations = rule.check(None, config={"spatial_model": None})
        assert violations == []

    def test_no_thermal_constraints_returns_empty(self) -> None:
        """Test 14b: No thermal constraints returns empty list."""
        from volta.validation.pcb_design_rules import ThermalProximityRule

        rule = ThermalProximityRule()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=0.0, Y=0.0), reference="U1"),
            ],
        )
        violations = rule.check(
            None,
            config={"spatial_model": model, "constraints": []},
        )
        assert violations == []


# ---------------------------------------------------------------------------
# Tests 15-17: Factory and integration
# ---------------------------------------------------------------------------


class TestFactoryAndIntegration:
    """Tests for get_pcb_design_rules factory and DesignRuleEngine integration."""

    def test_get_pcb_design_rules_returns_three(self) -> None:
        """Test 15: get_pcb_design_rules() returns list of 3 rule instances."""
        from volta.validation.pcb_design_rules import (
            ClearanceCheckRule,
            ImpedanceCheckRule,
            ThermalProximityRule,
            get_pcb_design_rules,
        )

        rules = get_pcb_design_rules()
        assert len(rules) == 3
        assert isinstance(rules[0], ClearanceCheckRule)
        assert isinstance(rules[1], ImpedanceCheckRule)
        assert isinstance(rules[2], ThermalProximityRule)

    def test_rules_registered_with_engine(self) -> None:
        """Test 16: All 3 rules can be registered with DesignRuleEngine via add_rule()."""
        from volta.validation.pcb_design_rules import get_pcb_design_rules

        rules = get_pcb_design_rules()
        engine = DesignRuleEngine()
        for rule in rules:
            engine.add_rule(rule)

        assert set(engine.rule_names) == {
            "PCB_CLEARANCE_01",
            "PCB_IMPEDANCE_01",
            "PCB_THERMAL_01",
        }

    def test_engine_run_with_pcb_rules(self) -> None:
        """Test 17: DesignRuleEngine.run() with all 3 PCB rules completes without error."""
        from volta.validation.pcb_design_rules import get_pcb_design_rules

        rules = get_pcb_design_rules()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=0.0, Y=0.0), reference="U1"),
                MockFootprint(position=MockPosition(X=0.1, Y=0.0), reference="U2"),
            ],
            layer_stackup=MockLayerStackup(_impedance=40.0),
        )
        constraints = [
            MockImpedanceConstraint(target_impedance=50.0),
            MockThermalConstraint(component_ref="U1"),
        ]
        config = {
            "PCB_CLEARANCE_01": {"spatial_model": model},
            "PCB_IMPEDANCE_01": {
                "spatial_model": model,
                "constraints": constraints,
            },
            "PCB_THERMAL_01": {
                "spatial_model": model,
                "constraints": constraints,
            },
        }

        engine = DesignRuleEngine(rules=rules, config=config)
        report = engine.run(None)

        # Clearance violation (0.1mm < 0.2mm), impedance violation (40 vs 50 +/-10%),
        # thermal violation (0.1mm < 2.0mm) -- all should fire
        assert report.rules_run == 3
        assert report.rules_failed == 3
        assert report.rules_passed == 0
        assert len(report.violations) >= 3

    def test_engine_run_all_clear(self) -> None:
        """Test 17b: Engine with passing config produces no violations."""
        from volta.validation.pcb_design_rules import get_pcb_design_rules

        rules = get_pcb_design_rules()
        model = MockSpatialModel(
            footprints=[
                MockFootprint(position=MockPosition(X=0.0, Y=0.0), reference="U1"),
                MockFootprint(position=MockPosition(X=50.0, Y=50.0), reference="U2"),
            ],
            layer_stackup=MockLayerStackup(_impedance=50.0),
        )
        constraints = [
            MockImpedanceConstraint(target_impedance=50.0),
            MockThermalConstraint(component_ref="U1"),
        ]
        config = {
            "PCB_CLEARANCE_01": {"spatial_model": model},
            "PCB_IMPEDANCE_01": {
                "spatial_model": model,
                "constraints": constraints,
            },
            "PCB_THERMAL_01": {
                "spatial_model": model,
                "constraints": constraints,
            },
        }

        engine = DesignRuleEngine(rules=rules, config=config)
        report = engine.run(None)

        assert report.rules_run == 3
        assert len(report.violations) == 0
