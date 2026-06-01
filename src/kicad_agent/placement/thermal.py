"""Thermal-aware placement with opt-in ThermalProfile.

Provides thermal separation calculations and exclusion zone generation
for components with known power dissipation. Falls back to distance-based
heuristic when no thermal data is provided -- no silent degradation.

Usage::

    from kicad_agent.placement.thermal import (
        ThermalProfile,
        compute_thermal_separation,
        apply_thermal_constraints,
    )

    profiles = [
        ThermalProfile("U1", power_dissipation_watts=5.0, max_temp_celsius=125.0),
        ThermalProfile("U2", power_dissipation_watts=2.0, max_temp_celsius=85.0),
    ]
    sep = compute_thermal_separation(profiles[0], profiles[1])
    zones = apply_thermal_constraints(positions, geometry, profiles)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from kicad_agent.placement.footprint_geometry import ComponentGeometry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_THERMAL_MARGIN_MM = 5.0
"""Default thermal separation distance in mm when no profiles provided."""

_POWER_SCALING_FACTOR = 0.5
"""mm per watt of combined dissipation added to thermal margin."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThermalProfile:
    """Thermal characteristics of a component for placement optimization.

    Opt-in: components without ThermalProfile data use the default
    distance heuristic fallback.

    Attributes:
        reference: Component reference designator (e.g., "U1").
        power_dissipation_watts: Estimated power dissipation in watts.
        max_temp_celsius: Maximum operating temperature in degrees Celsius.
        required_clearance_mm: Minimum clearance from other components in mm.
    """

    reference: str
    power_dissipation_watts: float
    max_temp_celsius: float
    required_clearance_mm: float = 5.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_thermal_separation(
    profile_a: ThermalProfile | None,
    profile_b: ThermalProfile | None,
) -> float:
    """Compute minimum thermal separation distance between two components.

    The separation is based on combined power dissipation and required
    clearances. When either profile is missing, a conservative fallback
    is used.

    Args:
        profile_a: ThermalProfile for component A, or None.
        profile_b: ThermalProfile for component B, or None.

    Returns:
        Minimum separation distance in mm.
    """
    if profile_a is not None and profile_b is not None:
        # Both profiles: use max clearance + power scaling for combined dissipation
        max_clearance = max(
            profile_a.required_clearance_mm,
            profile_b.required_clearance_mm,
        )
        combined_power = (
            profile_a.power_dissipation_watts
            + profile_b.power_dissipation_watts
        )
        return max_clearance + _POWER_SCALING_FACTOR * combined_power

    if profile_a is not None:
        # Only profile_a available
        return (
            profile_a.required_clearance_mm
            + _POWER_SCALING_FACTOR * profile_a.power_dissipation_watts
        )

    if profile_b is not None:
        # Only profile_b available
        return (
            profile_b.required_clearance_mm
            + _POWER_SCALING_FACTOR * profile_b.power_dissipation_watts
        )

    # Neither profile: return default margin
    return _DEFAULT_THERMAL_MARGIN_MM


def apply_thermal_constraints(
    positions: dict[str, tuple[float, float, float]],
    geometry: dict[str, ComponentGeometry] | None,
    thermal_profiles: list[ThermalProfile] | None,
) -> list[tuple[float, float, float, float]]:
    """Generate thermal exclusion zones from thermal profiles.

    Each hot component gets an exclusion zone centered on its position.
    The zone radius is determined by required_clearance_mm plus a power-
    scaled margin. When component geometry is available, the zone expands
    by the component's half-dimensions.

    Args:
        positions: Current component positions: ref -> (x, y, rotation).
        geometry: Optional component geometry from PcbIR.
        thermal_profiles: Optional list of ThermalProfile, or None.

    Returns:
        List of thermal exclusion zones as (x1, y1, x2, y2) rectangles.
        These are intended to be added to keepout_zones for SA refinement.
    """
    if thermal_profiles is None:
        logger.info(
            "No thermal profiles provided -- using distance heuristic fallback",
        )
        return []

    if not thermal_profiles:
        return []

    # Build ref -> ThermalProfile lookup
    profile_map: dict[str, ThermalProfile] = {
        p.reference: p for p in thermal_profiles
    }

    exclusion_zones: list[tuple[float, float, float, float]] = []

    for profile in thermal_profiles:
        pos = positions.get(profile.reference)
        if pos is None:
            continue

        cx, cy, _ = pos

        # Base radius from clearance + power scaling
        radius = (
            profile.required_clearance_mm
            + _POWER_SCALING_FACTOR * profile.power_dissipation_watts
        )

        # Expand by geometry half-dimensions if available
        half_w = 0.0
        half_h = 0.0
        if geometry and profile.reference in geometry:
            geo = geometry[profile.reference]
            half_w = geo.width_mm / 2.0
            half_h = geo.height_mm / 2.0

        x1 = cx - radius - half_w
        y1 = cy - radius - half_h
        x2 = cx + radius + half_w
        y2 = cy + radius + half_h

        exclusion_zones.append((x1, y1, x2, y2))

    logger.info(
        "Created %d thermal exclusion zone(s)",
        len(exclusion_zones),
    )

    return exclusion_zones
