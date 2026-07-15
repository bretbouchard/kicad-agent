"""BoardSpec — manufacturing specification model with sidecar JSON persistence.

Phase 205: META-04, META-05. Persists surface finish, copper weight, soldermask/
silkscreen color, and controlled impedance requirements as a sidecar JSON file
(.kicad_build_spec.json) alongside the .kicad_pcb file.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from volta.io.atomic_write import atomic_write


class SurfaceFinish(str, Enum):
    """PCB surface finish options."""
    HASL = "HASL"
    ENIG = "ENIG"
    HASL_LEAD_FREE = "HASL_LEAD_FREE"
    HARD_GOLD = "HARD_GOLD"
    OSP = "OSP"
    ENEPIG = "ENEPIG"


class SoldermaskColor(str, Enum):
    """Soldermask color options (matches KiCad color names)."""
    GREEN = "GREEN"
    RED = "RED"
    BLUE = "BLUE"
    BLACK = "BLACK"
    WHITE = "WHITE"
    YELLOW = "YELLOW"
    PURPLE = "PURPLE"
    MATTE_BLACK = "MATTE_BLACK"


class SilkscreenColor(str, Enum):
    """Silkscreen color options."""
    WHITE = "WHITE"
    BLACK = "BLACK"


class ImpedanceRequirement(BaseModel):
    """Controlled impedance requirement for a specific net (META-05)."""
    net_name: str = Field(min_length=1, max_length=128, description="Net with impedance requirement")
    target_ohms: float = Field(gt=0, description="Target impedance in ohms (50, 75, 90, 100, 120 common)")
    reference_layer: str = Field(min_length=1, max_length=64, description="Reference layer name (e.g., 'GND', 'L02')")


class BoardSpec(BaseModel):
    """Manufacturing specification for a PCB board (META-04, META-05).

    Persisted as a sidecar JSON file (.kicad_build_spec.json) alongside the
    .kicad_pcb file. NOT a KiCad file — this is volta's own extension.
    """
    schema_version: int = 1
    surface_finish: SurfaceFinish = SurfaceFinish.HASL
    copper_weight_outer_oz: float = Field(default=1.0, gt=0, description="Outer layer copper weight in oz")
    copper_weight_inner_oz: float = Field(default=0.5, gt=0, description="Inner layer copper weight in oz")
    soldermask_color: SoldermaskColor = SoldermaskColor.GREEN
    silkscreen_color: SilkscreenColor = SilkscreenColor.WHITE
    impedance_requirements: tuple[ImpedanceRequirement, ...] = ()


def load_board_spec(pcb_path: Path) -> BoardSpec | None:
    """Load BoardSpec from sidecar JSON. Returns None if sidecar absent."""
    sidecar = pcb_path.with_suffix(".kicad_build_spec.json")
    if not sidecar.is_file():
        return None
    return BoardSpec.model_validate_json(sidecar.read_text(encoding="utf-8"))


def save_board_spec(pcb_path: Path, spec: BoardSpec) -> Path:
    """Save BoardSpec to sidecar JSON atomically. Returns sidecar path.

    For board.kicad_pcb -> board.kicad_build_spec.json.
    Uses atomic_write (tempfile + os.replace) for crash-safe writes.
    """
    sidecar = pcb_path.with_suffix(".kicad_build_spec.json")
    atomic_write(sidecar, spec.model_dump_json(indent=2))
    return sidecar
