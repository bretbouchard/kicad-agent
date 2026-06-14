"""Design constraint schemas for PCB layout.

Three constraint categories: electrical (impedance, current, diff pairs),
mechanical (board outline, keepouts, mounting holes), and fab profile
(manufacturer minimums, material).

These schemas capture design constraints before layout begins, giving
placement and routing stages explicit rules to follow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class DiffPairSpec(BaseModel):
    """Differential pair specification."""

    pair_name: str
    gap_mm: float = Field(gt=0, description="Gap between pair members in mm")
    length_match_mm: Optional[float] = Field(
        default=None, ge=0, description="Target matched length in mm"
    )
    tolerance_mm: Optional[float] = Field(
        default=None, ge=0, description="Allowed length mismatch tolerance in mm"
    )


class LengthMatchSpec(BaseModel):
    """Length-matching specification for a group of nets."""

    target_mm: float = Field(ge=0, description="Target length in mm")
    tolerance_mm: float = Field(ge=0, description="Allowed deviation in mm")
    group_name: str = Field(description="Name identifying the matched group")


class MountingHoleSpec(BaseModel):
    """Mounting hole specification."""

    position: tuple[float, float] = Field(description="(x, y) position in mm")
    drill_diameter_mm: float = Field(
        gt=0, description="Hole diameter in mm"
    )
    plating: str = Field(
        default="non_plated", description="'plated' or 'non_plated'"
    )

    @field_validator("plating")
    @classmethod
    def _valid_plating(cls, v: str) -> str:
        allowed = {"plated", "non_plated"}
        if v not in allowed:
            raise ValueError(
                f"plating must be one of {allowed}, got '{v}'"
            )
        return v


class KeepoutZone(BaseModel):
    """Keepout zone restricting placement or routing."""

    bounds: tuple[float, float, float, float] = Field(
        description="(x1, y1, x2, y2) bounding box in mm"
    )
    zone_type: str = Field(
        default="copper",
        description="Keepout type: 'copper', 'via', or 'track'",
    )

    @field_validator("zone_type")
    @classmethod
    def _valid_zone_type(cls, v: str) -> str:
        allowed = {"copper", "via", "track"}
        if v not in allowed:
            raise ValueError(
                f"zone_type must be one of {allowed}, got '{v}'"
            )
        return v


class LockZone(BaseModel):
    """Connector lock zone -- area reserved for a specific connector."""

    bounds: tuple[float, float, float, float] = Field(
        description="(x1, y1, x2, y2) bounding box in mm"
    )
    connector_ref: str = Field(
        description="Reference designator of the locked connector"
    )


# ---------------------------------------------------------------------------
# ElectricalConstraints
# ---------------------------------------------------------------------------


class ElectricalConstraints(BaseModel):
    """Per-net electrical design constraints.

    Each instance corresponds to a single net (identified by net_name)
    and captures impedance, current, differential pair, length matching,
    frequency, and max length requirements.
    """

    net_name: str
    current_ma: Optional[float] = Field(default=None, ge=0)
    voltage_v: Optional[float] = Field(default=None, gt=0)
    impedance_ohm: Optional[float] = Field(default=None, gt=0)
    diff_pair: Optional[DiffPairSpec] = None
    length_match: Optional[LengthMatchSpec] = None
    frequency_hz: Optional[float] = Field(default=None, gt=0)
    max_length_mm: Optional[float] = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# MechanicalConstraints
# ---------------------------------------------------------------------------


class MechanicalConstraints(BaseModel):
    """Board-level mechanical constraints.

    Includes board outline polygon, mounting holes, keepout zones,
    and connector lock zones.
    """

    board_outline: Optional[list[tuple[float, float]]] = None
    mounting_holes: list[MountingHoleSpec] = Field(default_factory=list)
    keepouts: list[KeepoutZone] = Field(default_factory=list)
    connector_lock_zones: list[LockZone] = Field(default_factory=list)

    @field_validator("board_outline")
    @classmethod
    def _validate_polygon_closure(cls, v: Optional[list[tuple[float, float]]]) -> Optional[list[tuple[float, float]]]:
        """Ensure polygon closure: first point must equal last point, and >= 3 unique vertices."""
        if v is None:
            return v
        if len(v) < 3:
            raise ValueError(
                f"board_outline must have at least 3 points, got {len(v)}"
            )
        if v[0] != v[-1]:
            raise ValueError(
                "board_outline polygon must be closed (first point == last point)"
            )
        # A closed polygon needs at least 3 unique vertices (triangle).
        # len(v) includes the repeated closing point, so check unique count.
        unique_points = set(v[:-1])  # exclude closing point for uniqueness
        if len(unique_points) < 3:
            raise ValueError(
                f"board_outline must have at least 3 unique vertices, got {len(unique_points)}"
            )
        return v


# ---------------------------------------------------------------------------
# FabProfileConstraints
# ---------------------------------------------------------------------------


class FabProfileConstraints(BaseModel):
    """Fabrication profile specifying manufacturer capabilities.

    Presets are aligned with dfm/profiles.py keys.
    """

    min_trace_width_mm: float = 0.15
    min_drill_mm: float = 0.2
    min_clearance_mm: float = 0.15
    layer_count: int = Field(default=2, ge=1)
    copper_weight_oz: float = Field(default=1.0, ge=0.25)
    material: str = "FR-4"

    @field_validator("material")
    @classmethod
    def _valid_material(cls, v: str) -> str:
        allowed = {"FR-4", "FR-4 High Tg", "Rogers", "Aluminum", "Polyimide"}
        if v not in allowed:
            raise ValueError(
                f"material must be one of {allowed}, got '{v}'"
            )
        return v

    # ------------------------------------------------------------------
    # Named presets (aligned with dfm/profiles.py keys)
    # ------------------------------------------------------------------

    @classmethod
    def jlcpcb(cls) -> "FabProfileConstraints":
        """JLCPCB standard 2-layer profile."""
        return cls(
            min_trace_width_mm=0.127,
            min_drill_mm=0.2,
            min_clearance_mm=0.127,
            layer_count=2,
            copper_weight_oz=1.0,
            material="FR-4",
        )

    @classmethod
    def jlcpcb_4layer(cls) -> "FabProfileConstraints":
        """JLCPCB standard 4-layer profile."""
        return cls(
            min_trace_width_mm=0.1,
            min_drill_mm=0.2,
            min_clearance_mm=0.1,
            layer_count=4,
            copper_weight_oz=1.0,
            material="FR-4",
        )

    @classmethod
    def pcbway(cls) -> "FabProfileConstraints":
        """PCBWay standard 2-layer profile."""
        return cls(
            min_trace_width_mm=0.1,
            min_drill_mm=0.2,
            min_clearance_mm=0.1,
            layer_count=2,
            copper_weight_oz=1.0,
            material="FR-4",
        )

    @classmethod
    def osh_park(cls) -> "FabProfileConstraints":
        """OSH Park standard 2-layer profile (note: underscore, not 'oshpark')."""
        return cls(
            min_trace_width_mm=0.1524,
            min_drill_mm=0.3556,
            min_clearance_mm=0.1524,
            layer_count=2,
            copper_weight_oz=1.0,
            material="FR-4",
        )

    # ------------------------------------------------------------------
    # Validation: check feasibility of constraints against fab profile
    # ------------------------------------------------------------------

    def validate_achievable(
        self, electrical: list[ElectricalConstraints]
    ) -> list[str]:
        """Check whether electrical constraints are achievable with this fab profile.

        Returns a list of warning strings (empty = all OK).

        Checks:
        1. Impedance on 2-layer FR4 requires specific trace geometry. If the
           trace width implied by the impedance target is below fab min trace,
           warn.
        2. Diff pair gap below fab min clearance.
        3. Diff pair gap below fab min trace width.
        """
        warnings: list[str] = []

        for ec in electrical:
            prefix = f"net '{ec.net_name}'"

            # Impedance check: rough 50-ohm microstrip on 2-layer FR4 needs
            # ~3x trace width for a given dielectric height. A simplified
            # feasibility check: if impedance < ~30 ohm, the required trace
            # width may exceed reasonable limits. More precisely, on a typical
            # 1.6mm FR4 2-layer board, 50-ohm microstrip needs ~2.7mm trace
            # width -- we warn if fab min_trace is very tight.
            if ec.impedance_ohm is not None:
                if self.layer_count == 2 and self.material == "FR-4":
                    # Approximate microstrip width for 50-ohm on 1.6mm FR4:
                    # Z0 ~ (87 / sqrt(epsilon_r + 1.41)) * ln(...)
                    # For 50 ohm: width ~ 2.7mm is typical
                    # For 30 ohm: width ~ 5mm (much larger)
                    if ec.impedance_ohm < 30:
                        warnings.append(
                            f"{prefix}: impedance {ec.impedance_ohm} ohm is very "
                            f"low for {self.layer_count}-layer {self.material}; "
                            f"trace width may exceed fab capability"
                        )

                # Higher impedance on multi-layer is fine but warn if
                # impedance target implies very narrow traces (< fab min)
                # Simplified: 90+ ohm on thin dielectric needs < 0.1mm trace
                if ec.impedance_ohm is not None and ec.impedance_ohm > 90:
                    if self.min_trace_width_mm > 0.1:
                        warnings.append(
                            f"{prefix}: impedance {ec.impedance_ohm} ohm target "
                            f"may require trace width below fab minimum "
                            f"{self.min_trace_width_mm}mm"
                        )

            # Diff pair gap checks
            if ec.diff_pair is not None:
                if ec.diff_pair.gap_mm < self.min_clearance_mm:
                    warnings.append(
                        f"{prefix}: diff pair gap {ec.diff_pair.gap_mm}mm "
                        f"below fab min clearance {self.min_clearance_mm}mm"
                    )
                if ec.diff_pair.gap_mm < self.min_trace_width_mm:
                    warnings.append(
                        f"{prefix}: diff pair gap {ec.diff_pair.gap_mm}mm "
                        f"below fab min trace width {self.min_trace_width_mm}mm"
                    )

        return warnings


# ---------------------------------------------------------------------------
# DesignConstraints (aggregate)
# ---------------------------------------------------------------------------


class DesignConstraints(BaseModel):
    """Aggregate of all design constraints for a PCB.

    Combines electrical, mechanical, and fab profile constraints into
    a single model that can be validated and propagated to .kicad_dru.
    """

    electrical: list[ElectricalConstraints] = Field(default_factory=list)
    mechanical: Optional[MechanicalConstraints] = None
    fab: FabProfileConstraints = Field(default_factory=FabProfileConstraints)

    def validate_cross_constraints(self) -> list[str]:
        """Check electrical constraints against fab profile capabilities.

        Returns a list of warning strings (empty = all OK).

        Checks:
        - Diff pair gap below fab min clearance
        - Diff pair gap below fab min trace width
        - High current with narrow trace (implied from impedance or fab min)
        - Any electrical constraint dimensions below fab minimums
        """
        warnings: list[str] = []

        for ec in self.electrical:
            prefix = f"net '{ec.net_name}'"

            # Current capacity check: high current (> 500mA) needs wider traces.
            # Simplified: 1oz copper can carry ~1A per 0.5mm trace width
            # ( IPC-2152 conservative). If impedance implies narrow trace but
            # current is high, warn.
            if ec.current_ma is not None and ec.current_ma > 500:
                # Estimate trace width from impedance or use fab min
                trace_width = self.fab.min_trace_width_mm
                if ec.impedance_ohm is not None and ec.impedance_ohm >= 50:
                    # 50 ohm on 2-layer FR4 ~ 2.7mm, higher impedance = narrower
                    trace_width = max(self.fab.min_trace_width_mm, 0.15)

                # IPC-2152 rough: capacity ~ 2A per mm at 10C rise for 1oz
                max_current = trace_width * 2.0 * 1000  # mA
                if ec.current_ma > max_current:
                    warnings.append(
                        f"{prefix}: current {ec.current_ma}mA exceeds "
                        f"estimated capacity {max_current:.0f}mA for "
                        f"trace width ~{trace_width}mm"
                    )

            # Diff pair gap checks
            if ec.diff_pair is not None:
                if ec.diff_pair.gap_mm < self.fab.min_clearance_mm:
                    warnings.append(
                        f"{prefix}: diff pair gap {ec.diff_pair.gap_mm}mm "
                        f"below fab min clearance {self.fab.min_clearance_mm}mm"
                    )
                if ec.diff_pair.gap_mm < self.fab.min_trace_width_mm:
                    warnings.append(
                        f"{prefix}: diff pair gap {ec.diff_pair.gap_mm}mm "
                        f"below fab min trace width {self.fab.min_trace_width_mm}mm"
                    )

        return warnings
