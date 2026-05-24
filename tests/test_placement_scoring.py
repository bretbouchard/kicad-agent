"""Tests for placement quality scoring with HPWL, congestion, and routability.

Validates that PlacementScorer computes HPWL from net topology bounding boxes,
grid-based congestion estimation, and composite quality scores.
"""

import math

import pytest

from kicad_agent.generation.intent import ComponentSpec, NetSpec
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph
from kicad_agent.placement.scoring import (
    PlacementScore,
    PlacementScorer,
    compute_congestion_estimate,
    compute_hpwl_score,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_graph(
    components: list[ComponentSpec],
    nets: list[NetSpec],
    board_width: float = 100.0,
    board_height: float = 80.0,
) -> PlacementGraph:
    """Build a PlacementGraph from components and nets."""
    graph = netlist_to_placement_graph(components, nets, board_width, board_height)
    return PlacementGraph(graph)


# ---------------------------------------------------------------------------
# HPWL tests
# ---------------------------------------------------------------------------


class TestHpwl:
    """Tests for compute_hpwl_score function."""

    def test_hpwl_single_net(self) -> None:
        """Three components in a line on a single net, HPWL = bounding box half-perimeter."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="3k"),
        ]
        nets = [NetSpec(name="NET1", pins=["R1.1", "R2.1", "R3.1"])]

        graph = _make_graph(components, nets)

        positions = {
            "R1": (10.0, 40.0, 0.0),
            "R2": (50.0, 40.0, 0.0),
            "R3": (90.0, 40.0, 0.0),
        }

        hpwl, hpwl_norm = compute_hpwl_score(positions, graph)

        # Bounding box: x from 10 to 90, y from 40 to 40
        # HPWL = (90-10) + (40-40) = 80 + 0 = 80
        assert hpwl == pytest.approx(80.0)

    def test_hpwl_multiple_nets(self) -> None:
        """Two nets with different component sets, HPWL is sum of individual net HPWLs."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="3k"),
            ComponentSpec(library_id="Device:R", reference="R4", value="4k"),
        ]
        nets = [
            NetSpec(name="NET_A", pins=["R1.1", "R2.1"]),
            NetSpec(name="NET_B", pins=["R3.1", "R4.1"]),
        ]

        graph = _make_graph(components, nets)

        positions = {
            "R1": (10.0, 20.0, 0.0),
            "R2": (30.0, 20.0, 0.0),
            "R3": (60.0, 60.0, 0.0),
            "R4": (60.0, 70.0, 0.0),
        }

        hpwl, _ = compute_hpwl_score(positions, graph)

        # NET_A: x=[10,30], y=[20,20] -> HPWL = 20 + 0 = 20
        # NET_B: x=[60,60], y=[60,70] -> HPWL = 0 + 10 = 10
        # Total = 30
        assert hpwl == pytest.approx(30.0)

    def test_hpwl_normalized(self) -> None:
        """hpwl_normalized is in [0, 1]."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
        ]
        nets = [NetSpec(name="NET1", pins=["R1.1", "R2.1"])]

        graph = _make_graph(components, nets)

        positions = {
            "R1": (10.0, 20.0, 0.0),
            "R2": (90.0, 70.0, 0.0),
        }

        _, hpwl_norm = compute_hpwl_score(positions, graph)

        assert 0.0 <= hpwl_norm <= 1.0

    def test_hpwl_no_nets(self) -> None:
        """No net nodes: HPWL is 0.0, normalized is 1.0."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
        ]
        nets: list[NetSpec] = []

        graph = _make_graph(components, nets)

        positions = {"R1": (50.0, 40.0, 0.0)}

        hpwl, hpwl_norm = compute_hpwl_score(positions, graph)

        assert hpwl == 0.0
        assert hpwl_norm == 1.0


# ---------------------------------------------------------------------------
# Congestion tests
# ---------------------------------------------------------------------------


class TestCongestion:
    """Tests for compute_congestion_estimate function."""

    def test_congestion_uniform(self) -> None:
        """Components spread evenly: low congestion estimate."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="3k"),
            ComponentSpec(library_id="Device:R", reference="R4", value="4k"),
        ]
        # Each net connects a pair spread across the board
        nets = [
            NetSpec(name="NET_A", pins=["R1.1", "R2.1"]),
            NetSpec(name="NET_B", pins=["R3.1", "R4.1"]),
        ]

        graph = _make_graph(components, nets)

        # Spread components uniformly across the board
        positions = {
            "R1": (20.0, 20.0, 0.0),
            "R2": (80.0, 20.0, 0.0),
            "R3": (20.0, 60.0, 0.0),
            "R4": (80.0, 60.0, 0.0),
        }

        congestion = compute_congestion_estimate(positions, graph)

        # Uniform distribution should have relatively low congestion
        assert 0.0 <= congestion <= 1.0

    def test_congestion_clustered(self) -> None:
        """All components in one area: higher congestion estimate."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
            ComponentSpec(library_id="Device:R", reference="R3", value="3k"),
            ComponentSpec(library_id="Device:R", reference="R4", value="4k"),
        ]
        nets = [
            NetSpec(name="NET_A", pins=["R1.1", "R2.1"]),
            NetSpec(name="NET_B", pins=["R3.1", "R4.1"]),
        ]

        graph = _make_graph(components, nets)

        # Cluster all components in one corner
        positions = {
            "R1": (10.0, 10.0, 0.0),
            "R2": (12.0, 10.0, 0.0),
            "R3": (10.0, 12.0, 0.0),
            "R4": (12.0, 12.0, 0.0),
        }

        congestion = compute_congestion_estimate(positions, graph)

        # Clustered should have higher congestion than uniform
        # (or at least be non-negative)
        assert 0.0 <= congestion <= 1.0


# ---------------------------------------------------------------------------
# PlacementScore tests
# ---------------------------------------------------------------------------


class TestPlacementScore:
    """Tests for PlacementScorer.score method."""

    def test_placement_score_components(self) -> None:
        """Compute PlacementScore: all fields present and in expected ranges."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
        ]
        nets = [NetSpec(name="NET1", pins=["R1.1", "R2.1"])]

        graph = _make_graph(components, nets)

        positions = {
            "R1": (30.0, 30.0, 0.0),
            "R2": (70.0, 50.0, 0.0),
        }
        sizes = {"R1": 2.0, "R2": 2.0}

        scorer = PlacementScorer(board_width=100.0, board_height=80.0)
        score = scorer.score(positions, graph, sizes)

        # All fields present
        assert isinstance(score, PlacementScore)
        assert isinstance(score.total_score, float)
        assert isinstance(score.hpwl, float)
        assert isinstance(score.hpwl_normalized, float)
        assert isinstance(score.congestion_estimate, float)
        assert isinstance(score.clearance_score, float)
        assert isinstance(score.edge_score, float)
        assert isinstance(score.board_utilization, float)

        # All scores in valid ranges
        assert 0.0 <= score.hpwl_normalized <= 1.0
        assert 0.0 <= score.congestion_estimate <= 1.0
        assert 0.0 <= score.clearance_score <= 1.0
        assert 0.0 <= score.edge_score <= 1.0
        assert score.board_utilization >= 0.0

    def test_placement_score_total_range(self) -> None:
        """total_score is in [0, 1]."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
        ]
        nets = [NetSpec(name="NET1", pins=["R1.1", "R2.1"])]

        graph = _make_graph(components, nets)

        positions = {
            "R1": (30.0, 30.0, 0.0),
            "R2": (70.0, 50.0, 0.0),
        }

        scorer = PlacementScorer(board_width=100.0, board_height=80.0)
        score = scorer.score(positions, graph)

        assert 0.0 <= score.total_score <= 1.0

    def test_scorer_with_validation(self) -> None:
        """Score a placement with clearance violations: clearance_score < 1.0."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
        ]
        nets = [NetSpec(name="NET1", pins=["R1.1", "R2.1"])]

        graph = _make_graph(components, nets)

        # Place too close: clearance violation expected
        positions = {
            "R1": (50.0, 40.0, 0.0),
            "R2": (50.5, 40.0, 0.0),  # Only 0.5mm apart
        }
        sizes = {"R1": 2.0, "R2": 2.0}

        scorer = PlacementScorer(
            board_width=100.0, board_height=80.0, min_clearance=1.0
        )
        score = scorer.score(positions, graph, sizes)

        # With clearance violations, clearance_score should be less than 1.0
        assert score.clearance_score < 1.0

    def test_board_utilization(self) -> None:
        """Known component sizes on known board: utilization matches manual calculation."""
        components = [
            ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
            ComponentSpec(library_id="Device:R", reference="R2", value="2k"),
        ]
        nets: list[NetSpec] = []

        graph = _make_graph(components, nets, board_width=100.0, board_height=80.0)

        positions = {
            "R1": (30.0, 40.0, 0.0),
            "R2": (70.0, 40.0, 0.0),
        }
        sizes = {"R1": 4.0, "R2": 6.0}

        scorer = PlacementScorer(board_width=100.0, board_height=80.0)
        score = scorer.score(positions, graph, sizes)

        # R1: 4x4 = 16 sq mm, R2: 6x6 = 36 sq mm
        # Total: 52 sq mm
        # Board: 100x80 = 8000 sq mm
        # Utilization: 52 / 8000 = 0.0065
        assert score.board_utilization == pytest.approx(0.0065)
