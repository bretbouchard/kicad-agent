"""Tests for analysis net classifier module."""

import pytest


class TestNetClassifierModule:
    """Tests for NetClassifier class."""

    def test_import(self):
        """NetClassifier is importable."""
        from kicad_agent.analysis.net_classifier import NetClassifier
        assert NetClassifier is not None


class TestSignalIntegrity:
    """Tests for SignalIntegrity enum."""

    def test_import(self):
        """SignalIntegrity is importable."""
        from kicad_agent.analysis.net_classifier import SignalIntegrity
        assert SignalIntegrity is not None

    def test_values(self):
        """SignalIntegrity has expected values."""
        values = [v for v in SignalIntegrity]
        assert len(values) >= 3


class TestNetImportance:
    """Tests for NetImportance enum."""

    def test_import(self):
        """NetImportance is importable."""
        from kicad_agent.analysis.net_classifier import NetImportance
        assert NetImportance is not None


class TestNetGraph:
    """Tests for NetGraph."""

    def test_import(self):
        """NetGraph is importable."""
        from kicad_agent.analysis.connectivity import NetGraph
        assert NetGraph is not None
