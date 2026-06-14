"""PCB image renderer for Gemma 4 vision input.

Renders PCB layers and schematics to PNG images suitable for
Gemma 4 vision input via kicad-cli.

Provides:
- render_pcb_layer_png: 2D PCB layer render to PIL.Image
- render_schematic_png: Schematic render to PIL.Image
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def render_pcb_layer_png(
    pcb_path: Path,
    layers: list[str] | None = None,
    width: int = 1600,
    height: int = 1200,
    theme: str | None = None,
) -> "PIL.Image.Image":
    """Render PCB layers to PNG via kicad-cli and return as PIL.Image.

    Uses kicad-cli pcb export svg then converts to PNG via PIL/cairosvg.
    For vision input, a top-down 2D view is more useful than 3D render.

    Args:
        pcb_path: Path to .kicad_pcb file.
        layers: Layer names to include (e.g. ["F.Cu", "B.Cu"]). None = all.
        width: Render width in pixels.
        height: Render height in pixels.
        theme: KiCad color theme name.

    Returns:
        PIL.Image of the rendered PCB.

    Raises:
        FileNotFoundError: If pcb_path or kicad-cli not found.
    """
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmpdir:
        svg_path = Path(tmpdir) / "render.svg"

        args = ["pcb", "export", "svg", "--output", str(svg_path)]
        if theme:
            args.extend(["--theme", theme])
        # KiCad 9+ requires at least one layer
        layer_list = layers if layers else ["F.Cu", "B.Cu", "Edge.Cuts"]
        args.extend(["--layers", ",".join(layer_list)])
        args.append(str(pcb_path))

        try:
            result = subprocess.run(
                ["kicad-cli"] + args,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.warning("kicad-cli SVG export failed: %s", result.stderr)
        except FileNotFoundError:
            logger.warning("kicad-cli not found, falling back to 3D render")
            return render_pcb_3d_png(pcb_path, width, height)

        if svg_path.exists():
            # Convert SVG to PNG
            png_path = Path(tmpdir) / "render.png"
            _svg_to_png(svg_path, png_path, width, height)
            if png_path.exists():
                img = Image.open(png_path)
                img.load()  # Force full read into memory before tmpdir cleanup
                return img

    # Fallback to 3D render
    return render_pcb_3d_png(pcb_path, width, height)


def render_pcb_3d_png(
    pcb_path: Path,
    width: int = 1600,
    height: int = 1200,
    rotate: str = "-45,0,45",
) -> "PIL.Image.Image":
    """Render PCB as 3D view via kicad-cli pcb render.

    Args:
        pcb_path: Path to .kicad_pcb file.
        width: Render width in pixels.
        height: Render height in pixels.
        rotate: Rotation string (format: "X,Y,Z" with numeric values).

    Returns:
        PIL.Image of the 3D PCB render.

    Raises:
        ValueError: If rotate format is invalid.
    """
    _ROTATION_RE = re.compile(r'^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$')
    if not _ROTATION_RE.match(rotate):
        raise ValueError(
            f"Invalid rotation format: {rotate!r}. "
            "Expected 'X,Y,Z' with numeric values (e.g. '-45,0,45')."
        )

    from PIL import Image

    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = Path(tmpdir) / "render.png"

        args = [
            "pcb", "render",
            "--width", str(width),
            "--height", str(height),
            "--rotate", rotate,
            "--output", str(png_path),
            str(pcb_path),
        ]

        try:
            result = subprocess.run(
                ["kicad-cli"] + args,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                logger.error("kicad-cli 3D render failed: %s", result.stderr)
        except FileNotFoundError:
            logger.error("kicad-cli not found")
            raise

        if png_path.exists():
            img = Image.open(png_path)
            img.load()  # Force full read into memory before tmpdir cleanup
            # Cap dimensions to prevent memory exhaustion
            max_dim = 4096
            if img.width > max_dim or img.height > max_dim:
                img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            return img

    raise RuntimeError(f"Failed to render PCB: {pcb_path}")


def render_schematic_png(
    sch_path: Path,
    page: str | None = None,
    width: int = 1600,
    height: int = 1200,
    theme: str | None = None,
) -> "PIL.Image.Image":
    """Render schematic to PNG via kicad-cli.

    Args:
        sch_path: Path to .kicad_sch file.
        page: Page identifier for multi-sheet schematics.
        width: Render width in pixels.
        height: Render height in pixels.
        theme: KiCad color theme name.

    Returns:
        PIL.Image of the schematic render.
    """
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmpdir:
        svg_path = Path(tmpdir) / "render.svg"

        args = ["sch", "export", "svg", "--output", str(svg_path)]
        if page:
            args.extend(["--page", page])
        if theme:
            args.extend(["--theme", theme])
        args.append(str(sch_path))

        try:
            result = subprocess.run(
                ["kicad-cli"] + args,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.error("kicad-cli schematic export failed: %s", result.stderr)
        except FileNotFoundError:
            logger.error("kicad-cli not found")
            raise

        if svg_path.exists():
            png_path = Path(tmpdir) / "render.png"
            _svg_to_png(svg_path, png_path, width, height)
            if png_path.exists():
                img = Image.open(png_path)
                img.load()  # Force full read into memory before tmpdir cleanup
                return img

    raise RuntimeError(f"Failed to render schematic: {sch_path}")


def _svg_to_png(svg_path: Path, png_path: Path, width: int, height: int) -> None:
    """Convert SVG to PNG using cairosvg or Pillow as fallback."""
    try:
        import cairosvg
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=width,
            output_height=height,
        )
    except ImportError:
        # Fallback: PIL can open SVG on some systems
        from PIL import Image
        try:
            img = Image.open(svg_path)
            img = img.resize((width, height), Image.LANCZOS)
            img.save(png_path, "PNG")
        except Exception as exc:
            logger.warning("SVG to PNG conversion failed: %s", exc)
