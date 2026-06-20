"""Hybrid placement engine combining ML prediction with rule-based fallback.

Provides the public API that consumers (Phase 15 AI Generation Wiring, CLI)
call: tries ML prediction first, falls back to rule-based placement if the
model is unavailable, validates the result with DRC checks, and scores it.
Interactive mode lets users fix some components and let AI place the rest.

Security (threat model):
  T-16-10: PlacementRequest validated by Pydantic, component count cap at 500.

Usage::

    from kicad_agent.placement.engine import (
        HybridPlacementEngine,
        PlacementRequest,
        PlacementOutput,
    )

    engine = HybridPlacementEngine()
    request = PlacementRequest(
        components=[...],
        nets=[...],
        board_width=100.0,
        board_height=80.0,
    )
    output = engine.place(request)
    print(f"Score: {output.score}, Source: {output.source}")
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from kicad_agent.generation.intent import ComponentSpec, NetSpec
from kicad_agent.generation.placement import PlacementEngine
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph
from kicad_agent.placement.interactive import ConstraintSet, interactive_placement
from kicad_agent.placement.scoring import PlacementScorer, compute_hpwl_score
from kicad_agent.placement.validation import PlacementValidator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_COMPONENTS = 500
"""Maximum component count per placement request (T-16-10)."""


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PlacementRequest(BaseModel):
    """Validated input for hybrid placement engine.

    Attributes:
        components: Components to place.
        nets: Net connections between components.
        board_width: Board width in mm (must be positive).
        board_height: Board height in mm (must be positive).
        fixed_positions: User-placed components (ref -> (x, y, rotation)).
        keepout_zones: Forbidden regions as (x1, y1, x2, y2) tuples.
        min_clearance: Minimum clearance between components in mm.
        use_ml: Try ML prediction first if True.
        refine_sa: Run SA refinement after ML prediction if True.
    """

    components: list[ComponentSpec] = Field(
        description="Components to place on the board",
    )
    nets: list[NetSpec] = Field(
        default_factory=list,
        description="Net connections between components",
    )
    board_width: float = Field(gt=0, description="Board width in mm")
    board_height: float = Field(gt=0, description="Board height in mm")
    fixed_positions: dict[str, tuple[float, float, float]] = Field(
        default_factory=dict,
        description="User-placed components: ref -> (x, y, rotation_degrees)",
    )
    keepout_zones: list[tuple[float, float, float, float]] = Field(
        default_factory=list,
        description="Forbidden regions: [(x1, y1, x2, y2), ...]",
    )
    min_clearance: float = Field(
        default=1.0,
        gt=0,
        description="Minimum clearance between components in mm",
    )
    use_ml: bool = Field(
        default=True,
        description="Try ML prediction first",
    )
    refine_sa: bool = Field(
        default=True,
        description="Run SA refinement after ML prediction",
    )


class PlacementOutput(BaseModel):
    """Result of a placement run.

    Attributes:
        positions: Mapping of ref to (x, y, rotation_degrees).
        score: Composite quality score in [0, 1].
        hpwl: Half-perimeter wirelength in mm.
        valid: True if passes DRC checks.
        violations: List of violation detail dicts.
        source: Placement source ("ml_prediction", "ml_refined",
            "rule_based", "interactive").
        component_scores: Per-component quality contribution.
    """

    positions: dict[str, tuple[float, float, float]]
    score: float
    hpwl: float
    valid: bool
    violations: list[dict[str, Any]]
    source: str
    component_scores: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Hybrid engine
# ---------------------------------------------------------------------------


class HybridPlacementEngine:
    """Hybrid placement engine: ML-first with rule-based fallback.

    Tries ML prediction, falls back to rule-based grid placement.
    Validates results with DRC checks and computes quality scores.
    Supports interactive mode for partial user placement.

    Args:
        model_path: Optional path to saved model weights.
        device: Torch device string (default "cpu").
    """

    def __init__(
        self,
        model_path: Path | None = None,
        device: str = "cpu",
    ) -> None:
        self._rule_engine: PlacementEngine | None = None
        self._predictor = None
        self._model_path = model_path
        self._device = device

        # Try to initialize predictor
        try:
            from kicad_agent.placement.predict import PlacementPredictor

            self._predictor = PlacementPredictor(
                model_path=model_path, device=device
            )
        except Exception:
            # predictor unavailable (e.g., torch not installed)
            self._predictor = None

    def place(self, request: PlacementRequest) -> PlacementOutput:
        """Execute placement using the best available strategy.

        Decision logic:
        1. If fixed_positions provided -> interactive mode
        2. Else if use_ml and predictor ready -> ML prediction
        3. Else -> rule-based grid fallback

        Args:
            request: Validated PlacementRequest.

        Returns:
            PlacementOutput with positions, score, and metadata.

        Raises:
            ValueError: If component count exceeds 500.
        """
        if len(request.components) > _MAX_COMPONENTS:
            raise ValueError(
                f"Component count {len(request.components)} exceeds maximum "
                f"{_MAX_COMPONENTS}"
            )

        # Build placement graph
        graph = self._build_graph(request)

        # Select placement strategy
        positions: dict[str, tuple[float, float, float]] = {}
        source: str = "rule_based"

        if request.fixed_positions:
            # Interactive mode: user fixed some components
            positions, source = self._place_interactive(request, graph)
        elif request.use_ml and self._predictor is not None and self._predictor.is_ready:
            if request.refine_sa:
                positions, source = self._place_ml_refined(request, graph)
            else:
                positions, source = self._place_ml(request, graph)
        else:
            positions, source = self._place_rule_based(request)

        # Validate positions
        component_sizes = self._extract_component_sizes(graph)
        validator = PlacementValidator(
            board_width=request.board_width,
            board_height=request.board_height,
            min_clearance=request.min_clearance,
        )
        is_valid, violations = validator.validate(positions, component_sizes)

        # Safety net: resolve any residual overlaps (skip fixed components)
        has_any, overlap_count = validator.has_overlaps(positions, component_sizes)
        if has_any:
            from kicad_agent.placement.packing import resolve_overlaps

            resolved = resolve_overlaps(
                positions,
                component_sizes,
                request.board_width,
                request.board_height,
                request.min_clearance,
            )
            # Restore fixed positions that resolve_overlaps may have shifted
            for ref, pos in request.fixed_positions.items():
                if ref in positions:
                    resolved[ref] = pos
            positions = resolved
            is_valid, violations = validator.validate(positions, component_sizes)

        # Score positions
        scorer = PlacementScorer(
            board_width=request.board_width,
            board_height=request.board_height,
            min_clearance=request.min_clearance,
        )
        score_result = scorer.score(positions, graph, component_sizes)

        # Compute per-component scores
        component_scores = self._compute_component_scores(
            positions, graph, component_sizes
        )

        # Build violation dicts
        violation_dicts = [
            {
                "type": v.violation_type,
                "message": v.message,
                "component_refs": list(v.component_refs),
                "distance_mm": v.distance_mm,
                "severity": v.severity,
            }
            for v in violations
        ]

        return PlacementOutput(
            positions=positions,
            score=score_result.total_score,
            hpwl=score_result.hpwl,
            valid=is_valid,
            violations=violation_dicts,
            source=source,
            component_scores=component_scores,
        )

    def place_components_simple(
        self,
        components: list[ComponentSpec],
        board_width: float,
        board_height: float,
    ) -> PlacementOutput:
        """Simplified API for basic usage (no nets, no fixed positions, no ML).

        Args:
            components: Components to place.
            board_width: Board width in mm.
            board_height: Board height in mm.

        Returns:
            PlacementOutput with positions and quality metrics.
        """
        request = PlacementRequest(
            components=components,
            board_width=board_width,
            board_height=board_height,
            use_ml=False,
        )
        return self.place(request)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_graph(self, request: PlacementRequest) -> PlacementGraph:
        """Build PlacementGraph from request components and nets."""
        graph = netlist_to_placement_graph(
            request.components,
            request.nets,
            request.board_width,
            request.board_height,
        )
        return PlacementGraph(graph)

    def _place_interactive(
        self,
        request: PlacementRequest,
        graph: PlacementGraph,
    ) -> tuple[dict[str, tuple[float, float, float]], str]:
        """Interactive mode: user fixed some components."""
        constraints = ConstraintSet(
            fixed_positions=request.fixed_positions,
            keepout_zones=request.keepout_zones,
            min_clearance=request.min_clearance,
        )
        positions = interactive_placement(
            graph, constraints, predictor=self._predictor
        )
        return positions, "interactive"

    def _place_ml(
        self,
        request: PlacementRequest,
        graph: PlacementGraph,
    ) -> tuple[dict[str, tuple[float, float, float]], str]:
        """ML prediction without SA refinement."""
        prediction = self._predictor.predict(graph)
        margin = request.min_clearance
        positions: dict[str, tuple[float, float, float]] = {}
        for ref, (x, y, rot) in prediction.positions.items():
            x = max(margin, min(request.board_width - margin, x))
            y = max(margin, min(request.board_height - margin, y))
            positions[ref] = (x, y, rot)
        return positions, "ml_prediction"

    def _place_ml_refined(
        self,
        request: PlacementRequest,
        graph: PlacementGraph,
    ) -> tuple[dict[str, tuple[float, float, float]], str]:
        """ML prediction with SA refinement of all positions."""
        # Use interactive_placement with no fixed positions to run SA on all
        constraints = ConstraintSet(
            keepout_zones=request.keepout_zones,
            min_clearance=request.min_clearance,
        )
        positions = interactive_placement(
            graph, constraints, predictor=self._predictor
        )
        return positions, "ml_refined"

    def _place_rule_based(
        self,
        request: PlacementRequest,
    ) -> tuple[dict[str, tuple[float, float, float]], str]:
        """Shelf packing initialization with overlap-free guarantee."""
        from kicad_agent.placement.packing import (
            pack_components_no_overlap,
            resolve_overlaps,
        )

        # Build component_sizes as (width, height) from components
        # ComponentSpec may not have width/height — use default 2.0mm footprint
        comp_sizes_wh: dict[str, tuple[float, float]] = {}
        for comp in request.components:
            w = getattr(comp, "width", 0.0)
            h = getattr(comp, "height", 0.0)
            w = w if w > 0 else 2.0
            h = h if h > 0 else 2.0
            comp_sizes_wh[comp.reference] = (w, h)

        result = pack_components_no_overlap(
            component_sizes=comp_sizes_wh,
            board_width=request.board_width,
            board_height=request.board_height,
            min_clearance=request.min_clearance,
            fixed_positions=request.fixed_positions,
            keepout_zones=request.keepout_zones,
        )

        # Convert (x, y) to (x, y, 0.0) format
        positions: dict[str, tuple[float, float, float]] = {
            ref: (x, y, rot) for ref, (x, y, rot) in result.positions.items()
        }

        return positions, "rule_based_packed"

    @staticmethod
    def _extract_component_sizes(graph: PlacementGraph) -> dict[str, float]:
        """Extract estimated component sizes from graph node data."""
        sizes: dict[str, float] = {}
        for node_id in graph.component_nodes():
            data = graph.graph.nodes[node_id]
            ref = data.get("reference", "")
            size = data.get("estimated_size", 2.0)
            sizes[ref] = size
        return sizes

    @staticmethod
    def _compute_component_scores(
        positions: dict[str, tuple[float, float, float]],
        graph: PlacementGraph,
        component_sizes: dict[str, float],
    ) -> dict[str, float]:
        """Compute per-component quality contribution.

        Based on average HPWL contribution per component across all nets.
        """
        if not positions:
            return {}

        # For each component, sum HPWL contributions from connected nets
        comp_hpwl: dict[str, float] = {ref: 0.0 for ref in positions}
        comp_net_count: dict[str, int] = {ref: 0 for ref in positions}

        for net_node in graph.net_nodes():
            comp_refs: list[str] = []
            for neighbor in graph.graph.neighbors(net_node):
                data = graph.graph.nodes[neighbor]
                if data.get("bipartite") == 0:
                    ref = data.get("reference", "")
                    if ref in positions:
                        comp_refs.append(ref)

            if len(comp_refs) < 2:
                continue

            xs = [positions[ref][0] for ref in comp_refs]
            ys = [positions[ref][1] for ref in comp_refs]
            hpwl_contribution = (max(xs) - min(xs)) + (max(ys) - min(ys))

            for ref in comp_refs:
                comp_hpwl[ref] += hpwl_contribution
                comp_net_count[ref] += 1

        # Normalize to [0, 1]: lower HPWL -> higher score
        board_diag = math.hypot(graph.board_width, graph.board_height)
        scores: dict[str, float] = {}
        for ref in positions:
            if comp_net_count[ref] > 0 and board_diag > 0:
                avg_hpwl = comp_hpwl[ref] / comp_net_count[ref]
                scores[ref] = max(0.0, min(1.0, 1.0 - avg_hpwl / board_diag))
            else:
                scores[ref] = 0.5  # Neutral score for unconnected components

        return scores
