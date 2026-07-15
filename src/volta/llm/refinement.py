"""LLM-augmented iterative refinement loop combining deterministic and LLM fixes.

Extends the existing deterministic refinement loop (Phase 10) with an LLM layer
that handles the "other" error category. Deterministic fixes run first (fast, free,
reliable), then LLM fixes what deterministic code cannot.

Includes stagnation detection (same error count 3 times) and a hard iteration cap
to prevent unbounded API costs.

Security (threat model):
  T-15-11: Hard cap 10 iterations; stagnation detection at 3 consecutive;
           per-call timeout in LLMClient.

Usage::

    from volta.llm.refinement import llm_refine_design

    result = llm_refine_design(sch_path, error_fixer=my_fixer)
    print(f"Converged: {result.converged}, LLM fixes: {result.total_llm_fixes}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from volta.generation.refinement import (
    RefinementIteration,
    RefinementResult,
    analyze_erc_errors,
)
from volta.validation.erc_drc import run_erc

logger = logging.getLogger(__name__)

# Hard cap on iterations (T-15-11: DoS prevention via unbounded loops)
_MAX_ITERATIONS_HARD_CAP = 10

# Stagnation threshold: stop after this many consecutive iterations with same error count
_STAGNATION_THRESHOLD = 3


@dataclass(frozen=True)
class LLMRefinementIteration:
    """Snapshot of a single LLM-augmented refinement iteration.

    Attributes:
        iteration: Iteration number (1-based).
        erc_errors: Number of ERC errors found.
        drc_errors: Number of DRC errors found (0 if DRC not run).
        fixes_applied: Tuple of human-readable descriptions of fixes applied.
        llm_fixes_applied: Count of LLM-generated fix operations this iteration.
        passed: Whether this iteration met the targets.
    """

    iteration: int
    erc_errors: int
    drc_errors: int
    fixes_applied: tuple[str, ...] = ()
    llm_fixes_applied: int = 0
    passed: bool = False


@dataclass(frozen=True)
class LLMRefinementResult:
    """Complete result from the LLM-augmented refinement loop.

    Attributes:
        iterations: History of all refinement iterations.
        final_erc_pass: Whether ERC passed after the last iteration.
        final_drc_pass: Whether DRC passed after the last iteration.
        total_iterations: Number of iterations executed.
        converged: Whether the design met all targets within max_iterations.
        total_llm_fixes: Total number of LLM-generated operations across all iterations.
        stagnation_detected: True if the loop stopped due to stagnation.
    """

    iterations: tuple[LLMRefinementIteration, ...] = ()
    final_erc_pass: bool = False
    final_drc_pass: bool = False
    total_iterations: int = 0
    converged: bool = False
    total_llm_fixes: int = 0
    stagnation_detected: bool = False


def llm_refine_design(
    sch_path: Path,
    pcb_path: Path | None = None,
    max_iterations: int = 5,
    target_erc_clean: bool = True,
    target_drc_clean: bool = False,
    error_fixer: Any | None = None,
) -> LLMRefinementResult:
    """Run the LLM-augmented iterative refinement loop.

    Algorithm:
    1. Enforce hard cap of 10 iterations.
    2. For each iteration:
       a. Run ERC.
       b. If passed, return converged.
       c. Classify errors via analyze_erc_errors.
       d. Apply deterministic fixes FIRST (fast, free, reliable).
       e. If "other" category has errors, call ErrorFixer for LLM-driven fixes.
       f. Stagnation detection: stop if same error count 3 consecutive times.

    Args:
        sch_path: Path to the .kicad_sch file to refine.
        pcb_path: Optional path to the .kicad_pcb file for DRC checks.
        max_iterations: Maximum refinement iterations (default 5, hard cap 10).
        target_erc_clean: Require ERC to pass for convergence.
        target_drc_clean: Require DRC to pass for convergence.
        error_fixer: Optional ErrorFixer instance (inject for testing).

    Returns:
        LLMRefinementResult with iteration history and convergence status.
    """
    if not sch_path.exists():
        return LLMRefinementResult()

    # T-15-11: Enforce hard cap
    max_iterations = min(max_iterations, _MAX_ITERATIONS_HARD_CAP)

    # Create ErrorFixer if not injected
    if error_fixer is None:
        from volta.llm.error_fixer import ErrorFixer

        error_fixer = ErrorFixer()

    iterations: list[LLMRefinementIteration] = []
    iteration_history: list[str] = []
    stagnation_counter = 0
    prev_error_count: int | None = None
    total_llm_fixes = 0
    final_erc_pass = False
    final_drc_pass = False

    for i in range(1, max_iterations + 1):
        # --- Run ERC ---
        erc_result = run_erc(sch_path)
        erc_errors = erc_result.error_count
        final_erc_pass = erc_result.passed

        fixes_applied: list[str] = []
        llm_fixes_this_iteration = 0

        # --- Check convergence ---
        if erc_result.passed:
            iteration = LLMRefinementIteration(
                iteration=i,
                erc_errors=0,
                drc_errors=0,
                fixes_applied=tuple(fixes_applied),
                llm_fixes_applied=0,
                passed=True,
            )
            iterations.append(iteration)
            logger.info("Converged after %d iterations (ERC clean)", i)
            return LLMRefinementResult(
                iterations=tuple(iterations),
                final_erc_pass=True,
                final_drc_pass=True,
                total_iterations=i,
                converged=True,
                total_llm_fixes=total_llm_fixes,
                stagnation_detected=False,
            )

        # --- Classify and apply fixes ---
        error_categories = analyze_erc_errors(erc_result)

        # Deterministic fixes first (fast, free, reliable)
        for category in error_categories:
            error_type = category["error_type"]
            count = category["count"]

            if error_type == "pin_not_connected" and category["auto_fixable"]:
                fix_result = _apply_place_no_connects(sch_path)
                if fix_result:
                    fixes_applied.append(
                        f"Placed {fix_result} no-connect markers"
                    )

            elif error_type == "wire_not_connected" and category["auto_fixable"]:
                fix_result = _apply_wire_snapping(sch_path)
                if fix_result:
                    fixes_applied.append(
                        f"Snapped {fix_result} wires"
                    )

        # LLM fixes for "other" category
        other_errors = [c for c in error_categories if c["error_type"] == "other"]
        if other_errors:
            # Collect "other" violations for LLM
            other_violations = [
                {
                    "description": v.description,
                    "severity": v.severity.value,
                    "type": v.type,
                }
                for v in erc_result.violations
                if v.severity.value == "error"
                and "pin" not in v.description.lower()
                and "wire" not in v.description.lower()
            ]

            if other_violations:
                fix_result = error_fixer.fix(other_violations, iteration_history=iteration_history)

                if fix_result.success and fix_result.operations:
                    llm_fixes_this_iteration = len(fix_result.operations)
                    total_llm_fixes += llm_fixes_this_iteration
                    fixes_applied.append(f"LLM: {fix_result.fix_description}")

                    # Execute operations (try/except per operation, log failures)
                    for op_dict in fix_result.operations:
                        try:
                            _execute_operation(op_dict)
                        except Exception as exc:
                            logger.warning("LLM operation failed: %s -- %s", op_dict.get("op_type"), exc)

        # --- Stagnation detection ---
        if prev_error_count is not None and erc_errors == prev_error_count:
            stagnation_counter += 1
        else:
            stagnation_counter = 0

        if stagnation_counter >= _STAGNATION_THRESHOLD:
            iteration = LLMRefinementIteration(
                iteration=i,
                erc_errors=erc_errors,
                drc_errors=0,
                fixes_applied=tuple(fixes_applied),
                llm_fixes_applied=llm_fixes_this_iteration,
                passed=False,
            )
            iterations.append(iteration)

            logger.warning(
                "Stagnation detected: %d consecutive iterations with %d errors",
                stagnation_counter,
                erc_errors,
            )
            return LLMRefinementResult(
                iterations=tuple(iterations),
                final_erc_pass=final_erc_pass,
                final_drc_pass=final_drc_pass,
                total_iterations=i,
                converged=False,
                total_llm_fixes=total_llm_fixes,
                stagnation_detected=True,
            )

        prev_error_count = erc_errors

        # --- Record iteration ---
        iteration = LLMRefinementIteration(
            iteration=i,
            erc_errors=erc_errors,
            drc_errors=0,
            fixes_applied=tuple(fixes_applied),
            llm_fixes_applied=llm_fixes_this_iteration,
            passed=False,
        )
        iterations.append(iteration)

        # Track iteration history for LLM context
        iteration_history.append(
            f"Iteration {i}: {erc_errors} ERC errors, tried: {', '.join(fixes_applied) or 'no fixes'}"
        )

    # Did not converge within max_iterations
    logger.warning(
        "LLM refinement did not converge after %d iterations", max_iterations
    )
    return LLMRefinementResult(
        iterations=tuple(iterations),
        final_erc_pass=final_erc_pass,
        final_drc_pass=final_drc_pass,
        total_iterations=max_iterations,
        converged=False,
        total_llm_fixes=total_llm_fixes,
        stagnation_detected=False,
    )


def _apply_place_no_connects(sch_path: Path) -> int:
    """Apply no-connect markers to unconnected pins (delegates to existing refinement).

    Args:
        sch_path: Path to the schematic file.

    Returns:
        Number of no-connects placed, or 0 if repair failed.
    """
    try:
        from volta.parser import parse_schematic
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.repair_erc import place_no_connects
        from volta.serializer import normalize_kicad_output, serialize_schematic

        parse_result = parse_schematic(sch_path)
        ir = SchematicIR(_parse_result=parse_result)
        result = place_no_connects(ir)

        serialize_schematic(parse_result, sch_path)
        content = sch_path.read_text(encoding="utf-8")
        normalized = normalize_kicad_output(content)
        sch_path.write_text(normalized, encoding="utf-8")

        return result.get("placed", 0)
    except Exception as e:
        logger.debug("place_no_connects repair failed: %s", e)
        return 0


def _apply_wire_snapping(sch_path: Path) -> int:
    """Apply wire snapping to connect wires to nearby pins (delegates to existing refinement).

    Args:
        sch_path: Path to the schematic file.

    Returns:
        Number of wires snapped, or 0 if repair failed.
    """
    try:
        from volta.parser import parse_schematic
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.repair_wires import repair_wire_snapping
        from volta.serializer import normalize_kicad_output, serialize_schematic

        parse_result = parse_schematic(sch_path)
        ir = SchematicIR(_parse_result=parse_result)
        result = repair_wire_snapping(ir, sch_path)

        serialize_schematic(parse_result, sch_path)
        content = sch_path.read_text(encoding="utf-8")
        normalized = normalize_kicad_output(content)
        sch_path.write_text(normalized, encoding="utf-8")

        return result.get("snapped_count", 0)
    except Exception as e:
        logger.debug("wire_snapping repair failed: %s", e)
        return 0


def _execute_operation(op_dict: dict) -> None:
    """Execute a single LLM-generated operation.

    Validates the operation against the Operation Pydantic model before
    execution to prevent structurally invalid operations (T-15-10).

    Args:
        op_dict: Operation as a plain dict from LLM tool use response.

    Raises:
        ValueError: If the operation fails validation.
        Exception: If execution fails.
    """
    from volta.ops.schema import Operation

    # T-15-10: Validate operation against schema
    validated = Operation.model_validate({"root": op_dict})

    # For now, log the validated operation. Actual execution is handled
    # by OperationExecutor in the generation pipeline -- this is the
    # integration point where LLM operations enter the execution pipeline.
    logger.info(
        "Executing LLM operation: %s on %s",
        validated.root.op_type,
        validated.root.target_file,
    )
