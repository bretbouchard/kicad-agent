"""Tests for export module: Gerber, drill, render, BOM, and CLI wrappers."""

from pathlib import Path

import pytest

from kicad_agent.export import (
    BomResult,
    ExportResult,
    RenderResult,
    export_bom,
    export_drill,
    export_footprint_svg,
    export_gerber,
    export_netlist,
    export_pcb_pdf,
    export_pcb_svg,
    export_position,
    export_schematic_pdf,
    export_schematic_svg,
    export_step,
    export_symbol_svg,
    get_board_statistics,
    parse_bom_csv,
    render_pcb,
    render_pcb_3d,
)


class TestExportResult:
    """Tests for ExportResult dataclass."""

    def test_creation(self):
        """ExportResult can be created with all fields."""
        result = ExportResult(
            success=True,
            output_dir=Path("/tmp/gerber"),
            files=(Path("/tmp/gerber/board.gtl"),),
            command="kicad-cli pcb export gerbers ...",
        )
        assert result.success is True
        assert len(result.files) == 1

    def test_frozen(self):
        """ExportResult is frozen."""
        result = ExportResult(
            success=True,
            output_dir=Path("/tmp"),
            files=(),
            command="",
        )
        with pytest.raises(AttributeError):
            result.success = False


class TestRenderResult:
    """Tests for RenderResult dataclass."""

    def test_creation(self):
        """RenderResult can be created with all fields."""
        result = RenderResult(
            success=True,
            output_path=Path("/tmp/render.png"),
            width_px=1600,
            height_px=1200,
            command="kicad-cli pcb render ...",
        )
        assert result.success is True
        assert result.width_px == 1600


class TestGerberExport:
    """Tests for Gerber export validation."""

    def test_export_gerber_nonexistent_file(self):
        """export_gerber raises FileNotFoundError for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            export_gerber(Path("/nonexistent/board.kicad_pcb"))

    def test_export_gerber_wrong_extension(self):
        """export_gerber raises ValueError for non-.kicad_pcb file."""
        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            export_gerber(Path("/nonexistent/board.kicad_sch"))

    def test_export_drill_nonexistent_file(self):
        """export_drill raises FileNotFoundError for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            export_drill(Path("/nonexistent/board.kicad_pcb"))


class TestRenderExport:
    """Tests for render export validation."""

    def test_render_pcb_nonexistent(self):
        """render_pcb raises FileNotFoundError for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            render_pcb(Path("/nonexistent/board.kicad_pcb"))


class TestExportImports:
    """Verify all export module exports."""

    def test_all_exports_importable(self):
        """All __all__ exports can be imported."""
        from kicad_agent import export
        for name in export.__all__:
            assert hasattr(export, name), f"Missing export: {name}"
