"""TDD tests for design rule engine and built-in rules.

DOMAIN-04: Domain-specific DRC beyond KiCad ERC/DRC.

Tests cover:
- DesignRuleViolation schema validation
- DesignRuleReport schema with summary
- DesignRuleEngine orchestration (no rules, mock rules, errors, disable)
- Custom rule ABC inheritance
- 8 built-in rules with topology-adapted test data
"""
from __future__ import annotations

import pytest

from volta.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)

# These will be implemented:
from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleReport,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from volta.analysis.design_rule_engine import DesignRuleEngine


# ---------------------------------------------------------------------------
# Topology helpers -- build test topologies using REAL types
# ---------------------------------------------------------------------------

_EMPTY_TOPOLOGY = CircuitTopology(
    nodes=(),
    edges=(),
    input_nets=(),
    output_nets=(),
    power_nets=(),
    signal_paths=(),
    stats={"component_count": 0, "net_count": 0, "signal_path_count": 0,
           "feedback_count": 0, "net_stats": {}},
)


def _ic_node(ref: str, lib_id: str, component_type: str = "ic",
             power_pins: tuple[str, ...] = (),
             input_pins: tuple[str, ...] = (),
             output_pins: tuple[str, ...] = ()) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id=lib_id,
        component_type=component_type,
        pin_count=max(len(power_pins), 1) + len(input_pins) + len(output_pins),
        power_pins=power_pins,
        input_pins=input_pins,
        output_pins=output_pins,
    )


def _cap_node(ref: str) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id="Device:C",
        component_type="capacitor",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _resistor_node(ref: str) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id="Device:R",
        component_type="resistor",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _diode_node(ref: str, lib_id: str = "Device:D") -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id=lib_id,
        component_type="diode",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _connector_node(ref: str) -> TopologyNode:
    return TopologyNode(
        ref=ref,
        lib_id="Connector:AudioJack2",
        component_type="connector",
        pin_count=2,
        power_pins=(),
        input_pins=(),
        output_pins=(),
    )


def _make_edge(source_ref: str, target_ref: str, net_name: str,
               signal_direction: str = "forward") -> TopologyEdge:
    return TopologyEdge(
        net_name=net_name,
        source_ref=source_ref,
        source_pin="1",
        target_ref=target_ref,
        target_pin="1",
        classification=None,  # type: ignore[arg-type]
        signal_direction=signal_direction,
    )


def _make_topology(
    nodes: tuple[TopologyNode, ...] = (),
    edges: tuple[TopologyEdge, ...] = (),
    input_nets: tuple[str, ...] = (),
    output_nets: tuple[str, ...] = (),
    power_nets: tuple[str, ...] = (),
) -> CircuitTopology:
    return CircuitTopology(
        nodes=nodes,
        edges=edges,
        input_nets=input_nets,
        output_nets=output_nets,
        power_nets=power_nets,
        signal_paths=(),
        stats={"component_count": len(nodes), "net_count": 0,
               "signal_path_count": 0, "feedback_count": 0, "net_stats": {}},
    )


# ---------------------------------------------------------------------------
# Task 1: Schema, ABC, Engine tests
# ---------------------------------------------------------------------------


class TestDesignRuleViolationSchema:
    """Test DesignRuleViolation Pydantic schema validation."""

    def test_valid_violation(self):
        """Test 1: Violation validates with required fields."""
        v = DesignRuleViolation(
            rule_id="BYPASS_CAP_01",
            description="U1 has no bypass capacitor",
            severity=RuleSeverity.WARNING,
            location="U1",
            suggestion="Add 100nF ceramic cap",
        )
        assert v.rule_id == "BYPASS_CAP_01"
        assert v.severity == RuleSeverity.WARNING
        assert v.location == "U1"
        assert v.suggestion == "Add 100nF ceramic cap"

    def test_empty_rule_id_rejected(self):
        """Test 2: Empty rule_id is rejected."""
        with pytest.raises(Exception):
            DesignRuleViolation(
                rule_id="",
                description="test",
                severity=RuleSeverity.WARNING,
                location="U1",
            )

    def test_invalid_rule_id_format_rejected(self):
        """Rule ID must match UPPER_CASE_NN pattern."""
        with pytest.raises(Exception):
            DesignRuleViolation(
                rule_id="invalid",
                description="test",
                severity=RuleSeverity.WARNING,
                location="U1",
            )

    def test_affected_components_default_empty(self):
        """affected_components defaults to empty tuple."""
        v = DesignRuleViolation(
            rule_id="TEST_01",
            description="test",
            severity=RuleSeverity.INFO,
            location="U1",
        )
        assert v.affected_components == ()

    def test_details_default_empty(self):
        """details defaults to empty dict."""
        v = DesignRuleViolation(
            rule_id="TEST_01",
            description="test",
            severity=RuleSeverity.INFO,
            location="U1",
        )
        assert v.details == {}


class TestDesignRuleReportSchema:
    """Test DesignRuleReport schema with summary computation."""

    def test_report_with_violations_computes_summary(self):
        """Test 3-4: Report computes summary counts by severity."""
        v1 = DesignRuleViolation(
            rule_id="TEST_01", description="critical",
            severity=RuleSeverity.CRITICAL, location="U1",
        )
        v2 = DesignRuleViolation(
            rule_id="TEST_02", description="warning",
            severity=RuleSeverity.WARNING, location="U2",
        )
        v3 = DesignRuleViolation(
            rule_id="TEST_03", description="info",
            severity=RuleSeverity.INFO, location="U3",
        )
        report = DesignRuleReport(
            violations=(v1, v2, v3),
            rules_run=3,
            rules_failed=3,
        )
        assert report.summary["CRITICAL"] == 1
        assert report.summary["WARNING"] == 1
        assert report.summary["INFO"] == 1
        assert report.summary["SUGGESTION"] == 0

    def test_empty_report_summary(self):
        """Empty report has all-zero summary."""
        report = DesignRuleReport()
        assert report.summary["CRITICAL"] == 0
        assert report.summary["WARNING"] == 0
        assert report.summary["SUGGESTION"] == 0
        assert report.summary["INFO"] == 0

    def test_report_tracks_rules_passed(self):
        """Report tracks how many rules had no violations."""
        report = DesignRuleReport(rules_run=5, rules_passed=3, rules_failed=2)
        assert report.rules_run == 5
        assert report.rules_passed == 3
        assert report.rules_failed == 2


class TestDesignRuleEngine:
    """Test DesignRuleEngine orchestration."""

    def test_engine_with_no_rules(self):
        """Test 5: Engine with no rules returns empty report."""
        engine = DesignRuleEngine(rules=[])
        report = engine.run(_EMPTY_TOPOLOGY)
        assert report.violations == ()
        assert report.rules_run == 0
        assert report.rules_passed == 0

    def test_engine_runs_mock_rule(self):
        """Test 6: Engine runs a mock rule and returns violations."""

        class MockRule(DesignRule):
            name = "MOCK_01"
            category = RuleCategory.BYPASS_CAPS
            default_severity = RuleSeverity.WARNING
            description = "mock rule"

            def check(self, topology, config=None):
                return [DesignRuleViolation(
                    rule_id="MOCK_01",
                    description="Mock violation for testing",
                    severity=RuleSeverity.WARNING,
                    location="U1",
                    suggestion="Fix the mock issue",
                )]

        engine = DesignRuleEngine(rules=[MockRule()])
        report = engine.run(_EMPTY_TOPOLOGY)
        assert len(report.violations) == 1
        assert report.violations[0].rule_id == "MOCK_01"
        assert report.rules_failed == 1
        assert report.rules_passed == 0

    def test_engine_runs_multiple_rules(self):
        """Test 7: Engine runs multiple rules and aggregates results."""

        class Rule1(DesignRule):
            name = "RULE1_01"
            category = RuleCategory.BYPASS_CAPS
            default_severity = RuleSeverity.WARNING
            description = "rule 1"

            def check(self, topology, config=None):
                return [DesignRuleViolation(
                    rule_id="RULE1_01", description="v1",
                    severity=RuleSeverity.WARNING, location="U1",
                )]

        class Rule2(DesignRule):
            name = "RULE2_01"
            category = RuleCategory.FEEDBACK
            default_severity = RuleSeverity.CRITICAL
            description = "rule 2"

            def check(self, topology, config=None):
                return [DesignRuleViolation(
                    rule_id="RULE2_01", description="v2",
                    severity=RuleSeverity.CRITICAL, location="U2",
                )]

        engine = DesignRuleEngine(rules=[Rule1(), Rule2()])
        report = engine.run(_EMPTY_TOPOLOGY)
        assert len(report.violations) == 2
        assert report.rules_failed == 2
        # CRITICAL should sort before WARNING
        assert report.violations[0].severity == RuleSeverity.CRITICAL

    def test_engine_skips_disabled_rules(self):
        """Test 8: Engine skips disabled rules."""

        class AlwaysFailRule(DesignRule):
            name = "ALWAYS_01"
            category = RuleCategory.BYPASS_CAPS
            default_severity = RuleSeverity.WARNING
            description = "always fails"

            def check(self, topology, config=None):
                return [DesignRuleViolation(
                    rule_id="ALWAYS_01", description="fail",
                    severity=RuleSeverity.WARNING, location="U1",
                )]

        engine = DesignRuleEngine(
            rules=[AlwaysFailRule()],
            disabled_rules={"ALWAYS_01"},
        )
        report = engine.run(_EMPTY_TOPOLOGY)
        assert len(report.violations) == 0
        assert report.rules_run == 0

    def test_engine_handles_rule_errors(self):
        """Test 9: Engine handles rule errors gracefully."""

        class ErrorRule(DesignRule):
            name = "ERROR_01"
            category = RuleCategory.BYPASS_CAPS
            default_severity = RuleSeverity.CRITICAL
            description = "always raises"

            def check(self, topology, config=None):
                raise RuntimeError("Simulated rule error")

        engine = DesignRuleEngine(rules=[ErrorRule()])
        report = engine.run(_EMPTY_TOPOLOGY)
        # Should not crash -- should produce a meta-violation
        assert len(report.violations) == 1
        assert "failed" in report.violations[0].description.lower()
        assert report.violations[0].severity == RuleSeverity.WARNING

    def test_engine_add_rule(self):
        """Engine supports adding rules after construction."""

        class NewRule(DesignRule):
            name = "NEW_01"
            category = RuleCategory.LAYOUT
            default_severity = RuleSeverity.INFO
            description = "new rule"

            def check(self, topology, config=None):
                return []

        engine = DesignRuleEngine(rules=[])
        engine.add_rule(NewRule())
        assert "NEW_01" in engine.rule_names

    def test_engine_enable_disable_rule(self):
        """Engine supports enabling/disabling rules dynamically."""

        class TestRule(DesignRule):
            name = "DYN_01"
            category = RuleCategory.LAYOUT
            default_severity = RuleSeverity.INFO
            description = "dynamic rule"

            def check(self, topology, config=None):
                return [DesignRuleViolation(
                    rule_id="DYN_01", description="v",
                    severity=RuleSeverity.INFO, location="U1",
                )]

        engine = DesignRuleEngine(rules=[TestRule()])
        engine.disable_rule("DYN_01")
        report = engine.run(_EMPTY_TOPOLOGY)
        assert len(report.violations) == 0

        engine.enable_rule("DYN_01")
        report = engine.run(_EMPTY_TOPOLOGY)
        assert len(report.violations) == 1


class TestCustomRule:
    """Test 10: Custom rule subclass works via ABC inheritance."""

    def test_custom_rule_inherits_abc(self):
        """Custom rules subclassing DesignRule work correctly."""

        class MyCustomRule(DesignRule):
            name = "CUSTOM_01"
            category = RuleCategory.SIGNAL
            default_severity = RuleSeverity.SUGGESTION
            description = "my custom rule"

            def check(self, topology, config=None):
                return [DesignRuleViolation(
                    rule_id="CUSTOM_01",
                    description="Custom violation",
                    severity=RuleSeverity.SUGGESTION,
                    location="U1",
                    suggestion="Fix it",
                )]

        rule = MyCustomRule()
        assert rule.name == "CUSTOM_01"
        assert rule.category == RuleCategory.SIGNAL
        violations = rule.check(_EMPTY_TOPOLOGY)
        assert len(violations) == 1
        assert violations[0].rule_id == "CUSTOM_01"


# ---------------------------------------------------------------------------
# Task 2: Built-in rules tests
# ---------------------------------------------------------------------------


class TestBypassCapRule:
    """Test BYPASS_CAP_01 rule."""

    def test_flags_ic_without_bypass_cap(self):
        """Test 1: IC without decoupling cap on power net is flagged."""
        from volta.analysis.builtin_rules import BypassCapRule

        ic = _ic_node("U1", "NE5532", power_pins=("4", "8"))
        # Power net edges but no cap
        edges = (
            _make_edge("U1", "R1", "+15V", "power"),
            _make_edge("U1", "R2", "-15V", "power"),
        )
        topo = _make_topology(
            nodes=(ic, _resistor_node("R1"), _resistor_node("R2")),
            edges=edges,
            power_nets=("+15V", "-15V"),
        )

        rule = BypassCapRule()
        violations = rule.check(topo)
        assert len(violations) >= 1
        assert any(v.location == "U1" for v in violations)

    def test_no_flag_ic_with_bypass_cap(self):
        """Test 2: IC with bypass cap is NOT flagged."""
        from volta.analysis.builtin_rules import BypassCapRule

        ic = _ic_node("U1", "NE5532", power_pins=("4", "8"))
        cap = _cap_node("C1")
        # Cap shares power net with IC
        edges = (
            _make_edge("U1", "C1", "+15V", "power"),
            _make_edge("U1", "R1", "-15V", "power"),
            _make_edge("C1", "U1", "+15V", "power"),
        )
        topo = _make_topology(
            nodes=(ic, cap, _resistor_node("R1")),
            edges=edges,
            power_nets=("+15V", "-15V"),
        )

        rule = BypassCapRule()
        violations = rule.check(topo)
        # Should not flag U1 for +15V since C1 is there
        plus_15v_violations = [
            v for v in violations
            if v.details.get("power_net") == "+15V"
        ]
        assert len(plus_15v_violations) == 0

    def test_ignores_non_ic_components(self):
        """Non-IC components are not flagged."""
        from volta.analysis.builtin_rules import BypassCapRule

        res = _resistor_node("R1")
        topo = _make_topology(
            nodes=(res,),
            edges=(_make_edge("R1", "R2", "+15V", "power"),),
            power_nets=("+15V",),
        )

        rule = BypassCapRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestFeedbackRule:
    """Test FEEDBACK_01 rule."""

    def test_flags_opamp_without_comp_cap(self):
        """Test 4: Op-amp with feedback resistor but no comp cap is flagged."""
        from volta.analysis.builtin_rules import FeedbackCompRule

        opamp = _ic_node("U1", "NE5532", output_pins=("1",), input_pins=("2", "3"))
        feedback_r = _resistor_node("R1")
        # Feedback path: U1 output -> R1 -> U1 inverting input
        edges = (
            _make_edge("U1", "R1", "FB_NET", "feedback"),
            _make_edge("R1", "U1", "FB_NET", "feedback"),
        )
        topo = _make_topology(
            nodes=(opamp, feedback_r),
            edges=edges,
        )

        rule = FeedbackCompRule()
        violations = rule.check(topo)
        assert len(violations) >= 1
        assert any(v.location == "U1" for v in violations)

    def test_no_flag_opamp_with_comp_cap(self):
        """Test 5: Op-amp with comp cap in feedback is NOT flagged."""
        from volta.analysis.builtin_rules import FeedbackCompRule

        opamp = _ic_node("U1", "NE5532", output_pins=("1",), input_pins=("2", "3"))
        feedback_r = _resistor_node("R1")
        comp_cap = _cap_node("C1")
        # Feedback with both R and C
        edges = (
            _make_edge("U1", "R1", "FB_NET", "feedback"),
            _make_edge("R1", "U1", "FB_NET", "feedback"),
            _make_edge("U1", "C1", "FB_NET", "feedback"),
            _make_edge("C1", "U1", "FB_NET", "feedback"),
        )
        topo = _make_topology(
            nodes=(opamp, feedback_r, comp_cap),
            edges=edges,
        )

        rule = FeedbackCompRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestImpedanceRule:
    """Test IMPEDANCE_01 rule."""

    def test_flags_high_speed_net_without_termination(self):
        """Test 6: High-speed net without series termination is flagged."""
        from volta.analysis.builtin_rules import ImpedanceRule

        ic1 = _ic_node("U1", "RP2040", output_pins=("1",))
        ic2 = _ic_node("U2", "CD4066", input_pins=("1",))
        edges = (
            _make_edge("U1", "U2", "SPI_CLK"),
        )
        topo = _make_topology(
            nodes=(ic1, ic2),
            edges=edges,
        )

        rule = ImpedanceRule()
        violations = rule.check(topo)
        assert len(violations) >= 1
        assert any("SPI_CLK" in v.location for v in violations)

    def test_no_flag_power_net(self):
        """Power nets are not flagged by impedance rule."""
        from volta.analysis.builtin_rules import ImpedanceRule

        ic1 = _ic_node("U1", "RP2040", power_pins=("1",))
        ic2 = _ic_node("U2", "NE5532", power_pins=("1",))
        edges = (_make_edge("U1", "U2", "SPI_VCC", "power"),)
        topo = _make_topology(
            nodes=(ic1, ic2),
            edges=edges,
            power_nets=("SPI_VCC",),
        )

        rule = ImpedanceRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestThermalRule:
    """Test THERMAL_01 rule."""

    def test_flags_power_regulator(self):
        """Test 7: Power regulator without thermal pad is flagged."""
        from volta.analysis.builtin_rules import ThermalRule

        reg = _ic_node("U1", "LM7805", power_pins=("1",))
        topo = _make_topology(nodes=(reg,))

        rule = ThermalRule()
        violations = rule.check(topo)
        assert len(violations) >= 1
        assert any(v.location == "U1" for v in violations)

    def test_no_flag_regular_ic(self):
        """Regular op-amps are not flagged by thermal rule."""
        from volta.analysis.builtin_rules import ThermalRule

        opamp = _ic_node("U1", "NE5532")
        topo = _make_topology(nodes=(opamp,))

        rule = ThermalRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestGroundRule:
    """Test GROUND_01 rule."""

    def test_flags_unconnected_ground_nets(self):
        """Test 8: Multiple ground nets without connection are flagged."""
        from volta.analysis.builtin_rules import GroundRule

        # IC1 on GND, IC2 on GNDA -- no component bridges them
        ic1 = _ic_node("U1", "NE5532")
        ic2 = _ic_node("U2", "TL072")
        edges = (
            _make_edge("U1", "R1", "GND", "power"),
            _make_edge("U2", "R2", "GNDA", "power"),
        )
        topo = _make_topology(
            nodes=(ic1, ic2, _resistor_node("R1"), _resistor_node("R2")),
            edges=edges,
            power_nets=("GND", "GNDA"),
        )

        rule = GroundRule()
        violations = rule.check(topo)
        assert len(violations) >= 1

    def test_single_ground_not_flagged(self):
        """Single ground net is not flagged."""
        from volta.analysis.builtin_rules import GroundRule

        ic = _ic_node("U1", "NE5532")
        topo = _make_topology(nodes=(ic,))

        rule = GroundRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestPowerRule:
    """Test POWER_01 rule."""

    def test_flags_power_net_without_bulk_cap(self):
        """Test 9: Power net without bulk cap is flagged."""
        from volta.analysis.builtin_rules import PowerFilterRule

        ic = _ic_node("U1", "NE5532", power_pins=("1",))
        edges = (
            _make_edge("U1", "R1", "+15V", "power"),
        )
        topo = _make_topology(
            nodes=(ic, _resistor_node("R1")),
            edges=edges,
            power_nets=("+15V",),
        )

        rule = PowerFilterRule()
        violations = rule.check(topo)
        assert len(violations) >= 1
        assert any("+15V" in v.location for v in violations)

    def test_no_flag_power_net_with_cap(self):
        """Power net with capacitor is not flagged."""
        from volta.analysis.builtin_rules import PowerFilterRule

        ic = _ic_node("U1", "NE5532", power_pins=("1",))
        cap = _cap_node("C1")
        edges = (
            _make_edge("U1", "C1", "+15V", "power"),
            _make_edge("C1", "U1", "+15V", "power"),
        )
        topo = _make_topology(
            nodes=(ic, cap),
            edges=edges,
            power_nets=("+15V",),
        )

        rule = PowerFilterRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestSignalRule:
    """Test SIGNAL_01 rule."""

    def test_flags_input_without_protection(self):
        """Test 10: Input net without protection is flagged."""
        from volta.analysis.builtin_rules import InputProtectionRule

        ic = _ic_node("U1", "NE5532", input_pins=("1",))
        conn = _connector_node("J1")
        edges = (
            _make_edge("J1", "U1", "AUDIO_IN"),
        )
        topo = _make_topology(
            nodes=(ic, conn),
            edges=edges,
            input_nets=("AUDIO_IN",),
        )

        rule = InputProtectionRule()
        violations = rule.check(topo)
        assert len(violations) >= 1
        assert any("AUDIO_IN" in v.location for v in violations)

    def test_no_flag_protected_input(self):
        """Input net with series resistor is not flagged."""
        from volta.analysis.builtin_rules import InputProtectionRule

        ic = _ic_node("U1", "NE5532", input_pins=("1",))
        conn = _connector_node("J1")
        res = _resistor_node("R1")
        edges = (
            _make_edge("J1", "R1", "AUDIO_IN"),
            _make_edge("R1", "U1", "AUDIO_IN"),
        )
        topo = _make_topology(
            nodes=(ic, conn, res),
            edges=edges,
            input_nets=("AUDIO_IN",),
        )

        rule = InputProtectionRule()
        violations = rule.check(topo)
        assert len(violations) == 0


class TestLayoutRule:
    """Test LAYOUT_01 rule."""

    def test_flags_high_fanout_net(self):
        """Test 11: Net with many connections is flagged."""
        from volta.analysis.builtin_rules import LayoutRule

        nodes = tuple(
            _ic_node(f"U{i}", f"IC_{i}") for i in range(7)
        )
        edges = tuple(
            _make_edge("U0", f"U{i}", "BUS_NET")
            for i in range(1, 7)
        )
        topo = _make_topology(nodes=nodes, edges=edges)

        rule = LayoutRule()
        violations = rule.check(topo)
        assert len(violations) >= 1

    def test_respects_custom_threshold(self):
        """Layout rule respects custom max_components config."""
        from volta.analysis.builtin_rules import LayoutRule

        nodes = tuple(
            _ic_node(f"U{i}", f"IC_{i}") for i in range(4)
        )
        edges = tuple(
            _make_edge("U0", f"U{i}", "BUS_NET")
            for i in range(1, 4)
        )
        topo = _make_topology(nodes=nodes, edges=edges)

        rule = LayoutRule()
        # Default threshold 5 -> 3 connections should not flag
        violations = rule.check(topo)
        assert len(violations) == 0

        # Custom threshold 2 -> should flag
        violations = rule.check(topo, config={"max_components_per_net": 2})
        assert len(violations) >= 1


class TestBuiltinRules:
    """Test get_builtin_rules() function."""

    def test_returns_8_rules(self):
        """Test 12: get_builtin_rules returns 8 rule instances."""
        from volta.analysis.builtin_rules import get_builtin_rules

        rules = get_builtin_rules()
        assert len(rules) == 8

        names = {r.name for r in rules}
        assert "BYPASS_CAP_01" in names
        assert "FEEDBACK_01" in names
        assert "IMPEDANCE_01" in names
        assert "THERMAL_01" in names
        assert "GROUND_01" in names
        assert "POWER_01" in names
        assert "SIGNAL_01" in names
        assert "LAYOUT_01" in names

    def test_all_rules_are_design_rule_subclasses(self):
        """All built-in rules subclass DesignRule."""
        from volta.analysis.builtin_rules import get_builtin_rules

        rules = get_builtin_rules()
        for rule in rules:
            assert isinstance(rule, DesignRule)


class TestEngineIntegration:
    """Integration test: run full engine with all built-in rules."""

    def test_full_engine_run(self):
        """Engine runs all 8 built-in rules on a topology."""
        from volta.analysis.builtin_rules import get_builtin_rules

        rules = get_builtin_rules()
        engine = DesignRuleEngine(rules=rules)

        # Simple topology: op-amp with no bypass cap
        ic = _ic_node("U1", "NE5532", power_pins=("4", "8"))
        edges = (
            _make_edge("U1", "R1", "+15V", "power"),
        )
        topo = _make_topology(
            nodes=(ic, _resistor_node("R1")),
            edges=edges,
            power_nets=("+15V",),
        )

        report = engine.run(topo)
        assert report.rules_run == 8
        assert len(report.violations) >= 1
        assert report.elapsed_ms >= 0
        assert isinstance(report.summary, dict)
