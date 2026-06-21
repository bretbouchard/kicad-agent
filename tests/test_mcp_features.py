"""Tests for MCP edit server and graceful shutdown."""

import pytest


class TestMcpEditServer:
    """Tests for MCP edit server."""

    def test_import(self):
        """MCP edit server module is importable."""
        from kicad_agent.mcp import edit_server
        assert edit_server is not None


class TestMcpGracefulShutdown:
    """Tests for MCP graceful shutdown."""

    def test_import(self):
        """MCP server lifespan (graceful shutdown) is importable."""
        from kicad_agent.mcp.edit_server import server_lifespan
        assert callable(server_lifespan)
