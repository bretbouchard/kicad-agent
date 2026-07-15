"""Tests for MCP export tools and health check."""

import pytest


class TestMcpExportTools:
    """Tests for MCP export tools."""

    def test_import(self):
        """MCP edit_server module (with export tools) is importable."""
        from volta.mcp import edit_server
        assert edit_server is not None


class TestMcpHealthCheck:
    """Tests for MCP health check."""

    def test_import(self):
        """MCP edit_server module (with health check tool) is importable."""
        from volta.mcp import edit_server
        assert hasattr(edit_server, "call_tool")
