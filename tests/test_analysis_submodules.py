"""Tests for analysis sub-modules: connectivity, net_classifier, topology."""

import pytest


class TestNetGraph:
    """Tests for NetGraph."""

    def test_import(self):
        """NetGraph is importable."""
        from volta.analysis.connectivity import NetGraph
        assert NetGraph is not None

    def test_empty_graph(self):
        """Empty NetGraph can be created."""
        from volta.analysis.connectivity import NetGraph
        g = NetGraph()
        assert g is not None


class TestCircuitTopology:
    """Tests for CircuitTopology."""

    def test_import(self):
        """CircuitTopology is importable."""
        from volta.analysis.topology_graph import CircuitTopology
        assert CircuitTopology is not None

    def test_creation(self):
        """CircuitTopology is a dataclass with required fields."""
        from volta.analysis.topology_graph import CircuitTopology
        import dataclasses
        assert dataclasses.is_dataclass(CircuitTopology)


class TestTopologyNode:
    """Tests for TopologyNode."""

    def test_import(self):
        """TopologyNode is importable."""
        from volta.analysis.topology_graph import TopologyNode
        assert TopologyNode is not None


class TestSubcircuitDetector:
    """Tests for SubcircuitDetector."""

    def test_import(self):
        """SubcircuitDetector is importable."""
        from volta.analysis.subcircuit_detector import SubcircuitDetector
        assert SubcircuitDetector is not None


class TestCircuitClassifierModule:
    """Tests for CircuitClassifier."""

    def test_import(self):
        """CircuitClassifier is importable."""
        from volta.analysis.circuit_classifier import CircuitClassifier
        assert CircuitClassifier is not None


class TestFeatureExtraction:
    """Tests for feature extraction."""

    def test_extract_features_import(self):
        """extract_features is callable."""
        from volta.analysis.feature_extraction import extract_features
        assert callable(extract_features)

    def test_subcircuit_features_import(self):
        """SubcircuitFeatures is importable."""
        from volta.analysis.feature_extraction import SubcircuitFeatures
        assert SubcircuitFeatures is not None
