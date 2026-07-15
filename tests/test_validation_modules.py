"""Tests for spatial reasoning and DRC modules."""

import pytest


class TestSpatialDRC:
    """Tests for spatial DRC module."""

    def test_import(self):
        """Spatial DRC is importable."""
        from volta.validation.spatial_drc import SpatialViolation
        assert SpatialViolation is not None


class TestStructuralValidation:
    """Tests for structural validation."""

    def test_import(self):
        """Structural validation is importable."""
        from volta.validation.structural import StructuralViolation
        assert StructuralViolation is not None


class TestFormatCheck:
    """Tests for format check module."""

    def test_import(self):
        """Format check is importable."""
        from volta.validation.format_check import FormatCheck
        assert FormatCheck is not None


class TestValidatorBase:
    """Tests for validator base module."""

    def test_import(self):
        """Validation pipeline is importable."""
        from volta.validation.pipeline import ValidationPipeline
        assert ValidationPipeline is not None


class TestTopologyUtils:
    """Tests for topology utility module."""

    def test_import(self):
        """Topology utils is importable."""
        from volta.analysis.topology_utils import (
            build_net_to_nodes,
            build_node_to_nets,
        )
        assert callable(build_net_to_nodes)
        assert callable(build_node_to_nets)
