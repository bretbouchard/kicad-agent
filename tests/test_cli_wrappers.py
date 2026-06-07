"""Tests for kicad-cli wrappers in export/cli_wrappers.py.

Tests cover 6 new kicad-cli wrappers: render_pcb_3d, export_schematic_svg,
export_symbol_svg, export_footprint_svg, export_pcb_svg, export_pcb_pdf.
All tests mock subprocess.run to avoid kicad-cli dependency in CI.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.export.cli_wrappers import (
    export_footprint_svg,
    export_pcb_pdf,
    export_pcb_svg,
    export_schematic_svg,
    export_symbol_svg,
    render_pcb_3d,
)
from kicad_agent.export.gerber import ExportResult


# --- Shared fixtures ---

@pytest.fixture
def fake_pcb(tmp_path):
    """Create a fake .kicad_pcb file."""
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20221018))")
    return pcb


@pytest.fixture
def fake_sch(tmp_path):
    """Create a fake .kicad_sch file."""
    sch = tmp_path / "schematic.kicad_sch"
    sch.write_text("(kicad_sch (version 20221018))")
    return sch


@pytest.fixture
def fake_sym(tmp_path):
    """Create a fake .kicad_sym file."""
    sym = tmp_path / "library.kicad_sym"
    sym.write_text('(kicad_symbol_lib (version 20221018))')
    return sym


@pytest.fixture
def fake_fp(tmp_path):
    """Create a fake .kicad_mod file."""
    fp = tmp_path / "footprint.kicad_mod"
    fp.write_text('(module "TEST" (layer "F.Cu"))')
    return fp


@pytest.fixture
def mock_kicad_cli():
    """Patch subprocess.run to simulate successful kicad-cli execution."""
    with patch("kicad_agent.export.gerber.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_cli_resolver():
    """Patch find_kicad_cli to return a fake path."""
    with patch("kicad_agent.export.gerber.find_kicad_cli") as mock_find:
        mock_cli = MagicMock()
        mock_cli.path = "/usr/local/bin/kicad-cli"
        mock_find.return_value = mock_cli
        yield mock_find


# === render_pcb_3d tests ===


class TestRenderPcb3d:
    """Tests for render_pcb_3d kicad-cli wrapper."""

    def test_basic_render(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 1: render_pcb_3d calls kicad-cli pcb render with correct basic args."""
        output_path = tmp_path / "render.png"
        result = render_pcb_3d(fake_pcb, output_path)

        mock_kicad_cli.assert_called_once()
        cmd = mock_kicad_cli.call_args[0][0]
        assert "pcb" in cmd
        assert "render" in cmd
        assert str(fake_pcb) in cmd
        assert "-o" in cmd or "--output" in cmd or str(output_path) in cmd
        assert result["image_path"] == output_path
        assert result["width_px"] == 4096
        assert result["height_px"] == 4096

    def test_rotation_and_side_options(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 2: render_pcb_3d accepts rotation, side, distance, width, height, theme, background."""
        output_path = tmp_path / "render.png"
        result = render_pcb_3d(
            fake_pcb,
            output_path,
            rotation="-45,0,45",
            side="bottom",
            distance=1000,
            width=2048,
            height=1024,
            theme="pcbnew",
            background="#ffffff",
        )

        cmd = mock_kicad_cli.call_args[0][0]
        assert "-45,0,45" in cmd
        assert "bottom" in cmd
        assert "1000" in cmd
        assert "2048" in cmd
        assert "1024" in cmd
        assert "pcbnew" in cmd
        assert "#ffffff" in cmd
        assert result["width_px"] == 2048
        assert result["height_px"] == 1024

    def test_defaults_top_no_rotation(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 3: render_pcb_3d defaults to side='top', no rotation, 4096x4096."""
        output_path = tmp_path / "render.png"
        result = render_pcb_3d(fake_pcb, output_path)

        cmd_str = " ".join(mock_kicad_cli.call_args[0][0])
        # "top" should be default; "bottom" should NOT appear
        assert "top" in cmd_str
        assert "bottom" not in cmd_str
        # No rotation flag by default
        assert "--rotate" not in cmd_str
        assert result["width_px"] == 4096
        assert result["height_px"] == 4096

    def test_returns_dict_not_export_result(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 12: render_pcb_3d returns dict (not ExportResult)."""
        output_path = tmp_path / "render.png"
        result = render_pcb_3d(fake_pcb, output_path)

        assert isinstance(result, dict)
        assert not isinstance(result, ExportResult)
        assert "image_path" in result
        assert "width_px" in result
        assert "height_px" in result
        assert "command" in result
        assert "stderr" in result

    def test_rejects_path_traversal(self, fake_pcb, mock_cli_resolver):
        """Test 10: render_pcb_3d rejects path traversal in output path."""
        output_path = Path("/safe/dir/../etc/passwd")
        with pytest.raises(ValueError, match="path traversal"):
            render_pcb_3d(fake_pcb, output_path)

    def test_file_not_found(self, mock_cli_resolver):
        """Test 11: render_pcb_3d raises FileNotFoundError for missing PCB file."""
        nonexistent = Path("/nonexistent/board.kicad_pcb")
        output_path = Path("/safe/render.png")
        with pytest.raises(FileNotFoundError):
            render_pcb_3d(nonexistent, output_path)

    def test_rejects_wrong_suffix(self, fake_sch, mock_cli_resolver):
        """Test 9: render_pcb_3d rejects non-.kicad_pcb files."""
        output_path = Path("/safe/render.png")
        with pytest.raises(ValueError, match=".kicad_pcb"):
            render_pcb_3d(fake_sch, output_path)

    def test_invalid_side_raises(self, fake_pcb, mock_cli_resolver, tmp_path):
        """render_pcb_3d rejects invalid side value."""
        output_path = tmp_path / "render.png"
        with pytest.raises(ValueError, match="side"):
            render_pcb_3d(fake_pcb, output_path, side="left")

    def test_invalid_background_raises(self, fake_pcb, mock_cli_resolver, tmp_path):
        """Test (T-79-06): render_pcb_3d validates background color format."""
        output_path = tmp_path / "render.png"
        with pytest.raises(ValueError, match="background"):
            render_pcb_3d(fake_pcb, output_path, background="not-a-color")


# === export_schematic_svg tests ===


class TestExportSchematicSvg:
    """Tests for export_schematic_svg kicad-cli wrapper."""

    def test_basic_export(self, fake_sch, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 4: export_schematic_svg calls kicad-cli sch export svg."""
        # Create the expected output file so ExportResult finds it
        svg_out = tmp_path / "schematic.svg"
        svg_out.write_text("<svg></svg>")

        result = export_schematic_svg(fake_sch, tmp_path)

        mock_kicad_cli.assert_called_once()
        cmd = mock_kicad_cli.call_args[0][0]
        assert "sch" in cmd
        assert "export" in cmd
        assert "svg" in cmd
        assert str(fake_sch) in cmd
        assert isinstance(result, ExportResult)

    def test_theme_option(self, fake_sch, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """export_schematic_svg passes theme option."""
        svg_out = tmp_path / "schematic.svg"
        svg_out.write_text("<svg></svg>")

        export_schematic_svg(fake_sch, tmp_path, theme="dark")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "dark" in cmd

    def test_page_option(self, fake_sch, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """export_schematic_svg passes page option for multi-page schematics."""
        svg_out = tmp_path / "schematic.svg"
        svg_out.write_text("<svg></svg>")

        export_schematic_svg(fake_sch, tmp_path, page="2")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "2" in cmd

    def test_rejects_wrong_suffix(self, fake_pcb, mock_cli_resolver):
        """Test 9: export_schematic_svg rejects non-.kicad_sch files."""
        with pytest.raises(ValueError, match=".kicad_sch"):
            export_schematic_svg(fake_pcb)

    def test_rejects_path_traversal(self, fake_sch, mock_cli_resolver):
        """Test 10: export_schematic_svg rejects path traversal."""
        with pytest.raises(ValueError, match="path traversal"):
            export_schematic_svg(fake_sch, Path("/safe/../etc"))

    def test_file_not_found(self, mock_cli_resolver):
        """Test 11: export_schematic_svg raises FileNotFoundError for missing file."""
        nonexistent = Path("/nonexistent/schematic.kicad_sch")
        with pytest.raises(FileNotFoundError):
            export_schematic_svg(nonexistent)


# === export_symbol_svg tests ===


class TestExportSymbolSvg:
    """Tests for export_symbol_svg kicad-cli wrapper."""

    def test_basic_export(self, fake_sym, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 5: export_symbol_svg calls kicad-cli sym export svg."""
        svg_out = tmp_path / "library.svg"
        svg_out.write_text("<svg></svg>")

        result = export_symbol_svg(fake_sym, tmp_path)

        mock_kicad_cli.assert_called_once()
        cmd = mock_kicad_cli.call_args[0][0]
        assert "sym" in cmd
        assert "export" in cmd
        assert "svg" in cmd
        assert str(fake_sym) in cmd
        assert isinstance(result, ExportResult)

    def test_rejects_wrong_suffix(self, fake_pcb, mock_cli_resolver):
        """Test 9: export_symbol_svg rejects non-.kicad_sym files."""
        with pytest.raises(ValueError, match=".kicad_sym"):
            export_symbol_svg(fake_pcb)

    def test_rejects_path_traversal(self, fake_sym, mock_cli_resolver):
        """Test 10: export_symbol_svg rejects path traversal."""
        with pytest.raises(ValueError, match="path traversal"):
            export_symbol_svg(fake_sym, Path("/safe/../etc"))

    def test_file_not_found(self, mock_cli_resolver):
        """Test 11: export_symbol_svg raises FileNotFoundError for missing file."""
        nonexistent = Path("/nonexistent/library.kicad_sym")
        with pytest.raises(FileNotFoundError):
            export_symbol_svg(nonexistent)


# === export_footprint_svg tests ===


class TestExportFootprintSvg:
    """Tests for export_footprint_svg kicad-cli wrapper."""

    def test_basic_export(self, fake_fp, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 6: export_footprint_svg calls kicad-cli fp export svg."""
        svg_out = tmp_path / "footprint.svg"
        svg_out.write_text("<svg></svg>")

        result = export_footprint_svg(fake_fp, tmp_path)

        mock_kicad_cli.assert_called_once()
        cmd = mock_kicad_cli.call_args[0][0]
        assert "fp" in cmd
        assert "export" in cmd
        assert "svg" in cmd
        assert str(fake_fp) in cmd
        assert isinstance(result, ExportResult)

    def test_rejects_wrong_suffix(self, fake_pcb, mock_cli_resolver):
        """Test 9: export_footprint_svg rejects non-.kicad_mod files."""
        with pytest.raises(ValueError, match=".kicad_mod"):
            export_footprint_svg(fake_pcb)

    def test_rejects_path_traversal(self, fake_fp, mock_cli_resolver):
        """Test 10: export_footprint_svg rejects path traversal."""
        with pytest.raises(ValueError, match="path traversal"):
            export_footprint_svg(fake_fp, Path("/safe/../etc"))

    def test_file_not_found(self, mock_cli_resolver):
        """Test 11: export_footprint_svg raises FileNotFoundError for missing file."""
        nonexistent = Path("/nonexistent/footprint.kicad_mod")
        with pytest.raises(FileNotFoundError):
            export_footprint_svg(nonexistent)


# === export_pcb_svg tests ===


class TestExportPcbSvg:
    """Tests for export_pcb_svg kicad-cli wrapper."""

    def test_basic_export(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 7: export_pcb_svg calls kicad-cli pcb export svg with layers."""
        svg_out = tmp_path / "board.svg"
        svg_out.write_text("<svg></svg>")

        result = export_pcb_svg(fake_pcb, tmp_path, layers=["F.Cu", "B.Cu"])

        mock_kicad_cli.assert_called_once()
        cmd = mock_kicad_cli.call_args[0][0]
        assert "pcb" in cmd
        assert "export" in cmd
        assert "svg" in cmd
        assert "F.Cu,B.Cu" in cmd
        assert str(fake_pcb) in cmd
        assert isinstance(result, ExportResult)

    def test_exclude_drawing_sheet(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """export_pcb_svg with exclude_drawing_sheet=True adds --exclude-drawing-sheet."""
        svg_out = tmp_path / "board.svg"
        svg_out.write_text("<svg></svg>")

        export_pcb_svg(fake_pcb, tmp_path, exclude_drawing_sheet=True)

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "--exclude-drawing-sheet" in cmd

    def test_theme_option(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """export_pcb_svg passes theme option."""
        svg_out = tmp_path / "board.svg"
        svg_out.write_text("<svg></svg>")

        export_pcb_svg(fake_pcb, tmp_path, theme="dark")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "dark" in cmd

    def test_no_layers(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """export_pcb_svg without layers does not add --layers flag."""
        svg_out = tmp_path / "board.svg"
        svg_out.write_text("<svg></svg>")

        export_pcb_svg(fake_pcb, tmp_path, layers=None)

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "--layers" not in cmd

    def test_rejects_wrong_suffix(self, fake_sch, mock_cli_resolver):
        """Test 9: export_pcb_svg rejects non-.kicad_pcb files."""
        with pytest.raises(ValueError, match=".kicad_pcb"):
            export_pcb_svg(fake_sch)

    def test_rejects_path_traversal(self, fake_pcb, mock_cli_resolver):
        """Test 10: export_pcb_svg rejects path traversal."""
        with pytest.raises(ValueError, match="path traversal"):
            export_pcb_svg(fake_pcb, Path("/safe/../etc"))

    def test_file_not_found(self, mock_cli_resolver):
        """Test 11: export_pcb_svg raises FileNotFoundError for missing file."""
        nonexistent = Path("/nonexistent/board.kicad_pcb")
        with pytest.raises(FileNotFoundError):
            export_pcb_svg(nonexistent)


# === export_pcb_pdf tests ===


class TestExportPcbPdf:
    """Tests for export_pcb_pdf kicad-cli wrapper."""

    def test_basic_export(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """Test 8: export_pcb_pdf calls kicad-cli pcb export pdf."""
        pdf_out = tmp_path / "board.pdf"
        pdf_out.write_text("%PDF-1.4")

        result = export_pcb_pdf(fake_pcb, pdf_out)

        mock_kicad_cli.assert_called_once()
        cmd = mock_kicad_cli.call_args[0][0]
        assert "pcb" in cmd
        assert "export" in cmd
        assert "pdf" in cmd
        assert str(fake_pcb) in cmd
        assert isinstance(result, ExportResult)

    def test_theme_option(self, fake_pcb, mock_kicad_cli, mock_cli_resolver, tmp_path):
        """export_pcb_pdf passes theme option."""
        pdf_out = tmp_path / "board.pdf"
        pdf_out.write_text("%PDF-1.4")

        export_pcb_pdf(fake_pcb, pdf_out, theme="pcbnew")

        cmd = " ".join(mock_kicad_cli.call_args[0][0])
        assert "pcbnew" in cmd

    def test_default_output_path(self, fake_pcb, mock_kicad_cli, mock_cli_resolver):
        """export_pcb_pdf defaults output path to stem.pdf in PCB parent dir."""
        pdf_out = fake_pcb.parent / "board.pdf"
        pdf_out.write_text("%PDF-1.4")

        export_pcb_pdf(fake_pcb)

        cmd = mock_kicad_cli.call_args[0][0]
        assert str(pdf_out) in " ".join(cmd)

    def test_rejects_wrong_suffix(self, fake_sch, mock_cli_resolver):
        """Test 9: export_pcb_pdf rejects non-.kicad_pcb files."""
        with pytest.raises(ValueError, match=".kicad_pcb"):
            export_pcb_pdf(fake_sch)

    def test_rejects_path_traversal(self, fake_pcb, mock_cli_resolver):
        """Test 10: export_pcb_pdf rejects path traversal in output path."""
        with pytest.raises(ValueError, match="path traversal"):
            export_pcb_pdf(fake_pcb, Path("/safe/../etc/board.pdf"))

    def test_file_not_found(self, mock_cli_resolver):
        """Test 11: export_pcb_pdf raises FileNotFoundError for missing file."""
        nonexistent = Path("/nonexistent/board.kicad_pcb")
        with pytest.raises(FileNotFoundError):
            export_pcb_pdf(nonexistent)
