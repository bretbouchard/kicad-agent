"""Component type classifier with net-intent-aware roles.

Extends the existing `_classify_component_type()` from topology_graph.py
with net-intent-aware classification for placement readiness checks.

Adds roles like DECOUPLING_CAP, BULK_CAP, POWER_REGULATOR, and THERMAL_IC
that depend on both the component's library ID and its connected net
classifications.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from kicad_agent.analysis.net_classifier import NetClassifier
from kicad_agent.analysis.types import NetClassification
from kicad_agent.analysis.topology_graph import _classify_component_type

logger = logging.getLogger(__name__)


class ComponentRole(str, Enum):
    """Role of a component in the circuit, used by placement gate checks."""

    IC = "ic"
    DECOUPLING_CAP = "decoupling_cap"
    BULK_CAP = "bulk_cap"
    POWER_REGULATOR = "power_regulator"
    THERMAL_IC = "thermal_ic"
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    DIODE = "diode"
    TRANSISTOR = "transistor"
    CONNECTOR = "connector"
    CRYSTAL = "crystal"
    FUSE = "fuse"
    MISC = "misc"


# Packages considered "small" -- typical decoupling cap footprints
_SMALL_PACKAGES: frozenset[str] = frozenset({
    "0402", "0603", "0805", "0201", "0204",
    "C0402", "C0603", "C0805", "C0201", "C0204",
    "L0402", "L0603", "L0805",
    "R0402", "R0603", "R0805",
})

# Known voltage regulator part number patterns (case-insensitive)
_REGULATOR_PATTERNS: frozenset[str] = frozenset({
    "LM7805", "LM7812", "LM7833", "LM7850",
    "LM317", "LM337",
    "AMS1117", "LM1117", "AP2112", "AP2125",
    "LM2940", "LT1086", "TLV1117",
    "7912", "7915", "LM7905", "LM7912",
    "AP7361", "AP2112K", "SPX3819",
    "LM1117-3.3", "LM1117-5.0",
    "XC6209", "RT9193", "TLV702",
    "NCP1117", "MIC5205", "LP2985",
})


class ComponentTypeClassifier:
    """Classifies components into roles for placement readiness checks.

    Extends the base `_classify_component_type()` with net-intent-aware
    classification. A capacitor on a power/ground net with a small package
    becomes a DECOUPLING_CAP; an IC matching known regulator patterns becomes
    a POWER_REGULATOR.
    """

    def __init__(self) -> None:
        self._base_classifier = NetClassifier()

    def classify(
        self,
        lib_id: str,
        package_size: str | None = None,
        connected_net_names: list[str] | None = None,
        net_classifications: dict[str, NetClassification] | None = None,
    ) -> ComponentRole:
        """Classify a component into a placement-relevant role.

        Args:
            lib_id: Library identifier (e.g., "Device:C_Small", "Regulator_Linear:LM7805").
            package_size: Optional package/footprint size string (e.g., "0402", "1206").
            connected_net_names: List of net names this component is connected to.
            net_classifications: Mapping of net name to NetClassification.

        Returns:
            ComponentRole enum value.
        """
        connected_net_names = connected_net_names or []
        net_classifications = net_classifications or {}
        base_type = _classify_component_type(lib_id)

        # --- Capacitor: check for decoupling vs bulk vs generic ---
        if base_type == "capacitor":
            return self._classify_capacitor(
                package_size,
                connected_net_names,
                net_classifications,
            )

        # --- IC: check for power regulator ---
        if base_type == "ic":
            if self._is_regulator(lib_id):
                return ComponentRole.POWER_REGULATOR
            return ComponentRole.IC

        # --- Map base types to enum ---
        _BASE_TO_ROLE: dict[str, ComponentRole] = {
            "resistor": ComponentRole.RESISTOR,
            "inductor": ComponentRole.INDUCTOR,
            "diode": ComponentRole.DIODE,
            "transistor": ComponentRole.TRANSISTOR,
            "connector": ComponentRole.CONNECTOR,
        }
        return _BASE_TO_ROLE.get(base_type, ComponentRole.MISC)

    def _classify_capacitor(
        self,
        package_size: str | None,
        connected_net_names: list[str],
        net_classifications: dict[str, NetClassification],
    ) -> ComponentRole:
        """Determine if a capacitor is decoupling, bulk, or generic."""
        has_power_or_ground = any(
            net_classifications.get(net) in (NetClassification.POWER, NetClassification.GROUND)
            for net in connected_net_names
        )

        if not has_power_or_ground:
            return ComponentRole.CAPACITOR

        # Normalize package size for comparison
        pkg = (package_size or "").upper().strip()

        if pkg in _SMALL_PACKAGES or any(
            pkg.endswith(s) for s in _SMALL_PACKAGES
        ):
            return ComponentRole.DECOUPLING_CAP

        # No package info or large package: default to DECOUPLING_CAP since
        # most bypass caps are small. Only BULK_CAP when explicitly large.
        if not pkg:
            return ComponentRole.DECOUPLING_CAP

        return ComponentRole.BULK_CAP

    def _is_regulator(self, lib_id: str) -> bool:
        """Check if lib_id matches a known voltage regulator pattern."""
        upper_id = lib_id.upper()
        return any(pat.upper() in upper_id for pat in _REGULATOR_PATTERNS)

    @staticmethod
    def is_thermal(role: ComponentRole) -> bool:
        """Check if a component role is thermally significant.

        Power regulators are always thermal. Additional thermal
        tagging can be added via constraints in the gate.
        """
        return role in (ComponentRole.POWER_REGULATOR, ComponentRole.THERMAL_IC)
