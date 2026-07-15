"""Reward scoring for PCB board reasoning chains.

Scores board analysis chains on format, quality, and coordinate accuracy.
Adapted from the maze reward scorer but works with RealBoardSample data
and BoardReasoningChain types.

Usage:
    from volta.training.board_reward import score_board_chain

    reward = score_board_chain(chain, sample)
    print(f"Total reward: {reward.total_reward:.2f}")
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from volta.training.board_chains import BoardReasoningChain
from volta.training.real_dataset import RealBoardSample


@dataclass(frozen=True)
class BoardRewardSignal:
    """Per-step reward components for a board chain."""

    step_index: int
    format_score: float
    quality_score: float
    accuracy_score: float
    total: float


@dataclass(frozen=True)
class BoardChainReward:
    """Aggregate reward for a complete board reasoning chain."""

    chain_id: int
    sample_id: int
    step_rewards: tuple[BoardRewardSignal, ...]
    total_reward: float
    reward_density: float


_COORD_RE = re.compile(r"<point\s+[\d.]+,\s*[\d.]+>")

_REASONING_TERMS = {
    "component", "net", "layer", "routing", "trace", "via",
    "footprint", "pad", "clearance", "impedance", "differential",
    "placement", "connectivity", "density", "centroid", "spread",
    "fanout", "complexity", "assessment", "analysis", "design",
    "connections", "buried", "region",
}


def _score_format(step: dict) -> float:
    """Score format correctness of a board analysis step."""
    score = 0.0
    text = step.get("text", "")

    # Coordinate reference present
    if _COORD_RE.search(text):
        score += 0.5

    # Step type valid
    step_type = step.get("step_type", "")
    valid_types = {
        "observation", "component_analysis", "connectivity_analysis",
        "spatial_analysis", "routing_assessment",
    }
    if step_type in valid_types:
        score += 0.25

    # Content non-empty and substantial
    if len(text) > 15:
        score += 0.25

    return min(1.0, score)


def _score_quality(step: dict) -> float:
    """Score reasoning quality of a board analysis step."""
    text = step.get("text", "").lower()
    score = 0.0

    # Technical reasoning terms
    term_count = sum(1 for term in _REASONING_TERMS if term in text)
    if term_count >= 3:
        score += 0.4
    elif term_count >= 1:
        score += 0.2

    # Coordinate specificity
    coord_matches = _COORD_RE.findall(text)
    if coord_matches:
        score += 0.3
        if len(coord_matches) >= 2:
            score += 0.1

    # Step specificity
    if len(text) > 40:
        score += 0.2

    return min(1.0, score)


def _score_accuracy(step: dict, sample: RealBoardSample) -> float:
    """Score coordinate accuracy against board ground truth.

    For board chains, accuracy means coordinates are within the board's
    spatial extent and reference actual component positions.
    """
    coords = step.get("coordinates", [])
    if not coords:
        # Steps without coordinates get neutral score
        return 0.5

    # Extract valid coordinates from the sample's graph
    import json
    graph_data = json.loads(sample.graph_json)
    valid_coords: list[tuple[float, float]] = []
    for node in graph_data.get("nodes", []):
        if "x_mm" in node and "y_mm" in node:
            valid_coords.append((node["x_mm"], node["y_mm"]))

    if not valid_coords:
        # No spatial data in sample — can't verify coordinates
        return 0.5

    # Check how many referenced coords are close to actual component positions
    correct = 0
    tolerance = 5.0  # mm tolerance for PCB coordinate matching
    for coord in coords:
        if isinstance(coord, (list, tuple)) and len(coord) == 2:
            cx, cy = float(coord[0]), float(coord[1])
            for vx, vy in valid_coords:
                dist = math.sqrt((cx - vx) ** 2 + (cy - vy) ** 2)
                if dist <= tolerance:
                    correct += 1
                    break

    return min(1.0, correct / len(coords)) if coords else 0.5


def score_board_chain(
    chain: BoardReasoningChain,
    sample: RealBoardSample,
) -> BoardChainReward:
    """Score a board reasoning chain against a real PCB sample.

    Args:
        chain: The board reasoning chain to score.
        sample: Ground-truth RealBoardSample.

    Returns:
        BoardChainReward with per-step signals and aggregate scores.
    """
    steps = chain.steps
    step_rewards: list[BoardRewardSignal] = []

    for i, step in enumerate(steps):
        fmt = _score_format(step)
        qual = _score_quality(step)
        acc = _score_accuracy(step, sample)

        total = 0.2 * fmt + 0.3 * qual + 0.5 * acc
        total = max(-1.0, min(1.0, total))

        step_rewards.append(BoardRewardSignal(
            step_index=i,
            format_score=round(fmt, 4),
            quality_score=round(qual, 4),
            accuracy_score=round(acc, 4),
            total=round(total, 4),
        ))

    total_reward = sum(sr.total for sr in step_rewards)
    reward_density = total_reward / len(step_rewards) if step_rewards else 0.0

    return BoardChainReward(
        chain_id=chain.sample_id,
        sample_id=sample.sample_id,
        step_rewards=tuple(step_rewards),
        total_reward=round(total_reward, 4),
        reward_density=round(reward_density, 4),
    )
