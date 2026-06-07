"""Routing constraints for DRC-aware pathfinding.

Frozen dataclass holding all design-rule parameters that govern trace
routing: clearances, trace/via dimensions, and grid resolution.

Usage:
    from kicad_agent.routing.constraints import RoutingConstraints

    constraints = RoutingConstraints()
    constraints = RoutingConstraints(clearance_mm=0.3, grid_resolution_mm=0.25)
"""

# Via Optimization Status:
# The via_cost_mm field provides a static penalty for layer transitions
# in the 3D routing graph. This is sufficient for simple-to-moderate boards.
# For complex boards with high via counts, the Freerouting integration
# (run_freeroute operation) handles via optimization as part of global
# routing. Built-in via minimization, via sharing, and dynamic cost
# adjustment are not implemented and deferred to Freerouting.

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
        via_cost_mm: Penalty cost (in mm-equivalent) added to each via
            transition between layers during pathfinding. Higher values
            discourage layer changes, producing fewer vias in routing
            results. Used as edge weight for via edges in the 3D
            routing graph (graph.py).

            Current optimization level: Static per-via cost. Does not implement:
            - Via minimization algorithms (e.g., Steiner via assignment)
            - Via sharing (multiple nets using the same via)
            - Dynamic cost adjustment based on layer congestion

            Complex boards with high via counts benefit from Freerouting
            integration (run_freeroute operation) which handles via placement
            as part of its global optimization.
    """

    clearance_mm: float = 0.2
    grid_resolution_mm: float = 0.5
    trace_width_mm: float = 0.25
    via_diameter_mm: float = 0.8
    via_drill_mm: float = 0.4
    max_nodes: int = 500_000
    via_cost_mm: float = 5.0
    layer_trace_widths: dict[str, float] | None = None
    dielectric_constant: float = 4.5
    dielectric_height_mm: float = 0.2
    copper_thickness_mm: float = 0.035

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
        if self.max_nodes > 2_000_000:
            raise ValueError(
                f"max_nodes must be <= 2_000_000, got {self.max_nodes}"
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
        if self.via_cost_mm <= 0:
            raise ValueError(
                f"via_cost_mm must be > 0, got {self.via_cost_mm}"
            )
        if self.dielectric_constant <= 0:
            raise ValueError(
                f"dielectric_constant must be > 0, "
                f"got {self.dielectric_constant}"
            )
        if self.dielectric_height_mm <= 0:
            raise ValueError(
                f"dielectric_height_mm must be > 0, "
                f"got {self.dielectric_height_mm}"
            )
        if self.copper_thickness_mm <= 0:
            raise ValueError(
                f"copper_thickness_mm must be > 0, "
                f"got {self.copper_thickness_mm}"
            )

    def effective_trace_width(self, layer: str) -> float:
        """Return trace width for a specific copper layer.

        If layer_trace_widths is set and contains the layer, returns
        the layer-specific width. Otherwise falls back to trace_width_mm.

        Args:
            layer: Copper layer name (e.g., "F.Cu", "B.Cu").

        Returns:
            Trace width in mm for the given layer.
        """
        if self.layer_trace_widths and layer in self.layer_trace_widths:
            return self.layer_trace_widths[layer]
        return self.trace_width_mm
