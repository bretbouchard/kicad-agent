"""DRC-aware placement validation with component-size-aware bounding boxes.

Extends the existing validate_placement_clearance with per-component estimated
sizes, rotation-aware bounding boxes, and SpatialQueryEngine-backed O(n log n)
clearance queries. Every suggested placement passes DRC clearance checks before
being accepted.

Security (threat model):
  T-16-06: O(n log n) clearance via SpatialQueryEngine STRtree, bounded by
           500 component cap.
  T-16-07: Board dimension validation prevents degenerate inputs.

Usage::

    from kicad_agent.placement.validation import (
        PlacementValidator,
        PlacementViolation,
        positions_to_boxes,
        validate_placement,
    )

    validator = PlacementValidator(board_width=100, board_height=80)
    valid, violations = validator.validate(positions, component_sizes)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kicad_agent.spatial.primitives import SpatialBox
from kicad_agent.spatial.query import SpatialQueryEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_COMPONENTS = 500
"""Maximum component count for validation (DoS prevention, T-16-06)."""

_DEFAULT_SIZE = 2.0
"""Default bounding box size in mm when component size is unknown."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlacementViolation:
    """A single placement rule violation.

    Attributes:
        violation_type: Category of violation ("clearance", "overlap",
            "bounds", "rotation").
        component_refs: Reference designators of the components involved.
        message: Human-readable description of the violation.
        distance_mm: Distance in mm for clearance violations, 0.0 for
            other types.
        severity: "critical" for overlap/bounds, "warning" for clearance
            below 2x minimum.
    """

    violation_type: str
    component_refs: tuple[str, ...]
    message: str
    distance_mm: float
    severity: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def positions_to_boxes(
    positions: dict[str, tuple[float, float, float]],
    component_sizes: dict[str, float],
) -> list[SpatialBox]:
    """Convert placement positions to SpatialBox list using per-component sizes.

    For each (ref, (x, y, rotation)) entry:
    1. Get estimated size from component_sizes (default 2.0 mm).
    2. Compute axis-aligned bounding box, applying rotation if non-zero.
    3. Create a SpatialBox with the computed corners.

    Rotation handling: the rectangle's corners are rotated by the given angle
    and the axis-aligned bounding box of the rotated corners is computed.

    Args:
        positions: Mapping of reference designator to (x, y, rotation_degrees).
        component_sizes: Mapping of reference designator to estimated size in mm.

    Returns:
        List of SpatialBox instances with computed corners.
    """
    boxes: list[SpatialBox] = []

    for ref, (x, y, rotation) in positions.items():
        size = component_sizes.get(ref, _DEFAULT_SIZE)
        half_w = size / 2.0
        half_h = size / 2.0

        if abs(rotation) < 1e-9:
            # No rotation -- simple axis-aligned box
            boxes.append(
                SpatialBox(
                    x1=x - half_w,
                    y1=y - half_h,
                    x2=x + half_w,
                    y2=y + half_h,
                    entity_type="component",
                    entity_id=ref,
                    reference=ref,
                )
            )
        else:
            # Rotation: compute axis-aligned bounding box of rotated rectangle
            angle_rad = math.radians(rotation)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            # Four corners relative to center
            corners = [
                (-half_w, -half_h),
                (half_w, -half_h),
                (half_w, half_h),
                (-half_w, half_h),
            ]

            # Rotate each corner and translate to position
            rotated_xs: list[float] = []
            rotated_ys: list[float] = []
            for cx, cy in corners:
                rx = cx * cos_a - cy * sin_a + x
                ry = cx * sin_a + cy * cos_a + y
                rotated_xs.append(rx)
                rotated_ys.append(ry)

            boxes.append(
                SpatialBox(
                    x1=min(rotated_xs),
                    y1=min(rotated_ys),
                    x2=max(rotated_xs),
                    y2=max(rotated_ys),
                    entity_type="component",
                    entity_id=ref,
                    reference=ref,
                )
            )

    return boxes


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class PlacementValidator:
    """DRC-aware placement validator with SpatialQueryEngine clearance checks.

    Validates placements against:
    - Pairwise clearance using SpatialQueryEngine for O(n log n) queries.
    - Board bounds with margin.
    - Component overlap detection.

    Args:
        board_width: Board width in mm (must be positive).
        board_height: Board height in mm (must be positive).
        min_clearance: Minimum allowed distance between components in mm.

    Raises:
        ValueError: If board dimensions are not positive.
    """

    def __init__(
        self,
        board_width: float,
        board_height: float,
        min_clearance: float = 1.0,
    ) -> None:
        if board_width <= 0 or board_height <= 0:
            raise ValueError(
                f"Board dimensions must be positive, got "
                f"width={board_width}, height={board_height}"
            )
        self._board_width = board_width
        self._board_height = board_height
        self._min_clearance = min_clearance

    def validate(
        self,
        positions: dict[str, tuple[float, float, float]],
        component_sizes: dict[str, float],
    ) -> tuple[bool, list[PlacementViolation]]:
        """Validate a placement configuration.

        Checks pairwise clearances, board bounds, and component overlaps.

        Args:
            positions: Mapping of ref to (x, y, rotation_degrees).
            component_sizes: Mapping of ref to estimated size in mm.

        Returns:
            Tuple of (is_valid, list of PlacementViolation).

        Raises:
            ValueError: If component count exceeds 500.
        """
        if not positions:
            return True, []

        if len(positions) > _MAX_COMPONENTS:
            raise ValueError(
                f"Component count {len(positions)} exceeds maximum "
                f"{_MAX_COMPONENTS}"
            )

        violations: list[PlacementViolation] = []

        # Build boxes from positions + sizes
        boxes = positions_to_boxes(positions, component_sizes)

        # Check pairwise clearances using SpatialQueryEngine
        engine = SpatialQueryEngine(boxes)
        search_radius = 2.0 * self._min_clearance

        seen_pairs: set[frozenset[str]] = set()

        for box in boxes:
            ref = box.reference or box.entity_id
            results = engine.clearance(box.entity_id, search_radius_mm=search_radius)

            for neighbor, distance in results:
                neighbor_ref = neighbor.reference or neighbor.entity_id
                pair = frozenset({ref, neighbor_ref})

                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                if distance < 1e-9:
                    # Overlap (critical)
                    violations.append(
                        PlacementViolation(
                            violation_type="overlap",
                            component_refs=(ref, neighbor_ref),
                            message=(
                                f"Components {ref} and {neighbor_ref} overlap "
                                f"(distance={distance:.3f}mm)"
                            ),
                            distance_mm=distance,
                            severity="critical",
                        )
                    )
                elif distance < self._min_clearance:
                    # Clearance violation
                    severity = (
                        "warning"
                        if distance >= self._min_clearance * 0.5
                        else "critical"
                    )
                    violations.append(
                        PlacementViolation(
                            violation_type="clearance",
                            component_refs=(ref, neighbor_ref),
                            message=(
                                f"Clearance violation between {ref} and "
                                f"{neighbor_ref}: {distance:.3f}mm < "
                                f"{self._min_clearance}mm"
                            ),
                            distance_mm=distance,
                            severity=severity,
                        )
                    )

        # Check board bounds
        margin = self._min_clearance
        for box in boxes:
            ref = box.reference or box.entity_id
            if (
                box.x1 < -margin
                or box.y1 < -margin
                or box.x2 > self._board_width + margin
                or box.y2 > self._board_height + margin
            ):
                violations.append(
                    PlacementViolation(
                        violation_type="bounds",
                        component_refs=(ref,),
                        message=(
                            f"Component {ref} extends outside board bounds: "
                            f"({box.x1:.2f},{box.y1:.2f})-"
                            f"({box.x2:.2f},{box.y2:.2f})"
                        ),
                        distance_mm=0.0,
                        severity="critical",
                    )
                )

        is_valid = len(violations) == 0
        return is_valid, violations

    def has_overlaps(
        self,
        positions: dict[str, tuple[float, float, float]],
        component_sizes: dict[str, float],
    ) -> tuple[bool, int]:
        """Quick check for overlapping components.

        Returns (True, count) if any overlaps exist, (False, 0) otherwise.
        Uses O(n^2) pairwise distance check which is fast for n <= 500.

        Args:
            positions: Mapping of ref to (x, y, rotation).
            component_sizes: Mapping of ref to estimated size in mm.

        Returns:
            Tuple of (has_any_overlaps, overlap_count).
        """
        refs = list(positions.keys())
        n = len(refs)
        if n < 2:
            return False, 0

        import math

        overlap_count = 0
        for i in range(n):
            xi, yi, _ = positions[refs[i]]
            si = component_sizes.get(refs[i], _DEFAULT_SIZE) / 2.0
            for j in range(i + 1, n):
                xj, yj, _ = positions[refs[j]]
                sj = component_sizes.get(refs[j], _DEFAULT_SIZE) / 2.0
                dist = math.hypot(xi - xj, yi - yj)
                if dist < si + sj:
                    overlap_count += 1

        return overlap_count > 0, overlap_count

    def validate_with_spatial_engine(
        self,
        positions: dict[str, tuple[float, float, float]],
        component_sizes: dict[str, float],
    ) -> dict:
        """Full validation returning structured result dict.

        Compatible with existing validate_placement_clearance output format,
        enriched with typed violations, board utilization, and component count.

        Args:
            positions: Mapping of ref to (x, y, rotation_degrees).
            component_sizes: Mapping of ref to estimated size in mm.

        Returns:
            Dict with keys:
            - "valid": bool
            - "violations": list[dict] with "type", "message", "distance_mm",
                "entities"
            - "placement_violations": list[PlacementViolation]
            - "min_clearance_found_mm": float
            - "n_components": int
            - "board_utilization": float
        """
        is_valid, placement_violations = self.validate(positions, component_sizes)

        # Compute minimum clearance found
        clearance_distances = [
            v.distance_mm
            for v in placement_violations
            if v.violation_type == "clearance"
        ]
        min_clearance_found = min(clearance_distances) if clearance_distances else 0.0

        # If no clearance violations, compute actual min clearance from pairs
        if not clearance_distances and positions:
            boxes = positions_to_boxes(positions, component_sizes)
            if len(boxes) > 1:
                min_dist = float("inf")
                for i in range(len(boxes)):
                    geom_i = boxes[i].to_shapely()
                    for j in range(i + 1, len(boxes)):
                        dist = geom_i.distance(boxes[j].to_shapely())
                        min_dist = min(min_dist, dist)
                min_clearance_found = min_dist if min_dist != float("inf") else 0.0

        # Compute board utilization
        board_area = self._board_width * self._board_height
        boxes = positions_to_boxes(positions, component_sizes)
        component_area = sum(
            (b.x2 - b.x1) * (b.y2 - b.y1) for b in boxes
        )
        utilization = component_area / board_area if board_area > 0 else 0.0

        # Build violation dicts (compatible with validate_placement_clearance)
        violation_dicts: list[dict] = []
        for v in placement_violations:
            violation_dicts.append({
                "type": v.violation_type,
                "message": v.message,
                "distance_mm": v.distance_mm,
                "entities": list(v.component_refs),
            })

        return {
            "valid": is_valid,
            "violations": violation_dicts,
            "placement_violations": placement_violations,
            "min_clearance_found_mm": round(min_clearance_found, 6),
            "n_components": len(positions),
            "board_utilization": round(utilization, 6),
        }


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def validate_placement(
    graph: "PlacementGraph",
    positions: dict[str, tuple[float, float, float]],
) -> tuple[bool, list[PlacementViolation]]:
    """Validate placement using a PlacementGraph for board dimensions and sizes.

    Convenience function that extracts component sizes from the graph's
    component node data, creates a PlacementValidator with the graph's board
    dimensions, and delegates to PlacementValidator.validate().

    Args:
        graph: PlacementGraph with board dimensions and component specs.
        positions: Mapping of ref to (x, y, rotation_degrees).

    Returns:
        Tuple of (is_valid, list of PlacementViolation).
    """
    # Extract component sizes from graph node data
    component_sizes: dict[str, float] = {}
    for node_id in graph.component_nodes():
        data = graph._graph.nodes[node_id]
        ref = data.get("reference", "")
        size = data.get("estimated_size", _DEFAULT_SIZE)
        component_sizes[ref] = size

    validator = PlacementValidator(
        board_width=graph.board_width,
        board_height=graph.board_height,
    )
    return validator.validate(positions, component_sizes)
