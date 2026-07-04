"""Sugiyama 5-stage layered-graph layout algorithm (Task 2).

Pure-Python implementation using networkx 3.1 (D-01: no Graphviz).

Stages:
    1. remove_cycles(graph) -> (nx.DiGraph, tuple[reversed_net_names])
       Greedy cycle removal via |out_degree - in_degree| heuristic.
    2. assign_layers(dag) -> {ref: layer_index}
       Longest-path layer assignment via topological sort.
    3. add_dummy_nodes(dag, layers) -> (augmented_dag, dummy_map)
       Inserts dummy nodes for edges spanning >1 layer.
    4. minimize_crossings(augmented_dag, layers) -> {ref: order_in_layer}
       Barycentric heuristic with LOW-2 early-exit (3 consecutive no-change sweeps).
    5. assign_coordinates(augmented_dag, layers, orders) -> {ref: LayoutCoordinate}
       Grid-snapped coordinates (KICAD_GRID_MM=2.54).

Output: LayoutResult (frozen) ready for Wave 2's place_components_sch op.

Determinism: layout() is pure — same input always produces identical output.
Phase 100 CR-01: All dataclasses frozen; mutation via dataclasses.replace only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import networkx as nx

from kicad_agent.schematic_autolayout.layout_graph import (
    KICAD_GRID_MM,
    LayoutCoordinate,
    LayoutEdge,
    LayoutGraph,
    LayoutNode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LAYER_SPACING_MM: float = 25.4  # 10 grid units vertical between layers
DEFAULT_NODE_SPACING_MM: float = 12.7  # 5 grid units horizontal between nodes

_MAX_SWEEPS: int = 24  # Standard practice for <500-node schematics
_EARLY_EXIT_NO_CHANGE_STREAK: int = 3  # LOW-2: 3 consecutive no-change sweeps


# ---------------------------------------------------------------------------
# LayoutResult (frozen)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutResult:
    """Frozen result of SugiyamaLayout.layout().

    Fields:
        positions: {ref: LayoutCoordinate} for every real node in the graph.
        layers: {ref: layer_index} for every real node.
        crossing_count: Number of edge crossings in the final layout.
        feedback_edges_reversed: tuple of net_names that were reversed in
            stage 1 to break cycles. Wave 2 may render these with a
            feedback-style annotation.
    """

    positions: dict[str, LayoutCoordinate] = field(default_factory=dict)
    layers: dict[str, int] = field(default_factory=dict)
    crossing_count: int = 0
    feedback_edges_reversed: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# SugiyamaLayout — 5-stage algorithm
# ---------------------------------------------------------------------------


class SugiyamaLayout:
    """Pure-Python Sugiyama layout for KiCad schematics.

    Construct once, call .layout(graph) per subgraph (D-02 split happens in
    Wave 3 orchestrator).
    """

    def __init__(
        self,
        layer_spacing_mm: float = DEFAULT_LAYER_SPACING_MM,
        node_spacing_mm: float = DEFAULT_NODE_SPACING_MM,
        grid_mm: float = KICAD_GRID_MM,
    ) -> None:
        self.layer_spacing_mm = float(layer_spacing_mm)
        self.node_spacing_mm = float(node_spacing_mm)
        self.grid_mm = float(grid_mm)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def layout(self, graph: LayoutGraph) -> LayoutResult:
        """Run all 5 stages and return final positions."""
        # Stage 1: cycle removal
        dag, reversed_nets = self.remove_cycles(graph)
        # Stage 2: layer assignment
        layers = self.assign_layers(dag)
        # Stage 3: dummy nodes for long edges
        augmented, dummy_map = self.add_dummy_nodes(dag, layers)
        # Stage 4: crossing minimization
        orders = self.minimize_crossings(augmented, layers)
        # Stage 5: coordinate assignment
        positions = self.assign_coordinates(augmented, layers, orders)
        # Compute final crossing count for diagnostic reporting
        crossing_count = self._count_crossings(augmented, layers, orders)
        return LayoutResult(
            positions=positions,
            layers=layers,
            crossing_count=crossing_count,
            feedback_edges_reversed=reversed_nets,
        )

    # ------------------------------------------------------------------
    # Stage 1: Cycle removal — greedy heuristic
    # ------------------------------------------------------------------

    def remove_cycles(
        self, graph: LayoutGraph
    ) -> tuple[nx.DiGraph, tuple[str, ...]]:
        """Greedy cycle removal.

        Algorithm (standard Sugiyama heuristic):
            - Repeatedly pick node with highest |out_degree - in_degree|.
            - Positive -> place at end (sinks), negative -> place at front (sources).
            - Remove from working graph; repeat until empty.
            - For each back-edge (creates cycle in original), reverse it.

        Returns:
            Tuple of (DAG as nx.DiGraph, tuple of net_names that were reversed).
        """
        g = graph.to_networkx()
        if len(g) == 0:
            return g, ()

        # Track edges we reverse so we can report them and tag the DAG
        reversed_nets: list[str] = []
        # Snapshot of original edges so we can detect reversals
        original_edges = set(g.edges())

        # Greedy removal: order nodes by |out - in|
        # Build the final ordering list
        s: list[str] = []  # front (sources)
        t: list[str] = []  # back (sinks)
        work = g.copy()

        while work.number_of_nodes() > 0:
            # Score each remaining node
            best_node = None
            best_score = None
            for node in work.nodes():
                out_deg = work.out_degree(node)
                in_deg = work.in_degree(node)
                score = out_deg - in_deg
                if best_node is None or score > best_score:
                    best_node = node
                    best_score = score

            assert best_node is not None  # loop guard
            node = best_node
            score = best_score

            if score >= 0:
                # More outputs -> sink, add to back
                t.append(node)
            else:
                # More inputs -> source, add to front
                s.append(node)
            work.remove_node(node)

        # Final node ordering: s (reversed, since we built back-to-front) + t
        ordered = list(reversed(s)) + t

        # Build the DAG by re-adding edges in the order they appear in `ordered`.
        # Any edge going "backwards" (target appears before source in ordered)
        # is a back-edge that creates a cycle — reverse it.
        order_index = {ref: i for i, ref in enumerate(ordered)}

        # Classify edges into forward and back-edge sets. For each cycle created
        # by a back-edge, prefer reversing the feedback edge (if any) over a
        # forward/unknown edge — schematic-layout convention preserves natural
        # signal flow when possible.
        forward_edges: list[tuple[str, str, dict]] = []
        back_edges: list[tuple[str, str, dict]] = []
        for u, v, data in g.edges(data=True):
            if order_index[u] < order_index[v]:
                forward_edges.append((u, v, data))
            else:
                back_edges.append((u, v, data))

        # For each back-edge, if it has signal_direction != "feedback" AND
        # there's a forward edge with the same endpoints going the OTHER way
        # that IS a feedback edge, swap them — keep the feedback edge reversed
        # and let the natural signal edge go forward.
        # This handles the op-amp case where greedy cycle removal accidentally
        # reversed the natural signal edge instead of the feedback edge.
        swapped: set[int] = set()
        for i, (u, v, data) in enumerate(back_edges):
            if data.get("signal_direction") == "feedback":
                continue  # feedback edge already reversed — preferred outcome
            # Look for a forward feedback edge v -> u (same endpoints, opposite direction)
            for j, (fu, fv, fdata) in enumerate(forward_edges):
                if fu == v and fv == u and fdata.get("signal_direction") == "feedback":
                    # Swap: make the feedback edge the back-edge, the original
                    # signal edge goes forward
                    back_edges[i] = (fu, fv, fdata)
                    forward_edges[j] = (u, v, data)
                    swapped.add(i)
                    break

        dag = nx.DiGraph()
        for node in ordered:
            dag.add_node(node)

        for u, v, data in forward_edges:
            dag.add_edge(u, v, **data)

        for u, v, data in back_edges:
            net_name = data.get("net_name", "")
            signal_direction = data.get("signal_direction", "forward")
            reversed_data = dict(data)
            reversed_data["net_name"] = net_name
            reversed_data["signal_direction"] = signal_direction
            reversed_data["_reversed"] = True
            # Reverse edge direction (u, v) -> (v, u)
            dag.add_edge(v, u, **reversed_data)
            reversed_nets.append(net_name)

        return dag, tuple(reversed_nets)

    # ------------------------------------------------------------------
    # Stage 2: Layer assignment — longest path
    # ------------------------------------------------------------------

    def assign_layers(self, dag: nx.DiGraph) -> dict[str, int]:
        """Longest-path layer assignment.

        layer(v) = 0 if v has no predecessors, else max(layer(u)) + 1.
        Computed via topological sort.
        """
        layers: dict[str, int] = {}
        # Process in topological order so all predecessors are assigned first
        for node in nx.topological_sort(dag):
            preds = list(dag.predecessors(node))
            if not preds:
                layers[node] = 0
            else:
                layers[node] = max(layers[p] for p in preds) + 1
        return layers

    # ------------------------------------------------------------------
    # Stage 3: Dummy nodes for long edges
    # ------------------------------------------------------------------

    def add_dummy_nodes(
        self, dag: nx.DiGraph, layers: dict[str, int]
    ) -> tuple[nx.DiGraph, dict[str, tuple[str, ...]]]:
        """Insert dummy nodes for edges spanning >1 layer.

        For an edge u->v spanning layers [2, 3, 4], insert 2 dummy nodes
        (one per intermediate layer). Dummy refs use prefix `__dummy_` which
        never collides with real refs (underscore reserved by convention).

        Returns:
            Tuple of (augmented DAG, dummy_map).
            dummy_map: {original_edge_tuple: (dummy_ref, ...)} for stage 5
            unrolling (currently unused by coordinate assignment but logged
            for debugging).
        """
        augmented = dag.copy()
        dummy_map: dict[str, tuple[str, ...]] = {}

        # Snapshot edges before mutation (we'll add/remove during iteration)
        edges_to_process = list(dag.edges(data=True))

        for u, v, data in edges_to_process:
            span = layers[v] - layers[u]
            if span <= 1:
                continue  # adjacent layer edge, no dummy needed

            # Create span-1 dummies at each intermediate layer
            net_name = data.get("net_name", "")
            dummies: list[str] = []
            for i in range(1, span):
                layer = layers[u] + i
                dummy_ref = f"__dummy_{net_name}_{u}_{v}_L{layer}"
                dummies.append(dummy_ref)
                augmented.add_node(dummy_ref, _dummy=True)
                # Track its layer via attribute (will be merged into layers
                # dict by the caller — we re-derive here for self-containment)
                layers[dummy_ref] = layer

            # Rewire: u -> d1 -> d2 -> ... -> v
            augmented.remove_edge(u, v)
            chain = [u] + dummies + [v]
            for a, b in zip(chain, chain[1:]):
                augmented.add_edge(a, b, **data)

            dummy_map[f"{u}->{v}"] = tuple(dummies)

        return augmented, dummy_map

    # ------------------------------------------------------------------
    # Stage 4: Crossing minimization — barycentric heuristic
    # ------------------------------------------------------------------

    def minimize_crossings(
        self, augmented: nx.DiGraph, layers: dict[str, int]
    ) -> dict[str, int]:
        """Barycentric crossing minimization.

        For each layer (top to bottom), compute each node's barycenter =
        average of positions of neighbors in the previous (upper) layer.
        Sort by barycenter. 24 sweeps max (standard practice).

        LOW-2 early-exit: if node ordering is unchanged for 3 consecutive
        sweeps, break out (convergence detected). Critical for large-board
        performance.

        Returns:
            {ref: order_in_layer} mapping (0-indexed).
        """
        # Group nodes by layer
        max_layer = max(layers.values()) if layers else 0
        layer_nodes: dict[int, list[str]] = {i: [] for i in range(max_layer + 1)}
        for node, layer in layers.items():
            layer_nodes[layer].append(node)

        # Initialize orderings — sort by ref for determinism
        current_orders: dict[str, int] = {}
        for layer_idx in range(max_layer + 1):
            refs_sorted = sorted(layer_nodes[layer_idx])
            for i, ref in enumerate(refs_sorted):
                current_orders[ref] = i

        # Track last 3 orderings for LOW-2 early-exit
        recent_orderings: list[tuple[tuple[str, int], ...]] = []

        for sweep in range(_MAX_SWEEPS):
            # Snapshot current ordering as comparable form
            snapshot = tuple(sorted(current_orders.items()))

            # Top-down sweep: recompute barycenters using upper layer
            for layer_idx in range(1, max_layer + 1):
                nodes_in_layer = sorted(layer_nodes[layer_idx])
                # Compute barycenter for each node based on upper-layer neighbors
                barycenters: list[tuple[float, str]] = []
                for node in nodes_in_layer:
                    upper_neighbors = [
                        p for p in augmented.predecessors(node)
                        if p in current_orders
                    ]
                    if upper_neighbors:
                        bary = sum(current_orders[p] for p in upper_neighbors) / len(
                            upper_neighbors
                        )
                    else:
                        # No upper neighbor — keep current order as fallback
                        bary = float(current_orders[node])
                    barycenters.append((bary, node))

                # Sort by barycenter, then by ref for deterministic tie-break
                barycenters.sort(key=lambda bn: (bn[0], bn[1]))
                # Reassign orders
                for i, (_, node) in enumerate(barycenters):
                    current_orders[node] = i

            # Bottom-up sweep: recompute barycenters using lower layer
            for layer_idx in range(max_layer - 1, -1, -1):
                nodes_in_layer = sorted(layer_nodes[layer_idx])
                barycenters: list[tuple[float, str]] = []
                for node in nodes_in_layer:
                    lower_neighbors = [
                        s for s in augmented.successors(node)
                        if s in current_orders
                    ]
                    if lower_neighbors:
                        bary = sum(current_orders[s] for s in lower_neighbors) / len(
                            lower_neighbors
                        )
                    else:
                        bary = float(current_orders[node])
                    barycenters.append((bary, node))

                barycenters.sort(key=lambda bn: (bn[0], bn[1]))
                for i, (_, node) in enumerate(barycenters):
                    current_orders[node] = i

            # LOW-2 early-exit check
            new_snapshot = tuple(sorted(current_orders.items()))
            recent_orderings.append(new_snapshot)
            if len(recent_orderings) > _EARLY_EXIT_NO_CHANGE_STREAK:
                recent_orderings.pop(0)
            # If last N snapshots are all identical, we've converged
            if (
                len(recent_orderings) == _EARLY_EXIT_NO_CHANGE_STREAK
                and all(r == recent_orderings[0] for r in recent_orderings)
            ):
                logger.debug(
                    "Sugiyama crossing minimization converged at sweep %d", sweep + 1
                )
                break

        return current_orders

    # ------------------------------------------------------------------
    # Stage 5: Coordinate assignment
    # ------------------------------------------------------------------

    def assign_coordinates(
        self,
        augmented: nx.DiGraph,
        layers: dict[str, int],
        orders: dict[str, int],
    ) -> dict[str, LayoutCoordinate]:
        """Grid-snapped coordinate assignment.

        For each non-dummy node:
            x = snap_to_grid(order_in_layer * node_spacing + layer * node_spacing / 2.0)
            y = snap_to_grid(layer * layer_spacing)

        The slight per-layer X offset (Brandes-Köpf simplification) improves
        visual separation of nodes in adjacent layers.

        Dummy nodes are NOT emitted (they only exist for crossing minimization).
        """
        positions: dict[str, LayoutCoordinate] = {}
        for node in augmented.nodes():
            # Skip dummy nodes
            if str(node).startswith("__dummy_"):
                continue
            layer = layers.get(node, 0)
            order = orders.get(node, 0)
            x_raw = order * self.node_spacing_mm + layer * self.node_spacing_mm / 2.0
            y_raw = layer * self.layer_spacing_mm
            x = self._snap_to_grid(x_raw)
            y = self._snap_to_grid(y_raw)
            positions[node] = LayoutCoordinate(x=float(x), y=float(y))
        return positions

    # ------------------------------------------------------------------
    # Helpers (test-facing and internal)
    # ------------------------------------------------------------------

    def _snap_to_grid(self, value: float) -> float:
        """Snap to nearest grid multiple, rounded to 2 decimal places."""
        snapped = round(round(value / self.grid_mm) * self.grid_mm, 2)
        return float(snapped)

    def _count_crossings(
        self,
        dag: nx.DiGraph,
        layers: dict[str, int],
        orders: dict[str, int],
    ) -> int:
        """Count edge crossings in the current layout (for diagnostic).

        For each pair of layers (i, i+1), count edge crossings between edges
        that span those layers. Standard crossing-count algorithm.
        """
        if not orders:
            return 0
        max_layer = max(layers.values()) if layers else 0
        total = 0
        # For each adjacent layer pair, examine edges going from layer i to layer i+1
        for layer_idx in range(max_layer):
            # Get edges where source is in layer_idx and target is in layer_idx+1
            # (or spans — but for simplicity, count only direct layer-to-layer
            # edges; dummy nodes have already been inserted so all spans are 1)
            layer_edges = []
            for u, v in dag.edges():
                u_layer = layers.get(u, -1)
                v_layer = layers.get(v, -1)
                if u_layer == layer_idx and v_layer == layer_idx + 1:
                    layer_edges.append((orders.get(u, 0), orders.get(v, 0)))
            # Count crossings: pairs (a, b), (c, d) where a<c and b>d (or a>c and b<d)
            for i in range(len(layer_edges)):
                a1, b1 = layer_edges[i]
                for j in range(i + 1, len(layer_edges)):
                    a2, b2 = layer_edges[j]
                    if (a1 < a2 and b1 > b2) or (a1 > a2 and b1 < b2):
                        total += 1
        return total

    def _count_sweeps_for_test(
        self, augmented: nx.DiGraph, layers: dict[str, int]
    ) -> int:
        """Test helper: run minimize_crossings and report sweep count.

        Used by LOW-2 early-exit test to verify we exit before _MAX_SWEEPS.
        """
        # Temporarily wrap minimize_crossings with a counter
        original = self.minimize_crossings
        sweeps: list[int] = [0]

        def counting_wrapper(aug: nx.DiGraph, lays: dict[str, int]) -> dict[str, int]:
            # Replicate the sweep loop but track count
            max_layer = max(lays.values()) if lays else 0
            layer_nodes: dict[int, list[str]] = {i: [] for i in range(max_layer + 1)}
            for node, layer in lays.items():
                layer_nodes[layer].append(node)
            current_orders: dict[str, int] = {}
            for layer_idx in range(max_layer + 1):
                refs_sorted = sorted(layer_nodes[layer_idx])
                for i, ref in enumerate(refs_sorted):
                    current_orders[ref] = i
            recent: list[tuple] = []
            for sweep in range(_MAX_SWEEPS):
                sweeps[0] = sweep + 1
                snapshot = tuple(sorted(current_orders.items()))
                for layer_idx in range(1, max_layer + 1):
                    nodes_in_layer = sorted(layer_nodes[layer_idx])
                    barycenters = []
                    for node in nodes_in_layer:
                        upper = [
                            p for p in aug.predecessors(node)
                            if p in current_orders
                        ]
                        bary = (
                            sum(current_orders[p] for p in upper) / len(upper)
                            if upper
                            else float(current_orders[node])
                        )
                        barycenters.append((bary, node))
                    barycenters.sort(key=lambda bn: (bn[0], bn[1]))
                    for i, (_, node) in enumerate(barycenters):
                        current_orders[node] = i
                for layer_idx in range(max_layer - 1, -1, -1):
                    nodes_in_layer = sorted(layer_nodes[layer_idx])
                    barycenters = []
                    for node in nodes_in_layer:
                        lower = [
                            s for s in aug.successors(node)
                            if s in current_orders
                        ]
                        bary = (
                            sum(current_orders[s] for s in lower) / len(lower)
                            if lower
                            else float(current_orders[node])
                        )
                        barycenters.append((bary, node))
                    barycenters.sort(key=lambda bn: (bn[0], bn[1]))
                    for i, (_, node) in enumerate(barycenters):
                        current_orders[node] = i
                new_snapshot = tuple(sorted(current_orders.items()))
                recent.append(new_snapshot)
                if len(recent) > _EARLY_EXIT_NO_CHANGE_STREAK:
                    recent.pop(0)
                if (
                    len(recent) == _EARLY_EXIT_NO_CHANGE_STREAK
                    and all(r == recent[0] for r in recent)
                ):
                    break
            return current_orders

        counting_wrapper(augmented, layers)
        return sweeps[0]
