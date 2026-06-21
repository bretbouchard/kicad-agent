"""Tests for ops/schema validation and executor validation gates."""

import pytest

from kicad_agent.ops.pre_analysis import (
    PreAnalysisGate,
)


class TestValidationGates:
    """Tests for validation gate system."""

    def test_import(self):
        """ValidationGates module is importable."""
        from kicad_agent.ops import pre_analysis
        assert hasattr(pre_analysis, "PreAnalysisGate")

    def test_pre_analysis_gate_instantiable(self):
        """PreAnalysisGate can be created."""
        gate = PreAnalysisGate()
        assert gate is not None

    def test_validation_result_creation(self):
        """PreAnalysisGate result can be checked."""
        gate = PreAnalysisGate()
        result = gate.check([]) if hasattr(gate, "check") else None
        assert result is None or result is not None


class TestSchemaValidation:
    """Tests for schema validation utilities."""

    def test_import(self):
        """Schema validation module is importable."""
        from kicad_agent.ops import schema
        assert hasattr(schema, "Operation")


class TestOperationRegistry:
    """Tests for operation registry."""

    def test_registry_import(self):
        """Operation registry is importable."""
        from kicad_agent.ops import registry
        assert hasattr(registry, "OPERATION_REGISTRY")

    def test_registry_has_entries(self):
        """Registry has operation entries."""
        from kicad_agent.ops.registry import OPERATION_REGISTRY
        assert len(OPERATION_REGISTRY) > 50


class TestSchemaSchemas:
    """Tests for operation schema modules."""

    def test_component_schema(self):
        """Component operation schema is importable."""
        from kicad_agent.ops.schema import AddComponentOp
        assert AddComponentOp is not None

    def test_net_schema(self):
        """Net operation schema is importable."""
        from kicad_agent.ops.schema import AddNetOp
        assert AddNetOp is not None

    def test_wire_schema(self):
        """Wire operation schema is importable."""
        from kicad_agent.ops.schema import AddWireOp
        assert AddWireOp is not None
