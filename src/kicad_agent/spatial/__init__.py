"""Spatial primitives for PCB coordinate-grounded reasoning.

VP-02, VP-03: Spatial primitive types and extraction pipeline.

Provides:
    - SpatialPoint, SpatialBox, SpatialPath, SpatialRegion: frozen dataclasses
    - extract_points, extract_boxes, extract_paths, extract_regions, extract_all:
      extraction functions that produce spatial primitives from PcbIR
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
]
