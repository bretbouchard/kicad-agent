"""Tests for analysis schematic reviewer and spatial modules."""

import pytest


class TestSchematicReviewerModule:
    """Tests for schematic reviewer."""

    def test_import(self):
        """SchematicReviewer is importable."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer
        assert SchematicReviewer is not None

    def test_creation(self):
        """SchematicReviewer can be created."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer
        reviewer = SchematicReviewer()
        assert reviewer is not None


class TestSchematicSpatialModule:
    """Tests for schematic spatial analyzer."""

    def test_import(self):
        """SchematicSpatialAnalyzer is importable."""
        from kicad_agent.analysis.schematic_spatial import SchematicSpatialAnalyzer
        assert SchematicSpatialAnalyzer is not None


class TestReadabilityRules:
    """Tests for readability rules."""

    def test_import(self):
        """ReadabilityRules is importable."""
        from kicad_agent.analysis.readability_rules import ReadabilityRules
        assert ReadabilityRules is not None


class TestReadabilityScorer:
    """Tests for readability scorer."""

    def test_import(self):
        """ReadabilityScorer is importable."""
        from kicad_agent.analysis.readability_scorer import ReadabilityScorer
        assert ReadabilityScorer is not None
