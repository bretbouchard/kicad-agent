"""Tests for MultiPassRouter (#42).

Covers:
- MultiPassRouter 3-pass strategy
- Pass progression and fallback logic
- Per-net history tracking
- Summary statistics
- Council C-03 compliance: max 3 passes
"""

from volta.routing.multi_pass import MultiPassRouter, NetPassHistory
from volta.routing.pathfinder import RouteResult
from volta.routing.constraints import RoutingConstraints


class TestNetPassHistory:
    """Per-net pass history tracking."""

    def test_record_successful_attempt(self):
        """Successful attempt is recorded and marks net as routed."""
        history = NetPassHistory(net_name="VCC")
        result = RouteResult(
            net_name="VCC",
            path=((0.0, 0.0), (10.0, 20.0)),
            length_mm=22.36,
            success=True,
        )
        history.record_attempt(1, result, "astar_obstacle_blocking")
        assert history.routed is True
        assert history.best_result is not None
        assert history.best_result.length_mm == 22.36
        assert len(history.attempts) == 1

    def test_record_failed_attempt(self):
        """Failed attempt does not mark net as routed."""
        history = NetPassHistory(net_name="SIG")
        history.record_attempt(1, None, "astar_obstacle_blocking")
        assert history.routed is False
        assert history.best_result is None
        assert len(history.attempts) == 1

    def test_best_result_is_shortest(self):
        """Best result is the shortest path across attempts."""
        history = NetPassHistory(net_name="VCC")
        result1 = RouteResult("VCC", ((0, 0), (10, 20)), 25.0, True)
        result2 = RouteResult("VCC", ((0, 0), (5, 10)), 11.18, True)
        history.record_attempt(1, result1, "pass1")
        history.record_attempt(2, result2, "pass2")
        assert history.best_result.length_mm == 11.18

    def test_multiple_attempts_recorded(self):
        """Multiple attempts are recorded in order."""
        history = NetPassHistory(net_name="SIG")
        result = RouteResult("SIG", ((0, 0), (10, 10)), 14.14, True)
        history.record_attempt(1, result, "astar")
        history.record_attempt(2, None, "ripup")
        history.record_attempt(3, result, "aggressive")
        assert len(history.attempts) == 3
        assert history.attempts[0]["pass"] == 1
        assert history.attempts[1]["pass"] == 2
        assert history.attempts[2]["pass"] == 3


class TestMultiPassRouter:
    """MultiPassRouter integration with routing graph."""

    def _create_graph_and_netlist(self):
        """Create a simple routing scenario."""
        constraints = RoutingConstraints(
            dielectric_constant=4.5,
            dielectric_height_mm=0.2,
            copper_thickness_mm=0.035,
        )
        bounds = (0, 0, 100, 80)
        from volta.routing.pathfinder import build_routing_graph
        graph = build_routing_graph(bounds, constraints=constraints)
        netlist = {
            "VCC": [(10.0, 20.0), (80.0, 60.0)],
            "GND": [(20.0, 10.0), (70.0, 70.0)],
            "SIG1": [(5.0, 5.0), (95.0, 75.0)],
        }
        return graph, netlist

    def test_route_all_returns_results(self):
        """route_all returns results for routable nets."""
        graph, netlist = self._create_graph_and_netlist()
        router = MultiPassRouter(graph, netlist)
        results = router.route_all()
        # All nets should route in the simple scenario
        assert len(results) > 0

    def test_summary_has_required_fields(self):
        """Summary contains total, routed, and failed counts."""
        graph, netlist = self._create_graph_and_netlist()
        router = MultiPassRouter(graph, netlist)
        router.route_all()
        summary = router.summary
        assert "total_nets" in summary
        assert "routed_nets" in summary
        assert "failed_nets" in summary
        assert summary["total_nets"] == 3

    def test_pass_history_available(self):
        """Pass history is accessible after routing."""
        graph, netlist = self._create_graph_and_netlist()
        router = MultiPassRouter(graph, netlist)
        router.route_all()
        history = router.pass_history
        assert len(history) == 3
        for name, h in history.items():
            assert len(h.attempts) > 0

    def test_max_three_passes(self):
        """Router uses maximum 3 passes (Council C-03)."""
        graph, netlist = self._create_graph_and_netlist()
        router = MultiPassRouter(graph, netlist)
        router.route_all()
        for name, h in router.pass_history.items():
            assert len(h.attempts) <= 3, (
                f"Net {name} exceeded 3 passes: {len(h.attempts)}"
            )

    def test_single_pin_nets_skipped(self):
        """Nets with fewer than 2 pins are not routed."""
        graph, _ = self._create_graph_and_netlist()
        netlist = {"single_pin": [(50.0, 40.0)]}
        router = MultiPassRouter(graph, netlist)
        results = router.route_all()
        assert "single_pin" not in results

    def test_empty_netlist(self):
        """Empty netlist produces empty results."""
        graph, _ = self._create_graph_and_netlist()
        router = MultiPassRouter(graph, {})
        results = router.route_all()
        assert results == {}
        assert router.summary["total_nets"] == 0
