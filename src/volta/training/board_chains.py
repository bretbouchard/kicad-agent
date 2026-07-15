"""Cold-start reasoning chain synthesis from real PCB board graphs.

Generates coordinate-grounded reasoning chains from RealBoardSample data.
Each chain describes component placement, net connectivity, and spatial
analysis with coordinate references in `<point x,y>` format.

Mirrors the MazeReasoningChain pattern but adapted for PCB graph data.

Usage:
    from volta.training.board_chains import synthesize_board_chain

    chain = synthesize_board_chain(sample)
    print(chain.chain_text)
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Sequence

from volta.training.real_dataset import RealBoardSample

logger = logging.getLogger(__name__)

# Coordinate format regex (shared with maze reward module)
_COORD_RE = re.compile(r"<point\s+[\d.]+,\s*[\d.]+>")

# Board-relevant reasoning terms
_REASONING_TERMS = {
    "component", "net", "layer", "routing", "trace", "via",
    "clearance", "impedance", "placement", "connectivity", "footprint",
    "fanout", "density", "cluster", "centroid", "spread", "quadrant",
    "buried", "through-hole", "smd", "pad", "pin", "signal", "power",
    "ground", "requires", "connections", "assessment",
}


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
    hard_negative_weight: float = 0.4,
) -> BoardReasoningChain:
    """Build an intentionally imperfect chain for contrast training.

    Args:
        sample: RealBoardSample to generate a corrupted chain for.
        corruption_type: Corruption type name, or "random" for weighted selection.
        rng_seed: Optional seed for deterministic corruption.
        hard_negative_weight: Probability of hard negative when random (default 0.4).

    Returns:
        BoardReasoningChain with introduced errors.
    """
    import random

    rng = random.Random(rng_seed)

    if corruption_type == "random":
        if rng.random() < hard_negative_weight:
            corruption_type = rng.choice(_HARD_CORRUPTIONS)
        else:
            corruption_type = rng.choice(_EASY_CORRUPTIONS)

    if corruption_type == "wrong_coords":
        return _corrupt_wrong_coords(sample, rng)
    elif corruption_type == "missing_steps":
        return _corrupt_missing_steps(sample)
    elif corruption_type == "subtle_coord_drift":
        return _corrupt_subtle_coord_drift(sample, rng)
    elif corruption_type == "swapped_components":
        return _corrupt_swapped_components(sample, rng)
    elif corruption_type == "wrong_net_count":
        return _corrupt_wrong_net_count(sample, rng)
    elif corruption_type == "plausible_wrong_analysis":
        return _corrupt_plausible_wrong_analysis(sample, rng)
    elif corruption_type == "layer_confusion":
        return _corrupt_layer_confusion(sample, rng)
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


def _corrupt_subtle_coord_drift(
    sample: RealBoardSample, rng,
) -> BoardReasoningChain:
    """Shift coordinates 1-3mm toward nearest neighbor's position.

    Produces a full correct chain then nudges each coordinate toward
    an adjacent component. The drift is small enough to look plausible
    but large enough to fail the 5mm accuracy tolerance.
    """
    correct = synthesize_board_chain(sample)
    graph_data = _extract_graph_data(sample)
    components = _get_component_nodes(graph_data)

    # Collect all valid component positions for neighbor lookup
    valid_positions = [
        (c["x_mm"], c["y_mm"]) for c in components
        if "x_mm" in c and "y_mm" in c
    ]

    # Build coordinate shift map
    coord_map: dict[tuple[float, float], tuple[float, float]] = {}
    for cx, cy in valid_positions:
        # Find nearest *different* position
        best_dist = float("inf")
        best_pos = None
        for ox, oy in valid_positions:
            if ox == cx and oy == cy:
                continue
            d = math.sqrt((cx - ox) ** 2 + (cy - oy) ** 2)
            if d < best_dist:
                best_dist = d
                best_pos = (ox, oy)

        if best_pos and best_dist < 20.0:
            # Drift toward neighbor: 40-70% of the way
            ratio = rng.uniform(0.4, 0.7)
            nx = cx + (best_pos[0] - cx) * ratio
            ny = cy + (best_pos[1] - cy) * ratio
            coord_map[(cx, cy)] = (nx, ny)
        else:
            # Small random drift fallback
            dx = rng.uniform(1.5, 3.0) * rng.choice([-1, 1])
            dy = rng.uniform(1.5, 3.0) * rng.choice([-1, 1])
            coord_map[(cx, cy)] = (max(0, cx + dx), max(0, cy + dy))

    # Apply shifts to chain text
    shifted_text = correct.chain_text
    for old, new in coord_map.items():
        shifted_text = shifted_text.replace(
            _point_str(old[0], old[1]),
            _point_str(new[0], new[1]),
        )

    # Update step coordinates
    shifted_steps = []
    for step in correct.steps:
        new_coords = []
        for coord in step.get("coordinates", []):
            key = (float(coord[0]), float(coord[1]))
            if key in coord_map:
                new_coords.append(coord_map[key])
            else:
                new_coords.append(coord)
        shifted_steps.append({**step, "coordinates": new_coords})

    shifted_all = tuple(
        coord_map.get(c, c) for c in correct.coordinates_referenced
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=shifted_text,
        steps=tuple(shifted_steps),
        coordinates_referenced=shifted_all,
        is_correct=False,
    )


def _corrupt_swapped_components(
    sample: RealBoardSample, rng,
) -> BoardReasoningChain:
    """Swap coordinates of two components. Chain looks perfect otherwise."""
    correct = synthesize_board_chain(sample)
    graph_data = _extract_graph_data(sample)
    components = _get_component_nodes(graph_data)

    with_coords = [c for c in components if "x_mm" in c and "y_mm" in c]
    if len(with_coords) < 2:
        # Fallback: not enough components to swap
        return _corrupt_subtle_coord_drift(sample, rng)

    # Pick two random components and swap positions
    a, b = rng.sample(with_coords, 2)
    a_pos = (a["x_mm"], a["y_mm"])
    b_pos = (b["x_mm"], b["y_mm"])

    swapped_text = correct.chain_text
    # Use temp markers to avoid double-replace
    temp_a = _point_str(-999.0, -998.0)
    temp_b = _point_str(-998.0, -999.0)
    swapped_text = swapped_text.replace(_point_str(a_pos[0], a_pos[1]), temp_a)
    swapped_text = swapped_text.replace(_point_str(b_pos[0], b_pos[1]), temp_b)
    swapped_text = swapped_text.replace(temp_a, _point_str(b_pos[0], b_pos[1]))
    swapped_text = swapped_text.replace(temp_b, _point_str(a_pos[0], a_pos[1]))

    # Update step coordinates
    swapped_steps = []
    for step in correct.steps:
        new_coords = []
        for coord in step.get("coordinates", []):
            c = (float(coord[0]), float(coord[1]))
            if c == a_pos:
                new_coords.append(b_pos)
            elif c == b_pos:
                new_coords.append(a_pos)
            else:
                new_coords.append(coord)
        swapped_steps.append({**step, "coordinates": new_coords})

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=swapped_text,
        steps=tuple(swapped_steps),
        coordinates_referenced=correct.coordinates_referenced,
        is_correct=False,
    )


def _corrupt_wrong_net_count(
    sample: RealBoardSample, rng,
) -> BoardReasoningChain:
    """Full correct chain but perturb net/connection counts."""
    correct = synthesize_board_chain(sample)

    # Perturb counts by ±10-25%
    net_factor = rng.uniform(0.75, 1.25)
    edge_factor = rng.uniform(0.80, 1.20)
    fake_nets = max(1, round(sample.net_count * net_factor))

    graph_data = _extract_graph_data(sample)
    edges = _get_net_edges(graph_data)
    fake_edges = max(1, round(len(edges) * edge_factor))

    text = correct.chain_text
    # Replace net count claims
    text = re.sub(
        rf"{sample.net_count}\s+nets",
        f"{fake_nets} nets",
        text,
    )
    text = re.sub(
        rf"{sample.net_count}\s+net",
        f"{fake_nets} net",
        text,
    )
    # Replace connection count claims
    text = re.sub(
        rf"{len(edges)}\s+connections",
        f"{fake_edges} connections",
        text,
    )
    text = re.sub(
        rf"{len(edges)}\s+trace connections",
        f"{fake_edges} trace connections",
        text,
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=text,
        steps=correct.steps,
        coordinates_referenced=correct.coordinates_referenced,
        is_correct=False,
    )


def _corrupt_plausible_wrong_analysis(
    sample: RealBoardSample, rng,
) -> BoardReasoningChain:
    """Correct coordinates but wrong analytical conclusions."""
    correct = synthesize_board_chain(sample)

    text = correct.chain_text

    # Swap densest quadrant: Q1<->Q3, Q2<->Q4
    text = text.replace("Densest region: Q1(top-right)", "Densest region: Q3(bottom-left)")
    text = text.replace("Densest region: Q2(top-left)", "Densest region: Q4(bottom-right)")
    text = text.replace("Densest region: Q3(bottom-left)", "Densest region: Q1(top-right)")
    text = text.replace("Densest region: Q4(bottom-right)", "Densest region: Q2(top-left)")

    # Reverse complexity assessment
    text = text.replace(
        "High net count suggests careful trace width and clearance planning needed.",
        "Simple routing with minimal design constraints.",
    )
    text = text.replace(
        "Moderate complexity routing with standard design rules.",
        "Complex routing requiring careful impedance management.",
    )

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=text,
        steps=correct.steps,
        coordinates_referenced=correct.coordinates_referenced,
        is_correct=False,
    )


def _corrupt_layer_confusion(
    sample: RealBoardSample, rng,
) -> BoardReasoningChain:
    """Correct chain but wrong layer count claim."""
    correct = synthesize_board_chain(sample)
    real_layers = sample.layer_count

    # Pick plausible wrong layer count
    layer_map = {1: 2, 2: 4, 4: rng.choice([2, 6]), 6: rng.choice([4, 8]),
                 8: rng.choice([6, 10]), 10: 8}
    fake_layers = layer_map.get(real_layers, real_layers + rng.choice([-2, 2]))
    fake_layers = max(1, fake_layers)

    text = correct.chain_text
    text = text.replace(
        f"{real_layers}-layer PCB",
        f"{fake_layers}-layer PCB",
    )
    text = text.replace(
        f"{real_layers} layers",
        f"{fake_layers} layers",
    )
    # Adjust multi-layer routing claims
    if fake_layers > 2 and "buried vias" not in text:
        text = text.replace(
            "Routing assessment:",
            "Routing assessment: Multi-layer design enables buried vias.",
        )
    elif fake_layers <= 2:
        text = text.replace(" enables buried vias.", ".")

    return BoardReasoningChain(
        sample_id=sample.sample_id,
        difficulty=sample.difficulty,
        chain_text=text,
        steps=correct.steps,
        coordinates_referenced=correct.coordinates_referenced,
        is_correct=False,
    )


# Corruption type pools
_EASY_CORRUPTIONS = ["wrong_coords", "missing_steps", "vague_reasoning"]
_HARD_CORRUPTIONS = [
    "subtle_coord_drift", "swapped_components", "wrong_net_count",
    "plausible_wrong_analysis", "layer_confusion",
]


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def synthesize_board_chains(
    samples: Sequence[RealBoardSample],
    hard_negative_weight: float = 0.4,
) -> tuple[list[str], list[tuple[float, float, float]]]:
    """Synthesize chains and compute ground-truth labels for a batch of samples.

    For each sample, generates a correct chain and a corrupted variant,
    then computes (format, quality, accuracy) labels from chain features.

    Args:
        samples: RealBoardSample objects to process.
        hard_negative_weight: Probability of selecting a hard negative
            corruption (0.0-1.0). Default 0.4 = 40% hard, 60% easy.

    Returns:
        (texts, labels) where texts is a list of chain_text strings
        and labels is a list of (format, quality, accuracy) tuples.
    """
    import random

    rng = random.Random(42)
    texts: list[str] = []
    labels: list[tuple[float, float, float]] = []

    for sample in samples:
        # Correct chain
        correct = synthesize_board_chain(sample)
        texts.append(correct.chain_text)
        c_labels = _compute_chain_labels(correct, sample)
        labels.append(c_labels)

        # Corrupted chain — weighted easy/hard selection
        if rng.random() < hard_negative_weight:
            corruption = rng.choice(_HARD_CORRUPTIONS)
        else:
            corruption = rng.choice(_EASY_CORRUPTIONS)
        corrupted = synthesize_corrupted_board_chain(sample, corruption)
        texts.append(corrupted.chain_text)
        x_labels = _compute_chain_labels(corrupted, sample)
        labels.append(x_labels)

    return texts, labels


def _check_factual_accuracy(
    text: str,
    sample: RealBoardSample,
    base_acc: float,
) -> float:
    """Penalize factual errors in chain text (wrong counts, wrong layers)."""
    acc = base_acc

    # Check component count claims
    comp_match = re.search(r"(\d+)\s+components?", text)
    if comp_match and int(comp_match.group(1)) != sample.component_count:
        acc *= 0.5

    # Check net count claims
    net_match = re.search(r"(\d+)\s+nets?", text)
    if net_match and int(net_match.group(1)) != sample.net_count:
        acc *= 0.5

    # Check layer count claims
    layer_match = re.search(r"(\d+)-layer", text)
    if layer_match and int(layer_match.group(1)) != sample.layer_count:
        acc *= 0.5
    layer_match2 = re.search(r"(\d+)\s+layers", text)
    if layer_match2 and int(layer_match2.group(1)) != sample.layer_count:
        acc *= 0.5

    return max(0.0, acc)


def _compute_chain_labels(
    chain: BoardReasoningChain,
    sample: RealBoardSample,
) -> tuple[float, float, float]:
    """Compute ground-truth (format, quality, accuracy) labels for a chain.

    These labels are what the reward model learns to predict.

    Args:
        chain: BoardReasoningChain to score.
        sample: Source RealBoardSample for ground-truth reference.

    Returns:
        (format_score, quality_score, accuracy_score) tuple.
    """
    n_steps = len(chain.steps)
    fmt_scores = []
    qual_scores = []
    acc_scores = []

    for step in chain.steps:
        text = step.get("text", "")

        # Format: coordinate refs + step structure
        fmt = 0.0
        if _COORD_RE.search(text):
            fmt += 0.5
        if step.get("step_type") in {
            "observation", "component_analysis", "connectivity_analysis",
            "spatial_analysis", "routing_assessment",
        }:
            fmt += 0.25
        if len(text) > 20:
            fmt += 0.25
        fmt_scores.append(min(1.0, fmt))

        # Quality: reasoning terms + specificity
        qual = 0.0
        text_lower = text.lower()
        term_count = sum(1 for term in _REASONING_TERMS if term in text_lower)
        if term_count >= 3:
            qual += 0.4
        elif term_count >= 1:
            qual += 0.2
        coord_count = len(_COORD_RE.findall(text))
        if coord_count >= 2:
            qual += 0.4
        elif coord_count >= 1:
            qual += 0.2
        if len(text) > 50:
            qual += 0.2
        qual_scores.append(min(1.0, qual))

        # Accuracy: coordinates match ground truth graph data
        coords = step.get("coordinates", [])
        if not coords:
            acc = 0.5  # neutral for non-spatial steps
            # Factual accuracy: check claimed counts match reality
            if step.get("step_type") in ("observation", "connectivity_analysis"):
                acc = _check_factual_accuracy(text, sample, acc)
            acc_scores.append(acc)
        else:
            # Check referenced coords against graph data
            graph_data = _extract_graph_data(sample)
            valid_coords = []
            for node in graph_data.get("nodes", []):
                if "x_mm" in node and "y_mm" in node:
                    valid_coords.append((node["x_mm"], node["y_mm"]))

            if not valid_coords:
                acc = 0.5
            else:
                coord_correct = 0
                for coord in coords:
                    if isinstance(coord, (list, tuple)) and len(coord) == 2:
                        cx, cy = float(coord[0]), float(coord[1])
                        for vx, vy in valid_coords:
                            dist = math.sqrt((cx - vx) ** 2 + (cy - vy) ** 2)
                            if dist <= 5.0:  # 5mm tolerance for board-scale
                                coord_correct += 1
                                break
                acc = min(1.0, coord_correct / max(len(coords), 1))

            # Also check factual accuracy on spatial/routing steps
            if step.get("step_type") in ("spatial_analysis", "routing_assessment"):
                acc = _check_factual_accuracy(text, sample, acc)

            acc_scores.append(acc)

    # Average across steps
    n = max(n_steps, 1)
    return (
        round(sum(fmt_scores) / n, 4),
        round(sum(qual_scores) / n, 4),
        round(sum(acc_scores) / n, 4),
    )
