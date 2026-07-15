"""Tests for analysis topology modules: builder, utils, graph."""

import pytest


class TestTopologyBuilder:
    """Tests for TopologyBuilder class."""

    def test_import(self):
        """TopologyBuilder is importable."""
        from volta.analysis.topology_builder import TopologyBuilder
        assert TopologyBuilder is not None

    def test_creation(self):
        """TopologyBuilder can be created."""
        from volta.analysis.topology_builder import TopologyBuilder
        builder = TopologyBuilder()
        assert builder is not None


class TestTopologyUtils:
    """Tests for topology utility functions."""

    def test_build_net_to_nodes_callable(self):
        """build_net_to_nodes is callable."""
        from volta.analysis.topology_utils import build_net_to_nodes
        assert callable(build_net_to_nodes)

    def test_build_node_to_nets_callable(self):
        """build_node_to_nets is callable."""
        from volta.analysis.topology_utils import build_node_to_nets
        assert callable(build_node_to_nets)
