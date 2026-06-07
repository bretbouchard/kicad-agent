"""Manufacturer profile for DFM constraints.

DFM-02: Manufacturer-specific manufacturing constraints loaded from
YAML/JSON config. Ships with 4 built-in profiles.

Security:
  T-54-02: yaml.safe_load prevents arbitrary code execution
  (same pattern as analysis/rule_config.py T-48-10).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ManufacturerProfile(BaseModel):
    """Manufacturer-specific PCB manufacturing constraints.

    Used by DFM checks to validate board design against
    manufacturer capabilities.

    Attributes:
        name: Profile display name (e.g. "JLCPCB Standard 2-Layer").
        min_trace_width_mm: Minimum trace width in mm.
        min_drill_mm: Minimum drill diameter in mm.
        min_annular_ring_mm: Minimum annular ring around drill in mm.
        min_solder_mask_sliver_mm: Minimum solder mask web/sliver in mm.
        min_clearance_mm: Minimum clearance between features in mm.
        min_via_diameter_mm: Minimum via pad diameter in mm.
        max_board_dim_mm: Maximum board dimension in mm.
        supports_blind_vias: Whether blind/buried vias are supported.
        supports_castellated: Whether castellated holes are supported.
        extra: Manufacturer-specific extra constraints.
    """

    name: str = Field(min_length=1, max_length=256)
    min_trace_width_mm: float = Field(gt=0, description="Minimum trace width (mm)")
    min_drill_mm: float = Field(gt=0, description="Minimum drill diameter (mm)")
    min_annular_ring_mm: float = Field(ge=0, default=0.1, description="Minimum annular ring (mm)")
    min_solder_mask_sliver_mm: float = Field(ge=0, default=0.1, description="Minimum solder mask sliver (mm)")
    min_clearance_mm: float = Field(ge=0, default=0.127, description="Minimum clearance (mm)")
    min_via_diameter_mm: float = Field(gt=0, default=0.4, description="Minimum via diameter (mm)")
    max_board_dim_mm: float = Field(gt=0, default=500.0, description="Maximum board dimension (mm)")
    supports_blind_vias: bool = Field(default=False)
    supports_castellated: bool = Field(default=False)
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path_or_string: str) -> ManufacturerProfile:
        """Load profile from a YAML file path or string.

        T-54-02: Uses yaml.safe_load to prevent arbitrary code execution.

        Args:
            path_or_string: File path (if exists on disk) or YAML string.

        Returns:
            ManufacturerProfile parsed from YAML data.
        """
        path = Path(path_or_string)
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            data = yaml.safe_load(path_or_string)
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, path_or_string: str) -> ManufacturerProfile:
        """Load profile from a JSON file path or string.

        Args:
            path_or_string: File path (if exists on disk) or JSON string.

        Returns:
            ManufacturerProfile parsed from JSON data.
        """
        path = Path(path_or_string)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(path_or_string)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManufacturerProfile:
        """Construct profile from a dictionary directly.

        Args:
            data: Dictionary with profile fields.

        Returns:
            ManufacturerProfile validated from dict.
        """
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Built-in manufacturer profiles
# ---------------------------------------------------------------------------

_JLCPCB_STANDARD = ManufacturerProfile(
    name="JLCPCB Standard 2-Layer",
    min_trace_width_mm=0.127,
    min_drill_mm=0.2,
    min_annular_ring_mm=0.1,
    min_solder_mask_sliver_mm=0.1,
    min_clearance_mm=0.127,
    min_via_diameter_mm=0.4,
    max_board_dim_mm=500.0,
    supports_blind_vias=False,
    supports_castellated=True,
)

_JLCPCB_4LAYER = ManufacturerProfile(
    name="JLCPCB Standard 4-Layer",
    min_trace_width_mm=0.1,
    min_drill_mm=0.2,
    min_annular_ring_mm=0.1,
    min_solder_mask_sliver_mm=0.1,
    min_clearance_mm=0.1,
    min_via_diameter_mm=0.4,
    max_board_dim_mm=300.0,
    supports_blind_vias=False,
    supports_castellated=True,
    extra={
        "layer_count": 4,
        "impedance_control": "optional_add_on",
        "default_solder_mask": "green",
        "default_silkscreen": "white",
        "copper_weight": "1oz",
    },
)

_PCBWAY_STANDARD = ManufacturerProfile(
    name="PCBWay Standard 2-Layer",
    min_trace_width_mm=0.1,
    min_drill_mm=0.2,
    min_annular_ring_mm=0.1,
    min_solder_mask_sliver_mm=0.1,
    min_clearance_mm=0.1,
    min_via_diameter_mm=0.4,
    max_board_dim_mm=500.0,
    supports_blind_vias=True,
    supports_castellated=True,
)

_OSH_PARK = ManufacturerProfile(
    name="OSH Park 2-Layer",
    min_trace_width_mm=0.1524,     # 6 mil
    min_drill_mm=0.3556,           # 14 mil
    min_annular_ring_mm=0.1524,    # 6 mil
    min_solder_mask_sliver_mm=0.1016,  # 4 mil
    min_clearance_mm=0.1524,       # 6 mil
    min_via_diameter_mm=0.6604,    # 26 mil
    max_board_dim_mm=400.0,
    supports_blind_vias=False,
    supports_castellated=False,
)

_GENERIC_CONSERVATIVE = ManufacturerProfile(
    name="Generic Conservative 2-Layer",
    min_trace_width_mm=0.2,
    min_drill_mm=0.4,
    min_annular_ring_mm=0.15,
    min_solder_mask_sliver_mm=0.15,
    min_clearance_mm=0.2,
    min_via_diameter_mm=0.6,
    max_board_dim_mm=300.0,
    supports_blind_vias=False,
    supports_castellated=False,
)

_PROFILES: dict[str, ManufacturerProfile] = {
    "jlcpcb": _JLCPCB_STANDARD,
    "jlcpcb-4layer": _JLCPCB_4LAYER,
    "pcbway": _PCBWAY_STANDARD,
    "osh_park": _OSH_PARK,
    "generic": _GENERIC_CONSERVATIVE,
}


def get_builtin_profiles() -> dict[str, ManufacturerProfile]:
    """Return all built-in manufacturer profiles.

    Returns:
        Dict mapping profile key to ManufacturerProfile instance.
        Keys: jlcpcb, pcbway, osh_park, generic.
    """
    return dict(_PROFILES)


def load_profile(name_or_path: str) -> ManufacturerProfile:
    """Load a manufacturer profile by name or file path.

    Resolution order:
    1. If name matches a built-in profile key, return it.
    2. If it's a file path that exists on disk, load YAML or JSON.
    3. Otherwise raise ValueError.

    Args:
        name_or_path: Profile key ("jlcpcb", "pcbway", etc.) or file path.

    Returns:
        ManufacturerProfile instance.

    Raises:
        ValueError: If name_or_path does not match any profile or file.
    """
    if name_or_path in _PROFILES:
        return _PROFILES[name_or_path]

    path = Path(name_or_path)
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return ManufacturerProfile.from_yaml(name_or_path)
        elif suffix == ".json":
            return ManufacturerProfile.from_json(name_or_path)
        else:
            # Try YAML first, then JSON
            try:
                return ManufacturerProfile.from_yaml(name_or_path)
            except Exception:
                return ManufacturerProfile.from_json(name_or_path)

    available = ", ".join(sorted(_PROFILES.keys()))
    raise ValueError(
        f"Unknown profile '{name_or_path}'. "
        f"Available built-in profiles: {available}. "
        f"Or provide a path to a YAML/JSON profile file."
    )
