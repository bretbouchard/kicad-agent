"""Routing graph model and A* pathfinding with DRC constraints.

Provides:
    - RoutingConstraints: Frozen dataclass of design-rule parameters.
    - RoutingGraph: Grid-based routing graph with DRC-aware edge costs.
    - RouteResult: Frozen dataclass for a routed net path.
    - RouteFailure: Phase 103 — frozen dataclass for a failed route (carries
      the true dead-end point for diagnosis).
    - DiffPairResult: Frozen dataclass for differential pair routing.
    - SuggestionStatus: Enum for routing suggestion lifecycle.
    - RoutingSuggestion: Mutable suggestion with approve/reject status.
    - InteractiveRoutingSession: Session with suggestion/approval cycles.
    - build_routing_graph: Convenience function for graph construction.
    - route_net: A* pathfinding for a single net.
    - route_all_nets: Batch routing for multiple nets (shortest first).
    - route_differential_pair: Differential pair routing with length matching.
    - BlockerDiagnostician: Phase 104 — reverse-perspective blocker diagnosis.
    - BlockerDiagnosis: Phase 104 — per-failed-net blocker report.
    - diagnose_routing_failures: Phase 104 — standalone diagnostic function.
    - TrackSegment: KiCad PCB track segment dataclass.
    - ViaSegment: KiCad via segment dataclass.
    - ImpedanceResult: IPC-2141 impedance solve result.
    - solve_trace_width: Bisection solver for impedance-controlled widths.
    - LengthMatchResult: Sawtooth length matching result.
    - add_sawtooth_matching: Sawtooth bump insertion for length equalization.
"""

from volta.routing.bridge import TrackSegment, ViaSegment
from volta.routing.constraints import RoutingConstraints
from volta.routing.diagnostician import (
    Blocker,
    BlockerDiagnosis,
    BlockerDiagnostician,
    diagnose_routing_failures,
)
from volta.routing.diagnostician_model import BlockerDiagnosticianModel
from volta.routing.diff_pair import DiffPairResult, route_differential_pair
from volta.routing.graph import RoutingGraph
from volta.routing.impedance import ImpedanceResult, solve_trace_width
from volta.routing.interactive import (
    InteractiveRoutingSession,
    RoutingSuggestion,
    SuggestionStatus,
)
from volta.routing.length_matching import LengthMatchResult, add_sawtooth_matching
from volta.routing.pathfinder import (
    RouteFailure,
    RouteResult,
    build_routing_graph,
    route_all_nets,
    route_net,
)

__all__ = [
    "RoutingConstraints",
    "RoutingGraph",
    "RouteResult",
    "RouteFailure",
    "DiffPairResult",
    "SuggestionStatus",
    "RoutingSuggestion",
    "InteractiveRoutingSession",
    "build_routing_graph",
    "route_net",
    "route_all_nets",
    "route_differential_pair",
    "Blocker",
    "BlockerDiagnosis",
    "BlockerDiagnostician",
    "BlockerDiagnosticianModel",
    "diagnose_routing_failures",
    "TrackSegment",
    "ViaSegment",
    "ImpedanceResult",
    "solve_trace_width",
    "LengthMatchResult",
    "add_sawtooth_matching",
]
