"""Component placement engine with clearance validation and spatial scoring.

GEN-09: Provides deterministic placement algorithms with clearance validation
against other components and board edges. Includes decoupling capacitor
proximity heuristic and placement quality scoring.

Security (threat model):
  T-10-15: Pairwise clearance O(n^2) bounded by 500 component cap.
  T-10-16: All coordinates validated within board bounds.

Usage::

    from volta.generation.placement import PlacementEngine, PlacementResult

    engine = PlacementEngine(board_width=100, board_height=80)
    result = engine.place_components(components)
    if result.valid:
        print(f"Score: {result.score}, Positions: {result.positions}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from volta.generation.intent import ComponentSpec, NetSpec
from volta.spatial.primitives import SpatialBox

# DoS prevention: maximum number of components for pairwise checks
_MAX_COMPONENTS = 500


@dataclass(frozen=True)
class PlacementResult:
    """Result of a component placement run.

    Attributes:
        positions: Mapping of reference designator to (x, y) coordinates in mm.
        score: Placement quality score from 0.0 (worst) to 1.0 (best).
        violations: List of clearance or bounds violation descriptions.
        valid: True if no violations were found.
    """

    positions: dict[str, tuple[float, float]]
    score: float
    violations: list[str]
    valid: bool


def validate_placement_clearance(
    boxes: list[SpatialBox],
    min_clearance_mm: float = 1.0,
    board_bounds: tuple[float, float, float, float] | None = None,
) -> dict:
    """Validate clearance between placement bounding boxes.

    Checks pairwise distances between all boxes and optionally verifies
    each box is within the board boundary with the clearance margin.

    Args:
        boxes: List of SpatialBox instances to check.
        min_clearance_mm: Minimum allowed distance between boxes in mm.
        board_bounds: Optional (x1, y1, x2, y2) board boundary in mm.

    Returns:
        Dict with keys:
        - "valid": bool -- True if no violations.
        - "violations": list[dict] -- Each with "type", "message" keys.
        - "min_clearance_found_mm": float -- Smallest pairwise distance found.
    """
    violations: list[dict] = []
    min_distance = float("inf")

    # Check pairwise distances
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            geom_i = boxes[i].to_shapely()
            geom_j = boxes[j].to_shapely()
            dist = geom_i.distance(geom_j)
            min_distance = min(min_distance, dist)
            if dist < min_clearance_mm:
                ref_i = boxes[i].reference or boxes[i].entity_id
                ref_j = boxes[j].reference or boxes[j].entity_id
                violations.append({
                    "type": "clearance",
                    "message": (
                        f"Clearance violation between {ref_i} and {ref_j}: "
                        f"{dist:.3f}mm < {min_clearance_mm}mm"
                    ),
                    "distance_mm": dist,
                    "entities": [ref_i, ref_j],
                })

    # Check board bounds
    if board_bounds is not None:
        bx1, by1, bx2, by2 = board_bounds
        for box in boxes:
            if box.x1 < bx1 or box.y1 < by1 or box.x2 > bx2 or box.y2 > by2:
                ref = box.reference or box.entity_id
                violations.append({
                    "type": "bounds",
                    "message": (
                        f"Component {ref} extends outside board bounds: "
                        f"({box.x1:.2f},{box.y1:.2f})-({box.x2:.2f},{box.y2:.2f})"
                    ),
                    "entity": ref,
                })

    if min_distance == float("inf"):
        min_distance = 0.0

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "min_clearance_found_mm": round(min_distance, 6),
    }


class PlacementEngine:
    """Deterministic component placement engine with clearance validation.

    Uses a grid placement algorithm: the board is divided into cells based on
    component count, and components are placed at grid centers with clearance
    validation and quality scoring.

    Args:
        board_width: Board width in mm.
        board_height: Board height in mm.
        min_clearance: Minimum clearance between components in mm.
    """

    def __init__(
        self,
        board_width: float,
        board_height: float,
        min_clearance: float = 1.0,
    ) -> None:
        if board_width <= 0 or board_height <= 0:
            raise ValueError("Board dimensions must be positive")
        self._board_width = board_width
        self._board_height = board_height
        self._min_clearance = min_clearance

    def place_components(self, components: list[ComponentSpec]) -> PlacementResult:
        """Place components using a grid algorithm with clearance validation.

        Sorts components by estimated size (larger first), divides the board
        into a grid, places each component at a grid cell center, validates
        clearances, and scores the result.

        Args:
            components: List of ComponentSpec to place (max 500).

        Returns:
            PlacementResult with positions, score, and violations.

        Raises:
            ValueError: If component count exceeds 500.
        """
        if len(components) > _MAX_COMPONENTS:
            raise ValueError(
                f"Component count {len(components)} exceeds maximum {_MAX_COMPONENTS}"
            )

        if not components:
            return PlacementResult(
                positions={},
                score=1.0,
                violations=[],
                valid=True,
            )

        # Sort by estimated size (larger first for better packing)
        sorted_comps = sorted(
            components,
            key=lambda c: self._estimate_size(c),
            reverse=True,
        )

        # Calculate grid dimensions
        n = len(sorted_comps)
        cols = math.ceil(math.sqrt(n * self._board_width / self._board_height))
        rows = math.ceil(n / cols)
        if cols < 1:
            cols = 1
        if rows < 1:
            rows = 1

        cell_w = self._board_width / cols
        cell_h = self._board_height / rows

        # Place each component at grid cell center
        positions: dict[str, tuple[float, float]] = {}
        for idx, comp in enumerate(sorted_comps):
            row = idx // cols
            col = idx % cols
            x = (col + 0.5) * cell_w
            y = (row + 0.5) * cell_h
            positions[comp.reference] = (x, y)

        # Build bounding boxes for clearance check
        boxes = self._build_boxes(components, positions)

        # Validate clearance
        margin = self._min_clearance
        board_bounds = (
            margin,
            margin,
            self._board_width - margin,
            self._board_height - margin,
        )
        validation = validate_placement_clearance(
            boxes,
            min_clearance_mm=self._min_clearance,
            board_bounds=board_bounds,
        )

        violations = [v["message"] for v in validation["violations"]]
        valid = validation["valid"]

        # Score placement
        score = self.score_placement(positions, [])

        return PlacementResult(
            positions=positions,
            score=score,
            violations=violations,
            valid=valid,
        )

    def place_decoupling_caps(
        self,
        components: list[ComponentSpec],
        ic_refs: list[str],
        cap_refs: list[str],
        max_distance_mm: float = 5.0,
    ) -> dict:
        """Place decoupling capacitors near their associated ICs.

        Identifies ICs and bypass capacitors, then places each cap within
        max_distance of the nearest IC's position. Assumes IC positions are
        already determined (from a previous place_components call).

        Args:
            components: All components (ICs and caps must be included).
            ic_refs: List of reference designators for IC components.
            cap_refs: List of reference designators for decoupling caps.
            max_distance_mm: Maximum distance from IC to cap in mm.

        Returns:
            Dict with:
            - "placed": list of dicts with "cap_ref", "ic_ref", "position".
            - "unplaced": list of cap refs that could not be placed.
        """
        placed: list[dict] = []
        unplaced: list[str] = []

        if not ic_refs or not cap_refs:
            return {"placed": placed, "unplaced": list(cap_refs)}

        # Get IC positions (from component specs with positions or center of board)
        comp_map = {c.reference: c for c in components}

        ic_positions: dict[str, tuple[float, float]] = {}
        for ref in ic_refs:
            comp = comp_map.get(ref)
            if comp and comp.position is not None:
                ic_positions[ref] = (comp.position.x, comp.position.y)
            else:
                # Default IC to board center
                ic_positions[ref] = (
                    self._board_width / 2,
                    self._board_height / 2,
                )

        assigned_caps: set[str] = set()

        for cap_ref in cap_refs:
            cap_comp = comp_map.get(cap_ref)
            if cap_comp is None:
                unplaced.append(cap_ref)
                continue

            # Find nearest IC
            best_ic = None
            best_dist = float("inf")
            for ic_ref, ic_pos in ic_positions.items():
                # If cap already has a position, use it
                if cap_comp.position is not None:
                    cap_pos = (cap_comp.position.x, cap_comp.position.y)
                else:
                    cap_pos = (0.0, 0.0)

                dist = math.hypot(ic_pos[0] - cap_pos[0], ic_pos[1] - cap_pos[1])
                if dist < best_dist:
                    best_dist = dist
                    best_ic = ic_ref

            if best_ic is None:
                unplaced.append(cap_ref)
                continue

            # Place cap near the IC (offset slightly to avoid overlap)
            ic_x, ic_y = ic_positions[best_ic]
            # Place cap at offset from IC
            angle = len(placed) * (math.pi / 4)  # Distribute around IC
            offset = min(max_distance_mm, self._min_clearance * 2)
            cap_x = ic_x + offset * math.cos(angle)
            cap_y = ic_y + offset * math.sin(angle)

            # Clamp to board bounds
            cap_x = max(self._min_clearance, min(self._board_width - self._min_clearance, cap_x))
            cap_y = max(self._min_clearance, min(self._board_height - self._min_clearance, cap_y))

            placed.append({
                "cap_ref": cap_ref,
                "ic_ref": best_ic,
                "position": (cap_x, cap_y),
            })
            assigned_caps.add(cap_ref)

        # Any caps not placed go to unplaced
        for cap_ref in cap_refs:
            if cap_ref not in assigned_caps:
                unplaced.append(cap_ref)

        return {"placed": placed, "unplaced": unplaced}

    def score_placement(
        self,
        positions: dict[str, tuple[float, float]],
        nets: list[NetSpec],
    ) -> float:
        """Score placement quality from 0.0 (worst) to 1.0 (best).

        Computes a weighted score based on:
        - Wire length: Manhattan distances between connected components.
        - Clearance: Fraction of component pairs with adequate clearance.
        - Edge penalty: Penalty for components too close to board edges.

        Args:
            positions: Mapping of reference designator to (x, y) positions.
            nets: List of NetSpec for wire length estimation.

        Returns:
            Score from 0.0 to 1.0.
        """
        if not positions:
            return 1.0

        refs = list(positions.keys())
        n = len(refs)

        # --- Wire length score ---
        wire_score = 1.0
        if nets and n > 1:
            total_wire = 0.0
            connections = 0
            for net in nets:
                # Extract unique references from pins
                net_refs: set[str] = set()
                for pin in net.pins:
                    parts = pin.split(".")
                    if parts:
                        net_refs.add(parts[0])

                # Sum pairwise Manhattan distances
                net_refs_with_pos = [r for r in net_refs if r in positions]
                for i in range(len(net_refs_with_pos)):
                    for j in range(i + 1, len(net_refs_with_pos)):
                        p1 = positions[net_refs_with_pos[i]]
                        p2 = positions[net_refs_with_pos[j]]
                        total_wire += abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
                        connections += 1

            if connections > 0:
                avg_wire = total_wire / connections
                # Normalize: board diagonal as reference
                diag = math.hypot(self._board_width, self._board_height)
                wire_score = max(0.0, min(1.0, 1.0 - (avg_wire / diag)))

        # --- Clearance score ---
        clearance_score = 1.0
        if n > 1:
            boxes = self._build_boxes_from_positions(positions)
            pairs_ok = 0
            total_pairs = 0
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    total_pairs += 1
                    dist = boxes[i].to_shapely().distance(boxes[j].to_shapely())
                    if dist >= self._min_clearance:
                        pairs_ok += 1

            if total_pairs > 0:
                clearance_score = pairs_ok / total_pairs

        # --- Edge score ---
        edge_margin = self._min_clearance * 2
        edge_penalty = 0.0
        for ref, (x, y) in positions.items():
            if (x < edge_margin or x > self._board_width - edge_margin
                    or y < edge_margin or y > self._board_height - edge_margin):
                edge_penalty += 0.1  # 10% penalty per edge violation

        edge_score = max(0.0, 1.0 - edge_penalty)

        # Weighted average
        score = 0.3 * wire_score + 0.4 * clearance_score + 0.3 * edge_score
        return round(max(0.0, min(1.0, score)), 4)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_size(comp: ComponentSpec) -> float:
        """Estimate component size for sorting (larger = placed first).

        Uses heuristic: ICs are large, resistors/caps are small.
        """
        ref = comp.reference.upper()
        if ref.startswith("U"):
            return 10.0
        if ref.startswith("Q") or ref.startswith("TR"):
            return 8.0
        if ref.startswith("L") or ref.startswith("D"):
            return 5.0
        if ref.startswith("R") or ref.startswith("C"):
            return 2.0
        return 3.0  # Default

    @staticmethod
    def _build_boxes(
        components: list[ComponentSpec],
        positions: dict[str, tuple[float, float]],
    ) -> list[SpatialBox]:
        """Build SpatialBox list from components and their positions.

        Uses a default 2mm x 2mm bounding box for each component.
        """
        boxes: list[SpatialBox] = []
        for comp in components:
            pos = positions.get(comp.reference)
            if pos is None:
                continue
            x, y = pos
            # Default bounding box: 2mm x 2mm centered on position
            half_w = 1.0
            half_h = 1.0
            boxes.append(
                SpatialBox(
                    x1=x - half_w,
                    y1=y - half_h,
                    x2=x + half_w,
                    y2=y + half_h,
                    entity_type="component",
                    entity_id=comp.library_id,
                    reference=comp.reference,
                )
            )
        return boxes

    def _build_boxes_from_positions(
        self,
        positions: dict[str, tuple[float, float]],
    ) -> list[SpatialBox]:
        """Build SpatialBox list from positions dict using default sizes."""
        boxes: list[SpatialBox] = []
        for ref, (x, y) in positions.items():
            half_w = 1.0
            half_h = 1.0
            boxes.append(
                SpatialBox(
                    x1=x - half_w,
                    y1=y - half_h,
                    x2=x + half_h,
                    y2=y + half_h,
                    entity_type="component",
                    entity_id=ref,
                    reference=ref,
                )
            )
        return boxes
