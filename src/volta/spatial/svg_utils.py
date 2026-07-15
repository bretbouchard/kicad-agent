"""SVG parsing and manipulation utilities for KiCad-generated schematics.

Handles KiCad SVG namespace quirks, coordinate transforms, and
element creation for annotation overlays.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


# KiCad SVG namespace constants
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"


def parse_svg(path: Path) -> ET.Element:
    """Parse an SVG file and return the root element.

    Args:
        path: Path to SVG file.

    Returns:
        Root Element of the parsed SVG.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file is not valid SVG.
    """
    if not path.exists():
        raise FileNotFoundError(f"SVG file not found: {path}")

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid SVG: {exc}") from exc

    tag = root.tag
    if not (tag.endswith("svg") or "svg" in tag):
        raise ValueError(f"Not an SVG file (root tag: {tag})")

    return root


def get_svg_dimensions(root: ET.Element) -> tuple[float, float]:
    """Extract dimensions in mm from SVG viewBox.

    Args:
        root: SVG root element.

    Returns:
        (width_mm, height_mm) tuple.
    """
    viewbox = root.attrib.get("viewBox", root.attrib.get("viewbox", ""))
    if viewbox:
        parts = viewbox.split()
        if len(parts) == 4:
            return float(parts[2]), float(parts[3])

    w = root.attrib.get("width", "297mm").replace("mm", "")
    h = root.attrib.get("height", "210mm").replace("mm", "")
    return float(w), float(h)


def svg_to_mm(root: ET.Element, svg_x: float, svg_y: float) -> tuple[float, float]:
    """Convert SVG coordinate to mm using viewBox transform.

    KiCad SVGs use mm in the viewBox, so coordinates are typically 1:1.
    This handles the general case where viewBox offset is non-zero.

    Args:
        root: SVG root element (for viewBox extraction).
        svg_x: X coordinate in SVG units.
        svg_y: Y coordinate in SVG units.

    Returns:
        (x_mm, y_mm) tuple.
    """
    viewbox = root.attrib.get("viewBox", root.attrib.get("viewbox", ""))
    if viewbox:
        parts = viewbox.split()
        if len(parts) == 4:
            offset_x = float(parts[0])
            offset_y = float(parts[1])
            return svg_x - offset_x, svg_y - offset_y
    return svg_x, svg_y


def create_svg_circle(
    cx: float, cy: float, r: float,
    fill: str = "red", opacity: float = 0.3, stroke: str = "red", stroke_width: float = 0.5,
) -> ET.Element:
    """Create an SVG circle element for annotation markers."""
    return ET.Element(
        f"{{{SVG_NS}}}circle",
        attrib={
            "cx": str(cx), "cy": str(cy), "r": str(r),
            "fill": fill, "opacity": str(opacity),
            "stroke": stroke, "stroke-width": str(stroke_width),
        },
    )


def create_svg_text(
    x: float, y: float, text: str,
    font_size: float = 2.5, fill: str = "red", font_weight: str = "bold",
) -> ET.Element:
    """Create an SVG text element for annotation labels."""
    elem = ET.Element(
        f"{{{SVG_NS}}}text",
        attrib={
            "x": str(x), "y": str(y),
            "font-size": str(font_size), "fill": fill,
            "font-weight": font_weight,
            "font-family": "monospace",
        },
    )
    elem.text = text
    return elem


def create_svg_group(id_attr: str | None = None) -> ET.Element:
    """Create an SVG g element for grouping annotations."""
    attrib = {}
    if id_attr:
        attrib["id"] = id_attr
    return ET.Element(f"{{{SVG_NS}}}g", attrib=attrib)


# Event handler attributes to strip during sanitization
_UNSAFE_ATTRS = {"onclick", "onload", "onerror", "onmouseover", "onmouseout", "onfocus", "onblur"}
_JS_RE = re.compile(r"^\s*javascript:", re.IGNORECASE)


def sanitize_svg(root: ET.Element) -> ET.Element:
    """Strip dangerous elements and attributes from SVG.

    Removes <script> elements, event handler attributes, and javascript: URLs.
    Returns the sanitized root (mutates in-place).

    Args:
        root: SVG root element.

    Returns:
        Sanitized root element.
    """
    # Remove script elements
    for script in root.findall(f".//{{{SVG_NS}}}script"):
        root.remove(script)
    # Also check without namespace
    for script in root.findall(".//script"):
        root.remove(script)

    # Walk all elements and strip unsafe attributes
    for elem in root.iter():
        to_remove = []
        for attr_name, attr_val in elem.attrib.items():
            lower = attr_name.lower()
            if lower in _UNSAFE_ATTRS:
                to_remove.append(attr_name)
            elif "href" in lower and isinstance(attr_val, str) and _JS_RE.match(attr_val):
                to_remove.append(attr_name)
        for attr_name in to_remove:
            del elem.attrib[attr_name]

    return root
