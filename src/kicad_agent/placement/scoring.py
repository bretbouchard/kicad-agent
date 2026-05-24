"""Placement quality scoring with HPWL, congestion, and routability metrics.

Provides composite quality metrics for component placement evaluation.
HPWL (Half-Perimeter Wirelength) measures total wiring demand from net
topology bounding boxes. Grid-based congestion estimation provides routing
density metric. Combined score supports both ML training rewards and
user-facing quality feedback.

Security (threat model):
  T-16-07: Congestion grid computation bounded by grid_resolution cap (10x10).
  T-16-06: Clearance scoring bounded by 500 component cap.

Usage::

    from kicad_agent.placement.scoring import (
        PlacementScorer,
        PlacementScore,
        compute_hpwl_score,
        compute_congestion_estimate,
    )

    scorer = PlacementScorer(board_width=100, board_height=80)
    score = scorer.score(positions, graph, component_sizes)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kicad_agent.placement.graph import PlacementGraph
from kicad_agent.placement.validation import PlacementValidator, positions_to_boxes

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlacementScore:
    """Composite quality score for a placement configuration.

    All sub-scores are in [0, 1] where higher is better unless noted.

    Attributes:
        total_score: Weighted combination of all sub-scores [0, 1].
        hpwl: Half-perimeter wirelength in mm (raw, lower is better).
        hpwl_normalized: HPWL normalized to [0, 1] (higher is better).
        congestion_estimate: Routing congestion [0, 1] (lower is better).
        clearance_score: Fraction of pairs with adequate clearance [0, 1].
        edge_score: Penalty for components near board edges [0, 1].
        board_utilization: Total component area / board area.
    """

    total_score: float
    hpwl: float
    hpwl_normalized: float
    congestion_estimate: float
    clearance_score: float
    edge_score: float
    board_utilization: float


# ---------------------------------------------------------------------------
# HPWL computation
# ---------------------------------------------------------------------------


def compute_hpwl_score(
    positions: dict[str, tuple[float, float, float]],
    graph: PlacementGraph,
) -> tuple[float, float]:
    """Compute HPWL and normalized HPWL from placement positions and net topology.

    For each net, computes the bounding box of connected component positions.
    HPWL contribution per net = (max_x - min_x) + (max_y - min_y).

    Args:
        positions: Mapping of ref to (x, y, rotation_degrees).
        graph: PlacementGraph with net topology.

    Returns:
        Tuple of (raw HPWL in mm, normalized HPWL in [0, 1]).
        Normalized: 1.0 - (hpwl / (board_diagonal * n_components)), clamped to [0, 1].
    """
    net_nodes = graph.net_nodes()
    if not net_nodes:
        return 0.0, 1.0

    total_hpwl = 0.0

    for net_node in net_nodes:
        # Find component neighbors of this net node
        comp_refs: list[str] = []
        for neighbor in graph._graph.neighbors(net_node):
            data = graph._graph.nodes[neighbor]
            if data.get("bipartite") == 0:
                ref = data.get("reference", "")
                if ref in positions:
                    comp_refs.append(ref)

        if len(comp_refs) < 2:
            continue

        # Compute bounding box of component positions
        xs = [positions[ref][0] for ref in comp_refs]
        ys = [positions[ref][1] for ref in comp_refs]

        hpwl_contribution = (max(xs) - min(xs)) + (max(ys) - min(ys))
        total_hpwl += hpwl_contribution

    # Normalize
    n_components = max(len(positions), 1)
    board_diagonal = math.hypot(graph.board_width, graph.board_height)
    if board_diagonal <= 0:
        return total_hpwl, 1.0

    hpwl_normalized = 1.0 - (total_hpwl / (board_diagonal * n_components))
    hpwl_normalized = max(0.0, hpwl_normalized)

    return total_hpwl, hpwl_normalized


# ---------------------------------------------------------------------------
# Congestion estimation
# ---------------------------------------------------------------------------


def compute_congestion_estimate(
    positions: dict[str, tuple[float, float, float]],
    graph: PlacementGraph,
    grid_resolution: int = 10,
) -> float:
    """Estimate routing congestion using a grid-based approach.

    Overlays a grid_resolution x grid_resolution grid on the board.
    For each net, draws a bounding box between connected components and
    increments a congestion counter for each grid cell intersected.

    Congestion = max_cell_congestion / mean_cell_congestion (or 0 if no nets).
    Lower is better (more uniform routing density). Capped at 1.0.

    Args:
        positions: Mapping of ref to (x, y, rotation_degrees).
        graph: PlacementGraph with net topology.
        grid_resolution: Grid cells per axis (default 10).

    Returns:
        Congestion estimate in [0, 1]. Lower is better.
    """
    net_nodes = graph.net_nodes()
    if not net_nodes:
        return 0.0

    board_w = graph.board_width
    board_h = graph.board_height
    if board_w <= 0 or board_h <= 0:
        return 0.0

    # Initialize congestion grid
    grid = [[0] * grid_resolution for _ in range(grid_resolution)]

    cell_w = board_w / grid_resolution
    cell_h = board_h / grid_resolution

    for net_node in net_nodes:
        # Find component neighbors
        comp_refs: list[str] = []
        for neighbor in graph._graph.neighbors(net_node):
            data = graph._graph.nodes[neighbor]
            if data.get("bipartite") == 0:
                ref = data.get("reference", "")
                if ref in positions:
                    comp_refs.append(ref)

        if len(comp_refs) < 2:
            continue

        # Compute bounding box
        xs = [positions[ref][0] for ref in comp_refs]
        ys = [positions[ref][1] for ref in comp_refs]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        # Determine grid cell range intersected by this bounding box
        col_start = max(0, int(min_x / cell_w))
        col_end = min(grid_resolution - 1, int(max_x / cell_w))
        row_start = max(0, int(min_y / cell_h))
        row_end = min(grid_resolution - 1, int(max_y / cell_h))

        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                grid[row][col] += 1

    # Compute congestion metric
    all_cells = [grid[r][c] for r in range(grid_resolution) for c in range(grid_resolution)]
    active_cells = [v for v in all_cells if v > 0]

    if not active_cells:
        return 0.0

    max_congestion = max(all_cells)
    mean_congestion = sum(active_cells) / len(active_cells)

    if mean_congestion <= 0:
        return 0.0

    congestion = max_congestion / mean_congestion
    # Lower is better: invert so that uniform distribution -> low value
    # Scale: uniform=1.0, concentrated=higher. Cap at some reasonable value
    # and normalize to [0, 1]
    # We want: more uniform -> lower congestion_estimate
    # ratio >= 1.0 always (max >= mean)
    # congestion_estimate = min(1.0, (ratio - 1.0) / ratio)
    if congestion <= 1.0:
        return 0.0

    estimate = min(1.0, (congestion - 1.0) / congestion)
    return estimate


# ---------------------------------------------------------------------------
# Placement scorer
# ---------------------------------------------------------------------------


class PlacementScorer:
    """Composite quality scorer for component placements.

    Computes a weighted combination of:
    - HPWL (wirelength): 30% weight
    - Congestion: 20% weight
    - Clearance: 30% weight
    - Edge proximity: 20% weight

    Args:
        board_width: Board width in mm (must be positive).
        board_height: Board height in mm (must be positive).
        min_clearance: Minimum clearance between components in mm.

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

    def score(
        self,
        positions: dict[str, tuple[float, float, float]],
        graph: PlacementGraph,
        component_sizes: dict[str, float] | None = None,
    ) -> PlacementScore:
        """Compute composite placement quality score.

        Args:
            positions: Mapping of ref to (x, y, rotation_degrees).
            graph: PlacementGraph with net topology.
            component_sizes: Optional mapping of ref to estimated size in mm.
                If None, defaults all sizes to 2.0 mm.

        Returns:
            PlacementScore with all sub-metrics and weighted total.
        """
        if component_sizes is None:
            component_sizes = {ref: 2.0 for ref in positions}

        # 1. HPWL
        hpwl, hpwl_normalized = compute_hpwl_score(positions, graph)

        # 2. Congestion
        congestion = compute_congestion_estimate(positions, graph)

        # 3. Clearance score
        clearance_score = self._compute_clearance_score(positions, component_sizes)

        # 4. Edge score
        edge_score = self._compute_edge_score(positions)

        # 5. Board utilization
        board_area = self._board_width * self._board_height
        boxes = positions_to_boxes(positions, component_sizes)
        component_area = sum((b.x2 - b.x1) * (b.y2 - b.y1) for b in boxes)
        board_utilization = component_area / board_area if board_area > 0 else 0.0

        # 6. Weighted total
        total_score = (
            0.3 * hpwl_normalized
            + 0.2 * (1.0 - congestion)
            + 0.3 * clearance_score
            + 0.2 * edge_score
        )
        total_score = max(0.0, min(1.0, total_score))

        return PlacementScore(
            total_score=round(total_score, 6),
            hpwl=round(hpwl, 6),
            hpwl_normalized=round(hpwl_normalized, 6),
            congestion_estimate=round(congestion, 6),
            clearance_score=round(clearance_score, 6),
            edge_score=round(edge_score, 6),
            board_utilization=round(board_utilization, 6),
        )

    def _compute_clearance_score(
        self,
        positions: dict[str, tuple[float, float, float]],
        component_sizes: dict[str, float],
    ) -> float:
        """Compute fraction of component pairs with adequate clearance.

        Uses PlacementValidator for pairwise clearance checking.

        Returns:
            Score in [0, 1] where 1.0 means all pairs have adequate clearance.
        """
        if len(positions) < 2:
            return 1.0

        validator = PlacementValidator(
            board_width=self._board_width,
            board_height=self._board_height,
            min_clearance=self._min_clearance,
        )
        _, violations = validator.validate(positions, component_sizes)

        # Count total pairs
        n = len(positions)
        total_pairs = n * (n - 1) / 2

        # Count clearance and overlap violations
        clearance_violations = [
            v for v in violations if v.violation_type in ("clearance", "overlap")
        ]

        if total_pairs == 0:
            return 1.0

        pairs_ok = total_pairs - len(clearance_violations)
        return max(0.0, pairs_ok / total_pairs)

    def _compute_edge_score(
        self,
        positions: dict[str, tuple[float, float, float]],
    ) -> float:
        """Compute penalty for components near board edges.

        Components within 2*min_clearance of any edge receive a 0.1 penalty
        per violation.

        Returns:
            Score in [0, 1] where 1.0 means no edge violations.
        """
        if not positions:
            return 1.0

        edge_margin = self._min_clearance * 2.0
        edge_penalty = 0.0

        for ref, (x, y, _) in positions.items():
            if (
                x < edge_margin
                or x > self._board_width - edge_margin
                or y < edge_margin
                or y > self._board_height - edge_margin
            ):
                edge_penalty += 0.1

        return max(0.0, 1.0 - edge_penalty)
