"""Tests for analysis module: public API imports and basic functionality."""

import pytest

from volta.analysis import (
    CircuitClassifier,
    CircuitTopology,
    ClassificationResult,
    DesignFinding,
    DesignGoal,
    DesignIntent,
    DesignReview,
    DesignReviewer,
    DesignRule,
    DesignRuleEngine,
    DesignRuleReport,
    DesignRuleViolation,
    InferenceResult,
    IntentInferrer,
    NetClassification,
    NetClassifier,
    NetImportance,
    NetStats,
    PinRole,
    ReviewCategory,
    ReviewSeverity,
    RuleCategory,
    RuleConfig,
    RuleConfigLoader,
    RuleSeverity,
    SignalIntegrity,
    Subcircuit,
    SubcircuitDetector,
    SubcircuitFeatures,
    SubcircuitType,
    TopologyBuilder,
    TopologyEdge,
    TopologyNode,
    extract_features,
    generate_json_report,
    generate_markdown_report,
    get_builtin_rules,
)


class TestAnalysisImports:
    """Verify all analysis module exports are importable and correctly typed."""

    def test_net_classifier_classes(self):
        """NetClassifier, SignalIntegrity, NetImportance are importable."""
        assert NetClassifier is not None
        assert SignalIntegrity is not None
        assert NetImportance is not None

    def test_topology_classes(self):
        """Topology classes are importable."""
        assert TopologyBuilder is not None
        assert CircuitTopology is not None
        assert TopologyNode is not None
        assert TopologyEdge is not None
        assert NetStats is not None

    def test_classification_types(self):
        """NetClassification and PinRole enums are importable."""
        assert NetClassification is not None
        assert PinRole is not None

    def test_subcircuit_detector(self):
        """SubcircuitDetector and related types are importable."""
        assert SubcircuitDetector is not None
        assert Subcircuit is not None
        assert SubcircuitType is not None

    def test_circuit_classifier(self):
        """CircuitClassifier and ClassificationResult are importable."""
        assert CircuitClassifier is not None
        assert ClassificationResult is not None

    def test_feature_extraction(self):
        """SubcircuitFeatures and extract_features are importable."""
        assert SubcircuitFeatures is not None
        assert callable(extract_features)

    def test_intent_schemas(self):
        """DesignGoal, DesignIntent, SubcircuitIntent are importable."""
        assert DesignGoal is not None
        assert DesignIntent is not None

    def test_intent_inference(self):
        """IntentInferrer and InferenceResult are importable."""
        assert IntentInferrer is not None
        assert InferenceResult is not None

    def test_design_review(self):
        """DesignReviewer and related types are importable."""
        assert DesignReviewer is not None
        assert DesignFinding is not None
        assert DesignReview is not None
        assert ReviewCategory is not None
        assert ReviewSeverity is not None

    def test_design_rules(self):
        """DesignRule types are importable."""
        assert DesignRule is not None
        assert DesignRuleReport is not None
        assert DesignRuleViolation is not None
        assert RuleCategory is not None
        assert RuleSeverity is not None

    def test_design_rule_engine(self):
        """DesignRuleEngine is importable."""
        assert DesignRuleEngine is not None

    def test_builtin_rules(self):
        """get_builtin_rules is callable."""
        assert callable(get_builtin_rules)

    def test_rule_config(self):
        """RuleConfig and RuleConfigLoader are importable."""
        assert RuleConfig is not None
        assert RuleConfigLoader is not None

    def test_rule_report(self):
        """generate_json_report and generate_markdown_report are callable."""
        assert callable(generate_json_report)
        assert callable(generate_markdown_report)


class TestNetClassification:
    """Tests for NetClassification enum."""

    def test_known_values(self):
        """NetClassification has known classification values."""
        values = [v.value for v in NetClassification]
        assert "POWER" in values or "power" in values
        assert "SIGNAL" in values or "signal" in values


class TestPinRole:
    """Tests for PinRole enum."""

    def test_known_values(self):
        """PinRole has known role values."""
        values = [v.value for v in PinRole]
        assert len(values) >= 3  # At least: passives, power, signal


class TestSubcircuitType:
    """Tests for SubcircuitType enum."""

    def test_known_values(self):
        """SubcircuitType has known types."""
        values = [v.value for v in SubcircuitType]
        assert len(values) >= 5


class TestReviewSeverity:
    """Tests for ReviewSeverity enum."""

    def test_known_values(self):
        """ReviewSeverity has expected severity levels."""
        values = [v.value for v in ReviewSeverity]
        assert "INFO" in values or "info" in values
        assert "WARNING" in values or "warning" in values
        assert "CRITICAL" in values or "critical" in values


class TestDesignGoal:
    """Tests for DesignGoal enum."""

    def test_known_values(self):
        """DesignGoal has expected goal categories."""
        values = [v.value for v in DesignGoal]
        assert len(values) >= 5


class TestGetBuiltinRules:
    """Tests for get_builtin_rules."""

    def test_returns_list(self):
        """get_builtin_rules returns a non-empty list."""
        rules = get_builtin_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_rules_have_ids(self):
        """All builtin rules have name attributes."""
        rules = get_builtin_rules()
        for rule in rules:
            assert hasattr(rule, "name")


class TestRuleReportFormatting:
    """Tests for report formatting functions."""

    def test_markdown_report_minimal(self):
        """generate_markdown_report produces markdown string."""
        report = DesignRuleReport(
            schematic_path="test.kicad_sch",
            rules_run=5,
            rules_passed=5,
            rules_failed=0,
            violations=(),
        )
        output = generate_markdown_report(report)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_json_report_minimal(self):
        """generate_json_report produces JSON string."""
        report = DesignRuleReport(
            schematic_path="test.kicad_sch",
            rules_run=5,
            rules_passed=5,
            rules_failed=0,
            violations=(),
        )
        output = generate_json_report(report)
        assert isinstance(output, str)
        import json
        parsed = json.loads(output)
        assert "schematic_path" in parsed
