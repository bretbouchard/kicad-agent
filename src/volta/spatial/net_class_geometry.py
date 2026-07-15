"""Per-net geometry parameters sourced from net class definitions.

SI-04: Provides trace_width, clearance, via parameters per net name,
sourced from PcbIR net class definitions or design rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NetClassGeometry:
    """Geometry parameters for a single net class.

    Frozen dataclass holding trace width, clearance, and via parameters
    that govern routing and DRC for nets in this class.

    Attributes:
        trace_width_mm: Default trace width in mm.
        clearance_mm: Minimum clearance to other nets in mm.
        via_diameter_mm: Via pad diameter in mm.
        via_drill_mm: Via drill diameter in mm.
        diff_pair_width_mm: Differential pair trace width in mm (0.0 if N/A).
        diff_pair_gap_mm: Differential pair gap in mm (0.0 if N/A).
    """

    trace_width_mm: float
    clearance_mm: float
    via_diameter_mm: float
    via_drill_mm: float
    diff_pair_width_mm: float
    diff_pair_gap_mm: float

    @staticmethod
    def default() -> NetClassGeometry:
        """Return NetClassGeometry with KiCad default values.

        Defaults: trace_width=0.25mm, clearance=0.0mm,
        via_diameter=0.8mm, via_drill=0.4mm, diff_pair values=0.0.
        """
        return NetClassGeometry(
            trace_width_mm=0.25,
            clearance_mm=0.0,
            via_diameter_mm=0.8,
            via_drill_mm=0.4,
            diff_pair_width_mm=0.0,
            diff_pair_gap_mm=0.0,
        )

    @staticmethod
    def from_net_class_def(nc: Any) -> NetClassGeometry:
        """Create NetClassGeometry from a NetClassDef object.

        Maps NetClassDef fields from design_rules.py to geometry parameters.

        Args:
            nc: A NetClassDef object with track_width, clearance,
                via_diameter, via_drill, diff_pair_width, diff_pair_gap fields.

        Returns:
            Frozen NetClassGeometry instance.
        """
        return NetClassGeometry(
            trace_width_mm=float(getattr(nc, "track_width", 0.0)),
            clearance_mm=float(getattr(nc, "clearance", 0.0)),
            via_diameter_mm=float(getattr(nc, "via_diameter", 0.0)),
            via_drill_mm=float(getattr(nc, "via_drill", 0.0)),
            diff_pair_width_mm=float(getattr(nc, "diff_pair_width", 0.0)),
            diff_pair_gap_mm=float(getattr(nc, "diff_pair_gap", 0.0)),
        )


def build_net_class_map(net_classes: list[Any]) -> dict[str, NetClassGeometry]:
    """Build a mapping from net class name to NetClassGeometry.

    Args:
        net_classes: List of NetClassDef objects (or any object with
            a ``name`` attribute and track/clearance/via fields).

    Returns:
        Dict mapping net class name to NetClassGeometry instance.
    """
    result: dict[str, NetClassGeometry] = {}
    for nc in net_classes:
        name = getattr(nc, "name", None)
        if name is not None:
            result[name] = NetClassGeometry.from_net_class_def(nc)
    return result
