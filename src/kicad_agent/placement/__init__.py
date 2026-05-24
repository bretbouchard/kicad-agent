"""Placement module: bipartite graph construction and feature extraction.

Provides the netlist-to-placement-graph converter that transforms
schematic netlists into bipartite component-net graphs suitable for
GNN-based placement prediction.

Usage::

    from kicad_agent.placement import PlacementGraph, netlist_to_placement_graph
"""

from kicad_agent.placement.features import (
    COMP_FEATURE_DIM,
    NET_FEATURE_DIM,
    extract_component_features,
    extract_net_features,
)
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph

__all__ = [
    "PlacementGraph",
    "netlist_to_placement_graph",
    "extract_component_features",
    "extract_net_features",
    "COMP_FEATURE_DIM",
    "NET_FEATURE_DIM",
]
