"""Manufacturing layer — board specs, build records, handoff packages.

Phase 205: BoardSpec model + sidecar JSON persistence.
"""
from volta.manufacturing.build import Build, BuildDiff, BuildStatus, diff_builds
from volta.manufacturing.board_spec import (
    BoardSpec,
    ImpedanceRequirement,
    SurfaceFinish,
    SoldermaskColor,
    SilkscreenColor,
    load_board_spec,
    save_board_spec,
)
from volta.manufacturing.handoff import HandoffResult, HandoffValidation, export_handoff

__all__ = [
    "Build",
    "BuildDiff",
    "BuildStatus",
    "BoardSpec",
    "HandoffResult",
    "HandoffValidation",
    "ImpedanceRequirement",
    "SurfaceFinish",
    "SoldermaskColor",
    "SilkscreenColor",
    "diff_builds",
    "export_handoff",
    "load_board_spec",
    "save_board_spec",
]
