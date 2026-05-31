"""Tests for MCP health_check tool (INFRA-02).

Covers: status reporting, uptime tracking, in-flight count, project directory.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_agent.mcp.edit_server import (
    _ALL_TOOLS,
    _META_TOOLS,
    dispatch_tool,
)
from kicad_agent.ops.executor import OperationExecutor


class TestHealthCheckReturnsStatus:
    """health_check returns structured JSON with status, uptime, executor readiness."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_health_check_returns_healthy_status(self, mock_executor: tuple) -> None:
        """health_check returns status=healthy, uptime_seconds > 0, executor_ready=True."""
        executor, base_dir = mock_executor
        result = await dispatch_tool("health_check", {}, executor, base_dir)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["status"] == "healthy"
        assert body["uptime_seconds"] > 0
        assert body["executor_ready"] is True

    @pytest.mark.asyncio
    async def test_health_check_in_flight_zero(self, mock_executor: tuple) -> None:
        """health_check reports in_flight_operations=0 when no ops running."""
        executor, base_dir = mock_executor
        result = await dispatch_tool("health_check", {}, executor, base_dir)
        body = json.loads(result.content[0].text)
        assert body["in_flight_operations"] == 0

    @pytest.mark.asyncio
    async def test_health_check_project_dir(self, mock_executor: tuple) -> None:
        """health_check reports correct project_dir matching base_dir."""
        executor, base_dir = mock_executor
        result = await dispatch_tool("health_check", {}, executor, base_dir)
        body = json.loads(result.content[0].text)
        assert body["project_dir"] == str(base_dir)

    @pytest.mark.asyncio
    async def test_health_check_total_tools_available(self, mock_executor: tuple) -> None:
        """health_check reports total_tools_available matching _ALL_TOOLS length."""
        executor, base_dir = mock_executor
        result = await dispatch_tool("health_check", {}, executor, base_dir)
        body = json.loads(result.content[0].text)
        assert body["total_tools_available"] == len(_ALL_TOOLS)

    def test_health_check_in_meta_tools(self) -> None:
        """health_check is listed in _META_TOOLS with readOnlyHint."""
        names = {t.name for t in _META_TOOLS}
        assert "health_check" in names
        hc_tool = next(t for t in _META_TOOLS if t.name == "health_check")
        assert hc_tool.annotations is not None
        assert hc_tool.annotations.readOnlyHint is True
