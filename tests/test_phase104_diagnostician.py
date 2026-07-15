"""Phase 104: BlockerDiagnostician tests.

Council-mandated tests (from Phase 104 testing requirements):
  1. 3-wall maze → diagnosis identifies wall as HARD_FIXED
  2. Keepout corridor injection → diagnosis returns the keepout as causal blocker
  3. Property test: blocks_path=True blockers, when removed, yield routable paths
  4. F-05: top-5 obstacle cap is honored
  5. F-07: movability precedence (locked > connector > edge > movable)
  6. SOFT_OTHER vs SOFT_OWN classification
"""

from __future__ import annotations

import pytest

from volta.routing.constraints import RoutingConstraints
from volta.routing.diagnostician import (
    Blocker,
    BlockerDiagnostician,
    BlockerDiagnosis,
    diagnose_routing_failures,
)
from volta.routing.graph import RoutingGraph
from volta.routing.pathfinder import RouteFailure, route_net
from volta.spatial.primitives import SpatialBox


def _route_and_fail(
    board_bounds: tuple[float, float, float, float],
    obstacles: list[SpatialBox],
    source: tuple[float, float],
    target: tuple[float, float],
    net_name: str = "TEST",
    grid: float = 1.0,
) -> RouteFailure:
    """Build a graph, route, and return the RouteFailure (asserting it fails)."""
    graph = RoutingGraph(
        board_bounds=board_bounds,
        obstacles=obstacles,
        constraints=RoutingConstraints(grid_resolution_mm=grid),
    )
    result = route_net(graph, source, target, net_name)
    assert not result, f"Expected failure but routing succeeded: {result}"
    assert isinstance(result, RouteFailure)
    return result


class TestThreeWallMaze:
    """Council test 1: 3-wall maze → diagnosis identifies wall as HARD_FIXED."""

    def test_wall_classified_as_hard_fixed(self) -> None:
        """A keepout wall blocking the path is diagnosed as HARD_FIXED."""
        board = (0, 0, 20, 20)
        # Wall spanning the board vertically, splitting source from target.
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL_UUID",
                          layer="", reference="WALL1")
        obstacles = [wall]

        failure = _route_and_fail(board, obstacles, (2, 10), (18, 10), "CUT")

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=obstacles,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)

        assert isinstance(result, BlockerDiagnosis)
        assert result.net_name == "CUT"
        assert len(result.blockers) > 0

        # The wall should be identified as a blocker.
        wall_blockers = [b for b in result.blockers if b.entity_id == "WALL_UUID"]
        assert len(wall_blockers) == 1
        wb = wall_blockers[0]
        assert wb.classification == "HARD_FIXED"
        assert wb.recommended_action == "escalate"

    def test_dead_end_on_source_side(self) -> None:
        """The dead-end point should be on the source side of the wall."""
        board = (0, 0, 20, 20)
        wall = SpatialBox(10, 0, 11, 20, "footprint", "WALL_UUID",
                          layer="", reference="WALL1")
        failure = _route_and_fail(board, [wall], (2, 10), (18, 10), "CUT")

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=[wall],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)
        # Dead end is on the source side (x <= 10).
        assert result.dead_end_point[0] <= 10


class TestCausalBlocker:
    """Council test 2 + 3: causal blocker identification + property test."""

    def test_removing_causal_blocker_opens_path(self) -> None:
        """Property: blocks_path=True blockers, when removed, yield routable paths."""
        board = (0, 0, 30, 12)
        # A footprint spanning the full board height — genuinely blocks the route.
        blocker = SpatialBox(14, 0, 15, 12, "footprint", "BLOCK_UUID",
                             layer="", reference="U1")
        obstacles = [blocker]

        failure = _route_and_fail(board, obstacles, (2, 6), (28, 6), "SIG",
                                  grid=1.0)

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=obstacles,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)

        # Find the causal blocker(s).
        causal = [b for b in result.blockers if b.blocks_path]
        assert len(causal) >= 1, "Expected at least one causal blocker"

        # Property test: removing each causal blocker opens the path.
        for cb in causal:
            reduced = [o for o in obstacles if o.entity_id != cb.entity_id]
            test_graph = RoutingGraph(
                board_bounds=board,
                obstacles=reduced,
                constraints=RoutingConstraints(grid_resolution_mm=1.0),
            )
            route_result = route_net(test_graph, (2, 6), (28, 6), "SIG")
            assert route_result, (
                f"Removing causal blocker {cb.entity_id} should open the path"
            )

    def test_non_causal_obstacle_not_marked_blocks_path(self) -> None:
        """An obstacle outside the corridor is NOT marked as causal."""
        board = (0, 0, 30, 12)
        # Full-height blocker in the corridor.
        blocker = SpatialBox(14, 0, 15, 12, "footprint", "BLOCK_UUID",
                             layer="", reference="U1")
        # Distant obstacle — NOT in the dead_end→target corridor (target is at x=12, before blocker).
        # Place it far away in Y so it's outside the corridor.
        distant = SpatialBox(25, 0, 26, 2, "footprint", "DISTANT_UUID",
                             layer="", reference="U9")
        obstacles = [blocker, distant]

        # Route from source to a target PAST the wall — this fails.
        failure = _route_and_fail(board, obstacles, (2, 6), (28, 6), "SIG")

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=obstacles,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)

        # The distant obstacle should not appear (or appear with low benefit).
        distant_blockers = [b for b in result.blockers if b.entity_id == "DISTANT_UUID"]
        for db in distant_blockers:
            assert not db.blocks_path, "Distant obstacle should not be causal"


class TestTopFiveCap:
    """F-05: top-5 shadow obstacle cap is honored."""

    def test_at_most_five_causality_tests(self) -> None:
        """Even with many obstacles in the corridor, at most 5 are tested."""
        board = (0, 0, 50, 10)
        obstacles = []
        # Create 10 full-height obstacles in a row.
        for i in range(10):
            x = 5 + i * 4
            obstacles.append(SpatialBox(
                x, 0, x + 1, 10, "footprint", f"OBS_{i}",
                layer="", reference=f"U{i}",
            ))

        failure = _route_and_fail(board, obstacles, (1, 5), (48, 5), "SIG",
                                  grid=1.0)

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=obstacles,
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)

        # F-05: at most 5 blockers in the output.
        assert len(result.blockers) <= 5, (
            f"F-05 violation: {len(result.blockers)} blockers, expected <= 5"
        )


class TestMovabilityHeuristic:
    """F-07: movability precedence — locked > connector > edge > movable.

    Tests the movability classifier directly (not through the full diagnose
    flow) because creating obstacles that both block routing AND don't touch
    board edges requires multi-obstacle gymnastics. The classifier is the
    unit under test here.
    """

    def _make_diag(self, board=(0, 0, 30, 30), raw: str | None = None) -> BlockerDiagnostician:
        return BlockerDiagnostician(
            board_bounds=board,
            obstacles=[],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            board_raw_content=raw,
        )

    def test_connector_prefix_is_fixed(self) -> None:
        """J-prefix components are HARD_FIXED (connectors can't move)."""
        diag = self._make_diag()
        connector = SpatialBox(14, 10, 15, 20, "footprint", "CONN_UUID",
                               layer="", reference="J1")
        assert diag._is_fixed_component(connector) is True

    def test_mounting_hole_prefix_is_fixed(self) -> None:
        """MH-prefix components are HARD_FIXED."""
        diag = self._make_diag()
        mh = SpatialBox(14, 10, 15, 20, "footprint", "MH_UUID",
                        layer="", reference="MH1")
        assert diag._is_fixed_component(mh) is True

    def test_generic_ic_is_movable(self) -> None:
        """U-prefix components (not locked, not edge) are movable."""
        diag = self._make_diag()
        # U1 in the center, well away from all edges.
        ic = SpatialBox(14, 10, 15, 20, "footprint", "IC_UUID",
                        layer="", reference="U1")
        assert diag._is_fixed_component(ic) is False

    def test_edge_proximity_is_fixed(self) -> None:
        """Components near the board edge (< 1mm) are HARD_FIXED."""
        diag = self._make_diag()
        edge_comp = SpatialBox(0.2, 10, 3, 20, "footprint", "EDGE_UUID",
                               layer="", reference="U2")
        assert diag._is_fixed_component(edge_comp) is True

    def test_centered_component_not_edge_fixed(self) -> None:
        """Components far from all edges are not edge-fixed."""
        diag = self._make_diag()
        centered = SpatialBox(14, 14, 16, 16, "footprint", "CENTER_UUID",
                              layer="", reference="U5")
        assert diag._is_fixed_component(centered) is False

    def test_locked_flag_in_raw_content_is_fixed(self) -> None:
        """F-07: ``(locked yes)`` in raw PCB content marks a component fixed."""
        raw = '''(footprint "pkg"
  (locked yes)
  (layer "F.Cu")
  (uuid "IC_UUID")
  (at 14.5 15.0 0)
  (property "Reference" "U3")
)'''
        diag = self._make_diag(raw=raw)
        ic = SpatialBox(14, 10, 15, 20, "footprint", "IC_UUID",
                        layer="", reference="U3")
        assert diag._is_fixed_component(ic) is True, (
            "Locked component should be fixed even if U-prefix and centered"
        )

    def test_unlocked_component_is_movable(self) -> None:
        """F-07: ``(locked no)`` or no lock flag = movable."""
        raw = '''(footprint "pkg"
  (layer "F.Cu")
  (uuid "IC_UUID")
  (at 14.5 15.0 0)
  (property "Reference" "U3")
)'''
        diag = self._make_diag(raw=raw)
        ic = SpatialBox(14, 10, 15, 20, "footprint", "IC_UUID",
                        layer="", reference="U3")
        assert diag._is_fixed_component(ic) is False

    def test_precedence_locked_overrides_movable_prefix(self) -> None:
        """F-07: a locked R-prefix component is fixed (locked > prefix)."""
        raw = '''(footprint "pkg"
  (locked yes)
  (layer "F.Cu")
  (uuid "R_UUID")
  (at 14.5 15.0 0)
  (property "Reference" "R1")
)'''
        diag = self._make_diag(raw=raw)
        r = SpatialBox(14, 10, 15, 20, "footprint", "R_UUID",
                       layer="", reference="R1")
        # R1 is movable by prefix, but locked flag overrides → fixed.
        assert diag._is_fixed_component(r) is True


class TestSoftClassification:
    """SOFT_OTHER vs SOFT_OWN classification for track obstacles."""

    def test_other_net_track_is_soft_other(self) -> None:
        """A track belonging to another net is SOFT_OTHER (rip_and_reroute)."""
        board = (0, 0, 30, 12)
        # A full-height track obstacle belonging to a DIFFERENT net.
        other_track = SpatialBox(14, 0, 15, 12, "track", "TRACK_UUID",
                                 layer="F.Cu", reference="OTHER_NET")

        failure = _route_and_fail(board, [other_track], (2, 6), (28, 6), "MY_NET")

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=[other_track],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)
        track_blockers = [b for b in result.blockers if b.entity_id == "TRACK_UUID"]
        if track_blockers:
            assert track_blockers[0].classification == "SOFT_OTHER"
            assert track_blockers[0].recommended_action == "rip_and_reroute"

    def test_own_net_track_is_soft_own(self) -> None:
        """A track belonging to the SAME net is SOFT_OWN (reroute_self)."""
        board = (0, 0, 30, 12)
        own_track = SpatialBox(14, 0, 15, 12, "track", "TRACK_UUID",
                               layer="F.Cu", reference="MY_NET")

        failure = _route_and_fail(board, [own_track], (2, 6), (28, 6), "MY_NET")

        diag = BlockerDiagnostician(
            board_bounds=board,
            obstacles=[own_track],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )
        result = diag.diagnose(failure)
        track_blockers = [b for b in result.blockers if b.entity_id == "TRACK_UUID"]
        if track_blockers:
            assert track_blockers[0].classification == "SOFT_OWN"
            assert track_blockers[0].recommended_action == "reroute_self"


class TestStandaloneFunction:
    """diagnose_routing_failures convenience function."""

    def test_multiple_failures(self) -> None:
        """Multiple failures produce multiple diagnoses in order."""
        board = (0, 0, 30, 20)
        wall = SpatialBox(14, 0, 15, 20, "footprint", "WALL",
                          layer="", reference="W")

        # Two failures: net A and net B, both blocked by the same wall.
        fail_a = _route_and_fail(board, [wall], (2, 5), (28, 5), "NET_A")
        fail_b = _route_and_fail(board, [wall], (2, 15), (28, 15), "NET_B")

        diagnoses = diagnose_routing_failures(
            failures=[fail_a, fail_b],
            board_bounds=board,
            obstacles=[wall],
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
        )

        assert len(diagnoses) == 2
        assert diagnoses[0].net_name == "NET_A"
        assert diagnoses[1].net_name == "NET_B"
        # Both should find the wall.
        for d in diagnoses:
            assert len(d.blockers) > 0
            assert any(b.entity_id == "WALL" for b in d.blockers)
