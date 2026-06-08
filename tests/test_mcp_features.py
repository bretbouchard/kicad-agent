"""Tests for MCP edit server and graceful shutdown."""

import pytest


class TestMcpEditServer:
    """Tests for MCP edit server."""

    def test_import(self):
        """MCP edit server is importable."""
        from kicad_agent.mcp.test_edit_server import TestEditServer
        assert TestEditServer is not None


class TestMcpGracefulShutdown:
    """Tests for MCP graceful shutdown."""

    def test_import(self):
        """MCP graceful shutdown module is importable."""
        from kicad_agent.mcp.test_mcp_graceful_shutdown import graceful_shutdown
        assert callable(graceful_shutdown)
