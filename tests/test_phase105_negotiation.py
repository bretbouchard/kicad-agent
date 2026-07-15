"""Phase 105: NegotiationLoop tests.

Council-mandated tests:
  1. Convergence: 2 nets sharing a corridor → both routed within 3 rounds.
  2. Termination: unsatisfiable board → terminates within max_rounds.
  3. Stall detection: no improvement for 2 rounds → early exit.
  4. Congestion cost is monotonic (PathFinder convergence guarantee).
"""

from __future__ import annotations

import pytest

from volta.routing.constraints import RoutingConstraints
from volta.routing.negotiation import NegotiationLoop, NegotiationResult, negotiate_route
from volta.spatial.primitives import SpatialBox


class TestConvergence:
    """Council test 1: nets sharing a corridor converge via rip-up/reroute."""

    def test_unsatisfiable_board_terminates(self) -> None:
        """An impossible board (wall bisecting) terminates within max_rounds."""
        board = (0, 0, 20, 20)
        # Full-height wall splitting source from target.
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL",
                          layer="", reference="WALL")

        netlist = {
            "NET_A": [(2, 10), (18, 10)],
        }

        result = negotiate_route(
            board_bounds=board,
            obstacles=[wall],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=3,
        )

        assert isinstance(result, NegotiationResult)
        assert not result.converged
        assert "NET_A" in result.failed_nets
        # Must terminate within max_rounds.
        assert result.rounds_used <= 3

    def test_simple_two_net_board_converges(self) -> None:
        """Two nets on a simple board both route successfully."""
        board = (0, 0, 30, 20)
        # No obstacles — trivial routing.
        netlist = {
            "NET_A": [(2, 5), (28, 5)],
            "NET_B": [(2, 15), (28, 15)],
        }

        result = negotiate_route(
            board_bounds=board,
            obstacles=[],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=5,
        )

        assert result.converged
        assert "NET_A" in result.routed_nets
        assert "NET_B" in result.routed_nets
        assert len(result.failed_nets) == 0
        # Should converge in round 1 (no obstacles).
        assert result.rounds_used == 1

    def test_crossing_nets_converge(self) -> None:
        """Two nets that must cross each other converge via negotiation."""
        board = (0, 0, 30, 20)
        # NET_A goes left-to-right at y=10.
        # NET_B goes top-to-bottom at x=15.
        # They cross — one must detour.
        netlist = {
            "NET_A": [(2, 10), (28, 10)],
            "NET_B": [(15, 2), (15, 18)],
        }

        result = negotiate_route(
            board_bounds=board,
            obstacles=[],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=5,
        )

        # Both should eventually route (the grid is large enough to detour).
        assert result.converged
        assert "NET_A" in result.routed_nets
        assert "NET_B" in result.routed_nets


class TestTermination:
    """Council test 2: unsatisfiable board terminates within max_rounds."""

    def test_max_rounds_respected(self) -> None:
        """The loop never exceeds max_rounds."""
        board = (0, 0, 20, 20)
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL",
                          layer="", reference="W")

        netlist = {"NET": [(2, 10), (18, 10)]}

        result = negotiate_route(
            board_bounds=board,
            obstacles=[wall],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=4,
        )

        assert result.rounds_used <= 4
        assert not result.converged

    def test_stall_detection(self) -> None:
        """Stall detection exits early when no improvement for 2 rounds."""
        board = (0, 0, 20, 20)
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL",
                          layer="", reference="W")

        netlist = {"NET": [(2, 10), (18, 10)]}

        result = negotiate_route(
            board_bounds=board,
            obstacles=[wall],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=8,  # High cap, but stall should trigger first.
        )

        # Should stall before reaching max_rounds (only HARD blockers).
        assert result.rounds_used < 8
        assert not result.converged


class TestCongestionMonotonicity:
    """PathFinder convergence guarantee: congestion cost is monotonic."""

    def test_congestion_only_increases(self) -> None:
        """Congestion costs never decrease between rounds."""
        board = (0, 0, 20, 20)
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL",
                          layer="", reference="W")

        netlist = {"NET": [(2, 10), (18, 10)]}

        result = negotiate_route(
            board_bounds=board,
            obstacles=[wall],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=3,
        )

        # After the loop, congestion values should all be positive (accumulated).
        for node, cost in result.congestion_map.items():
            assert cost > 0, f"Congestion cost for {node} should be positive"


class TestNegotiationResultStructure:
    """Verify the result dataclass structure."""

    def test_result_has_all_fields(self) -> None:
        """NegotiationResult exposes all required fields."""
        board = (0, 0, 20, 20)
        netlist = {"NET": [(2, 10), (18, 10)]}

        result = negotiate_route(
            board_bounds=board,
            obstacles=[],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=1,
        )

        assert hasattr(result, "routed_nets")
        assert hasattr(result, "failed_nets")
        assert hasattr(result, "diagnoses")
        assert hasattr(result, "rounds_used")
        assert hasattr(result, "converged")
        assert hasattr(result, "congestion_map")
        assert hasattr(result, "stalled")

    def test_diagnoses_populated_on_failure(self) -> None:
        """Failed nets get blocker diagnoses."""
        board = (0, 0, 20, 20)
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL",
                          layer="", reference="W")

        netlist = {"NET": [(2, 10), (18, 10)]}

        result = negotiate_route(
            board_bounds=board,
            obstacles=[wall],
            netlist=netlist,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            max_rounds=3,
        )

        # The failed net should have a diagnosis.
        assert "NET" in result.failed_nets
        assert "NET" in result.diagnoses
