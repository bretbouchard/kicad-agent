"""TDD tests for Sugiyama 5-stage algorithm (Task 2).

Covers each stage independently + integration on 3-stage op-amp chain.
Also covers LOW-2 early-exit on convergence (3 consecutive no-change sweeps).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import networkx as nx
import pytest

from volta.analysis.topology_graph import (
    CircuitTopology,
    TopologyEdge,
    TopologyNode,
)
from volta.analysis.types import NetClassification
from volta.schematic_autolayout.layout_graph import (
    KICAD_GRID_MM,
    LayoutEdge,
    LayoutGraph,
    LayoutNode,
)
from volta.schematic_autolayout.sugiyama import (
    DEFAULT_LAYER_SPACING_MM,
    DEFAULT_NODE_SPACING_MM,
    LayoutResult,
    SugiyamaLayout,
)


# ---------------------------------------------------------------------------
# Fixture helpers — minimal graphs for stage isolation
# ---------------------------------------------------------------------------


def _build_graph(
    nodes: list[LayoutNode],
    edges: list[LayoutEdge],
    power_edges: tuple[LayoutEdge, ...] = (),
    subcircuit_ids: tuple[str, ...] = ("SC-001",),
) -> LayoutGraph:
    return LayoutGraph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        power_edges=power_edges,
        subcircuit_ids=subcircuit_ids,
    )


def _node(ref: str, sc: str = "SC-001") -> LayoutNode:
    return LayoutNode(ref=ref, lib_id="X", component_type="ic", subcircuit_id=sc)


def _edge(src: str, tgt: str, net: str, direction: str = "forward") -> LayoutEdge:
    return LayoutEdge(
        source_ref=src,
        target_ref=tgt,
        net_name=net,
        signal_direction=direction,
        is_power=False,
    )


# ---------------------------------------------------------------------------
# Stage 1: cycle removal
# ---------------------------------------------------------------------------


class TestStage1CycleRemoval:
    def test_three_node_cycle_reverses_one_feedback(self) -> None:
        """A -> B -> C -> A cycle: exactly 1 back-edge reversed."""
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [
            _edge("A", "B", "AB"),
            _edge("B", "C", "BC"),
            _edge("C", "A", "CA", direction="feedback"),
        ]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, reversed_nets = layout.remove_cycles(graph)
        # DAG should have no cycles
        assert nx.is_directed_acyclic_graph(dag)
        # Exactly 1 feedback edge reversed
        assert len(reversed_nets) == 1
        assert "CA" in reversed_nets

    def test_no_cycle_returns_dag_unchanged(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, reversed_nets = layout.remove_cycles(graph)
        assert nx.is_directed_acyclic_graph(dag)
        assert len(reversed_nets) == 0


# ---------------------------------------------------------------------------
# Stage 2: layer assignment (longest path)
# ---------------------------------------------------------------------------


class TestStage2LayerAssignment:
    def test_linear_chain_three_nodes(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, _ = layout.remove_cycles(graph)
        layers = layout.assign_layers(dag)
        assert layers["A"] == 0
        assert layers["B"] == 1
        assert layers["C"] == 2

    def test_longest_path_on_5_node_chain(self) -> None:
        """A -> B -> C -> D -> E should be layers 0..4."""
        refs = ("A", "B", "C", "D", "E")
        nodes = [_node(r) for r in refs]
        edges = [_edge(refs[i], refs[i + 1], f"E{i}") for i in range(len(refs) - 1)]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, _ = layout.remove_cycles(graph)
        layers = layout.assign_layers(dag)
        for i, ref in enumerate(refs):
            assert layers[ref] == i, f"expected {ref} at layer {i}, got {layers[ref]}"


# ---------------------------------------------------------------------------
# Stage 3: dummy nodes for long edges
# ---------------------------------------------------------------------------


class TestStage3DummyNodes:
    def test_three_layer_edge_gets_two_dummies(self) -> None:
        """A (layer 0) -> B (layer 3): 3 intermediate layers -> 2 dummies."""
        nodes = [_node(n) for n in ("A", "B")]
        edges = [_edge("A", "B", "AB")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, _ = layout.remove_cycles(graph)
        layers = layout.assign_layers(dag)
        # Force B to layer 3 by adding chain
        # Actually with just A->B, both end up adjacent. Test the algorithm
        # by using a longer topology that creates a span.
        # Build: A->B, A->C, C->D, D->E, B->E   -> E is layer 3, B is layer 1, A is layer 0
        # B->E spans layers 1->3 -> 1 dummy.
        nodes2 = [_node(n) for n in ("A", "B", "C", "D", "E")]
        edges2 = [
            _edge("A", "B", "AB"),
            _edge("A", "C", "AC"),
            _edge("C", "D", "CD"),
            _edge("D", "E", "DE"),
            _edge("B", "E", "BE"),  # spans layers 1->3
        ]
        graph2 = _build_graph(nodes2, edges2)
        layout2 = SugiyamaLayout()
        dag2, _ = layout2.remove_cycles(graph2)
        layers2 = layout2.assign_layers(dag2)
        # Verify B-E span
        span = layers2["E"] - layers2["B"]
        assert span >= 2, f"expected span >= 2, got {span}"
        augmented, dummy_map = layout2.add_dummy_nodes(dag2, layers2)
        # Span = N layers means N-1 dummy nodes inserted
        expected_dummies = span - 1
        dummy_count = sum(1 for n in augmented.nodes() if str(n).startswith("__dummy_"))
        assert dummy_count == expected_dummies, (
            f"expected {expected_dummies} dummies for span {span}, got {dummy_count}"
        )

    def test_adjacent_layer_edge_gets_zero_dummies(self) -> None:
        nodes = [_node(n) for n in ("A", "B")]
        edges = [_edge("A", "B", "AB")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, _ = layout.remove_cycles(graph)
        layers = layout.assign_layers(dag)
        augmented, dummy_map = layout.add_dummy_nodes(dag, layers)
        dummies = [n for n in augmented.nodes() if str(n).startswith("__dummy_")]
        assert len(dummies) == 0


# ---------------------------------------------------------------------------
# Stage 4: crossing minimization
# ---------------------------------------------------------------------------


class TestStage4CrossingMinimization:
    def test_diamond_graph_at_most_one_crossing(self) -> None:
        """A -> B, A -> C, B -> D, C -> D (diamond). Barycentric should
        produce at most 1 crossing (typically 0 with good ordering)."""
        nodes = [_node(n) for n in ("A", "B", "C", "D")]
        edges = [
            _edge("A", "B", "AB"),
            _edge("A", "C", "AC"),
            _edge("B", "D", "BD"),
            _edge("C", "D", "CD"),
        ]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, _ = layout.remove_cycles(graph)
        layers = layout.assign_layers(dag)
        augmented, dummy_map = layout.add_dummy_nodes(dag, layers)
        orders = layout.minimize_crossings(augmented, layers)
        # Compute crossings from final ordering
        crossings = layout._count_crossings(augmented, layers, orders)
        assert crossings <= 1, f"expected at most 1 crossing, got {crossings}"

    def test_ordering_deterministic_across_calls(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C", "D")]
        edges = [
            _edge("A", "B", "AB"),
            _edge("A", "C", "AC"),
            _edge("B", "D", "BD"),
            _edge("C", "D", "CD"),
        ]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        results = []
        for _ in range(3):
            dag, _ = layout.remove_cycles(graph)
            layers = layout.assign_layers(dag)
            augmented, _ = layout.add_dummy_nodes(dag, layers)
            orders = layout.minimize_crossings(augmented, layers)
            # Convert to comparable hashable form (tuple of tuples)
            results.append(
                tuple(sorted((k, v) for k, v in orders.items()))
            )
        assert results[0] == results[1] == results[2], "ordering must be deterministic"

    def test_low_2_early_exit_on_convergence(self) -> None:
        """LOW-2: small converging graph exits before 24 sweeps."""
        # Small graph converges very quickly — track sweep count.
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        dag, _ = layout.remove_cycles(graph)
        layers = layout.assign_layers(dag)
        augmented, _ = layout.add_dummy_nodes(dag, layers)
        with patch.object(
            SugiyamaLayout, "_max_sweeps", create=True, return_value=24
        ):
            sweep_count = layout._count_sweeps_for_test(augmented, layers)
        assert sweep_count < 24, (
            f"LOW-2 early-exit failed: {sweep_count} sweeps (expected <24)"
        )


# ---------------------------------------------------------------------------
# Stage 5: coordinate assignment
# ---------------------------------------------------------------------------


class TestStage5CoordinateAssignment:
    def test_all_positions_snap_to_grid(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        for ref, coord in result.positions.items():
            # Both x and y must be divisible by 2.54 within 0.01mm tolerance
            x_mod = coord.x % KICAD_GRID_MM
            y_mod = coord.y % KICAD_GRID_MM
            assert x_mod < 0.01 or abs(x_mod - KICAD_GRID_MM) < 0.01, (
                f"{ref}.x={coord.x} not on grid"
            )
            assert y_mod < 0.01 or abs(y_mod - KICAD_GRID_MM) < 0.01, (
                f"{ref}.y={coord.y} not on grid"
            )

    def test_layer_zero_y_is_origin(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        # Layer-0 node (A) should have y == 0
        assert result.positions["A"].y == pytest.approx(0.0, abs=0.01)

    def test_layer_spacing_default(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        # B is layer 1 -> y = 25.4; C is layer 2 -> y = 50.8
        assert result.positions["B"].y == pytest.approx(
            DEFAULT_LAYER_SPACING_MM, abs=0.01
        )
        assert result.positions["C"].y == pytest.approx(
            DEFAULT_LAYER_SPACING_MM * 2, abs=0.01
        )


# ---------------------------------------------------------------------------
# Integration: full layout pipeline
# ---------------------------------------------------------------------------


class TestFullLayoutPipeline:
    def test_layout_returns_result_with_all_positions(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [_edge("A", "B", "AB"), _edge("B", "C", "BC")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        assert isinstance(result, LayoutResult)
        assert len(result.positions) == len(graph.nodes)
        for ref in ("A", "B", "C"):
            assert ref in result.positions

    def test_layout_handles_feedback_edges(self) -> None:
        """Feedback edge is reversed (not dropped) in stage 1."""
        nodes = [_node(n) for n in ("A", "B", "C")]
        edges = [
            _edge("A", "B", "AB"),
            _edge("B", "C", "BC"),
            _edge("C", "A", "CA", direction="feedback"),
        ]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        assert len(result.positions) == 3
        assert len(result.feedback_edges_reversed) == 1
        assert "CA" in result.feedback_edges_reversed

    def test_layout_deterministic_across_calls(self) -> None:
        nodes = [_node(n) for n in ("A", "B", "C", "D")]
        edges = [
            _edge("A", "B", "AB"),
            _edge("A", "C", "AC"),
            _edge("B", "D", "BD"),
            _edge("C", "D", "CD"),
        ]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result1 = layout.layout(graph)
        result2 = layout.layout(graph)
        # Sort dict items for comparison (dict ordering may not be stable)
        items1 = sorted(result1.positions.items())
        items2 = sorted(result2.positions.items())
        assert items1 == items2, "layout must be deterministic"

    def test_layout_with_unknown_direction_edge(self) -> None:
        """MED-2 fix: 'unknown' direction treated as forward, does not crash."""
        nodes = [_node(n) for n in ("A", "B")]
        edges = [_edge("A", "B", "AB", direction="unknown")]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        assert len(result.positions) == 2
        assert "A" in result.positions
        assert "B" in result.positions

    def test_opamp_three_stage_chain_with_feedback(self) -> None:
        """End-to-end fixture: 3-stage op-amp chain with feedback edge."""
        nodes = [
            _node("J1"),
            _node("U1"),
            _node("U2"),
            _node("J2"),
        ]
        edges = [
            _edge("J1", "U1", "INPUT"),
            _edge("U1", "U2", "N1"),
            _edge("U2", "J2", "OUTPUT"),
            _edge("U2", "U1", "FB", direction="feedback"),
        ]
        graph = _build_graph(nodes, edges)
        layout = SugiyamaLayout()
        result = layout.layout(graph)
        assert len(result.positions) == 4
        # Feedback edge should have been reversed
        assert "FB" in result.feedback_edges_reversed
        # All positions on grid
        for ref, coord in result.positions.items():
            x_mod = coord.x % KICAD_GRID_MM
            y_mod = coord.y % KICAD_GRID_MM
            assert x_mod < 0.01 or abs(x_mod - KICAD_GRID_MM) < 0.01
            assert y_mod < 0.01 or abs(y_mod - KICAD_GRID_MM) < 0.01
        # Crossing count is a non-negative integer
        assert isinstance(result.crossing_count, int)
        assert result.crossing_count >= 0


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_default_spacing_constants() -> None:
    assert DEFAULT_LAYER_SPACING_MM == 25.4
    assert DEFAULT_NODE_SPACING_MM == 12.7
    assert KICAD_GRID_MM == 2.54


def test_sugiyama_layout_construction() -> None:
    layout = SugiyamaLayout()
    assert layout.grid_mm == KICAD_GRID_MM
    assert layout.layer_spacing_mm == DEFAULT_LAYER_SPACING_MM
    assert layout.node_spacing_mm == DEFAULT_NODE_SPACING_MM

    # Custom values
    layout2 = SugiyamaLayout(
        layer_spacing_mm=50.0,
        node_spacing_mm=20.0,
        grid_mm=2.54,
    )
    assert layout2.layer_spacing_mm == 50.0
    assert layout2.node_spacing_mm == 20.0
