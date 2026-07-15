"""Visual diff engine for comparing two KiCad schematic SVGs.

Compares two SVGs element-by-element and highlights differences
with green/red overlay colors for added/removed elements.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from volta.spatial.svg_utils import (
    SVG_NS,
    create_svg_circle,
    create_svg_group,
    parse_svg,
    sanitize_svg,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualDiffResult:
    """Result of comparing two schematic SVGs.

    Attributes:
        added_count: Elements in 'after' not in 'before'.
        removed_count: Elements in 'before' not in 'after'.
        modified_count: Elements present in both but changed.
        diff_svg_path: Path to the diff SVG (None if not generated).
        summary: Brief human-readable diff summary.
    """

    added_count: int = 0
    removed_count: int = 0
    modified_count: int = 0
    diff_svg_path: str | None = None
    summary: str = ""


class VisualDiffer:
    """Compare two KiCad schematic SVGs and highlight differences.

    Compares element structure between two SVGs, identifying added,
    removed, and modified elements. Produces a diff SVG with color
    highlights.
    """

    def compare(
        self,
        before_path: Path,
        after_path: Path,
        output_path: Path | None = None,
    ) -> VisualDiffResult:
        """Compare two SVGs and produce a diff.

        Args:
            before_path: Path to the 'before' SVG.
            after_path: Path to the 'after' SVG.
            output_path: Path for diff SVG output. Defaults to before_dir/before_stem_diff.svg.

        Returns:
            VisualDiffResult with statistics and diff SVG path.
        """
        before_root = parse_svg(before_path)
        after_root = parse_svg(after_path)

        if output_path is None:
            output_path = before_path.with_name(f"{before_path.stem}_diff.svg")

        before_elements = self._extract_elements(before_root)
        after_elements = self._extract_elements(after_root)

        before_keys = set(before_elements.keys())
        after_keys = set(after_elements.keys())

        added = after_keys - before_keys
        removed = before_keys - after_keys
        common = before_keys & after_keys

        modified = set()
        for key in common:
            if before_elements[key] != after_elements[key]:
                modified.add(key)

        # Build diff SVG from 'after' with highlights
        diff_root = parse_svg(after_path)
        sanitize_svg(diff_root)
        overlay = create_svg_group(id_attr="visual-diff")

        # Highlight added elements (green)
        for key in added:
            elem = after_elements[key]
            x, y = self._element_position(elem)
            if x is not None and y is not None:
                marker = create_svg_circle(
                    cx=x, cy=y, r=2.0,
                    fill="lime", opacity=0.3, stroke="green", stroke_width=0.5,
                )
                overlay.append(marker)

        # Highlight removed elements (red) -- positions from before
        for key in removed:
            elem = before_elements[key]
            x, y = self._element_position(elem)
            if x is not None and y is not None:
                marker = create_svg_circle(
                    cx=x, cy=y, r=2.0,
                    fill="red", opacity=0.3, stroke="darkred", stroke_width=0.5,
                )
                overlay.append(marker)

        diff_root.append(overlay)

        tree = ET.ElementTree(diff_root)
        ET.indent(tree, space="  ")
        tree.write(str(output_path), xml_declaration=True, encoding="UTF-8")

        summary_parts = []
        if added:
            summary_parts.append(f"+{len(added)} added")
        if removed:
            summary_parts.append(f"-{len(removed)} removed")
        if modified:
            summary_parts.append(f"~{len(modified)} modified")
        summary = ", ".join(summary_parts) if summary_parts else "No changes"

        return VisualDiffResult(
            added_count=len(added),
            removed_count=len(removed),
            modified_count=len(modified),
            diff_svg_path=str(output_path),
            summary=summary,
        )

    @staticmethod
    def _extract_elements(root: ET.Element) -> dict[str, str]:
        """Extract identifiable elements from SVG as {key: serialized_element}.

        Uses element tag + key attributes as identity.
        """
        elements = {}
        for elem in root.iter():
            tag = elem.tag
            # Skip non-visual metadata elements
            if "defs" in tag or "metadata" in tag or "title" in tag:
                continue

            attrib = elem.attrib
            # Create identity key from tag + id or position
            elem_id = attrib.get("id", "")
            x = attrib.get("x", attrib.get("cx", ""))
            y = attrib.get("y", attrib.get("cy", ""))
            key = f"{tag}:{elem_id}:{x},{y}"

            if elem_id or (x and y):
                # Serialize to string for comparison
                text = elem.text or ""
                elements[key] = f"{tag}|{sorted(attrib.items())}|{text.strip()}"

        return elements

    @staticmethod
    def _element_position(serialized: str) -> tuple[float | None, float | None]:
        """Extract position from serialized element string."""
        try:
            parts = serialized.split("|")
            if len(parts) < 2:
                return None, None
            # Parse sorted attrib items for x/cx and y/cy
            import ast
            items = ast.literal_eval(parts[1])
            x = None
            y = None
            for k, v in items:
                k_lower = k.split("}")[-1] if "}" in k else k
                if k_lower in ("x", "cx") and v:
                    x = float(v)
                elif k_lower in ("y", "cy") and v:
                    y = float(v)
            return x, y
        except (ValueError, SyntaxError):
            return None, None
