"""Tests for routing readiness and post-route quality gates (Phase 90)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kicad_agent.validation.gate_types import GateResult
from kicad_agent.validation.gates.routing_gate import (
    PostRouteQualityGate,
    RoutingReadinessGate,
)


@pytest.fixture
def readiness_gate() -> RoutingReadinessGate:
    return RoutingReadinessGate()


@pytest.fixture
def quality_gate() -> PostRouteQualityGate:
    return PostRouteQualityGate()


def _make_basic_context(
    board_bounds: tuple | None = (0, 0, 100, 80),
    layer_count: int = 2,
    electrical_count: int = 1,
    placement_passed: bool = True,
) -> dict:
    """Create a minimal valid context for routing readiness."""
    constraints = MagicMock()
    constraints.fab.layer_count = layer_count
    constraints.electrical = [MagicMock()] * electrical_count

    pcb_ir = MagicMock()
    pcb_ir.get_board_bounds.return_value = board_bounds

    placement_result = MagicMock()
    placement_result.pass_ = placement_passed

    return {
        "pcb_ir": pcb_ir,
        "constraints": constraints,
        "gate_results": {"placement_readiness": placement_result},
    }


# ---------------------------------------------------------------------------
# RoutingReadinessGate
# ---------------------------------------------------------------------------


class TestRoutingReadiness:
    def test_missing_pcb_ir(self, readiness_gate: RoutingReadinessGate) -> None:
        result = readiness_gate.run({})
        assert result.pass_ is False
        assert any("pcb_ir" in b for b in result.blockers)

    def test_no_board_outline(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context(board_bounds=None)
        result = readiness_gate.run(ctx)
        assert result.pass_ is False
        assert any("outline" in b for b in result.blockers)

    def test_no_constraints(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context()
        ctx["constraints"] = None
        result = readiness_gate.run(ctx)
        assert result.pass_ is False
        assert any("constraints" in b for b in result.blockers)

    def test_no_stackup(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context()
        ctx["constraints"].fab.layer_count = 0
        result = readiness_gate.run(ctx)
        assert result.pass_ is False
        assert any("Stackup" in b for b in result.blockers)

    def test_no_electrical_constraints(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context(electrical_count=0)
        result = readiness_gate.run(ctx)
        assert result.pass_ is False
        assert any("electrical" in b for b in result.blockers)

    def test_placement_gate_not_run(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context()
        ctx["gate_results"] = {}
        result = readiness_gate.run(ctx)
        assert result.pass_ is False
        assert any("Placement gate" in b for b in result.blockers)

    def test_placement_gate_failed(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context(placement_passed=False)
        result = readiness_gate.run(ctx)
        assert result.pass_ is False
        assert any("did not pass" in b for b in result.blockers)

    def test_all_prerequisites_pass(self, readiness_gate: RoutingReadinessGate) -> None:
        ctx = _make_basic_context()
        result = readiness_gate.run(ctx)
        assert result.pass_ is True
        assert "routing stage" in str(result.next_actions)


# ---------------------------------------------------------------------------
# PostRouteQualityGate
# ---------------------------------------------------------------------------


class TestPostRouteQuality:
    def _make_quality_context(
        self,
        routed_pct: float = 100.0,
        has_diff_pair_issues: bool = False,
        has_return_path_risk: bool = False,
        net_count: int = 4,
    ) -> dict:
        ir = MagicMock()
        # Nets with proper string names
        nets = []
        for i in range(net_count):
            net = MagicMock()
            net.name = f"NET_{i}"
            nets.append(net)
        ir.nets = nets

        # Trace items simulating routed segments
        routed_count = int(net_count * routed_pct / 100)
        trace_items = []
        for i in range(routed_count):
            seg = MagicMock()
            net_name = f"NET_{i}"
            seg_net = MagicMock()
            seg_net.__str__ = lambda self, n=net_name: n
            seg.net = seg_net
            seg.start = MagicMock()
            seg.start.X, seg.start.Y = 0.0, 0.0
            seg.end = MagicMock()
            seg.end.X, seg.end.Y = 10.0, 10.0
            trace_items.append(seg)
        ir.trace_items = trace_items
        ir.footprints = []

        constraints = MagicMock()
        constraints.electrical = []

        if has_diff_pair_issues:
            ec = MagicMock()
            ec.diff_pair = MagicMock()
            ec.diff_pair.pair_name = "USB"
            ec.diff_pair.gap_mm = 0.15
            ec.diff_pair.length_match_mm = 50.0
            ec.diff_pair.tolerance_mm = 0.5
            constraints.electrical = [ec]

        # Zones
        if has_return_path_risk:
            ir.zones = []
        else:
            zone = MagicMock()
            zone.net_name = "GND"
            zone.layer = "F.Cu"
            zone.net = "GND"
            ir.zones = [zone]

        return {"pcb_ir": ir, "constraints": constraints}

    def test_fully_routed_passes(self, quality_gate: PostRouteQualityGate) -> None:
        ctx = self._make_quality_context(routed_pct=100.0)
        result = quality_gate.run(ctx)
        assert result.pass_ is True

    def test_incomplete_routing_blocks(self, quality_gate: PostRouteQualityGate) -> None:
        ctx = self._make_quality_context(routed_pct=50.0)
        result = quality_gate.run(ctx)
        assert result.pass_ is False
        assert any("incomplete" in b for b in result.blockers)

    def test_diff_pair_issues_block(self, quality_gate: PostRouteQualityGate) -> None:
        ctx = self._make_quality_context(
            routed_pct=100.0, has_diff_pair_issues=True
        )
        result = quality_gate.run(ctx)
        assert result.pass_ is False
        assert any("Diff pair" in b for b in result.blockers)

    def test_return_path_risk_warning(self, quality_gate: PostRouteQualityGate) -> None:
        ctx = self._make_quality_context(
            routed_pct=100.0, has_return_path_risk=True
        )
        result = quality_gate.run(ctx)
        # Return path risk is a warning, not a blocker
        assert any("return path" in w.lower() for w in result.warnings)

    def test_no_pcb_ir_fails(self, quality_gate: PostRouteQualityGate) -> None:
        result = quality_gate.run({})
        assert result.pass_ is False
        assert any("pcb_ir" in b for b in result.blockers)


class TestGateRegistration:
    def test_routing_readiness_registered(self) -> None:
        import kicad_agent.validation  # noqa: ensure gates registered
        from kicad_agent.validation.gate_runner import get_gate_runner

        runner = get_gate_runner()
        assert runner.get_gate("routing_readiness") is not None

    def test_post_route_quality_registered(self) -> None:
        import kicad_agent.validation  # noqa: ensure gates registered
        from kicad_agent.validation.gate_runner import get_gate_runner

        runner = get_gate_runner()
        assert runner.get_gate("post_route_quality") is not None
