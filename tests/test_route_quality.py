"""Tests for route quality metrics computation (Phase 90)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kicad_agent.validation.gates.route_quality import (
    RouteQualityMetrics,
    compute_route_quality,
    _count_routed_nets,
    _count_vias,
    _find_pair_nets,
)


class TestRouteQualityMetrics:
    """Test RouteQualityMetrics immutability and defaults."""

    def test_frozen_model(self) -> None:
        """RouteQualityMetrics is frozen."""
        m = RouteQualityMetrics(completion_pct=90.0)
        with pytest.raises(Exception):
            m.completion_pct = 100.0

    def test_defaults_prototype(self) -> None:
        """Default metrics have prototype status."""
        m = RouteQualityMetrics()
        assert m.quality_status == "prototype"
        assert m.completion_pct == 0.0
        assert m.quality_score == 0.0


class TestComputeRouteQuality:
    """Test compute_route_quality with mocked PcbIR."""

    def _make_pcb_ir(
        self,
        net_count: int = 5,
        routed_nets: list[str] | None = None,
        via_count: int = 10,
        zones: list[dict] | None = None,
        trace_net_names: list[str] | None = None,
    ) -> MagicMock:
        ir = MagicMock()

        # Nets
        nets = []
        for i in range(net_count):
            net = MagicMock()
            net.name = f"NET_{i}"
            nets.append(net)
        ir.nets = nets

        # Trace items (simulating routed segments)
        trace_items = []
        routed_set = set(routed_nets or [])
        for net_name in (trace_net_names or routed_set):
            seg = MagicMock()
            seg.net = MagicMock()
            seg.net.__str__ = lambda self, n=net_name: n
            seg.start = MagicMock()
            seg.start.X = 0.0
            seg.start.Y = 0.0
            seg.end = MagicMock()
            seg.end.X = 10.0
            seg.end.Y = 10.0
            trace_items.append(seg)
        ir.trace_items = trace_items

        # Footprints with vias
        fps = []
        for _ in range(via_count):
            fp = MagicMock()
            fp.pads = [MagicMock(type="thru_hole")]
            fps.append(fp)
        ir.footprints = fps

        # Zones
        ir.zones = zones or []

        return ir

    def test_fully_routed(self) -> None:
        """Fully routed board has 100% completion."""
        ir = self._make_pcb_ir(net_count=5, routed_nets=["NET_0", "NET_1", "NET_2", "NET_3", "NET_4"])
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert metrics.completion_pct == 100.0
        assert metrics.via_count == 10

    def test_partially_routed(self) -> None:
        """Partially routed board has <100% completion."""
        ir = self._make_pcb_ir(net_count=4, routed_nets=["NET_0", "NET_1"])
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert metrics.completion_pct == 50.0

    def test_no_nets(self) -> None:
        """Board with no nets has 0% completion."""
        ir = self._make_pcb_ir(net_count=0)
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert metrics.completion_pct == 0.0

    def test_diff_pair_gap_mismatch(self) -> None:
        """Diff pair with length mismatch outside tolerance produces issue."""
        ir = self._make_pcb_ir(
            net_count=2,
            trace_net_names=["USB_P", "USB_N"],
        )
        # Make USB_N longer than USB_P to force length mismatch
        # Default traces are (0,0)→(10,10) = 20mm Manhattan each
        # Extend USB_N: add a second segment (10,10)→(30,10) = +20mm extra
        long_seg = MagicMock()
        long_seg.net = MagicMock()
        long_seg.net.__str__ = lambda self: "USB_N"
        long_seg.start = MagicMock()
        long_seg.start.X, long_seg.start.Y = 10.0, 10.0
        long_seg.end = MagicMock()
        long_seg.end.X, long_seg.end.Y = 30.0, 10.0
        ir.trace_items.append(long_seg)
        # Override nets to include diff pair names
        dp_net_p = MagicMock()
        dp_net_p.name = "USB_P"
        dp_net_n = MagicMock()
        dp_net_n.name = "USB_N"
        ir.nets = [dp_net_p, dp_net_n]

        constraints = MagicMock()
        ec = MagicMock()
        ec.diff_pair = MagicMock()
        ec.diff_pair.pair_name = "USB"
        ec.diff_pair.gap_mm = 0.15
        ec.diff_pair.length_match_mm = 50.0
        ec.diff_pair.tolerance_mm = 0.5
        constraints.electrical = [ec]

        metrics = compute_route_quality(ir, constraints)
        assert len(metrics.diff_pair_issues) > 0
        assert "length mismatch" in metrics.diff_pair_issues[0]

    def test_return_path_risk_no_ground_planes(self) -> None:
        """No ground planes means return path risk for signal nets."""
        ir = self._make_pcb_ir(net_count=3, routed_nets=[], zones=[])
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert len(metrics.return_path_risk) > 0

    def test_quality_score_formula(self) -> None:
        """Quality score formula verified with known inputs."""
        # completion=100, vias=0, clearance=0, length_mismatch=0
        # score = 1.0*0.4 + 1.0*0.2 + 1.0*0.2 + 1.0*0.2 = 1.0
        ir = self._make_pcb_ir(
            net_count=2, routed_nets=["NET_0", "NET_1"], via_count=0
        )
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert metrics.quality_score == pytest.approx(1.0, abs=0.01)

    def test_quality_score_partial_routing(self) -> None:
        """Partial routing reduces quality score."""
        # completion=50, vias=0, clearance=0, length_mismatch=0
        # score = 0.5*0.4 + 1.0*0.2 + 1.0*0.2 + 1.0*0.2 = 0.8
        ir = self._make_pcb_ir(
            net_count=2, routed_nets=["NET_0"], via_count=0
        )
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert metrics.quality_score == pytest.approx(0.8, abs=0.01)

    def test_quality_status_defaults_prototype(self) -> None:
        """compute_route_quality always returns prototype status."""
        ir = self._make_pcb_ir()
        constraints = MagicMock()
        constraints.electrical = []

        metrics = compute_route_quality(ir, constraints)
        assert metrics.quality_status == "prototype"


class TestFindPairNets:
    """Test _find_pair_nets pattern matching."""

    def test_finds_p_n_suffix(self) -> None:
        ir = MagicMock()
        net_p = MagicMock()
        net_p.name = "USB_P"
        net_n = MagicMock()
        net_n.name = "USB_N"
        ir.nets = [net_p, net_n]
        result = _find_pair_nets(ir, "USB")
        assert result == ["USB_P", "USB_N"]

    def test_finds_plus_minus_suffix(self) -> None:
        ir = MagicMock()
        net_p = MagicMock()
        net_p.name = "SDA+"
        net_n = MagicMock()
        net_n.name = "SDA-"
        ir.nets = [net_p, net_n]
        result = _find_pair_nets(ir, "SDA")
        assert result == ["SDA+", "SDA-"]

    def test_no_match(self) -> None:
        ir = MagicMock()
        net1 = MagicMock()
        net1.name = "NET_1"
        net2 = MagicMock()
        net2.name = "NET_2"
        ir.nets = [net1, net2]
        result = _find_pair_nets(ir, "USB")
        assert result == []
