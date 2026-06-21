"""Tests for export render module."""

from pathlib import Path

import pytest

from kicad_agent.export.render import RenderResult, render_pcb


class TestRenderModuleDetailed:
    """Detailed tests for render module."""

    def test_import(self):
        """RenderResult is importable."""
        assert RenderResult is not None

    def test_render_pcb_callable(self):
        """render_pcb is callable."""
        assert callable(render_pcb)

    def test_render_result_creation(self):
        """RenderResult can be created."""
        result = RenderResult(
            success=False,
            output_path=Path("/tmp/render.png"),
            width_px=800,
            height_px=600,
            command="",
        )
        assert result.width_px == 800
