"""Vendor DRC profile registry — bundled .kicad_dru files + capabilities metadata.

Phase 206: Ships verified .kicad_dru files for PCBWay, JLCPCB, AISLER (2/4/6/8L),
OSH Park, Advanced Circuits, and a generic conservative profile. The files are
the source of truth for vendor numeric limits and loadable in the KiCad GUI.
The automated drc_vendor op uses an internal evaluator (manufacturing/vendor_drc.py)
that checks board geometry against these limits, because kicad-cli does not load
.kicad_dru sidecars (RESEARCH RQ1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PROFILES_DIR = Path(__file__).parent
_VENDOR_NAME_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class VendorDrcProfileInfo:
    """Capabilities metadata for one bundled vendor DRC profile (DRC-08)."""

    vendor: str
    display_name: str
    drc_rules_path: str
    min_trace_width_mm: float
    min_clearance_mm: float
    min_drill_mm: float
    min_annular_ring_mm: float
    min_via_diameter_mm: float
    supports_blind_vias: bool
    supports_castellated: bool
    source: str
    last_verified: str


# Co-located metadata registry — mirrors _PROFILES dict pattern in dfm/profiles.py.
# Numeric values match the .kicad_dru files (single source of truth, RESEARCH RQ3).
_PROFILE_INFOS: dict[str, VendorDrcProfileInfo] = {
    "pcbway": VendorDrcProfileInfo(
        vendor="pcbway",
        display_name="PCBWay",
        drc_rules_path="pcbway.kicad_dru",
        min_trace_width_mm=0.127,
        min_clearance_mm=0.127,
        min_drill_mm=0.2,
        min_annular_ring_mm=0.15,
        min_via_diameter_mm=0.4,
        supports_blind_vias=True,
        supports_castellated=True,
        source="Cimos/KiCad-CustomDesignRules (MIT)",
        last_verified="2026-07-10",
    ),
    "jlcpcb": VendorDrcProfileInfo(
        vendor="jlcpcb",
        display_name="JLCPCB",
        drc_rules_path="jlcpcb.kicad_dru",
        min_trace_width_mm=0.127,
        min_clearance_mm=0.127,
        min_drill_mm=0.2,
        min_annular_ring_mm=0.15,
        min_via_diameter_mm=0.4,
        supports_blind_vias=True,
        supports_castellated=True,
        source="Cimos/KiCad-CustomDesignRules (MIT)",
        last_verified="2026-07-10",
    ),
    "aisler_2layer": VendorDrcProfileInfo(
        vendor="aisler_2layer",
        display_name="AISLER 2-Layer",
        drc_rules_path="aisler_2layer.kicad_dru",
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
        min_drill_mm=0.2,
        min_annular_ring_mm=0.2,
        min_via_diameter_mm=0.45,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Authored from published numeric specifications",
        last_verified="2026-07-10",
    ),
    "aisler_4layer": VendorDrcProfileInfo(
        vendor="aisler_4layer",
        display_name="AISLER 4-Layer",
        drc_rules_path="aisler_4layer.kicad_dru",
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
        min_drill_mm=0.2,
        min_annular_ring_mm=0.2,
        min_via_diameter_mm=0.45,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Authored from published numeric specifications",
        last_verified="2026-07-10",
    ),
    "aisler_6layer": VendorDrcProfileInfo(
        vendor="aisler_6layer",
        display_name="AISLER 6-Layer",
        drc_rules_path="aisler_6layer.kicad_dru",
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
        min_drill_mm=0.2,
        min_annular_ring_mm=0.2,
        min_via_diameter_mm=0.45,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Authored from published numeric specifications",
        last_verified="2026-07-10",
    ),
    "aisler_8layer": VendorDrcProfileInfo(
        vendor="aisler_8layer",
        display_name="AISLER 8-Layer",
        drc_rules_path="aisler_8layer.kicad_dru",
        min_trace_width_mm=0.15,
        min_clearance_mm=0.15,
        min_drill_mm=0.2,
        min_annular_ring_mm=0.2,
        min_via_diameter_mm=0.45,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Authored from published numeric specifications",
        last_verified="2026-07-10",
    ),
    "oshpark": VendorDrcProfileInfo(
        vendor="oshpark",
        display_name="OSH Park",
        drc_rules_path="oshpark.kicad_dru",
        min_trace_width_mm=0.1524,
        min_clearance_mm=0.1524,
        min_drill_mm=0.3556,
        min_annular_ring_mm=0.1524,
        min_via_diameter_mm=0.6604,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Authored from published numeric specifications",
        last_verified="2026-07-10",
    ),
    "advanced_circuits": VendorDrcProfileInfo(
        vendor="advanced_circuits",
        display_name="Advanced Circuits",
        drc_rules_path="advanced_circuits.kicad_dru",
        min_trace_width_mm=0.1524,
        min_clearance_mm=0.1524,
        min_drill_mm=0.15,
        min_annular_ring_mm=0.15,
        min_via_diameter_mm=0.45,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Authored from published numeric specifications",
        last_verified="2026-07-10",
    ),
    "generic": VendorDrcProfileInfo(
        vendor="generic",
        display_name="Generic Conservative",
        drc_rules_path="generic.kicad_dru",
        min_trace_width_mm=0.2,
        min_clearance_mm=0.2,
        min_drill_mm=0.4,
        min_annular_ring_mm=0.15,
        min_via_diameter_mm=0.6,
        supports_blind_vias=False,
        supports_castellated=False,
        source="Conservative defaults for unknown vendors",
        last_verified="2026-07-10",
    ),
}


def get_drc_profile_path(vendor: str) -> Path:
    """Resolve a vendor name to its bundled .kicad_dru file path.

    Security (threat model scenario 1): validates vendor name against
    ^[a-z0-9_]+$ AND verifies the resolved path is a real file. This
    prevents path traversal (no slashes/dots in vendor name) and confirms
    only allowlisted vendors resolve.

    Args:
        vendor: Vendor key (e.g. "pcbway", "jlcpcb", "aisler_2layer").

    Returns:
        Absolute Path to the bundled .kicad_dru file.

    Raises:
        ValueError: If vendor name is malformed or unknown.
    """
    if not _VENDOR_NAME_RE.match(vendor):
        raise ValueError(
            f"Invalid vendor name {vendor!r}: must match ^[a-z0-9_]+$"
        )
    path = _PROFILES_DIR / f"{vendor}.kicad_dru"
    if not path.is_file():
        available = ", ".join(sorted(_PROFILE_INFOS.keys()))
        raise ValueError(
            f"Unknown vendor {vendor!r}. Available DRC profiles: {available}."
        )
    return path


def list_drc_profiles() -> list[VendorDrcProfileInfo]:
    """Return all bundled vendor DRC profiles with capabilities metadata (DRC-08).

    Returns:
        List of VendorDrcProfileInfo, one entry per bundled .kicad_dru file.
    """
    return list(_PROFILE_INFOS.values())


__all__ = [
    "VendorDrcProfileInfo",
    "get_drc_profile_path",
    "list_drc_profiles",
]
