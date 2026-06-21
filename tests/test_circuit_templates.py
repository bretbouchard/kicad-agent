"""Tests for circuit templates and reasoning chains."""

import pytest


class TestCircuitTemplates:
    """Tests for circuit template module."""

    def test_import(self):
        """Circuit templates module is importable if it exists."""
        try:
            from kicad_agent.analysis.circuit_templates import CircuitTemplateDB
            assert CircuitTemplateDB is not None
        except ImportError:
            pytest.skip("circuit_templates module not present in this version")

    def test_creation(self):
        """CircuitTemplateDB can be created."""
        try:
            from kicad_agent.analysis.circuit_templates import CircuitTemplateDB
        except ImportError:
            pytest.skip("circuit_templates module not present in this version")
        db = CircuitTemplateDB()
        assert db is not None


class TestReasoningChains:
    """Tests for reasoning chains in analysis."""

    def test_import(self):
        """Reasoning chains module is importable if it exists."""
        try:
            from kicad_agent.analysis.reasoning_chains import ReasoningChainDB
            assert ReasoningChainDB is not None
        except ImportError:
            # Module may not exist in this version
            pytest.skip("reasoning_chains module not present in this version")


class TestIntentSchemas:
    """Tests for intent schemas in analysis."""

    def test_import(self):
        """Intent schemas are importable."""
        from kicad_agent.analysis.intent_schemas import (
            DesignGoal,
            DesignIntent,
            SubcircuitIntent,
        )
        assert DesignGoal is not None
        assert DesignIntent is not None
        assert SubcircuitIntent is not None
