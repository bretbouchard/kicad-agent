"""Routing readiness and post-route quality gates.

RoutingReadinessGate checks prerequisites before routing begins:
board outline, stackup, net classes, constraints, and placement gate pass.

PostRouteQualityGate validates routing quality with two tiers:
- Tier 1 (PcbIR-based): completion %, diff pairs, return path risk -- always runs
- Tier 2 (kicad-cli-based): DRC, unconnected items -- runs if kicad-cli available

Both gates register for stage transitions via module-level register_gate().
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from kicad_agent.validation.gate_runner import register_gate
from kicad_agent.validation.gate_types import DesignStage, GateDefinition, GateResult
from kicad_agent.validation.gates.route_quality import (
    RouteQualityMetrics,
    compute_route_quality,
)

logger = logging.getLogger(__name__)


class RoutingReadinessGate:
    """Validates prerequisites before routing begins.

    Checks:
    1. Board outline exists (via pcb_ir)
    2. Constraints loaded (DesignConstraints in context)
    3. Stackup defined (via constraints.fab.layer_count)
    4. Net classes present (via constraints.electrical)
    5. Placement gate passed (via context gate_results)

    Gate context dict requires:
        - "pcb_ir": PcbIR instance
        - "constraints": DesignConstraints instance
        - "gate_results": dict of gate_name -> GateResult (must include "placement_readiness")
    """

    def run(self, context: dict[str, Any]) -> GateResult:
        pcb_ir = context.get("pcb_ir")
        constraints = context.get("constraints")
        gate_results = context.get("gate_results", {})

        # Check 1: PcbIR present
        if pcb_ir is None:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=["No pcb_ir in context. Load a PCB before routing."],
            )

        # Check 2: Board outline exists
        board_bounds = pcb_ir.get_board_bounds()
        if board_bounds is None:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=["No board outline found. Define Edge.Cuts before routing."],
            )

        # Check 3: Constraints loaded
        if constraints is None:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=["No design constraints in context. Run set_constraints first."],
            )

        # Check 4: Stackup defined
        layer_count = getattr(constraints.fab, "layer_count", 0)
        if layer_count < 1:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=["Stackup not defined in constraints. Set fab profile layer_count."],
            )

        # Check 5: Net classes present
        electrical_count = len(getattr(constraints, "electrical", []))
        if electrical_count == 0:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=["No electrical constraints defined. Add net classes before routing."],
            )

        # Check 6: Placement gate passed
        placement_result = gate_results.get("placement_readiness")
        if placement_result is None:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=[
                    "Placement gate has not been run. "
                    "Run placement_readiness gate before routing."
                ],
            )
        placement_passed = getattr(placement_result, "pass_", False)
        if not placement_passed:
            return GateResult(
                pass_=False,
                gate_name="routing_readiness",
                stage=DesignStage.ROUTING,
                blockers=[
                    "Placement gate did not pass. "
                    f"Fix placement issues: {getattr(placement_result, 'blockers', [])}"
                ],
            )

        w = board_bounds[2] - board_bounds[0]
        h = board_bounds[3] - board_bounds[1]
        return GateResult(
            pass_=True,
            gate_name="routing_readiness",
            stage=DesignStage.ROUTING,
            artifacts=[
                f"board: {w:.1f} x {h:.1f} mm",
                f"stackup: {layer_count} layers",
                f"{electrical_count} electrical constraints",
            ],
            next_actions=["Proceed to routing stage"],
        )


class PostRouteQualityGate:
    """Validates routing quality before manufacturing.

    Two-tier check:
    - Tier 1 (PcbIR-based, always runs): completion %, diff pairs, return path risk
    - Tier 2 (kicad-cli, runs if available): DRC violations, unconnected items

    Gate context dict requires:
        - "pcb_ir": PcbIR instance
        - "constraints": DesignConstraints instance
    """

    def run(self, context: dict[str, Any]) -> GateResult:
        pcb_ir = context.get("pcb_ir")
        constraints = context.get("constraints")

        if pcb_ir is None:
            return GateResult(
                pass_=False,
                gate_name="post_route_quality",
                stage=DesignStage.ROUTING,
                blockers=["No pcb_ir in context."],
            )

        # --- Tier 1: PcbIR-based checks (always run) ---
        metrics = compute_route_quality(pcb_ir, constraints)

        blockers: list[str] = []
        warnings: list[str] = []

        # Completion check: all nets must be routed
        if metrics.completion_pct < 100.0:
            blockers.append(
                f"Routing incomplete: {metrics.completion_pct:.1f}% "
                f"({100 - metrics.completion_pct:.1f}% unrouted)"
            )

        # Diff pair issues
        for issue in metrics.diff_pair_issues:
            blockers.append(f"Diff pair: {issue}")

        # Return path risk
        if metrics.return_path_risk:
            warnings.append(
                f"Return path risk: {len(metrics.return_path_risk)} net(s) "
                f"without adjacent ground plane"
            )

        # --- Tier 2: kicad-cli-dependent checks ---
        kicad_cli = shutil.which("kicad-cli")
        if kicad_cli is not None:
            drc_result = self._run_drc(pcb_ir)
            if drc_result is not None:
                if drc_result.error_message:
                    warnings.append(f"DRC error: {drc_result.error_message}")

                if not drc_result.passed:
                    for v in drc_result.violations:
                        if getattr(v, "severity", "").lower() == "error":
                            blockers.append(f"DRC violation: {getattr(v, 'message', v)}")

                for uc in drc_result.unconnected_items:
                    blockers.append(
                        f"Unconnected: {getattr(uc, 'message', uc)}"
                    )
        else:
            warnings.append(
                "kicad-cli not available -- DRC and unconnected-item checks skipped"
            )

        # Determine quality_status
        passed = len(blockers) == 0
        quality_status = "verified" if passed else "prototype"

        artifacts = [
            f"completion: {metrics.completion_pct:.1f}%",
            f"vias: {metrics.via_count}",
            f"quality_score: {metrics.quality_score:.3f}",
            f"quality_status: {quality_status}",
        ]

        return GateResult(
            pass_=passed,
            gate_name="post_route_quality",
            stage=DesignStage.ROUTING,
            blockers=blockers,
            warnings=warnings,
            artifacts=artifacts,
            next_actions=(
                ["Proceed to manufacturing stage"]
                if passed
                else ["Fix routing issues and re-run gate"]
            ),
        )

    @staticmethod
    def _run_drc(pcb_ir: Any) -> Any:
        """Run DRC via kicad-cli if available. Returns DrcResult or None."""
        try:
            from kicad_agent.validation.erc_drc import run_drc
            file_path = getattr(
                pcb_ir._parse_result if hasattr(pcb_ir, "_parse_result") else pcb_ir,
                "file_path",
                None,
            )
            if file_path and Path(file_path).exists():
                return run_drc(Path(file_path))
        except Exception as exc:
            logger.warning("DRC failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Module-level gate registration
# ---------------------------------------------------------------------------

_readiness_gate = RoutingReadinessGate()
_quality_gate = PostRouteQualityGate()

register_gate(
    GateDefinition(
        name="routing_readiness",
        from_stage=DesignStage.PLACEMENT,
        to_stage=DesignStage.ROUTING,
        check_fn_name="routing_readiness_gate",
    ),
    check_fn=_readiness_gate.run,
)

register_gate(
    GateDefinition(
        name="post_route_quality",
        from_stage=DesignStage.ROUTING,
        to_stage=DesignStage.MANUFACTURING,
        check_fn_name="post_route_quality_gate",
    ),
    check_fn=_quality_gate.run,
)
