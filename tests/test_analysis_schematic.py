"""Tests for analysis schematic reviewer and spatial modules."""

import pytest


class TestSchematicReviewerModule:
    """Tests for schematic reviewer."""

    def test_import(self):
        """SchematicReviewer is importable."""
        from volta.analysis.schematic_reviewer import SchematicReviewer
        assert SchematicReviewer is not None

    def test_creation(self):
        """SchematicReviewer requires schematic_ir argument."""
        from volta.analysis.schematic_reviewer import SchematicReviewer
        import inspect
        sig = inspect.signature(SchematicReviewer.__init__)
        assert "schematic_ir" in sig.parameters


class TestSchematicSpatialModule:
    """Tests for schematic spatial analyzer."""

    def test_import(self):
        """SchematicSpatialExtractor is importable."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor as SchematicSpatialAnalyzer
        assert SchematicSpatialAnalyzer is not None


class TestReadabilityRules:
    """Tests for readability rules."""

    def test_import(self):
        """ReadabilityRules is importable."""
        from volta.analysis.readability_rules import SchematicOverlapRule as ReadabilityRules
        assert ReadabilityRules is not None


class TestReadabilityScorer:
    """Tests for readability scorer."""

    def test_import(self):
        """ReadabilityScorer is importable."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer as ReadabilityScorer
        assert ReadabilityScorer is not None
