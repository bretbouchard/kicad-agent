"""CapInputs — value object carrying D-04 cap inputs (CR-110-04 fix).

CR-110-04 problem: ReadabilityReport (Phase 48.5 SRS) does NOT carry
bounding_box_mm2, component_footprint_area_mm2, or crossing_count. The
D-04 caps need all three. Computing them ad-hoc at every call site
scatters logic and forces the caps to take loose float parameters.

CapInputs is a frozen value object with two factories:
  - from_layout_result(): post-autolayout path. crossing_count comes from
    a Phase 108 LayoutResult; bbox/footprint computed from a SchematicIR.
  - from_spatial_extractor(): raw-schematic path. bbox/footprint computed
    from a SchematicSpatialExtractor; crossing_count defaults to 0
    (raw schematics have no layout yet).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from volta.analysis.schematic_spatial import SchematicSpatialExtractor
    from volta.ir.schematic_ir import SchematicIR
    from volta.schematic_autolayout.sugiyama import LayoutResult


@dataclass(frozen=True)
class CapInputs:
    """CR-110-04 fix: value object carrying the three inputs D-04 caps need.

    ReadabilityReport (Phase 48.5 SRS) does NOT carry bounding_box_mm2,
    component_footprint_area_mm2, or crossing_count. These must be computed
    from a Phase 108 LayoutResult (when available — post-autolayout training
    data) or directly from a SchematicIR via SchematicSpatialExtractor
    (when no layout exists — raw crawled schematics).

    Construction discipline:
      - Use from_layout_result() when you have an autolayout output
      - Use from_spatial_extractor() when scoring a raw schematic

    Attributes:
        bounding_box_mm2: Area of the bounding box of all components in mm^2.
        component_footprint_area_mm2: Sum of individual component footprint
            areas in mm^2.
        crossing_count: Number of edge crossings in the layout (0 for raw
            schematics with no layout yet).
    """

    bounding_box_mm2: float
    component_footprint_area_mm2: float
    crossing_count: int

    @classmethod
    def from_layout_result(
        cls,
        layout_result: "LayoutResult",
        sch_ir: "SchematicIR",
    ) -> "CapInputs":
        """Post-autolayout path. crossing_count from LayoutResult,
        bbox/footprint computed from sch_ir component positions."""
        if layout_result is None:
            raise ValueError(
                "layout_result must not be None — use from_spatial_extractor for raw schematics"
            )
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        extractor = SchematicSpatialExtractor(sch_ir)
        bbox, footprint = _compute_bbox_and_footprint(extractor.extract_component_boxes())
        return cls(
            bounding_box_mm2=bbox,
            component_footprint_area_mm2=footprint,
            crossing_count=int(layout_result.crossing_count),
        )

    @classmethod
    def from_spatial_extractor(
        cls,
        extractor: "SchematicSpatialExtractor",
        crossing_count: int = 0,
    ) -> "CapInputs":
        """Raw-schematic path. crossing_count defaults to 0 (no LayoutResult
        available). bbox/footprint computed from extractor."""
        bbox, footprint = _compute_bbox_and_footprint(extractor.extract_component_boxes())
        return cls(
            bounding_box_mm2=bbox,
            component_footprint_area_mm2=footprint,
            crossing_count=int(crossing_count),
        )


def _compute_bbox_and_footprint(boxes: list) -> tuple[float, float]:
    """Compute total bounding box area and sum of component footprint areas.

    Returns (0.0, 0.0) for empty list. CompactnessCap handles the 0-case
    via max(footprint_mm2, 1.0) guard.
    """
    if not boxes:
        return 0.0, 0.0
    x_min = min(b.x1 for b in boxes)
    x_max = max(b.x2 for b in boxes)
    y_min = min(b.y1 for b in boxes)
    y_max = max(b.y2 for b in boxes)
    bbox_area = max((x_max - x_min) * (y_max - y_min), 0.0)
    footprint = sum(
        max((b.x2 - b.x1) * (b.y2 - b.y1), 0.0) for b in boxes
    )
    return bbox_area, footprint
