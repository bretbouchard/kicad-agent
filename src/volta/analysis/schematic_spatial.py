"""Schematic spatial analysis -- extract spatial primitives from schematics.

READ-01: Converts schematic elements (components, text, labels, wires)
into SpatialBox/SpatialPoint primitives for overlap detection and
readability analysis.

Uses existing spatial/query.py SpatialQueryEngine for O(log n) lookups.
Component bounding boxes are estimated from library symbol graphics
with rotation-aware AABB expansion.

Usage:
    from volta.analysis.schematic_spatial import SchematicSpatialExtractor

    extractor = SchematicSpatialExtractor(schematic_ir)
    boxes = extractor.extract_all()
    engine = SpatialQueryEngine(boxes)
"""
from __future__ import annotations

import math
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.ir.schematic_ir import SchematicIR

from volta.spatial.primitives import SpatialBox, SpatialPoint

logger = logging.getLogger(__name__)

# Default bounding box estimates (mm) when lib symbol data unavailable.
_DEFAULT_SYMBOL_SIZE = (5.0, 3.0)  # width, height
_IC_SYMBOL_SIZE = (10.0, 8.0)
_PASSIVE_SYMBOL_SIZE = (2.54, 3.81)
_POWER_SYMBOL_SIZE = (3.0, 3.0)

# Text sizing: KiCad default 1.27mm font height, ~0.6x width ratio
_DEFAULT_FONT_HEIGHT = 1.27
_CHAR_WIDTH_RATIO = 0.6
_TEXT_PADDING = 0.5  # mm padding around text bounding box


class SchematicSpatialExtractor:
    """Extract spatial primitives from a SchematicIR.

    Converts components, text, labels, and wires into SpatialBox
    and SpatialPoint objects suitable for spatial queries.

    Args:
        schematic_ir: SchematicIR from parsed .kicad_sch file.
    """

    def __init__(self, schematic_ir: "SchematicIR") -> None:
        self._ir = schematic_ir

    def extract_component_boxes(self) -> list[SpatialBox]:
        """Extract bounding boxes for all schematic components.

        Returns axis-aligned bounding boxes accounting for rotation.
        Estimates size from lib_id heuristics when exact graphics
        data is unavailable.
        """
        result: list[SpatialBox] = []
        for sym in self._ir.components:
            ref = self._ir.get_component_property(sym, "Reference") or ""
            lib_id = sym.libId
            sx = sym.position.X
            sy = sym.position.Y
            angle = sym.position.angle or 0.0

            w, h = self._estimate_symbol_size(lib_id)
            # Rotation-aware AABB expansion
            if angle in (0, 180):
                bw, bh = w, h
            elif angle in (90, 270):
                bw, bh = h, w
            else:
                # Arbitrary rotation: expand to cover rotated rect
                rad = math.radians(angle)
                bw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
                bh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))

            result.append(SpatialBox(
                x1=sx - bw / 2, y1=sy - bh / 2,
                x2=sx + bw / 2, y2=sy + bh / 2,
                entity_type="component",
                entity_id=ref,
            ))
        return result

    def extract_text_boxes(self) -> list[SpatialBox]:
        """Extract bounding boxes for reference designators and values.

        Text width estimated from font size and character count.
        Position derived from component position with typical KiCad offsets.
        """
        result: list[SpatialBox] = []
        for sym in self._ir.components:
            ref = self._ir.get_component_property(sym, "Reference") or ""
            value = self._ir.get_component_property(sym, "Value") or ""
            sx = sym.position.X
            sy = sym.position.Y

            # Reference text: positioned above component center
            ref_width = len(ref) * _DEFAULT_FONT_HEIGHT * _CHAR_WIDTH_RATIO
            ref_height = _DEFAULT_FONT_HEIGHT
            result.append(SpatialBox(
                x1=sx - ref_width / 2 - _TEXT_PADDING,
                y1=sy - ref_height - _TEXT_PADDING,
                x2=sx + ref_width / 2 + _TEXT_PADDING,
                y2=sy + _TEXT_PADDING,
                entity_type="text_ref",
                entity_id=f"{ref}_ref",
            ))

            # Value text: positioned below component center
            val_width = len(value) * _DEFAULT_FONT_HEIGHT * _CHAR_WIDTH_RATIO
            result.append(SpatialBox(
                x1=sx - val_width / 2 - _TEXT_PADDING,
                y1=sy + _TEXT_PADDING,
                x2=sx + val_width / 2 + _TEXT_PADDING,
                y2=sy + ref_height + _TEXT_PADDING,
                entity_type="text_value",
                entity_id=f"{ref}_value",
            ))
        return result

    def extract_label_boxes(self) -> list[SpatialBox]:
        """Extract bounding boxes for all labels (local, global, hierarchical).

        Label width estimated from text length and font size.
        """
        result: list[SpatialBox] = []
        for label in self._ir.get_label_positions():
            name = label["name"]
            lx = label["x"]
            ly = label["y"]
            lt = label["label_type"]

            width = len(name) * _DEFAULT_FONT_HEIGHT * _CHAR_WIDTH_RATIO
            height = _DEFAULT_FONT_HEIGHT
            result.append(SpatialBox(
                x1=lx - _TEXT_PADDING,
                y1=ly - height / 2 - _TEXT_PADDING,
                x2=lx + width + _TEXT_PADDING,
                y2=ly + height / 2 + _TEXT_PADDING,
                entity_type=f"label_{lt}",
                entity_id=f"label_{name}_{lx:.1f}_{ly:.1f}",
            ))
        return result

    def extract_wire_points(self) -> list[SpatialPoint]:
        """Extract wire endpoints as SpatialPoint primitives."""
        result: list[SpatialPoint] = []
        for wire in self._ir.get_wire_endpoints():
            result.append(SpatialPoint(
                x=wire["start_x"], y=wire["start_y"],
                entity_type="wire_vertex",
                entity_id=wire.get("uuid", ""),
            ))
            result.append(SpatialPoint(
                x=wire["end_x"], y=wire["end_y"],
                entity_type="wire_vertex",
                entity_id=wire.get("uuid", ""),
            ))
        return result

    def extract_all(self) -> list[SpatialBox | SpatialPoint]:
        """Extract all spatial primitives."""
        result: list[SpatialBox | SpatialPoint] = []
        result.extend(self.extract_component_boxes())
        result.extend(self.extract_text_boxes())
        result.extend(self.extract_label_boxes())
        result.extend(self.extract_wire_points())
        return result

    @staticmethod
    def _estimate_symbol_size(lib_id: str) -> tuple[float, float]:
        """Estimate symbol bounding box from lib_id pattern.

        Returns (width, height) in mm.
        """
        lib_upper = lib_id.upper()
        # Power symbols are small
        if "POWER" in lib_upper or "PWR" in lib_upper:
            return _POWER_SYMBOL_SIZE
        # ICs are larger
        ic_patterns = (
            "NE5532", "TL07", "LM358", "THAT", "CD40",
            "RP2040", "PT2399", "OP07", "OPA", "RC4558",
            "JRC", "BA6110", "LM13700", "LF353",
        )
        if any(p.upper() in lib_upper for p in ic_patterns):
            return _IC_SYMBOL_SIZE
        # Passives
        if "DEVICE:R" in lib_upper or "DEVICE:C" in lib_upper:
            return _PASSIVE_SYMBOL_SIZE
        return _DEFAULT_SYMBOL_SIZE
