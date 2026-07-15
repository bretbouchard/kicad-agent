"""Phase 106: Prompt builder for the model-based blocker diagnostician.

Uses the EXACT user message format from generate_diagnostic_training_data.py
(the model was trained on this string — deviation hurts accuracy).
"""

from __future__ import annotations

from volta.routing.pathfinder import RouteFailure

_SYSTEM_PROMPT = (
    "You are a PCB design expert specializing in routing failure analysis. "
    "Given a routing failure (net name, dead-end point, target point), "
    "identify what is blocking the net's path and classify the blocker. "
    "Output the blocker type, classification, causal status, recommended "
    "action, and removal benefit."
)


def build_diagnostician_prompt(
    failure: RouteFailure,
    board_bounds: tuple[float, float, float, float],
) -> str:
    """Build the user prompt for blocker diagnosis.

    This MUST match the training format from generate_diagnostic_training_data.py
    exactly — the model was trained on this string.
    """
    return (
        f"PCB routing failure analysis.\n\n"
        f"Board bounds: ({board_bounds[0]:.1f}, {board_bounds[1]:.1f}) to "
        f"({board_bounds[2]:.1f}, {board_bounds[3]:.1f}) mm\n"
        f"Net '{failure.net_name}' failed to route.\n"
        f"Source: ({failure.source_point[0]:.2f}, {failure.source_point[1]:.2f})\n"
        f"Target: ({failure.target_point[0]:.2f}, {failure.target_point[1]:.2f})\n"
        f"Router dead-end: ({failure.dead_end_point[0]:.2f}, "
        f"{failure.dead_end_point[1]:.2f})\n"
        f"Failure type: {failure.failure_type}\n"
        f"Reachable nodes from source: {failure.reachable_count}\n\n"
        f"What is blocking this net's path? Classify the blocker and "
        f"recommend an action."
    )


def get_system_prompt() -> str:
    """Return the system prompt for the diagnostician."""
    return _SYSTEM_PROMPT
