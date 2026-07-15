"""Manufacturing layer — board specs, build records, handoff packages.

Phase 205: BoardSpec model + sidecar JSON persistence.
"""
from volta.manufacturing.board_spec import (
    BoardSpec,
    ImpedanceRequirement,
    SurfaceFinish,
    SoldermaskColor,
    SilkscreenColor,
    load_board_spec,
    save_board_spec,
)

__all__ = [
    "BoardSpec",
    "ImpedanceRequirement",
    "SurfaceFinish",
    "SoldermaskColor",
    "SilkscreenColor",
    "load_board_spec",
    "save_board_spec",
]
