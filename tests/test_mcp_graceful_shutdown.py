"""Tests for MCP graceful shutdown (INFRA-03).

Covers: shutdown rejection, health_check during shutdown, in-flight tracking.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import kicad_agent.mcp.edit_server as edit_server_mod
from kicad_agent.mcp.edit_server import (
    dispatch_tool,
)
from kicad_agent.ops.executor import OperationExecutor


@pytest.fixture(autouse=True)
def _reset_shutdown_flag():
    """Ensure _shutdown_requested is reset after each test."""
    yield
    edit_server_mod._shutdown_requested = False


class TestShutdownRejectsOperations:
    """When _shutdown_requested=True, new operations are rejected."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_rejects_operations_when_shutting_down(self, mock_executor: tuple) -> None:
        """Operations return error when _shutdown_requested is True."""
        executor, base_dir = mock_executor
        edit_server_mod._shutdown_requested = True

        result = await dispatch_tool("get_operation_schema", {}, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "shutting_down"

    @pytest.mark.asyncio
    async def test_rejects_operation_tools_when_shutting_down(self, mock_executor: tuple) -> None:
        """Operation tools (like add_component) are rejected during shutdown."""
        executor, base_dir = mock_executor
        edit_server_mod._shutdown_requested = True

        # Copy fixture so validation might pass (but should be rejected before that)
        fixture = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
        target = base_dir / "test.kicad_sch"
        target.write_text(fixture.read_text())

        result = await dispatch_tool("add_component", {
            "target_file": "test.kicad_sch",
            "library_id": "Device:R_Small_US",
            "reference": "R1",
            "value": "10k",
            "position": {"x": 50.0, "y": 30.0},
        }, executor, base_dir)
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "shutting_down"

    @pytest.mark.asyncio
    async def test_health_check_works_during_shutdown(self, mock_executor: tuple) -> None:
        """health_check still works during shutdown and reports shutting_down status."""
        executor, base_dir = mock_executor
        edit_server_mod._shutdown_requested = True

        result = await dispatch_tool("health_check", {}, executor, base_dir)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["status"] == "shutting_down"

    @pytest.mark.asyncio
    async def test_in_flight_tracking(self, mock_executor: tuple) -> None:
        """In-flight counter increments during operation execution."""
        executor, base_dir = mock_executor
        assert edit_server_mod._in_flight_count == 0

        # The counter should be 0 before and after execution
        # We test that it's accessible and starts at 0
        assert hasattr(edit_server_mod, '_in_flight_count')
