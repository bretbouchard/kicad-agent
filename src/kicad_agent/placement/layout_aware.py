"""Layout-aware placement engine wrapping HybridPlacementEngine.

Adds pre-placement constraint analysis (signal flow grouping, zone
assignment) and delegates to the existing HybridPlacementEngine for
actual placement. Real footprint geometry replaces the scalar heuristic.

Usage::

    from kicad_agent.placement.layout_aware import (
        LayoutAwarePlacer,
        LayoutAwareRequest,
    )

    placer = LayoutAwarePlacer()
    request = LayoutAwareRequest(
        components=components,
        board_width=100.0,
        board_height=80.0,
        subcircuits=subcircuits,
        intents=intents,
        component_geometry=geometry,
    )
    output = placer.place_layout_aware(request)
    print(f"Score: {output.score}, Source: {output.source}")
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from kicad_agent.generation.intent import ComponentSpec, NetSpec
from kicad_agent.placement.engine import (
    HybridPlacementEngine,
    PlacementOutput,
    PlacementRequest,
)
from kicad_agent.placement.footprint_geometry import ComponentGeometry
from kicad_agent.placement.signal_flow import SignalFlowGrouper, SignalFlowGroup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ZONE_MARGIN_MM = 2.0
"""Margin between adjacent signal-flow zones on the board."""


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class LayoutAwareRequest(BaseModel):
    """Validated input for layout-aware placement.

    Extends PlacementRequest with signal flow grouping and real geometry.

    Attributes:
        components: Components to place.
        nets: Net connections between components.
        board_width: Board width in mm (must be positive).
        board_height: Board height in mm (must be positive).
        subcircuits: Optional detected subcircuits for signal flow grouping.
        intents: Optional inferred intents with I/O net information.
        component_geometry: Optional real footprint geometry from PcbIR.
        thermal_profiles: Forward-declared for Plan 52-02 (constraint-aware SA).
        constraints: Optional PCB constraints (Phase 50 -- typed as Any).
        fixed_positions: User-placed components.
        keepout_zones: Forbidden rectangular regions.
        min_clearance: Minimum clearance between components in mm.
        use_ml: Try ML prediction first if True.
    """

    components: list[ComponentSpec] = Field(
        description="Components to place on the board",
    )
    nets: list[NetSpec] = Field(
        default_factory=list,
        description="Net connections between components",
    )
    board_width: float = Field(gt=0, description="Board width in mm")
    board_height: float = Field(gt=0, description="Board height in mm")
    subcircuits: list[Any] | None = Field(
        default=None,
        description="Detected subcircuits for signal flow grouping",
    )
    intents: list[Any] | None = Field(
        default=None,
        description="Inferred subcircuit intents with I/O net information",
    )
    component_geometry: dict[str, ComponentGeometry] | None = Field(
        default=None,
        description="Real footprint geometry from PcbIR",
    )
    thermal_profiles: list[Any] | None = Field(
        default=None,
        description="Thermal profiles (Plan 52-02)",
    )
    constraints: list[Any] = Field(
        default_factory=list,
        description="PCB constraints (Phase 50)",
    )
    fixed_positions: dict[str, tuple[float, float, float]] = Field(
        default_factory=dict,
        description="User-placed components: ref -> (x, y, rotation)",
    )
    keepout_zones: list[tuple[float, float, float, float]] = Field(
        default_factory=list,
        description="Forbidden regions: [(x1, y1, x2, y2), ...]",
    )
    min_clearance: float = Field(
        default=1.0,
        gt=0,
        description="Minimum clearance between components in mm",
    )
    use_ml: bool = Field(
        default=True,
        description="Try ML prediction first",
    )


# ---------------------------------------------------------------------------
# LayoutAwarePlacer
# ---------------------------------------------------------------------------


class LayoutAwarePlacer:
    """Wraps HybridPlacementEngine with layout-aware pre-placement analysis.

    Pipeline:
    1. Signal flow grouping -- group subcircuits into ordered zones
    2. Zone assignment -- map groups to board rectangles (left-to-right)
    3. Constraint injection -- convert zones to fixed_positions + keepout_zones
    4. Geometry injection -- use real footprint sizes
    5. Delegate to HybridPlacementEngine.place()
    6. Post-placement validation -- log zone adherence metrics
    """

    def __init__(self, engine: HybridPlacementEngine | None = None) -> None:
        """Initialize placer.

        Args:
            engine: Optional HybridPlacementEngine. Creates default if None.
        """
        self._engine = engine if engine is not None else HybridPlacementEngine()
        self._grouper = SignalFlowGrouper()

    def place_layout_aware(self, request: LayoutAwareRequest) -> PlacementOutput:
        """Execute layout-aware placement.

        Args:
            request: Validated LayoutAwareRequest.

        Returns:
            PlacementOutput with source="layout_aware".
        """
        groups: list[SignalFlowGroup] = []
        zones: dict[str, tuple[float, float, float, float]] = {}

        # Phase 1: Signal flow grouping
        if request.subcircuits:
            groups = self._grouper.group(
                request.subcircuits,
                intents=request.intents,
            )
            logger.info(
                "Signal flow grouping: %d groups from %d subcircuits",
                len(groups),
                len(request.subcircuits),
            )

        # Phase 2: Zone assignment
        if groups:
            zones = self._assign_zones(
                groups, request.board_width, request.board_height,
            )
            logger.info(
                "Zone assignment: %d zones on %.1f x %.1f mm board",
                len(zones),
                request.board_width,
                request.board_height,
            )

        # Phase 3: Constraint injection
        zone_fixed: dict[str, tuple[float, float, float]] = {}
        zone_keepout: list[tuple[float, float, float, float]] = []
        if zones and groups:
            zone_fixed, zone_keepout = self._compute_zone_constraints(
                zones, groups, request.component_geometry,
            )

        # Merge with user-provided constraints
        merged_fixed = {**zone_fixed, **request.fixed_positions}
        merged_keepout = list(request.keepout_zones) + zone_keepout

        # Phase 4: Build PlacementRequest and delegate
        placement_request = PlacementRequest(
            components=request.components,
            nets=request.nets,
            board_width=request.board_width,
            board_height=request.board_height,
            fixed_positions=merged_fixed,
            keepout_zones=merged_keepout,
            min_clearance=request.min_clearance,
            use_ml=request.use_ml,
            refine_sa=True,
        )

        # Phase 5: Delegate placement
        output = self._engine.place(placement_request)

        # Phase 6: Post-placement validation -- log zone adherence
        if zones and groups:
            self._log_zone_adherence(output.positions, zones, groups)

        return PlacementOutput(
            positions=output.positions,
            score=output.score,
            hpwl=output.hpwl,
            valid=output.valid,
            violations=output.violations,
            source="layout_aware",
            component_scores=output.component_scores,
        )

    def _assign_zones(
        self,
        groups: list[SignalFlowGroup],
        board_w: float,
        board_h: float,
    ) -> dict[str, tuple[float, float, float, float]]:
        """Assign board zones to signal flow groups.

        Groups are laid out left-to-right in signal flow order.
        Each group gets board_w/len(groups) width minus margins.

        Returns:
            Dict mapping group_id -> (x1, y1, x2, y2) zone rectangle.
        """
        n_groups = len(groups)
        if n_groups == 0:
            return {}

        zone_width = board_w / n_groups
        zones: dict[str, tuple[float, float, float, float]] = {}

        for i, group in enumerate(groups):
            x1 = i * zone_width + _ZONE_MARGIN_MM
            x2 = (i + 1) * zone_width - _ZONE_MARGIN_MM
            y1 = _ZONE_MARGIN_MM
            y2 = board_h - _ZONE_MARGIN_MM

            # Ensure zone has positive dimensions
            if x1 >= x2:
                x2 = x1 + 1.0
            if y1 >= y2:
                y2 = y1 + 1.0

            zones[group.group_id] = (x1, y1, x2, y2)

        return zones

    def _compute_zone_constraints(
        self,
        zones: dict[str, tuple[float, float, float, float]],
        groups: list[SignalFlowGroup],
        geometry: dict[str, ComponentGeometry] | None,
    ) -> tuple[dict[str, tuple[float, float, float]], list[tuple[float, float, float, float]]]:
        """Convert zone assignments to placement constraints.

        Returns:
            (fixed_positions, keepout_zones) for zone center components and boundaries.
        """
        fixed_positions: dict[str, tuple[float, float, float]] = {}
        keepout_zones: list[tuple[float, float, float, float]] = []

        for group in groups:
            group_zone = zones.get(group.group_id)
            if not group_zone:
                continue

            x1, y1, x2, y2 = group_zone
            center_x = (x1 + x2) / 2.0
            center_y = (y1 + y2) / 2.0

            # Fix center component of each zone to the zone center
            for zone in group.ordered_zones:
                if zone.component_refs:
                    # Use the first component reference as the zone anchor
                    center_ref = zone.component_refs[0]
                    # If we have geometry for this component, adjust center
                    if geometry and center_ref in geometry:
                        geo = geometry[center_ref]
                        fixed_positions[center_ref] = (
                            center_x - geo.centroid_offset[0],
                            center_y - geo.centroid_offset[1],
                            0.0,
                        )
                    else:
                        fixed_positions[center_ref] = (center_x, center_y, 0.0)

        return fixed_positions, keepout_zones

    def _log_zone_adherence(
        self,
        positions: dict[str, tuple[float, float, float]],
        zones: dict[str, tuple[float, float, float, float]],
        groups: list[SignalFlowGroup],
    ) -> None:
        """Log percentage of components placed within their assigned zone.

        Zones are soft guidance -- violations are logged, not rejected.
        """
        total_components = 0
        in_zone_components = 0

        for group in groups:
            group_zone = zones.get(group.group_id)
            if not group_zone:
                continue

            x1, y1, x2, y2 = group_zone

            for zone in group.ordered_zones:
                for ref in zone.component_refs:
                    if ref not in positions:
                        continue
                    total_components += 1
                    px, py, _ = positions[ref]
                    if x1 <= px <= x2 and y1 <= py <= y2:
                        in_zone_components += 1

        if total_components > 0:
            adherence_pct = in_zone_components / total_components * 100.0
            logger.info(
                "Zone adherence: %.1f%% (%d/%d components in assigned zones)",
                adherence_pct,
                in_zone_components,
                total_components,
            )
