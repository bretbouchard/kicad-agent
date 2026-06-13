"""Gate handlers -- dispatch gate check and status operations.

Handlers receive (op, ir, file_path) and return a result dict.
No Transaction wrapping, no serialization, no file writes.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from kicad_agent.validation.gate_types import DesignStage

logger = logging.getLogger(__name__)

_GATE_HANDLERS: dict[str, Callable] = {}


def register_gate_handler(op_type: str) -> Callable:
    """Decorator to register a gate operation handler."""
    def decorator(fn: Callable) -> Callable:
        _GATE_HANDLERS[op_type] = fn
        return fn
    return decorator


def get_gate_handler(op_type: str) -> Callable | None:
    """Look up a registered gate handler."""
    return _GATE_HANDLERS.get(op_type)


def list_gate_handlers() -> dict[str, Callable]:
    """Return all registered gate handlers."""
    return dict(_GATE_HANDLERS)


@register_gate_handler("run_gate_check")
def handle_run_gate_check(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Run a named gate check via GateRunner.

    Dispatches to the GateRunner singleton. If the gate references
    pre_pcb_schematic_gate, it delegates to the existing schematic
    validation pipeline.
    """
    from kicad_agent.validation.gate_runner import get_gate_runner

    runner = get_gate_runner()
    gate_name = op.gate_name
    context: dict[str, Any] = {
        "sch_path": file_path,
        "project_dir": op.project_dir,
    }

    gate_def = runner.get_gate(gate_name)
    if gate_def is None:
        return {
            "pass": False,
            "gate": gate_name,
            "ready_for_pcb": False,
            "blockers": [f"Gate '{gate_name}' is not registered"],
            "warnings": [],
            "recommendations": [f"Register gate '{gate_name}' or use a known gate name"],
        }

    result = runner.run_gate(gate_name, context)
    return result.to_dict()


@register_gate_handler("gate_status")
def handle_gate_status(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Return current design stage and all registered gate states.

    Returns a structured dict with:
    - current_stage: Current DesignStage (best guess from available files)
    - registered_gates: List of gate names and their stage transitions
    - last_results: Dict of gate_name -> GateResult for gates that have run
    """
    from kicad_agent.validation.gate_runner import get_gate_runner
    from kicad_agent.validation.gate_types import DesignStage  # noqa: F811

    runner = get_gate_runner()
    gates = runner.list_gates()

    # Determine current stage from available project files
    project_dir = Path(op.project_dir) if op.project_dir else file_path.parent
    current_stage = _detect_design_stage(project_dir)

    return {
        "current_stage": current_stage.value,
        "registered_gates": [
            {
                "name": g.name,
                "from_stage": g.from_stage.value,
                "to_stage": g.to_stage.value,
                "block_on_fail": g.block_on_fail,
            }
            for g in gates
        ],
        "next_actions": _suggest_next_actions(current_stage, gates),
    }


def _detect_design_stage(project_dir: Path) -> DesignStage:
    """Detect current design stage from project files."""
    has_sch = any(project_dir.glob("*.kicad_sch"))
    has_pcb = any(project_dir.glob("*.kicad_pcb"))
    has_gerbers = project_dir.is_dir() and bool(
        list(project_dir.glob("gerbers/**/*.gtl")) or list(project_dir.glob("gerbers/**/*.gbr"))
    )

    if has_gerbers:
        return DesignStage.MANUFACTURING
    if has_pcb:
        # Rough heuristic: if PCB exists, assume at least placement
        return DesignStage.ROUTING
    if has_sch:
        return DesignStage.SCHEMATIC
    return DesignStage.SCHEMATIC


def _suggest_next_actions(
    current_stage: DesignStage,
    gates: list[Any],
) -> list[str]:
    """Suggest next actions based on current stage and available gates."""
    actions: list[str] = []
    stage_gate_map: dict[str, str] = {}
    for g in gates:
        stage_gate_map[g.from_stage.value] = g.name

    if current_stage == DesignStage.SCHEMATIC:
        if "schematic" in stage_gate_map:
            actions.append(f"Run gate '{stage_gate_map['schematic']}' to validate schematic")
        actions.append("Ensure ERC passes before proceeding to PCB setup")
    elif current_stage == DesignStage.PCB_SETUP:
        if "pcb_setup" in stage_gate_map:
            actions.append(f"Run gate '{stage_gate_map['pcb_setup']}' to validate setup")
        actions.append("Define constraints before placement")
    elif current_stage == DesignStage.PLACEMENT:
        actions.append("Run placement readiness gate before routing")
    elif current_stage == DesignStage.ROUTING:
        actions.append("Run DRC before manufacturing export")
    elif current_stage == DesignStage.MANUFACTURING:
        actions.append("Manufacturing stage — verify exports are complete")

    if not actions:
        actions.append("No specific actions suggested for current stage")

    return actions
