"""Workflow runner (WORKFLOW-01, WORKFLOW-02).

Executes named workflows on PCB files. Built-in ``route_and_fill``
delegates to GapFillEngine. Generic workflows iterate a
WorkflowTemplate's steps via execute_batch.

Usage:
    from kicad_agent.ops.workflow_runner import WorkflowRunner

    runner = WorkflowRunner()
    result = runner.run("route_and_fill", "board.kicad_pcb")
    print(result.to_markdown())
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from kicad_agent.config import AgentConfig, load_config

if TYPE_CHECKING:
    from kicad_agent.analysis.gap_fill_engine import GapFillResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable result of a workflow execution."""

    success: bool
    workflow_name: str
    steps_completed: int = 0
    total_steps: int = 0
    gap_fill_result: GapFillResult | None = None
    batch_result: dict[str, Any] | None = None
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        result: dict[str, Any] = {
            "success": self.success,
            "workflow_name": self.workflow_name,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
        }
        if self.gap_fill_result is not None:
            result["gap_fill"] = self.gap_fill_result.to_json()
        if self.batch_result is not None:
            result["batch"] = self.batch_result
        if self.errors:
            result["errors"] = list(self.errors)
        return result

    def to_markdown(self) -> str:
        """Human-readable markdown report."""
        status = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"# Workflow: {self.workflow_name}",
            f"**Status:** {status}",
            f"**Steps:** {self.steps_completed}/{self.total_steps}",
        ]
        if self.gap_fill_result is not None:
            lines.append("")
            lines.append("## Gap Fill Results")
            lines.append(self.gap_fill_result.to_markdown())
        if self.batch_result is not None:
            lines.append("")
            lines.append("## Batch Results")
            lines.append(f"- Success: {self.batch_result.get('success', False)}")
            lines.append(f"- Operations: {self.batch_result.get('total', '?')}")
        if self.errors:
            lines.append("")
            lines.append("## Errors")
            for err in self.errors:
                lines.append(f"- {err}")
        return "\n".join(lines)


class WorkflowRunner:
    """Execute named workflows on PCB files.

    Args:
        config: Agent configuration (routing params, model settings).
            If None, config is auto-discovered from the PCB's project dir.
    """

    _BUILTIN_WORKFLOWS = frozenset({"route_and_fill"})

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig()

    def run(
        self,
        workflow_name: str,
        pcb_path: str | Path,
        **overrides: Any,
    ) -> WorkflowResult:
        """Execute a workflow by name.

        Built-in ``route_and_fill`` delegates to GapFillEngine.
        Other names are looked up in WorkflowTemplate registry.

        Args:
            workflow_name: Name of the workflow to run.
            pcb_path: Path to the PCB file.
            **overrides: Override config values (max_iterations, use_ai, etc.)

        Returns:
            WorkflowResult with success status and details.
        """
        pcb = Path(pcb_path)

        # Auto-discover config from project dir if not explicitly set
        if self._config == AgentConfig():
            self._config = load_config(pcb.parent)

        if not pcb.exists():
            return WorkflowResult(
                success=False,
                workflow_name=workflow_name,
                errors=(f"File not found: {pcb}",),
            )

        if workflow_name in self._BUILTIN_WORKFLOWS:
            return self._run_builtin(workflow_name, pcb, **overrides)

        return self._run_template(workflow_name, pcb, **overrides)

    def run_route_and_fill(
        self,
        pcb_path: str | Path,
        **overrides: Any,
    ) -> WorkflowResult:
        """Convenience method for the route-and-fill workflow.

        Args:
            pcb_path: Path to the PCB file.
            **overrides: Override config values.

        Returns:
            WorkflowResult with gap-fill details.
        """
        return self.run("route_and_fill", pcb_path, **overrides)

    def _run_builtin(
        self,
        name: str,
        pcb: Path,
        **overrides: Any,
    ) -> WorkflowResult:
        """Execute a built-in workflow."""
        if name == "route_and_fill":
            return self._builtin_route_and_fill(pcb, **overrides)

        return WorkflowResult(
            success=False,
            workflow_name=name,
            errors=(f"Unknown built-in workflow: {name}",),
        )

    def _builtin_route_and_fill(
        self,
        pcb: Path,
        **overrides: Any,
    ) -> WorkflowResult:
        """Route-and-fill: analyze gaps, then fill them via GapFillEngine."""
        from kicad_agent.analysis.gap_fill_engine import GapFillEngine

        max_iter = overrides.get("max_iterations", self._config.routing.max_iterations)
        target_pct = overrides.get("target_route_pct", self._config.routing.target_route_pct)
        run_drc = overrides.get("run_drc", True)
        use_ai = overrides.get("use_ai", self._config.models.use_ai)

        engine = GapFillEngine(
            max_iterations=max_iter,
            target_route_pct=target_pct,
            run_drc=run_drc,
            use_ai=use_ai,
        )

        try:
            result = engine.fill_gaps(str(pcb))
            return WorkflowResult(
                success=result.success,
                workflow_name="route_and_fill",
                steps_completed=1 if result.success else 0,
                total_steps=1,
                gap_fill_result=result,
                errors=result.errors if not result.success else (),
            )
        except Exception as exc:
            logger.exception("route_and_fill failed on %s", pcb)
            return WorkflowResult(
                success=False,
                workflow_name="route_and_fill",
                errors=(str(exc),),
            )

    def _run_template(
        self,
        template_name: str,
        pcb: Path,
        **overrides: Any,
    ) -> WorkflowResult:
        """Execute a generic WorkflowTemplate."""
        from kicad_agent.ops.workflows import get_workflow

        template = get_workflow(template_name)
        if template is None:
            return WorkflowResult(
                success=False,
                workflow_name=template_name,
                errors=(f"Unknown workflow: {template_name}",),
            )

        required_steps = [s for s in template.steps if s.required]
        total = len(template.steps)
        completed = 0

        try:
            from kicad_agent.ops.executor import OperationExecutor

            # Build operation dicts from template steps
            ops_dicts: list[dict[str, Any]] = []
            for step in template.steps:
                op_dict: dict[str, Any] = {
                    "op_type": step.op_type,
                    "target_file": str(pcb),
                }
                op_dict.update(overrides)
                ops_dicts.append(op_dict)

            # Execute via batch
            executor = OperationExecutor(project_dir=str(pcb.parent))
            batch_result = executor.execute_batch(ops_dicts)

            if batch_result.get("success"):
                completed = total
            else:
                completed = batch_result.get("completed", 0)

            return WorkflowResult(
                success=batch_result.get("success", False),
                workflow_name=template_name,
                steps_completed=completed,
                total_steps=total,
                batch_result=batch_result,
                errors=(
                    (batch_result.get("error", ""),)
                    if not batch_result.get("success")
                    else ()
                ),
            )
        except Exception as exc:
            logger.exception("Template workflow %s failed", template_name)
            return WorkflowResult(
                success=False,
                workflow_name=template_name,
                steps_completed=completed,
                total_steps=total,
                errors=(str(exc),),
            )
