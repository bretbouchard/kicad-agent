"""Schematic Readability Score (SRS) -- 4-factor composite quality metric.

READ-03/04: Produces a 0.0-1.0 score indicating schematic readability.

Four factors, equally weighted:
  - Density (0.25): Are components spread out enough?
  - Clarity (0.25): Are labels unique and readable?
  - Spacing (0.25): Are elements properly spaced?
  - Organization (0.25): Do components match functional groups?

Usage:
    from volta.analysis.readability_scorer import SchematicReadabilityScorer

    scorer = SchematicReadabilityScorer(extractor, topology)
    report = scorer.score()
    print(f"SRS: {report.srs:.2f}")
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.analysis.schematic_spatial import SchematicSpatialExtractor
    from volta.analysis.topology_graph import CircuitTopology

from volta.spatial.primitives import SpatialBox

logger = logging.getLogger(__name__)

# Minimum spacing between components in mm for readability
_MIN_COMPONENT_SPACING_MM = 5.0
# Maximum component density (components per 100x100mm area)
_MAX_DENSITY_PER_10000SQMM = 30


@dataclass(frozen=True)
class ReadabilityReport:
    """Schematic readability assessment report.

    Attributes:
        srs: Composite Schematic Readability Score (0.0-1.0).
        factors: Individual factor scores.
        suggestions: Ordered list of improvements by impact.
        element_count: Number of elements analyzed.
    """

    srs: float
    factors: dict[str, float] = field(default_factory=dict)
    suggestions: tuple[str, ...] = ()
    element_count: int = 0


class SchematicReadabilityScorer:
    """Scores schematic readability on a 0.0-1.0 scale.

    Args:
        extractor: SchematicSpatialExtractor with schematic data.
        topology: Optional CircuitTopology for organization scoring.
    """

    def __init__(
        self,
        extractor: "SchematicSpatialExtractor",
        topology: Any | None = None,
    ) -> None:
        self._extractor = extractor
        self._topology = topology
        self._component_boxes: list[SpatialBox] | None = None
        self._label_boxes: list[SpatialBox] | None = None

    def score(self) -> ReadabilityReport:
        """Compute the Schematic Readability Score."""
        self._component_boxes = self._extractor.extract_component_boxes()
        self._label_boxes = self._extractor.extract_label_boxes()
        all_elements = self._component_boxes + self._label_boxes

        density = self._score_density()
        clarity = self._score_clarity()
        spacing = self._score_spacing()
        organization = self._score_organization()

        factors = {
            "density": density,
            "clarity": clarity,
            "spacing": spacing,
            "organization": organization,
        }
        srs = sum(factors.values()) / len(factors)

        suggestions = self._generate_suggestions(factors)

        return ReadabilityReport(
            srs=srs,
            factors=factors,
            suggestions=tuple(suggestions),
            element_count=len(all_elements),
        )

    def _score_density(self) -> float:
        """Score component density. Lower density = better readability."""
        boxes = self._component_boxes or []
        if len(boxes) < 2:
            return 1.0

        x_min = min(b.x1 for b in boxes)
        x_max = max(b.x2 for b in boxes)
        y_min = min(b.y1 for b in boxes)
        y_max = max(b.y2 for b in boxes)
        area = max((x_max - x_min) * (y_max - y_min), 1.0)

        density = len(boxes) / (area / 10000.0)
        if density <= _MAX_DENSITY_PER_10000SQMM:
            return 1.0
        return max(0.0, 1.0 - (density - _MAX_DENSITY_PER_10000SQMM) / _MAX_DENSITY_PER_10000SQMM)

    def _score_clarity(self) -> float:
        """Score label clarity. Penalizes duplicate label names."""
        labels = self._label_boxes or []
        if not labels:
            return 1.0

        # Count duplicate label names (entity_id format: "label_{name}_{x:.1f}_{y:.1f}")
        name_counts: dict[str, int] = {}
        for lb in labels:
            body = lb.entity_id
            if body.startswith("label_"):
                body = body[len("label_"):]
            parts = body.rsplit("_", 2)
            name = parts[0] if len(parts) >= 3 else body
            name_counts[name] = name_counts.get(name, 0) + 1

        duplicates = sum(c - 1 for c in name_counts.values() if c > 1)
        if duplicates == 0:
            return 1.0

        penalty = min(duplicates * 0.1, 0.8)
        return max(0.0, 1.0 - penalty)

    def _score_spacing(self) -> float:
        """Score element spacing. Penalizes components too close together."""
        boxes = self._component_boxes or []
        if len(boxes) < 2:
            return 1.0

        too_close = 0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                gap = self._min_gap(boxes[i], boxes[j])
                if gap < _MIN_COMPONENT_SPACING_MM:
                    too_close += 1

        total_pairs = len(boxes) * (len(boxes) - 1) / 2
        if total_pairs == 0:
            return 1.0
        violation_ratio = too_close / total_pairs
        return max(0.0, 1.0 - violation_ratio)

    def _score_organization(self) -> float:
        """Score functional organization using subcircuit data."""
        if self._topology is None:
            return 0.75  # Neutral score when no topology data

        subcircuits = getattr(self._topology, "subcircuits", None)
        if not subcircuits:
            return 0.75

        boxes_by_ref = {b.entity_id: b for b in (self._component_boxes or [])}

        group_scores = []
        for sub in subcircuits:
            sub_boxes = [boxes_by_ref[ref] for ref in sub.components if ref in boxes_by_ref]
            if len(sub_boxes) < 2:
                continue

            cx = sum((b.x1 + b.x2) / 2 for b in sub_boxes) / len(sub_boxes)
            cy = sum((b.y1 + b.y2) / 2 for b in sub_boxes) / len(sub_boxes)

            max_dist = max(
                math.hypot((b.x1 + b.x2) / 2 - cx, (b.y1 + b.y2) / 2 - cy)
                for b in sub_boxes
            )
            group_scores.append(max(0.0, 1.0 - max_dist / 50.0))

        if not group_scores:
            return 0.75
        return sum(group_scores) / len(group_scores)

    @staticmethod
    def _min_gap(a: SpatialBox, b: SpatialBox) -> float:
        """Compute minimum gap between two axis-aligned boxes."""
        gap_x = max(0, max(a.x1, b.x1) - min(a.x2, b.x2))
        gap_y = max(0, max(a.y1, b.y1) - min(a.y2, b.y2))
        if gap_x > 0 and gap_y > 0:
            return min(gap_x, gap_y)
        if gap_x > 0:
            return gap_x
        if gap_y > 0:
            return gap_y
        return 0.0

    def _generate_suggestions(self, factors: dict[str, float]) -> list[str]:
        """Generate ordered improvement suggestions from factor scores."""
        suggestions = []
        for factor, score in sorted(factors.items(), key=lambda x: x[1]):
            if score < 0.5:
                if factor == "density":
                    suggestions.append("Spread components out -- density is too high for readability")
                elif factor == "clarity":
                    suggestions.append("Remove duplicate labels and resolve overlapping text")
                elif factor == "spacing":
                    suggestions.append("Increase spacing between components to at least 5mm")
                elif factor == "organization":
                    suggestions.append("Group subcircuit components closer together spatially")
        return suggestions
