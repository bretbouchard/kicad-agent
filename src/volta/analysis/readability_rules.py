"""Schematic readability rules -- overlap, text, label, spacing, and wire clutter.

READ-01/02/03/04: Six DesignRule implementations extending Phase 48's
rule engine with schematic-specific spatial quality checks.

Rules:
  SCHEMATIC_OVERLAP_01: Components with overlapping bounding boxes
  TEXT_OVERLAP_01: Text elements (refs, values, labels) that overlap
  DUPLICATE_LABEL_01: Redundant labels on same net within proximity
  LABEL_SPACING_01: Labels too close to distinguish
  COMPONENT_SPACING_01: Components too close for readability
  WIRE_CLUTTER_01: Wires crossing through component bodies

Usage:
    from volta.analysis.readability_rules import get_schematic_readability_rules

    rules = get_schematic_readability_rules()
    engine = DesignRuleEngine(rules=get_builtin_rules() + rules)
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.analysis.topology_graph import CircuitTopology

from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from volta.spatial.primitives import SpatialBox

logger = logging.getLogger(__name__)


def _iou(box_a: SpatialBox, box_b: SpatialBox) -> float:
    """Compute intersection over union for two SpatialBoxes.

    Returns:
        IoU value 0.0-1.0. 0.0 = no overlap, 1.0 = identical.
    """
    ix1 = max(box_a.x1, box_b.x1)
    iy1 = max(box_a.y1, box_b.y1)
    ix2 = min(box_a.x2, box_b.x2)
    iy2 = min(box_a.y2, box_b.y2)

    if ix1 >= ix2 or iy1 >= iy2:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    area_a = (box_a.x2 - box_a.x1) * (box_a.y2 - box_a.y1)
    area_b = (box_b.x2 - box_b.x1) * (box_b.y2 - box_b.y1)
    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0
    return intersection / union


def _iou_to_severity(iou: float) -> RuleSeverity:
    """Map IoU to severity level.

    >50% overlap = CRITICAL (components nearly stacked)
    10-50% overlap = WARNING (partial overlap, likely readability issue)
    <10% overlap = INFO (minor, may be intentional)
    """
    if iou > 0.5:
        return RuleSeverity.CRITICAL
    if iou > 0.1:
        return RuleSeverity.WARNING
    return RuleSeverity.INFO


class SchematicOverlapRule(DesignRule):
    """SCHEMATIC_OVERLAP_01: Detect components with overlapping bounding boxes.

    Uses SchematicSpatialExtractor to get component boxes, then
    checks all pairs for overlap using IoU metric.

    Config:
        iou_threshold: Minimum IoU to report (default 0.05).
    """

    name = "SCHEMATIC_OVERLAP_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.WARNING
    description = "Components with overlapping bounding boxes"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        iou_threshold = config.get("iou_threshold", 0.05)
        violations = []

        boxes = self._get_component_boxes(topology)
        if len(boxes) < 2:
            return violations

        # O(n^2) pairwise check -- fine for typical schematics (<200 components)
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                iou_val = _iou(boxes[i], boxes[j])
                if iou_val >= iou_threshold:
                    severity = _iou_to_severity(iou_val)
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=f"Components {boxes[i].entity_id} and "
                                    f"{boxes[j].entity_id} overlap "
                                    f"(IoU: {iou_val:.0%})",
                        severity=severity,
                        location=f"{boxes[i].entity_id} / {boxes[j].entity_id}",
                        suggestion=f"Move {boxes[j].entity_id} away from "
                                   f"{boxes[i].entity_id} to eliminate overlap",
                        affected_components=(boxes[i].entity_id, boxes[j].entity_id),
                        details={"iou": round(iou_val, 4)},
                    ))

        return violations

    def _get_component_boxes(self, topology: Any) -> list[SpatialBox]:
        """Extract component bounding boxes from topology."""
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            from volta.analysis.schematic_spatial import SchematicSpatialExtractor
            extractor = SchematicSpatialExtractor(ir)
            return extractor.extract_component_boxes()
        return []


class TextOverlapRule(DesignRule):
    """TEXT_OVERLAP_01: Detect overlapping text elements.

    Checks reference designators, value text, and labels for
    spatial overlap. Text width estimated from character count
    and default font size.

    Config:
        min_overlap_pct: Minimum IoU to report (default 0.1).
    """

    name = "TEXT_OVERLAP_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.WARNING
    description = "Text elements (refs, values, labels) that overlap"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        min_overlap_pct = config.get("min_overlap_pct", 0.1)
        violations = []

        text_boxes = self._get_text_boxes(topology)
        if len(text_boxes) < 2:
            return violations

        for i in range(len(text_boxes)):
            for j in range(i + 1, len(text_boxes)):
                iou_val = _iou(text_boxes[i], text_boxes[j])
                if iou_val >= min_overlap_pct:
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=f"Text {text_boxes[i].entity_id} overlaps "
                                    f"{text_boxes[j].entity_id} "
                                    f"(IoU: {iou_val:.0%})",
                        severity=RuleSeverity.WARNING,
                        location=f"{text_boxes[i].entity_id} / {text_boxes[j].entity_id}",
                        suggestion="Reposition or hide one of the overlapping text elements",
                        details={"iou": round(iou_val, 4)},
                    ))

        return violations

    def _get_text_boxes(self, topology: Any) -> list[SpatialBox]:
        """Extract text bounding boxes from topology."""
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            from volta.analysis.schematic_spatial import SchematicSpatialExtractor
            extractor = SchematicSpatialExtractor(ir)
            boxes = extractor.extract_text_boxes()
            boxes.extend(extractor.extract_label_boxes())
            return boxes
        return []


class DuplicateLabelRule(DesignRule):
    """DUPLICATE_LABEL_01: Detect redundant labels on the same net.

    Multiple labels with the same name within a proximity threshold
    are redundant and suggest the schematic was generated without
    label cleanup.

    Config:
        proximity_mm: Maximum distance to consider duplicates (default 20mm).
    """

    name = "DUPLICATE_LABEL_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.SUGGESTION
    description = "Redundant labels on the same net within proximity"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        proximity = config.get("proximity_mm", 20.0)
        violations = []

        label_boxes = self._get_label_boxes(topology)

        # Group by name extracted from entity_id: "label_{name}_{x:.1f}_{y:.1f}"
        by_name: dict[str, list[SpatialBox]] = {}
        for lb in label_boxes:
            # Strip "label_" prefix, then strip trailing "_xx.x_yy.y" coords
            body = lb.entity_id
            if body.startswith("label_"):
                body = body[len("label_"):]
            # Remove last two underscore-separated coordinate segments
            parts = body.rsplit("_", 2)
            name = parts[0] if len(parts) >= 3 else body
            by_name.setdefault(name, []).append(lb)

        for name, boxes in by_name.items():
            if len(boxes) < 2:
                continue
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    dist = self._center_distance(boxes[i], boxes[j])
                    if dist <= proximity:
                        violations.append(DesignRuleViolation(
                            rule_id=self.name,
                            description=f"Duplicate label '{name}' at "
                                        f"({boxes[i].x1:.1f},{boxes[i].y1:.1f}) and "
                                        f"({boxes[j].x1:.1f},{boxes[j].y1:.1f}) -- "
                                        f"{dist:.1f}mm apart",
                            severity=self.default_severity,
                            location=f"label:{name}",
                            suggestion=f"Remove duplicate '{name}' label or consolidate",
                            details={"label_name": name, "distance_mm": round(dist, 1)},
                        ))

        return violations

    @staticmethod
    def _center_distance(a: SpatialBox, b: SpatialBox) -> float:
        cx_a, cy_a = (a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2
        cx_b, cy_b = (b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2
        return math.hypot(cx_a - cx_b, cy_a - cy_b)

    def _get_label_boxes(self, topology: Any) -> list[SpatialBox]:
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            from volta.analysis.schematic_spatial import SchematicSpatialExtractor
            return SchematicSpatialExtractor(ir).extract_label_boxes()
        return []


class LabelSpacingRule(DesignRule):
    """LABEL_SPACING_01: Labels too close to distinguish.

    Config:
        min_spacing_mm: Minimum spacing between labels (default 3.0mm).
    """

    name = "LABEL_SPACING_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.SUGGESTION
    description = "Labels too close to distinguish"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        min_spacing = config.get("min_spacing_mm", 3.0)
        violations = []

        labels = self._get_label_boxes(topology)
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                gap = self._min_gap(labels[i], labels[j])
                if gap < min_spacing:
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=f"Labels {labels[i].entity_id} and {labels[j].entity_id} "
                                    f"are only {gap:.1f}mm apart (min: {min_spacing}mm)",
                        severity=self.default_severity,
                        location=f"{labels[i].entity_id} / {labels[j].entity_id}",
                        suggestion="Increase label spacing for readability",
                        details={"gap_mm": round(gap, 1)},
                    ))
        return violations

    @staticmethod
    def _min_gap(a: SpatialBox, b: SpatialBox) -> float:
        gap_x = max(0, max(a.x1, b.x1) - min(a.x2, b.x2))
        gap_y = max(0, max(a.y1, b.y1) - min(a.y2, b.y2))
        if gap_x > 0 and gap_y > 0:
            return min(gap_x, gap_y)
        if gap_x > 0:
            return gap_x
        if gap_y > 0:
            return gap_y
        return 0.0

    def _get_label_boxes(self, topology: Any) -> list[SpatialBox]:
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            from volta.analysis.schematic_spatial import SchematicSpatialExtractor
            return SchematicSpatialExtractor(ir).extract_label_boxes()
        return []


class ComponentSpacingRule(DesignRule):
    """COMPONENT_SPACING_01: Components too close for readability.

    Config:
        min_gap_mm: Minimum gap between components (default 2.0mm).
    """

    name = "COMPONENT_SPACING_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.INFO
    description = "Components too close for readability"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        min_gap = config.get("min_gap_mm", 2.0)
        violations = []

        boxes = self._get_component_boxes(topology)
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                gap = self._min_gap(boxes[i], boxes[j])
                if gap < min_gap:
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=f"{boxes[i].entity_id} and {boxes[j].entity_id} "
                                    f"are only {gap:.1f}mm apart",
                        severity=self.default_severity,
                        location=f"{boxes[i].entity_id} / {boxes[j].entity_id}",
                        suggestion=f"Increase spacing between {boxes[i].entity_id} "
                                   f"and {boxes[j].entity_id}",
                        details={"gap_mm": round(gap, 1)},
                    ))
        return violations

    @staticmethod
    def _min_gap(a: SpatialBox, b: SpatialBox) -> float:
        gap_x = max(0, max(a.x1, b.x1) - min(a.x2, b.x2))
        gap_y = max(0, max(a.y1, b.y1) - min(a.y2, b.y2))
        if gap_x > 0 and gap_y > 0:
            return min(gap_x, gap_y)
        if gap_x > 0:
            return gap_x
        if gap_y > 0:
            return gap_y
        return 0.0

    def _get_component_boxes(self, topology: Any) -> list[SpatialBox]:
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            from volta.analysis.schematic_spatial import SchematicSpatialExtractor
            return SchematicSpatialExtractor(ir).extract_component_boxes()
        return []


class WireClutterRule(DesignRule):
    """WIRE_CLUTTER_01: Wires crossing through component bodies.

    Flags wire segments whose line intersects a component bounding box.
    """

    name = "WIRE_CLUTTER_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.INFO
    description = "Wires crossing through component bodies"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations = []

        comp_boxes = self._get_component_boxes(topology)
        wire_segments = self._get_wire_segments(topology)

        for wire in wire_segments:
            for comp in comp_boxes:
                if self._line_intersects_box(wire, comp):
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=f"Wire segment at ({wire[0]:.1f},{wire[1]:.1f})-"
                                    f"({wire[2]:.1f},{wire[3]:.1f}) crosses "
                                    f"through {comp.entity_id}",
                        severity=self.default_severity,
                        location=comp.entity_id,
                        suggestion=f"Reroute wire to avoid crossing {comp.entity_id}",
                        details={"wire_start": (wire[0], wire[1]),
                                 "wire_end": (wire[2], wire[3])},
                    ))

        return violations

    @staticmethod
    def _line_intersects_box(
        segment: tuple[float, float, float, float],
        box: SpatialBox,
    ) -> bool:
        """Check if a line segment intersects a bounding box (Liang-Barsky)."""
        x1, y1, x2, y2 = segment
        dx = x2 - x1
        dy = y2 - y1

        p = [-dx, dx, -dy, dy]
        q = [x1 - box.x1, box.x2 - x1, y1 - box.y1, box.y2 - y1]

        t_min, t_max = 0.0, 1.0
        for i in range(4):
            if abs(p[i]) < 1e-10:
                if q[i] < 0:
                    return False
            else:
                t = q[i] / p[i]
                if p[i] < 0:
                    t_min = max(t_min, t)
                else:
                    t_max = min(t_max, t)
                if t_min > t_max:
                    return False

        return t_min < t_max  # Strict: exclude mere edge-touching

    def _get_component_boxes(self, topology: Any) -> list[SpatialBox]:
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            from volta.analysis.schematic_spatial import SchematicSpatialExtractor
            return SchematicSpatialExtractor(ir).extract_component_boxes()
        return []

    def _get_wire_segments(self, topology: Any) -> list[tuple[float, float, float, float]]:
        ir = getattr(topology, "_schematic_ir", None)
        if ir is not None:
            wires = ir.get_wire_endpoints()
            return [(w["start_x"], w["start_y"], w["end_x"], w["end_y"]) for w in wires]
        return []


def get_schematic_readability_rules() -> list[DesignRule]:
    """Return all 6 schematic readability rule instances."""
    return [
        SchematicOverlapRule(),
        TextOverlapRule(),
        DuplicateLabelRule(),
        LabelSpacingRule(),
        ComponentSpacingRule(),
        WireClutterRule(),
    ]
