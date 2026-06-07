"""Tests for obstacle-aware auto-routing on SMD test board (FEATURE-007 Sprint 1).

Validates end-to-end auto-routing with real PCB data:
- Obstacle extraction from footprint courtyards
- Pad-to-grid snapping
- Power net filtering
- Sequential routing with rip-up
- 100% routing success on 2-pin signal nets
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.pathfinder import (
    build_routing_graph,
    route_net,
)

# Fixture path
_SMD_BOARD = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"


def _parse_smd_board():
    """Parse the SMD test board via native parser and return PcbIR."""
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser.pcb_native_parser import NativeParser

    native_board = NativeParser.parse_pcb(_SMD_BOARD)
    return PcbIR.from_native(native_board)


class TestSmdBoardObstacleExtraction:
    """Obstacle extraction from footprint courtyards."""

    def test_footprint_count(self) -> None:
        """SMD test board has 8 footprints (4 resistors + 4 capacitors)."""
        ir = _parse_smd_board()
        assert len(ir.footprints) == 8

    def test_obstacle_count(self) -> None:
        """Each footprint produces one obstacle from courtyard."""
        ir = _parse_smd_board()
        obstacles = ir.extract_obstacles()
        assert len(obstacles) == 8

    def test_obstacles_cover_footprint_areas(self) -> None:
        """Obstacle bounding boxes are reasonable for 0805 components.

        Phase 78 verification: _parse_smd_board() creates fresh PcbIR per call
        (no shared state). Assertions check specific bounds (0.5 < dim < 5.0).
        Verified stable 5/5 consecutive runs.
        """
        ir = _parse_smd_board()
        obstacles = ir.extract_obstacles()
        for obs in obstacles:
            width = obs.x2 - obs.x1
            height = obs.y2 - obs.y1
            # Courtyard is 1.6x1.2mm (fp_rect -0.8..0.8 x -0.6..0.6)
            assert 0.5 < width < 5.0, f"Obstacle width {width} seems wrong"
            assert 0.5 < height < 5.0, f"Obstacle height {height} seems wrong"

    def test_obstacles_span_both_columns(self) -> None:
        """Obstacles exist at both x=10 (left) and x=50 (right) columns."""
        ir = _parse_smd_board()
        obstacles = ir.extract_obstacles()
        left_xs = [obs.x1 for obs in obstacles if obs.x1 < 20]
        right_xs = [obs.x1 for obs in obstacles if obs.x1 > 40]
        assert len(left_xs) == 4, "Expected 4 obstacles in left column"
        assert len(right_xs) == 4, "Expected 4 obstacles in right column"


class TestSmdBoardNetlist:
    """Netlist extraction and power net filtering."""

    def test_netlist_has_signal_and_power_nets(self) -> None:
        """Board has 3 signal nets (NET_A/B/C) and 2 power nets (VCC/GND)."""
        ir = _parse_smd_board()
        netlist = ir.extract_netlist()
        assert "NET_A" in netlist
        assert "NET_B" in netlist
        assert "NET_C" in netlist
        assert "VCC" in netlist
        assert "GND" in netlist

    def test_signal_nets_are_2_pin(self) -> None:
        """Each signal net has exactly 2 pins (one left, one right)."""
        ir = _parse_smd_board()
        netlist = ir.extract_netlist()
        for name in ("NET_A", "NET_B", "NET_C"):
            assert len(netlist[name]) == 2, f"{name} should have 2 pins"

    def test_power_nets_filtered(self) -> None:
        """Power net filtering correctly identifies VCC and GND."""
        ir = _parse_smd_board()
        netlist = ir.extract_netlist()
        power_prefixes = ("+", "GND", "AGND", "VDD", "VSS", "VCC")
        power_nets = {n for n in netlist if n.startswith(power_prefixes) or n == ""}
        assert "VCC" in power_nets
        assert "GND" in power_nets
        signal_nets = {n for n in netlist if n not in power_nets}
        assert "NET_A" in signal_nets
        assert "NET_B" in signal_nets
        assert "NET_C" in signal_nets


class TestSmdBoardRouting:
    """End-to-end auto-routing on SMD test board with obstacle awareness."""

    @pytest.fixture
    def routing_env(self):
        """Set up routing graph and filtered netlist for SMD board."""
        ir = _parse_smd_board()
        obstacles = ir.extract_obstacles()
        netlist = ir.extract_netlist()

        # Filter power nets
        power_prefixes = ("+", "GND", "AGND", "VDD", "VSS", "VCC")
        power_nets = {n for n in netlist if n.startswith(power_prefixes) or n == ""}
        route_nets = {n: pins for n, pins in netlist.items()
                      if n not in power_nets and len(pins) >= 2}

        # Collect all pad positions
        all_pads: set[tuple[float, float]] = set()
        for pins in route_nets.values():
            for px, py in pins:
                all_pads.add((px, py))

        # Compute bounds from pads + obstacles
        all_xs = [p[0] for p in all_pads] + [o.x1 for o in obstacles] + [o.x2 for o in obstacles]
        all_ys = [p[1] for p in all_pads] + [o.y1 for o in obstacles] + [o.y2 for o in obstacles]
        margin_mm = 0.25 + 0.25 + 1.0
        bounds = (min(all_xs) - margin_mm, min(all_ys) - margin_mm,
                  max(all_xs) + margin_mm, max(all_ys) + margin_mm)

        constraints = RoutingConstraints(grid_resolution_mm=0.25)
        graph = build_routing_graph(
            bounds, obstacles=obstacles, constraints=constraints,
            layers=["F.Cu"], required_nodes=all_pads,
        )

        return graph, route_nets, constraints

    def test_pad_snap_100_percent(self, routing_env) -> None:
        """All signal net pads snap to grid nodes."""
        graph, route_nets, _ = routing_env
        all_pads: set[tuple[float, float]] = set()
        for pins in route_nets.values():
            for px, py in pins:
                all_pads.add((px, py))

        snapped = sum(1 for px, py in all_pads
                      if graph.snap_to_node(px, py) is not None)
        assert snapped == len(all_pads), (
            f"Expected {len(all_pads)} pads snapped, got {snapped}"
        )

    def test_routing_success_100_percent(self, routing_env) -> None:
        """All 3 signal nets route successfully."""
        graph, route_nets, constraints = routing_env

        routed: list[str] = []
        failed: list[str] = []
        for net_name in sorted(route_nets.keys()):
            pins = route_nets[net_name]
            result = route_net(graph, pins[0], pins[1], net_name)
            if result is not None and result.success:
                routed.append(net_name)
                graph.mark_path_as_obstacle(
                    result.path, clearance=constraints.trace_width_mm,
                )
            else:
                failed.append(net_name)

        assert len(routed) == 3, f"Expected 3 routed, got {len(routed)}. Failed: {failed}"
        assert len(failed) == 0

    def test_routed_paths_span_board(self, routing_env) -> None:
        """Routed paths span the ~40mm gap between columns."""
        graph, route_nets, constraints = routing_env

        for net_name in sorted(route_nets.keys()):
            pins = route_nets[net_name]
            result = route_net(graph, pins[0], pins[1], net_name)
            assert result is not None and result.success
            # Left column at x~9-11, right at x~49-51, so path must be >35mm
            assert result.length_mm > 35.0, (
                f"{net_name} path too short: {result.length_mm:.1f}mm"
            )
            # And reasonable -- shouldn't be absurdly long
            assert result.length_mm < 60.0, (
                f"{net_name} path too long: {result.length_mm:.1f}mm"
            )
            graph.mark_path_as_obstacle(
                result.path, clearance=constraints.trace_width_mm,
            )

    def test_sequential_routing_no_reuse(self, routing_env) -> None:
        """Sequential routing marks paths as obstacles, forcing unique routes."""
        graph, route_nets, constraints = routing_env

        paths: dict[str, tuple] = {}
        for net_name in sorted(route_nets.keys()):
            pins = route_nets[net_name]
            result = route_net(graph, pins[0], pins[1], net_name)
            assert result is not None and result.success
            paths[net_name] = result.path
            graph.mark_path_as_obstacle(
                result.path, clearance=constraints.trace_width_mm,
            )

        # All three nets should take unique paths (different Y coordinates)
        # since they're at y=10, 18, 26
        for name, path in paths.items():
            y_vals = {pt[1] for pt in path}
            # NET_A routes near y=10, NET_B near y=18, NET_C near y=26
            if name == "NET_A":
                assert min(y_vals) < 11, f"{name} too far from y=10"
            elif name == "NET_B":
                assert min(y_vals) < 20, f"{name} too far from y=18"
            elif name == "NET_C":
                assert min(y_vals) < 28, f"{name} too far from y=26"
