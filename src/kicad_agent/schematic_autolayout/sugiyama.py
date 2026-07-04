"""Stub — full 5-stage implementation lands in Task 2.

Constants and the LayoutResult dataclass are defined here so __init__.py
exports work during Task 1's RED phase. SugiyamaLayout.layout() raises
NotImplementedError until Task 2 GREEN.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kicad_agent.schematic_autolayout.layout_graph import LayoutCoordinate

DEFAULT_LAYER_SPACING_MM: float = 25.4  # 10 grid units vertical between layers
DEFAULT_NODE_SPACING_MM: float = 12.7  # 5 grid units horizontal between nodes
KICAD_GRID_MM: float = 2.54


@dataclass(frozen=True)
class LayoutResult:
    """Frozen result of SugiyamaLayout.layout().

    Populated by Task 2. Defined here so __init__ exports resolve in Task 1.
    """

    positions: dict[str, LayoutCoordinate] = field(default_factory=dict)  # type: ignore[assignment]
    layers: dict[str, int] = field(default_factory=dict)  # type: ignore[assignment]
    crossing_count: int = 0
    feedback_edges_reversed: tuple[str, ...] = ()


# Imported at bottom to avoid circular import during Task 1 RED phase
# (Task 2 fills in SugiyamaLayout fully)
