"""Routing constraints for DRC-aware pathfinding.

Frozen dataclass holding all design-rule parameters that govern trace
routing: clearances, trace/via dimensions, and grid resolution.

Usage:
    from kicad_agent.routing.constraints import RoutingConstraints

    constraints = RoutingConstraints()
    constraints = RoutingConstraints(clearance_mm=0.3, grid_resolution_mm=0.25)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingConstraints:
    """Design-rule constraints for PCB trace routing.

    All dimensions in millimeters. Frozen dataclass -- immutable after
    construction.

    Attributes:
        clearance_mm: Minimum copper-to-copper clearance between traces
            and obstacles (pads, vias, other traces).
        grid_resolution_mm: Spacing between routing grid nodes. Smaller
            values give finer paths but increase graph size.
        trace_width_mm: Default trace width for routed connections.
        via_diameter_mm: Via pad diameter.
        via_drill_mm: Via drill hole diameter.
        max_nodes: Maximum number of grid nodes allowed. Prevents
            excessive memory usage on large boards.
    """

    clearance_mm: float = 0.2
    grid_resolution_mm: float = 0.5
    trace_width_mm: float = 0.25
    via_diameter_mm: float = 0.8
    via_drill_mm: float = 0.4
    max_nodes: int = 500_000

    def __post_init__(self) -> None:
        """Validate constraint values at construction time.

        Raises:
            ValueError: If any constraint is out of valid range.
        """
        if self.clearance_mm <= 0:
            raise ValueError(
                f"clearance_mm must be > 0, got {self.clearance_mm}"
            )
        if self.grid_resolution_mm < 0.1:
            raise ValueError(
                f"grid_resolution_mm must be >= 0.1, "
                f"got {self.grid_resolution_mm}"
            )
        if self.max_nodes > 1_000_000:
            raise ValueError(
                f"max_nodes must be <= 1_000_000, got {self.max_nodes}"
            )
        if self.trace_width_mm <= 0:
            raise ValueError(
                f"trace_width_mm must be > 0, got {self.trace_width_mm}"
            )
        if self.via_diameter_mm <= 0:
            raise ValueError(
                f"via_diameter_mm must be > 0, got {self.via_diameter_mm}"
            )
        if self.via_drill_mm <= 0:
            raise ValueError(
                f"via_drill_mm must be > 0, got {self.via_drill_mm}"
            )
