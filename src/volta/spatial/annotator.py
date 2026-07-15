"""SVG annotation engine for KiCad schematics.

Takes a KiCad schematic SVG and a list of violations, produces an
annotated SVG with numbered red circles at violation positions,
callout labels, and a summary legend.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from volta.spatial.svg_utils import (
    SVG_NS,
    create_svg_circle,
    create_svg_group,
    create_svg_text,
    get_svg_dimensions,
    parse_svg,
    sanitize_svg,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnnotationStyle:
    """Visual style for SVG annotations.

    Attributes:
        color: Marker fill color.
        stroke: Marker stroke color.
        font_size: Callout text font size in SVG units.
        circle_radius: Marker circle radius in SVG units.
        opacity: Marker fill opacity (0-1).
        stroke_width: Marker stroke width in SVG units.
        legend_font_size: Legend text font size.
    """

    color: str = "red"
    stroke: str = "darkred"
    font_size: float = 2.5
    circle_radius: float = 3.0
    opacity: float = 0.3
    stroke_width: float = 0.8
    legend_font_size: float = 2.0


@dataclass(frozen=True)
class Annotation:
    """A single annotation to place on the SVG.

    Attributes:
        x: X position in mm.
        y: Y position in mm.
        label: Short label text.
        description: Detailed description.
        severity: Severity level (error, warning, info).
    """

    x: float
    y: float
    label: str
    description: str
    severity: str = "error"


class SvgAnnotator:
    """Annotate KiCad schematic SVGs with violation markers.

    Args:
        style: Annotation visual style.
    """

    def __init__(self, style: AnnotationStyle | None = None) -> None:
        self._style = style or AnnotationStyle()

    def annotate(
        self,
        svg_path: Path,
        annotations: list[Annotation],
        output_path: Path | None = None,
    ) -> Path:
        """Annotate an SVG with violation markers and legend.

        Args:
            svg_path: Path to input SVG file.
            annotations: List of annotations to place.
            output_path: Path for output SVG. Defaults to input with _annotated suffix.

        Returns:
            Path to annotated SVG file.
        """
        root = parse_svg(svg_path)
        sanitize_svg(root)

        if output_path is None:
            output_path = svg_path.with_name(f"{svg_path.stem}_annotated{svg_path.suffix}")

        # Create annotation overlay group
        overlay = create_svg_group(id_attr="volta-annotations")

        # Add numbered markers at each annotation position
        for i, ann in enumerate(annotations, 1):
            severity_color = self._severity_color(ann.severity)

            marker = create_svg_circle(
                cx=ann.x, cy=ann.y, r=self._style.circle_radius,
                fill=severity_color, opacity=self._style.opacity,
                stroke=self._style.stroke, stroke_width=self._style.stroke_width,
            )
            overlay.append(marker)

            # Numbered callout
            number_text = create_svg_text(
                x=ann.x, y=ann.y + self._style.font_size * 0.35,
                text=str(i),
                font_size=self._style.font_size,
                fill="white", font_weight="bold",
            )
            overlay.append(number_text)

        # Add legend
        legend = self._build_legend(annotations)
        overlay.append(legend)

        root.append(overlay)

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(str(output_path), xml_declaration=True, encoding="UTF-8")

        return output_path

    def annotate_from_violations(
        self,
        svg_path: Path,
        violations: list[Any],
        output_path: Path | None = None,
    ) -> Path:
        """Annotate SVG from ErcViolation objects.

        Args:
            svg_path: Path to input SVG file.
            violations: List of ErcViolation objects with positions.
            output_path: Path for output SVG.

        Returns:
            Path to annotated SVG file.
        """
        annotations = []
        for v in violations:
            positions = getattr(v, "positions", [])
            desc = getattr(v, "description", str(v))
            severity = getattr(v, "severity", "error")
            vtype = getattr(v, "type", "violation")

            for px, py in positions:
                annotations.append(Annotation(
                    x=px, y=py,
                    label=vtype,
                    description=desc,
                    severity=severity,
                ))

        return self.annotate(svg_path, annotations, output_path)

    def _build_legend(self, annotations: list[Annotation]) -> ET.Element:
        """Build a legend group summarizing all annotations."""
        width_mm, _ = get_svg_dimensions(
            # Create a dummy root for dimensions - we use a simple approach
            ET.Element(f"{{{SVG_NS}}}svg", attrib={"viewBox": f"0 0 {297} {210}"})
        )

        legend = create_svg_group(id_attr="annotation-legend")
        y_offset = 0.0

        # Legend title
        title = create_svg_text(
            x=2.0, y=y_offset + 3.0,
            text=f"Annotations ({len(annotations)})",
            font_size=self._style.legend_font_size * 1.2,
            fill="black", font_weight="bold",
        )
        legend.append(title)
        y_offset += 5.0

        # Individual entries
        for i, ann in enumerate(annotations[:20], 1):  # Cap at 20 for readability
            color = self._severity_color(ann.severity)
            entry = create_svg_text(
                x=4.0, y=y_offset + 2.0,
                text=f"{i}. [{ann.severity}] {ann.description[:60]}",
                font_size=self._style.legend_font_size,
                fill=color,
            )
            legend.append(entry)
            y_offset += 3.0

        return legend

    @staticmethod
    def _severity_color(severity: str) -> str:
        """Map severity to color."""
        return {
            "error": "red",
            "warning": "orange",
            "info": "dodgerblue",
            "exclusion": "gray",
        }.get(severity, "red")
