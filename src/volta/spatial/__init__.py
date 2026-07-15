"""Spatial primitives for PCB coordinate-grounded reasoning.

VP-01, VP-02, VP-03: Spatial primitive types, extraction pipeline, and rendering.
VP-04: Procedural maze-routing PCB generator.
VP-05: Cold-start reasoning chain synthesis from DRC/ERC violations.
VP-06: Spatial query engine with Shapely STRtree.
VP-08: Rick agent integration for coordinate-grounded domain reports.
SI-01: PCB spatial model with per-layer geometry and STRtree indexing.
SI-02: Layer stackup metadata extraction.
SI-03: Layer classification utility.
SI-04: Per-net geometry parameters.
SI-06: Board outline extraction from Edge.Cuts layer.

Provides:
    - SpatialPoint, SpatialBox, SpatialPath, SpatialRegion: frozen dataclasses
    - extract_points, extract_boxes, extract_paths, extract_regions, extract_all:
      extraction functions that produce spatial primitives from PcbIR
    - render_pcb_layer, render_pcb_layer_grid:
      PCB layer rendering with coordinate grid overlay
    - generate_maze_board: Procedural maze-routing PCB puzzle generator
    - synthesize_chain, synthesize_chains: Reasoning chain synthesis from violations
    - SpatialQueryEngine: Shapely STRtree spatial query engine
    - RickDomain, RickFinding, SpatialRickReport: Rick integration types
    - generate_spatial_report, generate_all_reports: Rick report generation
    - PcbSpatialModel: PCB spatial model with per-layer Shapely geometry and STRtree
    - LayerClassifier: KiCad layer name classification utility
    - LayerStackup, LayerInfo: Layer stackup metadata dataclasses
    - NetClassGeometry, build_net_class_map: Per-net geometry parameters
    - extract_board_outline: Board outline extraction from Edge.Cuts layer
"""

from volta.spatial.extractor import (
    extract_all,
    extract_boxes,
    extract_paths,
    extract_points,
    extract_regions,
)
from volta.spatial.layer_classifier import LayerClassifier
from volta.spatial.layer_stackup import LayerInfo, LayerStackup
from volta.spatial.maze_generator import MazeBoard, generate_maze_board
from volta.spatial.net_class_geometry import (
    NetClassGeometry,
    build_net_class_map,
)
from volta.spatial.pcb_model import (
    PcbSpatialModel,
    _CLEARANCE_TOLERANCE_MM,
)
from volta.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
    SpatialRegion,
)
from volta.spatial.query import SpatialQueryEngine
from volta.spatial.reasoning_chains import (
    ReasoningChain,
    ReasoningStep,
    synthesize_chain,
    synthesize_chains,
)
from volta.spatial.renderer import (
    render_pcb_layer,
    render_pcb_layer_grid,
)
from volta.spatial.board_outline import extract_board_outline
from volta.spatial.rick_integration import (
    RickDomain,
    RickFinding,
    SpatialRickReport,
    generate_all_reports,
    generate_spatial_report,
)

__all__ = [
    # Primitives
    "SpatialPoint",
    "SpatialBox",
    "SpatialPath",
    "SpatialRegion",
    # Extraction
    "extract_points",
    "extract_boxes",
    "extract_paths",
    "extract_regions",
    "extract_all",
    # Rendering
    "render_pcb_layer",
    "render_pcb_layer_grid",
    # Maze generator
    "MazeBoard",
    "generate_maze_board",
    # Reasoning chains
    "ReasoningChain",
    "ReasoningStep",
    "synthesize_chain",
    "synthesize_chains",
    # Query engine
    "SpatialQueryEngine",
    # Rick integration
    "RickDomain",
    "RickFinding",
    "SpatialRickReport",
    "generate_spatial_report",
    "generate_all_reports",
    # PCB Spatial Intelligence (SI)
    "PcbSpatialModel",
    "LayerClassifier",
    "LayerStackup",
    "LayerInfo",
    "NetClassGeometry",
    "build_net_class_map",
    "extract_board_outline",
]
