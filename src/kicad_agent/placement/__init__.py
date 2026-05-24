"""Placement module: graph construction, ML prediction, validation, and hybrid engine.

Provides the complete placement pipeline from netlist-to-graph conversion,
through ML-based prediction and interactive constraint propagation, to
DRC-aware validation and quality scoring.

Usage::

    from kicad_agent.placement import (
        HybridPlacementEngine,
        PlacementGraph,
        PlacementPredictor,
        interactive_placement,
    )
"""

from kicad_agent.placement.engine import (
    HybridPlacementEngine,
    PlacementOutput,
    PlacementRequest,
)
from kicad_agent.placement.features import (
    COMP_FEATURE_DIM,
    NET_FEATURE_DIM,
    extract_component_features,
    extract_net_features,
)
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph
from kicad_agent.placement.interactive import (
    ConstraintSet,
    interactive_placement,
    suggest_placements,
)
from kicad_agent.placement.model import BipartiteAttentionLayer, PlacementModel
from kicad_agent.placement.predict import PlacementPrediction, PlacementPredictor
from kicad_agent.placement.scoring import (
    PlacementScore,
    PlacementScorer,
    compute_congestion_estimate,
    compute_hpwl_score,
)
from kicad_agent.placement.validation import (
    PlacementValidator,
    PlacementViolation,
    positions_to_boxes,
    validate_placement,
)

__all__ = [
    # Engine (hybrid)
    "HybridPlacementEngine",
    "PlacementRequest",
    "PlacementOutput",
    # Graph
    "PlacementGraph",
    "netlist_to_placement_graph",
    # Features
    "extract_component_features",
    "extract_net_features",
    "COMP_FEATURE_DIM",
    "NET_FEATURE_DIM",
    # Model
    "PlacementModel",
    "BipartiteAttentionLayer",
    # Prediction
    "PlacementPredictor",
    "PlacementPrediction",
    # Validation
    "PlacementValidator",
    "PlacementViolation",
    "validate_placement",
    "positions_to_boxes",
    # Scoring
    "PlacementScorer",
    "PlacementScore",
    "compute_hpwl_score",
    "compute_congestion_estimate",
    # Interactive
    "interactive_placement",
    "suggest_placements",
    "ConstraintSet",
]
