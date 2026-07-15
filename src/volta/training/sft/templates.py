"""Task-specific prompt templates for PCB reasoning SFT.

Defines system prompts and task templates for converting maze reasoning
chains into instruction-following (ChatML) format.

Usage:
    from volta.training.sft.templates import (
        SYSTEM_PROMPT_SPATIAL,
        TASK_TEMPLATES,
        get_template_for_chain,
    )

    template = get_template_for_chain(chain_dict)
    prompt = template.format(context="Board is 30x30mm with 15 obstacles.")
"""

from __future__ import annotations

SYSTEM_PROMPT_SPATIAL: str = (
    "You are a PCB spatial reasoning assistant. "
    "Analyze board layouts using coordinate-grounded reasoning. "
    "Reference precise positions using <point x,y> format. "
    "Provide structured analysis with observation, spatial context, "
    "coordinate references, diagnosis, and routing recommendations."
)

TASK_TEMPLATES: dict[str, str] = {
    "spatial_reasoning": (
        "Perform a spatial analysis of this PCB routing problem:\n{context}"
    ),
    "routing": (
        "Analyze the routing path between two points on this PCB:\n{context}"
    ),
    "placement": (
        "Determine optimal component placement on this PCB layout:\n{context}"
    ),
    "clearance": (
        "Check clearance and DRC compliance for this PCB design:\n{context}"
    ),
}


def get_template_for_chain(chain_dict: dict) -> str:
    """Return the appropriate task template key based on chain metadata.

    Selects a template based on task type indicators in the chain metadata.
    Falls back to 'spatial_reasoning' for unrecognized or missing task types.

    Args:
        chain_dict: Chain dictionary with optional 'task_type' or 'task' field.

    Returns:
        Template key string matching TASK_TEMPLATES.
    """
    task = chain_dict.get("task_type", "") or chain_dict.get("task", "")
    task_lower = task.lower()

    if "route" in task_lower or "trace" in task_lower:
        return "routing"
    elif "place" in task_lower or "layout" in task_lower:
        return "placement"
    elif "clearance" in task_lower or "drc" in task_lower:
        return "clearance"
    return "spatial_reasoning"
