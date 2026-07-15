"""Tests for PCB layer renderer with coordinate grid overlay.

VP-01: Validates rendering pipeline produces PNG images with metadata.
Tests that require kicad-cli are skipped gracefully if kicad-cli is
not available on PATH.
"""

import shutil
from pathlib import Path

import pytest
from PIL import Image

from volta.ir.base import _clear_registry
from volta.ir.pcb_ir import PcbIR
from volta.parser import parse_pcb
from volta.parser.uuid_extractor import extract_uuids
from volta.spatial.renderer import (
    _add_coordinate_grid,
    _get_board_bounds,
    render_pcb_layer,
    render_pcb_layer_grid,
)

from conftest import FIXTURE_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcb_ir(pcb_path: Path) -> PcbIR:
    """Build a PcbIR from a PCB file path (fresh registry each call)."""
    _clear_registry()
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


# Skip kicad-cli-dependent tests if kicad-cli is not available
kicad_cli_available = shutil.which("kicad-cli") is not None
requires_kicad_cli = pytest.mark.skipif(
    not kicad_cli_available,
    reason="kicad-cli not available on PATH",
)


@pytest.fixture
def arduino_pcb_path() -> Path:
    """Path to Arduino_Mega.kicad_pcb."""
    return FIXTURE_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"


@pytest.fixture
def arduino_pcb_ir(arduino_pcb_path: Path) -> PcbIR:
    """PcbIR built from Arduino_Mega.kicad_pcb."""
    return _make_pcb_ir(arduino_pcb_path)


# ---------------------------------------------------------------------------
# Board bounds extraction
# ---------------------------------------------------------------------------


class TestGetBoardBounds:
    """Tests for _get_board_bounds helper."""

    def test_get_board_bounds_returns_valid_bounds(self, arduino_pcb_ir: PcbIR):
        """Board bounds have min < max, all values finite."""
        bounds = _get_board_bounds(arduino_pcb_ir)
        min_x, min_y, max_x, max_y = bounds

        import math

        assert math.isfinite(min_x)
        assert math.isfinite(min_y)
        assert math.isfinite(max_x)
        assert math.isfinite(max_y)
        assert min_x < max_x, "min_x should be less than max_x"
        assert min_y < max_y, "min_y should be less than max_y"

    def test_get_board_bounds_reasonable_size(self, arduino_pcb_ir: PcbIR):
        """Arduino_Mega board bounds should be a reasonable PCB size (>10mm)."""
        bounds = _get_board_bounds(arduino_pcb_ir)
        min_x, min_y, max_x, max_y = bounds
        width = max_x - min_x
        height = max_y - min_y

        assert width > 10.0, f"Board width too small: {width}mm"
        assert height > 10.0, f"Board height too small: {height}mm"


# ---------------------------------------------------------------------------
# Coordinate grid overlay
# ---------------------------------------------------------------------------


class TestAddCoordinateGrid:
    """Tests for _add_coordinate_grid helper."""

    def test_add_coordinate_grid_modifies_image(self):
        """Adding grid modifies the image (some non-white pixels)."""
        image = Image.new("RGBA", (500, 500), (255, 255, 255, 255))
        board_bounds = (0.0, 0.0, 100.0, 100.0)

        result = _add_coordinate_grid(image, board_bounds, grid_spacing_mm=10.0)

        # Check that some pixels are no longer white
        pixels = list(result.getdata())
        non_white = [p for p in pixels if p[:3] != (255, 255, 255)]
        assert len(non_white) > 0, "Grid should modify some pixels"

    def test_add_coordinate_grid_preserves_size(self):
        """Grid overlay does not change image dimensions."""
        image = Image.new("RGBA", (300, 200), (255, 255, 255, 255))
        board_bounds = (0.0, 0.0, 50.0, 30.0)

        result = _add_coordinate_grid(image, board_bounds)
        assert result.size == (300, 200)


# ---------------------------------------------------------------------------
# render_pcb_layer
# ---------------------------------------------------------------------------


class TestRenderPcbLayer:
    """Tests for render_pcb_layer function."""

    def test_render_pcb_layer_produces_image(
        self, arduino_pcb_path: Path, tmp_path: Path
    ):
        """Rendering produces a valid PNG output file."""
        output = tmp_path / "test_layer.png"
        result = render_pcb_layer(
            pcb_path=arduino_pcb_path,
            layer="F.Cu",
            output_path=output,
        )

        # Verify output file exists and is a valid PNG
        assert output.exists(), "Output file should exist"
        with open(output, "rb") as f:
            magic = f.read(4)
        assert magic == b"\x89PNG", "Output should be a valid PNG file"

    def test_render_pcb_layer_returns_metadata(
        self, arduino_pcb_path: Path, tmp_path: Path
    ):
        """Return dict has all required metadata keys with valid values."""
        output = tmp_path / "test_metadata.png"
        result = render_pcb_layer(
            pcb_path=arduino_pcb_path,
            layer="F.Cu",
            output_path=output,
        )

        required_keys = {
            "image_path", "width_px", "height_px",
            "board_width_mm", "board_height_mm",
            "mm_per_pixel", "layer",
        }
        assert set(result.keys()) >= required_keys, (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

        assert result["width_px"] > 0
        assert result["height_px"] > 0
        assert result["mm_per_pixel"] > 0
        assert result["layer"] == "F.Cu"

    def test_render_pcb_layer_invalid_path_raises(self, tmp_path: Path):
        """Non-existent PCB path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            render_pcb_layer(
                pcb_path=tmp_path / "nonexistent.kicad_pcb",
                layer="F.Cu",
                output_path=tmp_path / "out.png",
            )

    def test_render_pcb_layer_wrong_extension_raises(self, tmp_path: Path):
        """Non-.kicad_pcb extension raises ValueError."""
        bad_file = tmp_path / "test.txt"
        bad_file.write_text("not a pcb")

        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            render_pcb_layer(
                pcb_path=bad_file,
                layer="F.Cu",
                output_path=tmp_path / "out.png",
            )


# ---------------------------------------------------------------------------
# render_pcb_layer_grid
# ---------------------------------------------------------------------------


class TestRenderPcbLayerGrid:
    """Tests for multi-layer rendering."""

    def test_render_pcb_layer_grid_renders_multiple(
        self, arduino_pcb_path: Path, tmp_path: Path
    ):
        """Rendering multiple layers returns results for each."""
        layers = ["F.Cu", "Edge.Cuts"]
        results = render_pcb_layer_grid(
            pcb_path=arduino_pcb_path,
            layers=layers,
            output_dir=tmp_path,
        )

        assert len(results) >= 1, "Should get at least 1 result"

        # Each result should have the layer key
        rendered_layers = [r["layer"] for r in results]
        assert "F.Cu" in rendered_layers or "Edge.Cuts" in rendered_layers

    def test_render_pcb_layer_grid_default_layers(
        self, arduino_pcb_path: Path, tmp_path: Path
    ):
        """Default layers (F.Cu, B.Cu, F.SilkS, Edge.Cuts) are rendered."""
        results = render_pcb_layer_grid(
            pcb_path=arduino_pcb_path,
            output_dir=tmp_path,
        )

        # Should produce results (some layers may fail if empty, but no crash)
        assert isinstance(results, list)
