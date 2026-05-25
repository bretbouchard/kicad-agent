"""Cold-start reasoning chain synthesis from real PCB board graphs.

Generates coordinate-grounded reasoning chains from RealBoardSample data.
Each chain describes component placement, net connectivity, and spatial
analysis with coordinate references in `<point x,y>` format.

Mirrors the MazeReasoningChain pattern but adapted for PCB graph data.

Usage:
    from kicad_agent.training.board_chains import synthesize_board_chain

    chain = synthesize_board_chain(sample)
    print(chain.chain_text)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from kicad_agent.training.real_dataset import RealBoardSample


@dataclass(frozen=True)
class BoardReasoningChain:
    """A coordinate-grounded reasoning chain for a real PCB board.

    Attributes:
        sample_id: Links back to the RealBoardSample.
        difficulty: Inherited from sample ("easy"/"medium"/"hard").
        chain_text: Full reasoning chain as natural language text.
        steps: Structured steps with coordinates and step types.
        coordinates_referenced: All coordinates mentioned in the chain.
        is_correct: Always True for correctly parsed boards.
    """

    sample_id: int
    difficulty: str
    chain_text: str
    steps: tuple[dict, ...]
    coordinates_referenced: tuple[tuple[float, float], ...]
    is_correct: bool


def _point_str(x: float, y: float) -> str:
    """Format a coordinate as <point x,y>."""
    return f"<point {x:.1f},{y:.1f}>"


def _extract_graph_data(sample: RealBoardSample) -> dict:
    """Parse the graph_json field into a usable dict."""
    return json.loads(sample.graph_json)


def _get_component_nodes(graph_data: dict) -> list[dict]:
    """Extract component nodes from graph node-link-data."""
    nodes = []
    for node in graph_data.get("nodes", []):
        if node.get("node_type") == "component":
            nodes.append(node)
    return nodes


def _get_net_edges(graph_data: dict) -> list[dict]:
    """Extract net edges from graph node-link-data."""
    return graph_data.get("edges", [])


def _get_top_components(components: list[dict], n: int = 8) -> list[dict]:
    """Get top N components by connectivity (most edges).

    Falls back to position-based ordering if no edges exist.
    """
    if not components:
        return []
    # Components with spatial data are more interesting
    with_coords = [c for c in components if "x_mm" in c and "y_mm" in c]
    without_coords = [c for c in components if "x_mm" not in c or "y_mm" not in c]

    # Sort by number of attributes as proxy for importance
    with_coords.sort(key=lambda c: len(c), reverse=True)
    return (with_coords + without_coords)[:n]


def _compute_cluster_info(components: list[dict]) -> dict:
    """Compute spatial cluster statistics from component positions."""
    xs = [c["x_mm"] for c in components if "x_mm" in c]
    ys = [c["y_mm"] for c in components if "y_mm" in c]

    if not xs or not ys:
        return {"has_spatial": False}

    # Compute centroid and spread
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    # Find clusters: group by quadrant relative to centroid
    q1 = [c for c in components if "x_mm" in c and c["x_mm"] >= cx and c["y_mm"] >= cy]
    q2 = [c for c in components if "x_mm" in c and c["x_mm"] < cx and c["y_mm"] >= cy]
    q3 = [c for c in components if "x_mm" in c and c["x_mm"] < cx and c["y_mm"] < cy]
    q4 = [c for c in components if "x_mm" in c and c["x_mm"] >= cx and c["y_mm"] < cy]

    return {
        "has_spatial": True,
        "centroid": (cx, cy),
        "spread_x": max(xs) - min(xs),
        "spread_y": max(ys) - min(ys),
        "quadrants": [len(q1), len(q2), len(q3), len(q4)],
    }


def synthesize_board_chain(sample: RealBoardSample) -> BoardReasoningChain:
    """Build a 5-step reasoning chain from a real PCB board sample.

    Steps:
      1. observation: Board overview (components, nets, layers, dimensions)
      2. component_analysis: Key component positions and properties
      3. connectivity_analysis: Net structure and routing requirements
      4. spatial_analysis: Component clustering and density
      5. routing_assessment: Routing complexity and recommendations

    Args:
        sample: RealBoardSample with graph and spatial data.

    Returns:
        BoardReasoningChain with 5 ordered steps.
    """
    graph_data = _extract_graph_data(sample)
    components = _get_component_nodes(graph_data)
    edges = _get_net_edges(graph_data)
    top_components = _get_top_components(components, n=8)
    cluster_info = _compute_cluster_info(components)

    all_coords: list[tuple[float, float]] = []

    # Step 1: Observation
    obs_text = (
        f"Board analysis: {sample.component_count} components across "
        f"{sample.net_count} nets on {sample.layer_count}-layer PCB."
    )
    if sample.board_width_mm > 0 and sample.board_height_mm > 0:
        obs_text += (
            f" Board dimensions: {sample.board_width_mm:.1f}mm x "
            f"{sample.board_height_mm:.1f}mm."
        )

    # Step 2: Component analysis with coordinates
    comp_lines = []
    for comp in top_components:
        ref = comp.get("id", comp.get("label", "?"))
        value = comp.get("value", "")
        if "x_mm" in comp and "y_mm" in comp:
            coord = (comp["x_mm"], comp["y_mm"])
            all_coords.append(coord)
            line = f"{ref}"
            if value:
                line += f" ({value})"
            line += f" at {_point_str(coord[0], coord[1])}"
            if "rotation_deg" in comp and comp["rotation_deg"] != 0:
                line += f" rotated {comp['rotation_deg']:.0f}deg"
            comp_lines.append(line)

    comp_text = f"Key components ({len(top_components)} of {sample.component_count}):"
    if comp_lines:
        comp_text += " " + "; ".join(comp_lines) + "."
    else:
        comp_text += " No spatial data available."

    # Step 3: Connectivity analysis
    # Count unique nets from edges
    nets_in_edges: set[str] = set()
    for edge in edges:
        net_name = edge.get("net", "")
        if net_name:
            nets_in_edges.add(net_name)

    conn_text = f"Connectivity: {len(nets_in_edges)} nets with {len(edges)} connections."
    # Describe high-fanout components
    fanout: dict[str, int] = {}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        for node_id in (src, tgt):
            fanout[node_id] = fanout.get(node_id, 0) + 1

    high_fanout = sorted(fanout.items(), key=lambda x: x[1], reverse=True)[:3]
    if high_fanout:
        ho_strs = [f"{ref} ({count} connections)" for ref, count in high_fanout]
        conn_text += f" Highest connectivity: {', '.join(ho_strs)}."

    # Step 4: Spatial analysis
    spatial_text = f"Spatial distribution: {sample.difficulty} complexity board."
    if cluster_info.get("has_spatial"):
        cx, cy = cluster_info["centroid"]
        all_coords.append((cx, cy))
        spatial_text += (
            f" Component centroid at {_point_str(cx, cy)}."
            f" Spread: {cluster_info['spread_x']:.1f}mm x {cluster_info['spread_y']:.1f}mm."
        )
        quads = cluster_info["quadrants"]
        max_q = max(quads)
        if max_q > 0:
            densest = ["Q1(top-right)", "Q2(top-left)", "Q3(bottom-left)", "Q4(bottom-right)"]
            densest_idx = quads.index(max_q)
            spatial_text += f" Densest region: {densest[densest_idx]} with {max_q} components."

    # Step 5: Routing assessment
    route_text = f"Routing assessment: {sample.component_count} components require {len(edges)} trace connections."
    if sample.layer_count > 2:
        route_text += f" Multi-layer design ({sample.layer_count} layers) enables buried vias."
    if sample.net_count > 20:
        route_text += " High net count suggests careful trace width and clearance planning needed."
    elif sample.net_count > 10:
        route_text += " Moderate complexity routing with standard design rules."

    chain_text = "\n".join([obs_text, comp_text, conn_text, spatial_text, route_text])

    steps = (
        {"step_type": "observation", "text": obs_text,
         "coordinates": [(c["x_mm"], c["y_mm"]) for c in top_components[:2] if "x_mm" in c]},
        {"step_type": "component_analysis", "text": comp_text,
         "coordinates": [(c["x_mm"], c["y_mm"]) for c in top_components if "x_mm" in c]},
        {"step_type": "connectivity_analysis", "text": conn_text, "coordinates": []},
        {"step_type": "spatial_analysis", "text": spatial_text,
         "coordinates": [cluster_info["centroid"]] if cluster_info.get("has_spatial") else []},
        {"step_type": "routing_assessment", "text": route_text,
         "coordinates": [(c["x_mm"], c["y_mm"]) for c in top_components[:3] if "x_mm" in c]},
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=chain_text,
        steps=steps,
        coordinates_referenced=tuple(all_coords),
        is_correct=True,
    )


def synthesize_corrupted_board_chain(
    sample: RealBoardSample,
    corruption_type: str = "random",
    rng_seed: int | None = None,
) -> BoardReasoningChain:
    """Build an intentionally imperfect chain for contrast training.

    Args:
        sample: RealBoardSample to generate a corrupted chain for.
        corruption_type: "wrong_coords", "vague_reasoning", "missing_steps", "random".
        rng_seed: Optional seed for deterministic corruption.

    Returns:
        BoardReasoningChain with introduced errors.
    """
    import random

    rng = random.Random(rng_seed)

    if corruption_type == "random":
        corruption_type = rng.choice(["wrong_coords", "vague_reasoning", "missing_steps"])

    if corruption_type == "wrong_coords":
        return _corrupt_wrong_coords(sample, rng)
    elif corruption_type == "missing_steps":
        return _corrupt_missing_steps(sample)
    else:
        return _corrupt_vague_reasoning(sample)


def _corrupt_wrong_coords(sample: RealBoardSample, rng) -> BoardReasoningChain:
    """Shift component coordinates by random offsets."""
    graph_data = _extract_graph_data(sample)
    components = _get_component_nodes(graph_data)

    obs_text = (
        f"Board analysis: {sample.component_count} components across "
        f"{sample.net_count} nets on {sample.layer_count}-layer PCB."
    )

    # Shift coordinates randomly
    fake_coords: list[tuple[float, float]] = []
    comp_lines = []
    for comp in components[:6]:
        if "x_mm" in comp and "y_mm" in comp:
            dx = rng.uniform(10.0, 30.0) * rng.choice([-1, 1])
            dy = rng.uniform(10.0, 30.0) * rng.choice([-1, 1])
            fx = max(0, comp["x_mm"] + dx)
            fy = max(0, comp["y_mm"] + dy)
            fake_coords.append((fx, fy))
            ref = comp.get("id", comp.get("label", "?"))
            comp_lines.append(f"{ref} at {_point_str(fx, fy)}")

    comp_text = f"Key components: {'; '.join(comp_lines)}." if comp_lines else "Components placed."

    spatial_text = f"Spatial distribution: components spread across board."
    route_text = f"Routing assessment: {len(fake_coords)} placement points identified."

    chain_text = "\n".join([obs_text, comp_text, spatial_text, route_text])
    steps = (
        {"step_type": "observation", "text": obs_text, "coordinates": []},
        {"step_type": "component_analysis", "text": comp_text, "coordinates": fake_coords},
        {"step_type": "spatial_analysis", "text": spatial_text, "coordinates": fake_coords[:2]},
        {"step_type": "routing_assessment", "text": route_text, "coordinates": []},
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=chain_text,
        steps=steps,
        coordinates_referenced=tuple(fake_coords),
        is_correct=False,
    )


def _corrupt_missing_steps(sample: RealBoardSample) -> BoardReasoningChain:
    """Omit key analysis steps."""
    obs_text = (
        f"Board has {sample.component_count} components and {sample.net_count} nets."
    )
    route_text = "Route all connections."

    chain_text = f"{obs_text}\n{route_text}"
    steps = (
        {"step_type": "observation", "text": obs_text, "coordinates": []},
        {"step_type": "routing_assessment", "text": route_text, "coordinates": []},
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=chain_text,
        steps=steps,
        coordinates_referenced=(),
        is_correct=False,
    )


def _corrupt_vague_reasoning(sample: RealBoardSample) -> BoardReasoningChain:
    """Replace specific analysis with vague statements, no coordinates."""
    obs_text = "There is a board with some electronic components."
    comp_text = "Various components are placed on the board."
    conn_text = "Components are connected together."
    spatial_text = "The layout seems reasonable."
    route_text = "Route all the traces between components."

    chain_text = "\n".join([obs_text, comp_text, conn_text, spatial_text, route_text])
    steps = (
        {"step_type": "observation", "text": obs_text, "coordinates": []},
        {"step_type": "component_analysis", "text": comp_text, "coordinates": []},
        {"step_type": "connectivity_analysis", "text": conn_text, "coordinates": []},
        {"step_type": "spatial_analysis", "text": spatial_text, "coordinates": []},
        {"step_type": "routing_assessment", "text": route_text, "coordinates": []},
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=chain_text,
        steps=steps,
        coordinates_referenced=(),
        is_correct=False,
    )
