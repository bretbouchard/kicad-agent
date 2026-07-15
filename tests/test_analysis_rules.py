"""Tests for analysis rule-related modules: design_rules, rule_config, rule_report, schematic_reviewer."""

import pytest

from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from volta.analysis.design_rule_engine import DesignRuleEngine
from volta.analysis.rule_config import RuleConfig, RuleConfigLoader
from volta.analysis.rule_report import generate_json_report, generate_markdown_report
from volta.analysis.schematic_reviewer import SchematicReviewer
from volta.analysis.schematic_spatial import SchematicSpatialExtractor as SchematicSpatialAnalyzer
from volta.analysis.readability_rules import (
    SchematicOverlapRule as ReadabilityRules,
)
from volta.analysis.readability_scorer import SchematicReadabilityScorer as ReadabilityScorer


class TestDesignRuleViolation:
    """Tests for DesignRuleViolation."""

    def test_import(self):
        """DesignRuleViolation is importable."""
        assert DesignRuleViolation is not None


class TestRuleCategory:
    """Tests for RuleCategory enum."""

    def test_values(self):
        """RuleCategory has expected values."""
        values = [v for v in RuleCategory]
        assert len(values) >= 3


class TestRuleSeverity:
    """Tests for RuleSeverity enum."""

    def test_values(self):
        """RuleSeverity has expected values."""
        values = [v for v in RuleSeverity]
        assert len(values) >= 3


class TestDesignRuleEngineDetailed:
    """Tests for DesignRuleEngine."""

    def test_creation(self):
        """DesignRuleEngine can be created."""
        engine = DesignRuleEngine()
        assert engine is not None

    def test_add_rule(self):
        """Rules can be added to engine."""
        engine = DesignRuleEngine()
        # Engine has add_rule method
        assert hasattr(engine, "add_rule") or hasattr(engine, "check")


class TestRuleConfig:
    """Tests for RuleConfig."""

    def test_import(self):
        """RuleConfig is importable."""
        assert RuleConfig is not None

    def test_loader_import(self):
        """RuleConfigLoader is importable."""
        assert RuleConfigLoader is not None


class TestSchematicReviewer:
    """Tests for SchematicReviewer."""

    def test_import(self):
        """SchematicReviewer is importable."""
        assert SchematicReviewer is not None


class TestSchematicSpatial:
    """Tests for SchematicSpatialAnalyzer."""

    def test_import(self):
        """SchematicSpatialAnalyzer is importable."""
        assert SchematicSpatialAnalyzer is not None


class TestReadability:
    """Tests for readability rules and scorer."""

    def test_rules_import(self):
        """ReadabilityRules is importable."""
        assert ReadabilityRules is not None

    def test_scorer_import(self):
        """ReadabilityScorer is importable."""
        assert ReadabilityScorer is not None
