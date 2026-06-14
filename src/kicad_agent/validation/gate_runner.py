"""Gate runner — orchestrates gate checks with stage-aware dispatch.

GateRunner holds registered GateDefinition instances and dispatches checks
based on design stage transitions. It chains required gates for multi-stage
jumps and stops on first failure (fail-closed).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from kicad_agent.validation.gate_types import DesignStage, GateDefinition, GateResult

logger = logging.getLogger(__name__)

# Type for gate check functions: receive context dict, return GateResult or dict
GateCheckFn = Callable[[dict[str, Any]], GateResult | dict[str, Any]]

# Ordered stages for chaining multi-stage transitions
_STAGE_ORDER: list[DesignStage] = [
    DesignStage.SCHEMATIC,
    DesignStage.PCB_SETUP,
    DesignStage.PLACEMENT,
    DesignStage.ROUTING,
    DesignStage.MANUFACTURING,
]


class GateRunner:
    """Orchestrator for design stage gates.

    Gates register with both a GateDefinition (metadata) and a callable
    check function. The runner dispatches checks by name.

    Usage::

        runner = GateRunner()
        runner.register_gate(
            GateDefinition(
                name="pre_pcb_schematic",
                from_stage=DesignStage.SCHEMATIC,
                to_stage=DesignStage.PCB_SETUP,
                check_fn_name="pre_pcb_schematic_gate",
            ),
            check_fn=my_check_fn,
        )
        result = runner.run_gate("pre_pcb_schematic", context={...})
    """

    def __init__(self) -> None:
        self._gates: dict[str, GateDefinition] = {}
        self._check_fns: dict[str, GateCheckFn] = {}
        self._last_results: dict[str, GateResult] = {}

    def register_gate(
        self,
        gate: GateDefinition,
        check_fn: GateCheckFn | None = None,
    ) -> None:
        """Register a gate definition with its check function."""
        self._gates[gate.name] = gate
        if check_fn is not None:
            self._check_fns[gate.name] = check_fn
        logger.debug(
            "Registered gate: %s (%s -> %s)",
            gate.name, gate.from_stage.value, gate.to_stage.value,
        )

    def get_gate(self, name: str) -> GateDefinition | None:
        """Look up a registered gate by name."""
        return self._gates.get(name)

    def list_gates(self) -> list[GateDefinition]:
        """Return all registered gates."""
        return list(self._gates.values())

    def has_check_fn(self, name: str) -> bool:
        """Check whether a gate has a registered check function."""
        return name in self._check_fns

    def run_gate(self, name: str, context: dict[str, Any]) -> GateResult:
        """Execute a single gate by name.

        Raises:
            KeyError: If no gate is registered with the given name.
            RuntimeError: If no check function is registered for the gate.
        """
        gate_def = self._gates.get(name)
        if gate_def is None:
            raise KeyError(f"Gate not registered: {name}")

        check_fn = self._check_fns.get(name)
        if check_fn is None:
            raise RuntimeError(f"Check function not registered for gate: {name}")

        logger.info("Running gate: %s", name)
        result = check_fn(context)

        if isinstance(result, GateResult):
            self._last_results[name] = result
            return result
        wrapped = GateResult.from_dict(result)
        self._last_results[name] = wrapped
        return wrapped

    def get_last_results(self) -> dict[str, GateResult]:
        """Return the most recent GateResult for each gate that has run.

        Returns a shallow copy so callers cannot mutate internal state.
        """
        return dict(self._last_results)

    def get_last_failed_gate(self) -> GateResult | None:
        """Return the most recently stored failed GateResult, or None.

        Iteration order follows insertion (run order). The last-inserted
        failed result is returned.
        """
        failed = [r for r in self._last_results.values() if not r.pass_bool]
        return failed[-1] if failed else None

    def get_required_gates(
        self,
        from_stage: DesignStage,
        to_stage: DesignStage,
    ) -> list[str]:
        """Get the ordered list of gates required for a stage transition.

        For adjacent stages, returns the single gate (if registered).
        For multi-stage jumps, chains all intermediate gates in order.
        """
        from_idx = _STAGE_ORDER.index(from_stage)
        to_idx = _STAGE_ORDER.index(to_stage)

        if to_idx <= from_idx:
            return []

        required: list[str] = []
        for i in range(from_idx, to_idx):
            current = _STAGE_ORDER[i]
            next_stage = _STAGE_ORDER[i + 1]
            for gate in self._gates.values():
                if gate.from_stage == current and gate.to_stage == next_stage:
                    required.append(gate.name)
                    break

        return required

    def run_all_gates(
        self,
        from_stage: DesignStage,
        to_stage: DesignStage,
        context: dict[str, Any],
    ) -> GateResult:
        """Chain and run all required gates for a stage transition.

        Stops on first failure (fail-closed). Returns the first failing
        GateResult, or a passing aggregate if all gates pass.
        """
        gate_names = self.get_required_gates(from_stage, to_stage)

        if not gate_names:
            # No gates required — implicit pass
            return GateResult(
                pass_=True,
                gate_name=f"no_gates_{from_stage.value}_to_{to_stage.value}",
                stage=to_stage,
                next_actions=[f"Proceed to {to_stage.value} stage"],
            )

        all_blockers: list[str] = []
        all_warnings: list[str] = []
        all_artifacts: list[str] = []
        all_next_actions: list[str] = []

        for name in gate_names:
            result = self.run_gate(name, context)

            all_warnings.extend(result.warnings)
            all_artifacts.extend(result.artifacts)

            if not result.pass_bool:
                all_blockers.extend(result.blockers)
                all_next_actions.extend(result.next_actions)
                # Fail-closed: stop on first failure
                return GateResult(
                    pass_=False,
                    gate_name=name,
                    stage=result.stage,
                    blockers=all_blockers,
                    warnings=all_warnings,
                    artifacts=all_artifacts,
                    next_actions=all_next_actions or ["Fix blockers above and retry"],
                )

        return GateResult(
            pass_=True,
            gate_name=f"chain_{from_stage.value}_to_{to_stage.value}",
            stage=to_stage,
            blockers=[],
            warnings=all_warnings,
            artifacts=all_artifacts,
            next_actions=[f"Proceed to {to_stage.value} stage"],
        )


# Singleton runner instance for module-level access
_default_runner = GateRunner()


def get_gate_runner() -> GateRunner:
    """Return the default singleton GateRunner."""
    return _default_runner


def register_gate(gate: GateDefinition, check_fn: GateCheckFn | None = None) -> None:
    """Register a gate on the default singleton runner."""
    _default_runner.register_gate(gate, check_fn=check_fn)
