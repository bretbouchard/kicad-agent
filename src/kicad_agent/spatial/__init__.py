"""Spatial primitives for PCB coordinate-grounded reasoning.

VP-01, VP-02, VP-03: Spatial primitive types, extraction pipeline, and rendering.

Provides:
    - SpatialPoint, SpatialBox, SpatialPath, SpatialRegion: frozen dataclasses
    - extract_points, extract_boxes, extract_paths, extract_regions, extract_all:
      extraction functions that produce spatial primitives from PcbIR
    - render_pcb_layer, render_pcb_layer_grid:
      PCB layer rendering with coordinate grid overlay
"""

from kicad_agent.spatial.extractor import (
    extract_all,
    extract_boxes,
    extract_paths,
    extract_points,
    extract_regions,
)
from kicad_agent.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
    SpatialRegion,
)
from kicad_agent.spatial.renderer import (
    render_pcb_layer,
    render_pcb_layer_grid,
)

__all__ = [
    "SpatialPoint",
    "SpatialBox",
    "SpatialPath",
    "SpatialRegion",
    "extract_points",
    "extract_boxes",
    "extract_paths",
    "extract_regions",
    "extract_all",
    "render_pcb_layer",
    "render_pcb_layer_grid",
]
