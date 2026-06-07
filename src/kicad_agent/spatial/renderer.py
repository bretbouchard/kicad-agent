"""PCB layer renderer with coordinate grid overlay.

VP-01: Renders PCB layers as rasterized images using kicad-cli SVG export
with Pillow rasterization and mm-coordinate grid overlay.

Two rendering approaches:
1. Primary: kicad-cli SVG export + cairocffi rasterization (accurate)
2. Fallback: Pillow-only primitive rendering (when kicad-cli unavailable)

Usage:
    from kicad_agent.spatial.renderer import render_pcb_layer

    result = render_pcb_layer(
        Path("my_board.kicad_pcb"),
        layer="F.Cu",
        output_path=Path("output.png"),
    )
    print(result["image_path"], result["mm_per_pixel"])
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from kicad_agent.cli_resolver import find_kicad_cli
from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.parser import parse_pcb
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.spatial.extractor import extract_boxes, extract_points

logger = logging.getLogger(__name__)

# Default DPI for rasterization
_DEFAULT_DPI = 300

# Default grid spacing in mm
_DEFAULT_GRID_SPACING_MM = 10.0


def _find_kicad_cli() -> str:
    """Find kicad-cli on PATH.

    Returns:
        Absolute path to kicad-cli.

    Raises:
        FileNotFoundError: If kicad-cli is not found on PATH.
    """
    return find_kicad_cli().path


def _validate_pcb_path(pcb_path: Path) -> None:
    """Validate that the PCB path is a valid .kicad_pcb file.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not .kicad_pcb.
    """
    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")
    if pcb_path.suffix != ".kicad_pcb":
        raise ValueError(
            f"Expected .kicad_pcb file, got: {pcb_path.suffix}"
        )


def _validate_output_path(output_path: Path) -> None:
    """Validate output path has no path traversal.

    Mitigation for threat T-08-01.
    """
    resolved = output_path.resolve()
    # Basic path traversal check
    if ".." in str(output_path):
        raise ValueError(
            f"Output path must not contain '..': {output_path}"
        )


def _get_board_bounds(pcb_ir: PcbIR) -> tuple[float, float, float, float]:
    """Extract board bounding box from extracted primitives.

    Computes bounds from footprint bounding boxes. Falls back to pad
    positions if no boxes available.

    Args:
        pcb_ir: PCB intermediate representation.

    Returns:
        (min_x, min_y, max_x, max_y) in mm.
    """
    boxes = extract_boxes(pcb_ir)
    if boxes:
        min_x = min(b.x1 for b in boxes)
        min_y = min(b.y1 for b in boxes)
        max_x = max(b.x2 for b in boxes)
        max_y = max(b.y2 for b in boxes)
        return (min_x, min_y, max_x, max_y)

    # Fallback: use pad positions
    points = extract_points(pcb_ir)
    if points:
        min_x = min(p.x for p in points)
        min_y = min(p.y for p in points)
        max_x = max(p.x for p in points)
        max_y = max(p.y for p in points)
        return (min_x, min_y, max_x, max_y)

    # Ultimate fallback: 0-100mm default
    return (0.0, 0.0, 100.0, 100.0)


def _add_coordinate_grid(
    image: Image.Image,
    board_bounds: tuple[float, float, float, float],
    grid_spacing_mm: float = _DEFAULT_GRID_SPACING_MM,
    dpi: int = _DEFAULT_DPI,
) -> Image.Image:
    """Draw coordinate grid lines and mm labels on the image.

    Computes pixel-to-mm mapping from image dimensions and board bounds.

    Args:
        image: PIL Image to annotate.
        board_bounds: (min_x, min_y, max_x, max_y) in mm.
        grid_spacing_mm: Grid line spacing in mm (default 10mm).
        dpi: DPI used for rasterization (for font sizing).

    Returns:
        Modified image with grid overlay.
    """
    min_x, min_y, max_x, max_y = board_bounds
    board_w_mm = max_x - min_x
    board_h_mm = max_y - min_y

    if board_w_mm <= 0 or board_h_mm <= 0:
        return image

    img_w, img_h = image.size
    mm_per_pixel_x = board_w_mm / img_w
    mm_per_pixel_y = board_h_mm / img_h

    draw = ImageDraw.Draw(image)

    # Grid line color (light gray) and label color (dark)
    grid_color = (180, 180, 180, 120)
    label_color = (60, 60, 60, 200)

    # Try to get a font for labels
    try:
        font = ImageFont.load_default(size=12)
    except TypeError:
        # Older Pillow versions don't support size argument
        font = ImageFont.load_default()

    # Draw vertical grid lines (X coordinates)
    x_start = math.ceil(min_x / grid_spacing_mm) * grid_spacing_mm
    x = x_start
    while x <= max_x:
        px = int((x - min_x) / mm_per_pixel_x)
        if 0 <= px < img_w:
            draw.line([(px, 0), (px, img_h)], fill=grid_color, width=1)
            label = f"{x:.0f}"
            draw.text((px + 2, 2), label, fill=label_color, font=font)
        x += grid_spacing_mm

    # Draw horizontal grid lines (Y coordinates)
    y_start = math.ceil(min_y / grid_spacing_mm) * grid_spacing_mm
    y = y_start
    while y <= max_y:
        py = int((y - min_y) / mm_per_pixel_y)
        if 0 <= py < img_h:
            draw.line([(0, py), (img_w, py)], fill=grid_color, width=1)
            label = f"{y:.0f}"
            draw.text((2, py + 2), label, fill=label_color, font=font)
        y += grid_spacing_mm

    return image


def _render_primitives_fallback(
    pcb_ir: PcbIR,
    board_bounds: tuple[float, float, float, float],
    width_px: int = 1000,
) -> Image.Image:
    """Render spatial primitives as simple shapes on a white image.

    Fallback when kicad-cli SVG export is unavailable or fails.
    Renders footprints as rectangles, pads as circles, traces as lines.

    Args:
        pcb_ir: PCB intermediate representation.
        board_bounds: (min_x, min_y, max_x, max_y) in mm.
        width_px: Image width in pixels.

    Returns:
        PIL Image with primitive rendering.
    """
    min_x, min_y, max_x, max_y = board_bounds
    board_w_mm = max_x - min_x
    board_h_mm = max_y - min_y

    if board_w_mm <= 0 or board_h_mm <= 0:
        board_w_mm = board_h_mm = 100.0

    # Calculate image dimensions maintaining aspect ratio
    scale = width_px / board_w_mm
    height_px = int(board_h_mm * scale)

    image = Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)

    def mm_to_px(x_mm: float, y_mm: float) -> tuple[int, int]:
        """Convert mm coordinates to pixel coordinates."""
        px = int((x_mm - min_x) * scale)
        py = int((y_mm - min_y) * scale)
        return (px, py)

    # Draw footprint boxes
    boxes = extract_boxes(pcb_ir)
    for box in boxes:
        p1 = mm_to_px(box.x1, box.y1)
        p2 = mm_to_px(box.x2, box.y2)
        draw.rectangle([p1, p2], outline=(0, 0, 200, 180), width=2)
        # Label with reference
        if box.reference:
            draw.text((p1[0] + 2, p1[1] + 2), box.reference, fill=(0, 0, 150, 200))

    # Draw pad points
    points = extract_points(pcb_ir)
    for pt in points:
        px, py = mm_to_px(pt.x, pt.y)
        if pt.entity_type == "pad":
            draw.ellipse(
                [(px - 2, py - 2), (px + 2, py + 2)],
                fill=(200, 0, 0, 150),
            )

    return image


def render_pcb_layer(
    pcb_path: Path,
    layer: str = "F.Cu",
    output_path: Path | None = None,
    dpi: int = _DEFAULT_DPI,
    theme: str = "default",
) -> dict[str, Any]:
    """Render a single PCB layer as a PNG image with coordinate grid overlay.

    Primary approach: kicad-cli SVG export + cairocffi rasterization.
    Fallback: Pillow-only primitive rendering from extracted spatial data.

    Args:
        pcb_path: Path to a .kicad_pcb file.
        layer: KiCad layer name (e.g. "F.Cu", "B.Cu", "Edge.Cuts").
        output_path: Output PNG path. If None, creates a temp file.
        dpi: Rasterization DPI (default 300).
        theme: kicad-cli color theme name.

    Returns:
        Dict with keys: image_path, width_px, height_px, board_width_mm,
        board_height_mm, mm_per_pixel, layer.

    Raises:
        FileNotFoundError: If pcb_path doesn't exist or kicad-cli not found.
        ValueError: If pcb_path has wrong extension.
    """
    _validate_pcb_path(pcb_path)

    if output_path is not None:
        _validate_output_path(output_path)

    # Build PcbIR for board bounds and fallback rendering
    _clear_registry()
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    pcb_ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    board_bounds = _get_board_bounds(pcb_ir)
    min_x, min_y, max_x, max_y = board_bounds
    board_w_mm = max_x - min_x
    board_h_mm = max_y - min_y

    image: Image.Image | None = None
    tmpdir: str | None = None

    try:
        # Primary: kicad-cli SVG export
        cli_path = _find_kicad_cli()
        tmpdir = tempfile.mkdtemp(prefix="kicad-agent-render-")

        cmd = [
            cli_path, "pcb", "export", "svg",
            "--layers", layer,
            "--exclude-drawing-sheet",
            "--black-and-white",
            "--output", tmpdir,
            str(pcb_path),
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Find generated SVG
        svg_files = list(Path(tmpdir).glob("*.svg"))

        if svg_files and proc.returncode == 0:
            svg_path = svg_files[0]
            try:
                image = _rasterize_svg(svg_path, dpi)
            except Exception as e:
                logger.warning(
                    "SVG rasterization failed (%s), falling back to primitives", e
                )
                image = None
        else:
            stderr = proc.stderr.strip() if proc.stderr else ""
            logger.warning(
                "kicad-cli SVG export failed (rc=%d): %s. Falling back to primitives.",
                proc.returncode, stderr,
            )

    except FileNotFoundError:
        logger.warning("kicad-cli not found, falling back to primitive rendering")

    except subprocess.TimeoutExpired:
        logger.warning("kicad-cli timed out after 60s, falling back to primitives")

    finally:
        if tmpdir is not None:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    # Fallback: Pillow-only primitive rendering
    if image is None:
        image = _render_primitives_fallback(pcb_ir, board_bounds)

    # Add coordinate grid overlay
    image = _add_coordinate_grid(image, board_bounds, dpi=dpi)

    # Save to output path
    if output_path is None:
        output_fd, output_str = tempfile.mkstemp(
            suffix=".png", prefix="kicad-agent-layer-"
        )
        os.close(output_fd)
        output_path = Path(output_str)

    image.save(str(output_path), "PNG")
    os.chmod(str(output_path), 0o600)

    width_px, height_px = image.size
    mm_per_pixel = board_w_mm / width_px if width_px > 0 else 0.0

    return {
        "image_path": str(output_path),
        "width_px": width_px,
        "height_px": height_px,
        "board_width_mm": round(board_w_mm, 4),
        "board_height_mm": round(board_h_mm, 4),
        "mm_per_pixel": round(mm_per_pixel, 6),
        "layer": layer,
    }


def _rasterize_svg(svg_path: Path, dpi: int) -> Image.Image:
    """Rasterize an SVG file to a PIL Image using cairocffi.

    Args:
        svg_path: Path to the SVG file.
        dpi: Target DPI for rasterization.

    Returns:
        PIL Image (RGBA).
    """
    import cairocffi

    # Parse SVG to get viewBox dimensions
    tree = ET.parse(str(svg_path))
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}

    # Extract viewBox or width/height
    view_box = root.get("viewBox")
    svg_width = root.get("width")
    svg_height = root.get("height")

    if view_box:
        parts = view_box.split()
        vb_x, vb_y, vb_w, vb_h = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    else:
        # Parse width/height, stripping units
        def _strip_units(val: str | None) -> float:
            if val is None:
                return 100.0
            return float("".join(c for c in val if c.isdigit() or c == "."))

        vb_x, vb_y = 0.0, 0.0
        vb_w = _strip_units(svg_width)
        vb_h = _strip_units(svg_height)

    # Calculate output dimensions at target DPI
    # SVG units are typically in px (96 dpi by default)
    scale_factor = dpi / 96.0
    out_w = int(vb_w * scale_factor)
    out_h = int(vb_h * scale_factor)

    if out_w <= 0 or out_h <= 0:
        raise ValueError(f"Invalid SVG dimensions: {out_w}x{out_h}")

    # Render SVG using cairocffi
    surface = cairocffi.SVGSurface(str(svg_path))
    # Create image surface at target DPI
    image_surface = cairocffi.ImageSurface(cairocffi.FORMAT_ARGB32, out_w, out_h)
    context = cairocffi.Context(image_surface)
    context.set_source_rgb(1.0, 1.0, 1.0)  # White background
    context.paint()

    context.scale(scale_factor, scale_factor)
    context.translate(-vb_x, -vb_y)

    # Re-render from SVG surface
    svg_surface = cairocffi.SVGSurface(str(svg_path))
    context.set_source_surface(svg_surface)
    context.paint()

    # Convert cairocffi image to PIL Image
    buf = image_surface.get_data()
    pil_image = Image.frombytes(
        "RGBA", (out_w, out_h), buf, "raw", "BGRA", out_w * 4
    )

    return pil_image


def render_pcb_layer_grid(
    pcb_path: Path,
    layers: list[str] | None = None,
    output_dir: Path | None = None,
    dpi: int = _DEFAULT_DPI,
) -> list[dict[str, Any]]:
    """Render multiple PCB layers as PNG images with coordinate grid overlays.

    Args:
        pcb_path: Path to a .kicad_pcb file.
        layers: List of KiCad layer names. Default: ["F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"].
        output_dir: Directory for output files. If None, uses temp directory.
        dpi: Rasterization DPI.

    Returns:
        List of render result dicts, one per layer.
    """
    if layers is None:
        layers = ["F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"]

    if output_dir is not None:
        _validate_output_path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="kicad-agent-grid-"))

    results: list[dict[str, Any]] = []
    for layer in layers:
        safe_name = layer.replace(".", "_")
        output_path = output_dir / f"{safe_name}.png"
        try:
            result = render_pcb_layer(
                pcb_path=pcb_path,
                layer=layer,
                output_path=output_path,
                dpi=dpi,
            )
            results.append(result)
        except Exception as e:
            logger.warning("Failed to render layer %s: %s", layer, e)

    return results
