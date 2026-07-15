"""Gap fill engine orchestrator (GAP-08).

Runs the iterative analyze-fill-verify loop:
  1. GapAnalyzer produces a GapReport
  2. NetCompletionFiller generates AutoRouteOps for unrouted/incomplete nets
  3. DrcAutoFixer generates fix ops for DRC violations
  4. NetNamingValidator validates and produces RenameNetOps
  5. Operations are executed via OperationExecutor
  6. Re-analyze to verify progress; repeat until convergence or max iterations

Transaction safety: PCB file is snapshotted before the loop begins.
On regression (DRC count increases) or catastrophic failure, the snapshot
is restored.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from volta.analysis.gap_analyzer import GapAnalyzer
from volta.analysis.drc_auto_fixer import DrcAutoFixer
from volta.analysis.net_completion_filler import NetCompletionFiller
from volta.analysis.net_naming_validator import NetNamingValidator
from volta.ops.schema import Operation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GapFillIteration:
    """Stats from a single analyze-fill-verify iteration."""

    iteration: int
    nets_attempted: int
    nets_completed: int
    drc_violations_before: int
    drc_fixed: int
    nets_renamed: int
    route_percentage: float
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class GapFillResult:
    """Complete result from the gap-filling engine."""

    success: bool
    iterations: tuple[GapFillIteration, ...]
    total_nets_completed: int
    total_drc_fixed: int
    total_nets_renamed: int
    final_route_percentage: float
    rollback_performed: bool
    errors: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "success": self.success,
            "iterations": [
                {
                    "iteration": i.iteration,
                    "nets_attempted": i.nets_attempted,
                    "nets_completed": i.nets_completed,
                    "drc_violations_before": i.drc_violations_before,
                    "drc_fixed": i.drc_fixed,
                    "nets_renamed": i.nets_renamed,
                    "route_percentage": i.route_percentage,
                    "errors": list(i.errors),
                }
                for i in self.iterations
            ],
            "total_nets_completed": self.total_nets_completed,
            "total_drc_fixed": self.total_drc_fixed,
            "total_nets_renamed": self.total_nets_renamed,
            "final_route_percentage": self.final_route_percentage,
            "rollback_performed": self.rollback_performed,
            "errors": list(self.errors),
        }

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# Gap Fill Result")
        lines.append("")
        status = "SUCCESS" if self.success else "FAILED"
        lines.append(f"**Status:** {status}")
        lines.append(f"**Iterations:** {len(self.iterations)}")
        lines.append(f"**Route %:** {self.final_route_percentage:.1f}%")
        lines.append(f"**Nets completed:** {self.total_nets_completed}")
        lines.append(f"**DRC fixed:** {self.total_drc_fixed}")
        lines.append(f"**Nets renamed:** {self.total_nets_renamed}")
        lines.append(f"**Rollback:** {'yes' if self.rollback_performed else 'no'}")
        if self.errors:
            lines.append("")
            lines.append("## Errors")
            for e in self.errors:
                lines.append(f"- {e}")
        return "\n".join(lines)


class GapFillEngine:
    """Orchestrates the iterative gap-filling loop.

    Args:
        max_iterations: Maximum analyze-fill-verify cycles (1-3).
        target_route_pct: Target route percentage for convergence.
        run_drc: Whether to run DRC during analysis.
        use_ai: Whether to use AI for prioritization and fix suggestions.
    """

    def __init__(
        self,
        max_iterations: int = 3,
        target_route_pct: float = 95.0,
        run_drc: bool = True,
        use_ai: bool = True,
    ) -> None:
        self._max_iterations = max(1, min(3, max_iterations))
        self._target_route_pct = target_route_pct
        self._run_drc = run_drc
        self._use_ai = use_ai

    def fill_gaps(self, pcb_path: str | Path) -> GapFillResult:
        """Run the iterative gap-filling loop.

        Args:
            pcb_path: Path to the .kicad_pcb file.

        Returns:
            GapFillResult with iteration stats and final state.
        """
        pcb = Path(pcb_path)
        if not pcb.exists():
            return GapFillResult(
                success=False,
                iterations=(),
                total_nets_completed=0,
                total_drc_fixed=0,
                total_nets_renamed=0,
                final_route_percentage=0.0,
                rollback_performed=False,
                errors=(f"File not found: {pcb_path}",),
            )

        # Snapshot for transaction safety
        snapshot_path = pcb.with_suffix(".kicad_pcb.gapfill-backup")
        try:
            shutil.copy2(pcb, snapshot_path)
        except OSError as exc:
            return GapFillResult(
                success=False,
                iterations=(),
                total_nets_completed=0,
                total_drc_fixed=0,
                total_nets_renamed=0,
                final_route_percentage=0.0,
                rollback_performed=False,
                errors=(f"Cannot create snapshot: {exc}",),
            )

        analyzer = GapAnalyzer()
        iterations_list: list[GapFillIteration] = []
        total_completed = 0
        total_fixed = 0
        total_renamed = 0
        all_errors: list[str] = []
        rollback_performed = False

        try:
            for i in range(1, self._max_iterations + 1):
                errors: list[str] = []
                report = analyzer.analyze(str(pcb), run_drc=self._run_drc)

                # Check convergence
                if report.routing_stats.route_percentage >= self._target_route_pct:
                    logger.info(
                        "Target route %.1f%% reached at iteration %d (actual %.1f%%)",
                        self._target_route_pct, i,
                        report.routing_stats.route_percentage,
                    )
                    break

                route_pct_before = report.routing_stats.route_percentage
                drc_count_before = len(report.drc_violations)
                target_file = pcb.name

                # 1. Net completion
                filler = NetCompletionFiller(
                    target_file=target_file, use_ai=self._use_ai,
                )
                route_ops = filler.generate_ops(report, report.board_info)

                # 2. DRC fixes
                fixer = DrcAutoFixer(
                    target_file=target_file, use_ai=self._use_ai,
                )
                drc_ops = fixer.fix_violations(report.drc_violations)

                # 3. Net renaming
                validator = NetNamingValidator(
                    target_file=target_file, use_ai=self._use_ai,
                )
                rename_ops = validator.validate(
                    report.net_naming_issues, report.board_info,
                )

                # Execute all operations
                all_ops = route_ops + drc_ops + rename_ops
                nets_completed = 0
                drc_fixed = 0
                nets_renamed = len(rename_ops)

                for op_dict in all_ops:
                    try:
                        op = Operation.model_validate(op_dict)
                        from volta.ops.executor import OperationExecutor
                        executor = OperationExecutor(base_dir=pcb.parent)
                        result = executor.execute(op)
                        if result.get("success"):
                            if op_dict.get("op_type") == "auto_route":
                                nets_completed += 1
                            elif "fix" in op_dict.get("op_type", ""):
                                drc_fixed += 1
                    except Exception as exc:
                        errors.append(f"{op_dict.get('op_type', '?')}: {exc}")

                # Verify progress
                verify_report = analyzer.analyze(str(pcb), run_drc=self._run_drc)
                new_drc_count = len(verify_report.drc_violations)

                # Regression check
                if new_drc_count > drc_count_before and drc_count_before > 0:
                    logger.warning(
                        "DRC regression: %d -> %d, rolling back",
                        drc_count_before, new_drc_count,
                    )
                    shutil.copy2(snapshot_path, pcb)
                    rollback_performed = True
                    break

                route_pct_after = verify_report.routing_stats.route_percentage
                actual_nets_completed = (
                    verify_report.routing_stats.routed_nets
                    - report.routing_stats.routed_nets
                )
                if actual_nets_completed < 0:
                    actual_nets_completed = 0

                iteration = GapFillIteration(
                    iteration=i,
                    nets_attempted=len(route_ops),
                    nets_completed=max(actual_nets_completed, nets_completed),
                    drc_violations_before=drc_count_before,
                    drc_fixed=drc_fixed,
                    nets_renamed=nets_renamed,
                    route_percentage=route_pct_after,
                    errors=tuple(errors),
                )
                iterations_list.append(iteration)
                total_completed += iteration.nets_completed
                total_fixed += drc_fixed
                total_renamed += nets_renamed
                all_errors.extend(errors)

                # No progress check
                if route_pct_after <= route_pct_before and not nets_renamed:
                    logger.info(
                        "No progress at iteration %d (%.1f%% -> %.1f%%), stopping",
                        i, route_pct_before, route_pct_after,
                    )
                    break

        except Exception as exc:
            logger.error("Gap fill engine error: %s", exc)
            all_errors.append(str(exc))
            # Restore snapshot on catastrophic failure
            try:
                shutil.copy2(snapshot_path, pcb)
                rollback_performed = True
            except OSError:
                pass
        finally:
            # Clean up snapshot
            if snapshot_path.exists():
                try:
                    snapshot_path.unlink()
                except OSError:
                    pass

        final_report = analyzer.analyze(str(pcb), run_drc=self._run_drc)
        success = (
            final_report.routing_stats.route_percentage
            >= self._target_route_pct
            or len(iterations_list) > 0
        )

        return GapFillResult(
            success=success,
            iterations=tuple(iterations_list),
            total_nets_completed=total_completed,
            total_drc_fixed=total_fixed,
            total_nets_renamed=total_renamed,
            final_route_percentage=final_report.routing_stats.route_percentage,
            rollback_performed=rollback_performed,
            errors=tuple(all_errors),
        )
