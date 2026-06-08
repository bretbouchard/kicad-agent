"""Tests for MCP export tools and health check."""

import pytest


class TestMcpExportTools:
    """Tests for MCP export tools."""

    def test_import(self):
        """MCP export tools module is importable."""
        from kicad_agent.mcp.test_mcp_export_tools import TestMcpExportTools
        assert TestMcpExportTools is not None


class TestMcpHealthCheck:
    """Tests for MCP health check."""

    def test_import(self):
        """MCP health check module is importable."""
        from kicad_agent.mcp.test_mcp_health_check import TestMcpHealthCheck
        assert TestMcpHealthCheck is not None
