"""Tests for converter functions: to_routing_constraints, to_placement_constraints, to_net_class_defs.

CP-03: PCBConstraint as canonical source with pure converter functions.
"""

from kicad_agent.constraints.converters import (
    to_net_class_defs,
    to_placement_constraints,
    to_routing_constraints,
)
from kicad_agent.constraints.types import (
    ClearanceConstraint,
    ConstraintType,
    DecouplingConstraint,
    DifferentialPairConstraint,
    ImpedanceConstraint,
    ThermalConstraint,
)
from kicad_agent.placement.interactive import ConstraintSet
from kicad_agent.project.design_rules import NetClassDef
from kicad_agent.routing.constraints import RoutingConstraints


class TestToRoutingConstraints:
    """Test to_routing_constraints converter."""

    def test_extracts_clearance_and_width(self):
        """ClearanceConstraint + ImpedanceConstraint produce RoutingConstraints."""
        constraints = [
            ClearanceConstraint(
                net_names=("CLK+", "CLK-"),
                source_rule="impedance_extractor",
                confidence=0.9,
                component_refs=("U1",),
                rationale="High-speed clock pair",
                min_clearance_mm=0.15,
            ),
            ImpedanceConstraint(
                net_names=("USB_DP",),
                source_rule="impedance_extractor",
                confidence=0.85,
                rationale="USB impedance",
                target_impedance_ohm=90.0,
                trace_width_mm=0.12,
            ),
        ]
        result = to_routing_constraints(constraints)
        assert isinstance(result, RoutingConstraints)
        assert result.clearance_mm == 0.15
        assert result.trace_width_mm == 0.12

    def test_ignores_irrelevant_constraints(self):
        """DecouplingConstraint and ThermalConstraint are ignored."""
        constraints = [
            DecouplingConstraint(
                net_names=("VCC",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                ic_ref="U1",
                cap_ref="C1",
                max_distance_mm=2.0,
            ),
            ThermalConstraint(
                net_names=(),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                max_junction_temp_c=100.0,
            ),
        ]
        result = to_routing_constraints(constraints)
        # Should return defaults
        default = RoutingConstraints()
        assert result.clearance_mm == default.clearance_mm
        assert result.trace_width_mm == default.trace_width_mm

    def test_empty_list_returns_defaults(self):
        """Empty constraint list returns default RoutingConstraints."""
        result = to_routing_constraints([])
        default = RoutingConstraints()
        assert result.clearance_mm == default.clearance_mm
        assert result.trace_width_mm == default.trace_width_mm

    def test_takes_tightest_values(self):
        """Multiple constraints: takes smallest clearance and width."""
        constraints = [
            ClearanceConstraint(
                net_names=("A",),
                source_rule="test",
                confidence=0.9,
                rationale="test",
                min_clearance_mm=0.2,
            ),
            ClearanceConstraint(
                net_names=("B",),
                source_rule="test",
                confidence=0.8,
                rationale="test",
                min_clearance_mm=0.1,
            ),
            ImpedanceConstraint(
                net_names=("C",),
                source_rule="test",
                confidence=0.7,
                rationale="test",
                target_impedance_ohm=50.0,
                trace_width_mm=0.2,
            ),
            ImpedanceConstraint(
                net_names=("D",),
                source_rule="test",
                confidence=0.6,
                rationale="test",
                target_impedance_ohm=90.0,
                trace_width_mm=0.1,
            ),
        ]
        result = to_routing_constraints(constraints)
        assert result.clearance_mm == 0.1
        assert result.trace_width_mm == 0.1


class TestToPlacementConstraints:
    """Test to_placement_constraints converter."""

    def test_extracts_from_decoupling_constraint(self):
        """DecouplingConstraint max_distance_mm becomes min_clearance."""
        constraints = [
            DecouplingConstraint(
                net_names=("VCC",),
                source_rule="test",
                confidence=0.75,
                rationale="Decoupling",
                ic_ref="U1",
                cap_ref="C1",
                max_distance_mm=2.0,
            ),
        ]
        result = to_placement_constraints(constraints)
        assert isinstance(result, ConstraintSet)
        assert result.min_clearance == 2.0

    def test_takes_smallest_clearance(self):
        """Takes the tightest (smallest) clearance from all applicable."""
        constraints = [
            DecouplingConstraint(
                net_names=("VCC",),
                source_rule="test",
                confidence=0.75,
                rationale="Decoupling",
                ic_ref="U1",
                cap_ref="C1",
                max_distance_mm=3.0,
            ),
            ThermalConstraint(
                net_names=(),
                source_rule="test",
                confidence=0.7,
                rationale="Thermal",
                component_refs=("U2",),
                max_junction_temp_c=125.0,
                heat_dissipation_w=2.0,
            ),
        ]
        result = to_placement_constraints(constraints)
        assert result.min_clearance <= 3.0


class TestToNetClassDefs:
    """Test to_net_class_defs converter."""

    def test_extracts_from_clearance_and_impedance(self):
        """ClearanceConstraint + ImpedanceConstraint produce NetClassDef."""
        constraints = [
            ClearanceConstraint(
                net_names=("CLK+", "CLK-"),
                source_rule="HighSpeed",
                confidence=0.9,
                rationale="Clock clearance",
                min_clearance_mm=0.15,
                net_class_name="HighSpeed",
            ),
            ImpedanceConstraint(
                net_names=("USB_DP",),
                source_rule="HighSpeed",
                confidence=0.85,
                rationale="USB impedance",
                target_impedance_ohm=90.0,
                trace_width_mm=0.12,
            ),
        ]
        result = to_net_class_defs(constraints)
        assert len(result) == 1
        # Both should merge into one entry
        assert result[0].name == "HighSpeed"
        assert result[0].clearance == 0.15
        assert result[0].track_width == 0.12

    def test_uses_source_rule_when_no_net_class_name(self):
        """When net_class_name is empty, uses source_rule as name."""
        constraints = [
            ClearanceConstraint(
                net_names=("A",),
                source_rule="my_clearance_rule",
                confidence=0.5,
                rationale="test",
                min_clearance_mm=0.25,
            ),
        ]
        result = to_net_class_defs(constraints)
        assert len(result) == 1
        assert result[0].name == "my_clearance_rule"
        assert result[0].clearance == 0.25

    def test_ignores_thermal_and_decoupling(self):
        """ThermalConstraint and DecouplingConstraint produce no NetClassDefs."""
        constraints = [
            ThermalConstraint(
                net_names=(),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                max_junction_temp_c=100.0,
            ),
            DecouplingConstraint(
                net_names=("VCC",),
                source_rule="test",
                confidence=0.5,
                rationale="test",
                ic_ref="U1",
                cap_ref="C1",
                max_distance_mm=2.0,
            ),
        ]
        result = to_net_class_defs(constraints)
        assert len(result) == 0

    def test_merges_same_net_class(self):
        """Multiple constraints for same net_class_name are merged."""
        constraints = [
            ClearanceConstraint(
                net_names=("A",),
                source_rule="DiffPair",
                confidence=0.9,
                rationale="test",
                min_clearance_mm=0.15,
                net_class_name="DiffPair",
            ),
            ImpedanceConstraint(
                net_names=("A+", "A-"),
                source_rule="DiffPair",
                confidence=0.8,
                rationale="test",
                target_impedance_ohm=100.0,
                trace_width_mm=0.1,
            ),
        ]
        result = to_net_class_defs(constraints)
        # Should merge into one entry
        assert len(result) == 1
        assert result[0].name == "DiffPair"
        assert result[0].clearance == 0.15
        assert result[0].track_width == 0.1
