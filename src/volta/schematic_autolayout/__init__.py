"""Deterministic autolayout engine for KiCad schematics.

Pure-Python Sugiyama framework (D-01: no Graphviz). Five separately-testable
stages producing grid-snapped coordinates for every component on a
per-subcircuit basis.

Public API:
    SugiyamaLayout       — 5-stage layout algorithm + fit_to_page
    LayoutResult         — frozen result container
    LayoutGraph          — frozen graph + CircuitTopology adapter
    LayoutNode           — frozen node (component)
    LayoutEdge           — frozen edge (signal connection)
    LayoutCoordinate     — frozen (x, y) NamedTuple
    paper_sizes          — KiCad page dimensions + raw-content parser
"""

from volta.schematic_autolayout.layout_graph import (
    KICAD_GRID_MM,
    RC_PIN_OFFSET_MM,
    LayoutCoordinate,
    LayoutEdge,
    LayoutGraph,
    LayoutNode,
)
from volta.schematic_autolayout.sugiyama import (
    DEFAULT_LAYER_SPACING_MM,
    DEFAULT_NODE_SPACING_MM,
    LayoutResult,
    SugiyamaLayout,
)
from volta.schematic_autolayout import paper_sizes

__all__ = [
    "SugiyamaLayout",
    "LayoutResult",
    "LayoutGraph",
    "LayoutNode",
    "LayoutEdge",
    "LayoutCoordinate",
    "KICAD_GRID_MM",
    "RC_PIN_OFFSET_MM",
    "DEFAULT_LAYER_SPACING_MM",
    "DEFAULT_NODE_SPACING_MM",
    "paper_sizes",
]
