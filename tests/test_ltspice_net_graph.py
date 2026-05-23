"""Tests for LTspice net connectivity graph derivation from wire geometry.

Covers:
- LTSPICE-03: Net connectivity graph derivable from WIRE and FLAG statements
- Wire segments form connected graph with touching endpoints merged
- FLAG net names propagate across connected components
- Component pins positioned and matched to nets via coordinate geometry
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.ltspice.asc_parser import parse_asc
from kicad_agent.ltspice.net_graph import LTspiceNetGraph
from kicad_agent.ltspice.types import LTspiceSchematic

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ltspice"
BASIC_RC_ASC = FIXTURE_DIR / "basic_rc.asc"


@pytest.fixture
def basic_rc_schematic() -> LTspiceSchematic:
    """Parse basic_rc.asc into an LTspiceSchematic."""
    return parse_asc(BASIC_RC_ASC)


@pytest.fixture
def basic_rc_net_graph(basic_rc_schematic: LTspiceSchematic) -> LTspiceNetGraph:
    """Build net connectivity graph from basic_rc.asc."""
    return LTspiceNetGraph.from_schematic(basic_rc_schematic)


class TestLTspiceNetGraph:
    """Tests for LTspiceNetGraph wire connectivity and net assignment.

    The basic_rc.asc fixture is a parallel RC circuit with:
    - V1 at (32,256) R0: Pin1 (64,320), Pin2 (64,224)
    - R1 at (160,96) R0: Pin1 (192,144), Pin2 (192,64)
    - C1 at (288,96) R0: Pin1 (320,128), Pin2 (320,64)

    Wires form two rails:
    - VCC rail: V1.Pin1 -> R1.Pin1 -> C1.Pin1 (top, unlabeled)
    - GND rail: V1.Pin2 -> R1.Pin2 -> C1.Pin2 (bottom, FLAG "0")
    """

    def test_1_from_schematic_builds_nonempty_graph(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """LTspiceNetGraph.from_schematic builds a non-empty graph."""
        graph = basic_rc_net_graph.graph
        assert graph.number_of_nodes() > 0
        assert graph.number_of_edges() > 0

    def test_2_graph_has_wire_endpoints_as_nodes(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """Graph has nodes at wire endpoints and edges connecting them."""
        graph = basic_rc_net_graph.graph
        # Wire endpoints from the fixture should be graph nodes
        assert (64, 320) in graph.nodes  # V1.Pin1 / wire endpoint
        assert (128, 320) in graph.nodes  # VCC rail junction
        assert (64, 64) in graph.nodes  # GND rail / FLAG position
        assert (192, 64) in graph.nodes  # R1.Pin2 on GND rail

        # Edges exist for wire segments
        assert graph.number_of_edges() >= 8  # 8 wire segments

    def test_3_flag_assigns_net_name_to_connected_component(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """FLAG '0' at (64,64) assigns net name '0' to GND rail."""
        flag_map = basic_rc_net_graph._flag_map
        assert (64, 64) in flag_map
        assert flag_map[(64, 64)] == "0"

    def test_4_get_net_names_returns_flag_nets(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """get_net_names() returns a set containing '0' (the GND net)."""
        names = basic_rc_net_graph.get_net_names()
        assert isinstance(names, set)
        assert "0" in names

    def test_5_get_pins_on_net_returns_gnd_pins(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """get_pins_on_net('0') returns at least 3 pin references (R1, C1, V1 GND pins)."""
        pins = basic_rc_net_graph.get_pins_on_net("0")
        assert len(pins) >= 3

        refs = {ref for ref, _pin_num in pins}
        assert "R1" in refs  # R1.Pin2 on GND rail
        assert "C1" in refs  # C1.Pin2 on GND rail
        assert "V1" in refs  # V1.Pin2 on GND rail

    def test_6_get_net_stats_returns_counts(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """get_net_stats() returns dict with total_nets, total_nodes, total_edges, total_pins."""
        stats = basic_rc_net_graph.get_net_stats()
        assert "total_nets" in stats
        assert "total_nodes" in stats
        assert "total_edges" in stats
        assert "total_pins" in stats
        assert stats["total_nets"] >= 1  # At least GND net
        assert stats["total_nodes"] > 0
        assert stats["total_edges"] > 0
        assert stats["total_pins"] > 0

    def test_7_touching_wires_form_connected_component(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """Two wires sharing an endpoint are in the same connected component."""
        # Wire 6: (64,224)-(64,64) and Wire 7: (64,64)-(192,64) share (64,64)
        component = basic_rc_net_graph.get_connected_component((64, 64))
        assert (64, 224) in component  # V1.Pin2 on same rail
        assert (192, 64) in component  # R1.Pin2 on same rail
        assert (320, 64) in component  # C1.Pin2 on same rail

    def test_8_flag_endpoint_in_same_component_as_flag(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """Wire endpoint (64,224) is in the same component as FLAG at (64,64)."""
        flag_component = basic_rc_net_graph.get_connected_component((64, 64))
        assert (64, 224) in flag_component  # V1.Pin2 connected to GND

    def test_9_are_connected_checks_electrical_connection(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """are_connected returns True for points on the same rail."""
        # R1.Pin2 and C1.Pin2 both on GND rail
        assert basic_rc_net_graph.are_connected((192, 64), (320, 64))
        # V1.Pin1 and R1.Pin1 both on VCC rail
        assert basic_rc_net_graph.are_connected((64, 320), (192, 144))

    def test_10_pins_not_connected_across_rails(
        self, basic_rc_net_graph: LTspiceNetGraph
    ) -> None:
        """Pins on VCC rail are NOT connected to pins on GND rail."""
        # VCC and GND are separate connected components
        assert not basic_rc_net_graph.are_connected((64, 320), (64, 64))

    def test_11_vcc_pins_have_no_net_name(
        self, basic_rc_schematic: LTspiceSchematic
    ) -> None:
        """Pins on the VCC rail (no FLAG) have unnamed net."""
        graph = LTspiceNetGraph.from_schematic(basic_rc_schematic)
        # V1.Pin1 is on VCC rail which has no FLAG label
        vcc_pins = graph.get_pins_on_net("VCC")
        assert vcc_pins == []  # No VCC flag in the fixture
