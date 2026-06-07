"""Tests for MCP export/render convenience tools.

Covers: tool registration, dispatch handlers, result formatting,
error handling, and the render.py export module.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Any

import pytest

from kicad_agent.mcp.edit_server import (
    _ALL_TOOLS,
    _META_TOOLS,
    _bom_result_to_mcp,
    _export_result_to_mcp,
    _render_result_to_mcp,
    dispatch_tool,
)
from kicad_agent.ops.executor import OperationExecutor
from mcp import types


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestExportToolRegistration:
    """Verify all 9 export/render tools are registered as meta-tools."""

    EXPORT_TOOL_NAMES = {
        "render_pcb",
        "export_schematic_svg",
        "export_pcb_svg",
        "export_pcb_pdf",
        "export_schematic_bom",
        "export_pcb_step",
        "export_pcb_gerbers",
        "export_pcb_drill",
        "export_pcb_position",
    }

    def test_all_export_tools_registered(self) -> None:
        meta_names = {t.name for t in _META_TOOLS}
        missing = self.EXPORT_TOOL_NAMES - meta_names
        assert missing == set(), f"Missing export tools: {sorted(missing)}"

    def test_meta_tool_count_is_18(self) -> None:
        assert len(_META_TOOLS) == 18

    def test_export_tools_have_read_only_hint(self) -> None:
        for tool in _META_TOOLS:
            if tool.name in self.EXPORT_TOOL_NAMES:
                assert tool.annotations is not None, f"{tool.name} missing annotations"
                assert tool.annotations.readOnlyHint is True, f"{tool.name} should be readOnly"

    def test_export_tools_have_input_schema(self) -> None:
        for tool in _META_TOOLS:
            if tool.name in self.EXPORT_TOOL_NAMES:
                assert isinstance(tool.inputSchema, dict), f"{tool.name} missing inputSchema"
                assert "properties" in tool.inputSchema, f"{tool.name} missing properties"

    def test_export_tools_have_required_file_param(self) -> None:
        for tool in _META_TOOLS:
            if tool.name in self.EXPORT_TOOL_NAMES:
                required = tool.inputSchema.get("required", [])
                assert len(required) == 1, f"{tool.name} should have exactly 1 required param"
                file_param = tool.inputSchema["properties"][required[0]]
                assert file_param.get("type") == "string"

    def test_no_duplicate_export_tool_names(self) -> None:
        all_names = [t.name for t in _ALL_TOOLS]
        assert len(all_names) == len(set(all_names)), "Duplicate tool names detected"

    def test_all_export_tools_have_descriptions(self) -> None:
        for tool in _META_TOOLS:
            if tool.name in self.EXPORT_TOOL_NAMES:
                assert tool.description, f"{tool.name} missing description"
                assert len(tool.description) > 20, f"{tool.name} description too short"

    def test_pcb_tools_require_pcb_file(self) -> None:
        pcb_tools = {
            "render_pcb", "export_pcb_svg", "export_pcb_pdf",
            "export_pcb_step", "export_pcb_gerbers", "export_pcb_drill",
            "export_pcb_position",
        }
        for tool in _META_TOOLS:
            if tool.name in pcb_tools:
                required = tool.inputSchema.get("required", [])
                assert "pcb_file" in required, f"{tool.name} should require pcb_file"

    def test_schematic_tools_require_schematic_file(self) -> None:
        sch_tools = {"export_schematic_svg", "export_schematic_bom"}
        for tool in _META_TOOLS:
            if tool.name in sch_tools:
                required = tool.inputSchema.get("required", [])
                assert "schematic_file" in required, f"{tool.name} should require schematic_file"


# ---------------------------------------------------------------------------
# Result converters
# ---------------------------------------------------------------------------


class TestResultConverters:
    """Test _render_result_to_mcp, _export_result_to_mcp, _bom_result_to_mcp."""

    def test_render_result_to_mcp_success(self) -> None:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output_path = Path("/tmp/render.png")
        mock_result.width_px = 1600
        mock_result.height_px = 1200
        mock_result.command = "kicad-cli pcb render ..."
        mock_result.stderr = ""
        result = _render_result_to_mcp(mock_result)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["width_px"] == 1600
        assert body["height_px"] == 1200
        assert "output_path" in body
        assert "stderr" not in body

    def test_render_result_to_mcp_with_stderr(self) -> None:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output_path = Path("/tmp/render.png")
        mock_result.width_px = 800
        mock_result.height_px = 600
        mock_result.command = "kicad-cli pcb render ..."
        mock_result.stderr = "some warning"
        result = _render_result_to_mcp(mock_result)
        body = json.loads(result.content[0].text)
        assert body["stderr"] == "some warning"

    def test_export_result_to_mcp_success(self) -> None:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output_dir = Path("/tmp/gerber")
        mock_result.files = (Path("/tmp/gerber/board.gtl"), Path("/tmp/gerber/board.gbl"))
        mock_result.command = "kicad-cli pcb export gerbers ..."
        mock_result.stderr = ""
        result = _export_result_to_mcp(mock_result)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["file_count"] == 2
        assert len(body["files"]) == 2

    def test_export_result_to_mcp_empty(self) -> None:
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.output_dir = Path("/tmp")
        mock_result.files = ()
        mock_result.command = "kicad-cli pcb export ..."
        mock_result.stderr = "error output"
        result = _export_result_to_mcp(mock_result)
        body = json.loads(result.content[0].text)
        assert body["success"] is False
        assert body["file_count"] == 0
        assert body["stderr"] == "error output"

    def test_bom_result_to_mcp_success(self) -> None:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output_path = Path("/tmp/BOM.csv")
        mock_result.component_count = 42
        mock_result.unique_components = 15
        mock_result.command = "kicad-cli sch export bom ..."
        mock_result.stderr = ""
        result = _bom_result_to_mcp(mock_result)
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["component_count"] == 42
        assert body["unique_components"] == 15

    def test_bom_result_to_mcp_with_stderr(self) -> None:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output_path = Path("/tmp/BOM.csv")
        mock_result.component_count = 10
        mock_result.unique_components = 5
        mock_result.command = "kicad-cli sch export bom ..."
        mock_result.stderr = "warning"
        result = _bom_result_to_mcp(mock_result)
        body = json.loads(result.content[0].text)
        assert body["stderr"] == "warning"


# ---------------------------------------------------------------------------
# Dispatch handlers (mocked export functions)
# ---------------------------------------------------------------------------


class TestRenderPcbDispatch:
    """Test render_pcb MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_render_pcb_calls_render(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_path=base_dir / "board-render.png",
            width_px=1600,
            height_px=1200,
            command="kicad-cli pcb render ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_render_pcb", return_value=mock_result):
            result = await dispatch_tool(
                "render_pcb", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["width_px"] == 1600

    @pytest.mark.asyncio
    async def test_render_pcb_with_options(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_path=base_dir / "board-render.png",
            width_px=800,
            height_px=600,
            command="kicad-cli pcb render --rotate ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_render_pcb", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "render_pcb", {
                    "pcb_file": "board.kicad_pcb",
                    "width": 800,
                    "height": 600,
                    "rotate": "-45,0,45",
                    "side": "front",
                }, executor, base_dir,
            )
        mock_fn.assert_called_once()
        call_args = mock_fn.call_args
        assert call_args[0][0]["width"] == 800
        assert call_args[0][0]["rotate"] == "-45,0,45"

    @pytest.mark.asyncio
    async def test_render_pcb_file_not_found(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        with patch("kicad_agent.mcp.edit_server._export_render_pcb", side_effect=FileNotFoundError("board.kicad_pcb not found")):
            result = await dispatch_tool(
                "render_pcb", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "file_not_found"


class TestSchematicSvgDispatch:
    """Test export_schematic_svg MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_schematic_svg_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "schematic.svg",),
            command="kicad-cli sch export svg ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_schematic_svg_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_schematic_svg", {"schematic_file": "schematic.kicad_sch"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["file_count"] == 1

    @pytest.mark.asyncio
    async def test_export_schematic_svg_validation_error(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        with patch("kicad_agent.mcp.edit_server._export_schematic_svg_handler", side_effect=ValueError("Not a schematic")):
            result = await dispatch_tool(
                "export_schematic_svg", {"schematic_file": "bad.txt"}, executor, base_dir,
            )
        assert result.isError is True
        body = json.loads(result.content[0].text)
        assert body["error_type"] == "validation_error"


class TestPcbSvgDispatch:
    """Test export_pcb_svg MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_pcb_svg_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "board.svg",),
            command="kicad-cli pcb export svg ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_svg_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_pcb_svg", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_export_pcb_svg_with_layers(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "board.svg",),
            command="kicad-cli pcb export svg ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_svg_handler", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "export_pcb_svg", {
                    "pcb_file": "board.kicad_pcb",
                    "layers": ["F.Cu", "B.Cu"],
                }, executor, base_dir,
            )
        call_args = mock_fn.call_args
        assert call_args[0][0]["layers"] == ["F.Cu", "B.Cu"]


class TestPcbPdfDispatch:
    """Test export_pcb_pdf MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_pcb_pdf_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "board.pdf",),
            command="kicad-cli pcb export pdf ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_pdf_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_pcb_pdf", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True


class TestSchematicBomDispatch:
    """Test export_schematic_bom MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_schematic_bom_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_path=base_dir / "BOM.csv",
            component_count=42,
            unique_components=15,
            command="kicad-cli sch export bom ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_schematic_bom_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_schematic_bom", {"schematic_file": "schematic.kicad_sch"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["component_count"] == 42
        assert body["unique_components"] == 15

    @pytest.mark.asyncio
    async def test_export_schematic_bom_exclude_dnp(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_path=base_dir / "BOM.csv",
            component_count=30,
            unique_components=12,
            command="kicad-cli sch export bom ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_schematic_bom_handler", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "export_schematic_bom", {
                    "schematic_file": "schematic.kicad_sch",
                    "exclude_dnp": True,
                }, executor, base_dir,
            )
        call_args = mock_fn.call_args
        assert call_args[0][0]["exclude_dnp"] is True


class TestPcbStepDispatch:
    """Test export_pcb_step MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_pcb_step_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "board.step",),
            command="kicad-cli pcb export step ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_step_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_pcb_step", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["file_count"] == 1

    @pytest.mark.asyncio
    async def test_export_pcb_step_drill_origin(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "board.step",),
            command="kicad-cli pcb export step ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_step_handler", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "export_pcb_step", {
                    "pcb_file": "board.kicad_pcb",
                    "origin": "drill",
                    "no_dnp": False,
                }, executor, base_dir,
            )
        call_args = mock_fn.call_args
        assert call_args[0][0]["origin"] == "drill"
        assert call_args[0][0]["no_dnp"] is False


class TestPcbGerbersDispatch:
    """Test export_pcb_gerbers MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_pcb_gerbers_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir / "gerber",
            files=(base_dir / "gerber/board.gtl", base_dir / "gerber/board.gbl"),
            command="kicad-cli pcb export gerbers ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_gerbers_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_pcb_gerbers", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True
        assert body["file_count"] == 2

    @pytest.mark.asyncio
    async def test_export_pcb_gerbers_custom_dir(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir / "output",
            files=(),
            command="kicad-cli pcb export gerbers ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_gerbers_handler", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "export_pcb_gerbers", {
                    "pcb_file": "board.kicad_pcb",
                    "output_dir": "output",
                }, executor, base_dir,
            )
        call_args = mock_fn.call_args
        assert call_args[0][0]["output_dir"] == "output"


class TestPcbDrillDispatch:
    """Test export_pcb_drill MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_pcb_drill_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir / "gerber",
            files=(base_dir / "gerber/board.drl",),
            command="kicad-cli pcb export drill ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_drill_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_pcb_drill", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_export_pcb_drill_gerber_format(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir / "gerber",
            files=(),
            command="kicad-cli pcb export drill ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_drill_handler", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "export_pcb_drill", {
                    "pcb_file": "board.kicad_pcb",
                    "format": "gerber",
                }, executor, base_dir,
            )
        call_args = mock_fn.call_args
        assert call_args[0][0]["format"] == "gerber"


class TestPcbPositionDispatch:
    """Test export_pcb_position MCP tool dispatch."""

    @pytest.fixture
    def mock_executor(self, tmp_path: Path) -> tuple[MagicMock, Path]:
        executor = MagicMock(spec=OperationExecutor)
        return executor, tmp_path

    @pytest.mark.asyncio
    async def test_export_pcb_position_success(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(base_dir / "board-pos.csv",),
            command="kicad-cli pcb export pos ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_position_handler", return_value=mock_result):
            result = await dispatch_tool(
                "export_pcb_position", {"pcb_file": "board.kicad_pcb"}, executor, base_dir,
            )
        assert result.isError is not True
        body = json.loads(result.content[0].text)
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_export_pcb_position_csv_inches(self, mock_executor: tuple) -> None:
        executor, base_dir = mock_executor
        mock_result = MagicMock(
            success=True,
            output_dir=base_dir,
            files=(),
            command="kicad-cli pcb export pos ...",
            stderr="",
        )
        with patch("kicad_agent.mcp.edit_server._export_pcb_position_handler", return_value=mock_result) as mock_fn:
            await dispatch_tool(
                "export_pcb_position", {
                    "pcb_file": "board.kicad_pcb",
                    "format": "csv",
                    "units": "in",
                    "side": "front",
                }, executor, base_dir,
            )
        call_args = mock_fn.call_args
        assert call_args[0][0]["format"] == "csv"
        assert call_args[0][0]["units"] == "in"
        assert call_args[0][0]["side"] == "front"


# ---------------------------------------------------------------------------
# render.py module tests
# ---------------------------------------------------------------------------


class TestRenderModule:
    """Test the export/render.py module validation and structure."""

    def test_render_pcb_requires_pcb_file(self) -> None:
        from kicad_agent.export.render import render_pcb
        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            render_pcb(Path("not_a_pcb.txt"))

    def test_render_pcb_path_traversal_rejected(self) -> None:
        from kicad_agent.export.render import render_pcb
        with pytest.raises(ValueError, match="path traversal"):
            render_pcb(Path("../board.kicad_pcb"))

    def test_render_pcb_file_not_found(self) -> None:
        from kicad_agent.export.render import render_pcb
        with pytest.raises(FileNotFoundError):
            render_pcb(Path("nonexistent.kicad_pcb"))

    def test_export_schematic_svg_requires_sch_file(self) -> None:
        from kicad_agent.export.render import export_schematic_svg
        with pytest.raises(ValueError, match="Expected .kicad_sch"):
            export_schematic_svg(Path("not_a_sch.txt"))

    def test_export_schematic_svg_path_traversal_rejected(self) -> None:
        from kicad_agent.export.render import export_schematic_svg
        with pytest.raises(ValueError, match="path traversal"):
            export_schematic_svg(Path("../schematic.kicad_sch"))

    def test_export_pcb_svg_requires_pcb_file(self) -> None:
        from kicad_agent.export.render import export_pcb_svg
        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            export_pcb_svg(Path("not_a_pcb.txt"))

    def test_export_pcb_pdf_requires_pcb_file(self) -> None:
        from kicad_agent.export.render import export_pcb_pdf
        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            export_pcb_pdf(Path("not_a_pcb.txt"))

    def test_render_result_is_frozen_dataclass(self) -> None:
        from kicad_agent.export.render import RenderResult
        result = RenderResult(
            success=True,
            output_path=Path("/tmp/render.png"),
            width_px=1600,
            height_px=1200,
            command="test",
        )
        assert hasattr(result, "__dataclass_fields__")
        # Frozen: cannot set attributes
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]

    def test_export_module_exposes_render(self) -> None:
        from kicad_agent.export import render_pcb
        assert callable(render_pcb)

    def test_export_module_exposes_svg_exports(self) -> None:
        from kicad_agent.export import export_schematic_svg, export_pcb_svg
        assert callable(export_schematic_svg)
        assert callable(export_pcb_svg)

    def test_export_module_exposes_pcb_pdf(self) -> None:
        from kicad_agent.export import export_pcb_pdf
        assert callable(export_pcb_pdf)

    def test_export_module_exposes_render_result(self) -> None:
        from kicad_agent.export import RenderResult
        assert RenderResult is not None
