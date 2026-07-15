"""Tests for analysis net graph and connectivity."""

import pytest

from volta.analysis.connectivity import NetGraph


class TestNetGraphDetailed:
    """Detailed tests for NetGraph."""

    def test_import(self):
        """NetGraph is importable."""
        assert NetGraph is not None

    def test_creation(self):
        """NetGraph can be created."""
        graph = NetGraph()
        assert graph is not None
