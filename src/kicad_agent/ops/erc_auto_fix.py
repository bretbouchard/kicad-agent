"""ERC auto-fix meta-operation -- chains parse_erc to repair dispatch with iteration control.

Provides a single operation that:
1. Runs ERC via parse_erc
2. Groups violations by type
3. Dispatches appropriate repair functions in priority order
4. Iterates until violations are resolved or max_iterations is reached
5. Stops early if violation count does not decrease between iterations
6. Returns structured summary of fixes applied and remaining violations

GEN-03: Simplifies the common LLM/MCP workflow of parse_erc + manual repair chaining.

Usage:
    from kicad_agent.ops.erc_auto_fix import erc_auto_fix

    result = erc_auto_fix(ir, file_path, max_iterations=3)
    print(f"Fixed {len(result['fixes_applied'])} violation types in {result['iterations']} iterations")
"""

import logging
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.erc_parser import parse_erc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Violation type -> repair function mapping
# ---------------------------------------------------------------------------

# Maps ErcViolation.type strings to the repair function name in this module.
# These type strings come from kicad-cli ERC output as surfaced by parse_erc.
VIOLATION_REPAIR_MAP: dict[str, str] = {
    "pin_not_connected": "place_no_connects_from_erc",
    "power_pin_not_driven": "add_power_flags",
    "pin_to_pin": "fix_pin_type_mismatches",
    "missing_power_pin": "place_missing_units",
}

# Repair priority order. Shorts cause cascading errors and must be fixed first.
# Then pin type conflicts, missing units, power flags, and finally cosmetic fixes.
REPAIR_PRIORITY: list[str] = [
    "break_wire_shorts",       # shorts cause cascading errors
    "fix_pin_type_mismatches", # type conflicts
    "place_missing_units",     # missing units
    "add_power_flags",         # power pin issues (maps from power_pin_not_driven)
    "place_no_connects_from_erc",  # unconnected pins / cosmetic (maps from pin_not_connected)
    "snap_to_grid",            # off-grid / cosmetic
]


def _get_repair_function(repair_name: str) -> Any:
    """Import and return the repair function by name.

    Import paths follow the lazy-import pattern used throughout the executor.
    """
    if repair_name == "place_no_connects_from_erc":
        from kicad_agent.ops.repair import place_no_connects_from_erc
        return place_no_connects_from_erc
    elif repair_name == "add_power_flags":
        from kicad_agent.ops.repair import add_power_flags
        return add_power_flags
    elif repair_name == "fix_pin_type_mismatches":
        from kicad_agent.ops.repair import fix_pin_type_mismatches
        return fix_pin_type_mismatches
    elif repair_name == "place_missing_units":
        from kicad_agent.ops.repair import place_missing_units
        return place_missing_units
    elif repair_name == "break_wire_shorts":
        from kicad_agent.ops.repair import break_wire_shorts
        return break_wire_shorts
    elif repair_name == "snap_to_grid":
        from kicad_agent.ops.repair import snap_to_grid
        return snap_to_grid
    else:
        raise ValueError(f"Unknown repair function: {repair_name}")


def _violation_type_to_repair_name(vtype: str) -> str | None:
    """Map an ERC violation type to its repair function name.

    Direct mappings come from VIOLATION_REPAIR_MAP. Pattern-based mappings
    handle wire shorts (detected via "short" in the message/type) and
    off-grid pins (detected via "off_grid" in the type/message).
    """
    # Direct mapping
    if vtype in VIOLATION_REPAIR_MAP:
        return VIOLATION_REPAIR_MAP[vtype]

    # Pattern-based mappings
    if "short" in vtype.lower():
        return "break_wire_shorts"
    if "off_grid" in vtype.lower():
        return "snap_to_grid"

    return None


# ---------------------------------------------------------------------------
# Root cause mode helpers
# ---------------------------------------------------------------------------

# Maps diagnosis action names to existing repair function names.
_ACTION_TO_REPAIR_MAP: dict[str, str] = {
    "place_no_connect": "place_no_connects_from_erc",
    "break_wire_shorts": "break_wire_shorts",
    "fix_shorted_nets": "fix_shorted_nets",
    "add_power_flag": "add_power_flags",
    "snap_to_grid": "snap_to_grid",
    "fix_pin_type_mismatches": "fix_pin_type_mismatches",
}


def _action_to_repair_name(action: str) -> str | None:
    """Map a diagnosis action name to an existing repair function name.

    Returns None for actions that have no direct repair function mapping
    (e.g. "erc_auto_fix" from generic fallback, "add_wire" from diagnosis).
    """
    return _ACTION_TO_REPAIR_MAP.get(action)


def _empty_root_cause_result() -> dict[str, Any]:
    """Return the empty result structure for root cause mode with no violations."""
    return {
        "mode": "root_cause",
        "fixes_applied": [],
        "iterations": 0,
        "remaining_violations": 0,
        "pre_existing_documented": [],
        "benign_suppressed": 0,
        "config_issues": [],
        "summary": {"total": 0, "fixable": 0, "pre_existing": 0, "benign": 0, "config": 0},
    }


def erc_auto_fix(
    ir: SchematicIR,
    file_path: Path,
    max_iterations: int = 3,
    mode: str = "symptom",
    fix_classes: list[str] | None = None,
) -> dict[str, Any]:
    """Run ERC, dispatch repairs by violation type, iterate until resolved.

    Supports two modes:
    - ``symptom`` (default): existing iteration-based repair. Groups violations
      by type and dispatches repair functions in priority order.
    - ``root_cause``: classify first, diagnose fixable violations, apply targeted
      fixes, document pre-existing issues, suppress benign noise. Single-pass.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the schematic file (for ERC invocation).
        max_iterations: Maximum repair iterations (default 3, max 10 enforced by schema).
        mode: ``"symptom"`` for existing behavior, ``"root_cause"`` for classify-diagnose-fix.
        fix_classes: In root_cause mode, only fix these classes. None = fixable only.

    Returns:
        Dict with:
            fixes_applied: List of {type, count, repair} dicts for each violation type fixed.
            iterations: Number of iterations actually run.
            remaining_violations: Count of violations after last iteration.
            unhandled_violations: List of {type, count} for unmapped violation types.
            (root_cause mode adds: mode, pre_existing_documented, benign_suppressed,
             config_issues, summary)
    """
    if mode == "root_cause":
        return erc_auto_fix_root_cause(ir, file_path, max_iterations, fix_classes)

    # --- Symptom mode: existing iteration-based repair ---
    all_fixes: list[dict[str, Any]] = []
    all_unhandled: dict[str, int] = {}
    iteration_count = 0
    previous_count = -1

    # Known limitation (Council M-03): The IR object is NOT re-parsed between
    # iterations. Repair functions mutate the IR in memory, so later iterations
    # operate on the same (mutated) IR. This is acceptable because parse_erc
    # re-reads the file from disk for fresh ERC results, and the early-stop
    # heuristic catches stagnation.

    for iteration in range(max_iterations):
        violations = parse_erc(file_path)
        current_count = len(violations)

        # No violations -- done (don't count this as an iteration)
        if current_count == 0:
            break

        iteration_count = iteration + 1

        # Early stop: violation count did not decrease from previous iteration
        if previous_count >= 0 and current_count >= previous_count:
            logger.info(
                "Early stop at iteration %d: violations did not decrease (%d -> %d)",
                iteration_count, previous_count, current_count,
            )
            break

        previous_count = current_count

        # Group violations by type
        type_counts: dict[str, int] = {}
        for v in violations:
            type_counts[v.type] = type_counts.get(v.type, 0) + 1

        # Track which repair names we've already called this iteration
        # (multiple violation types can map to the same repair function)
        called_repairs: set[str] = set()

        # Dispatch repairs in priority order
        for repair_name in REPAIR_PRIORITY:
            # Find all violation types that map to this repair
            matching_types = []
            for vtype, count in type_counts.items():
                mapped = _violation_type_to_repair_name(vtype)
                if mapped == repair_name:
                    matching_types.append((vtype, count))

            if not matching_types or repair_name in called_repairs:
                continue

            called_repairs.add(repair_name)

            try:
                func = _get_repair_function(repair_name)
                # Call the repair function with (ir, file_path) and default args.
                # Council KR-04: auto-detect mode -- functions infer what to fix from IR state.
                func(ir, file_path)
                for vtype, count in matching_types:
                    all_fixes.append({
                        "type": vtype,
                        "count": count,
                        "repair": repair_name,
                    })
                    logger.info(
                        "Applied %s: %d violations of type '%s'",
                        repair_name, count, vtype,
                    )
            except Exception as exc:
                logger.warning(
                    "Repair %s failed: %s", repair_name, exc,
                )

        # Collect unhandled violations
        for vtype, count in type_counts.items():
            if _violation_type_to_repair_name(vtype) is None:
                all_unhandled[vtype] = all_unhandled.get(vtype, 0) + count

    # Final ERC check for remaining count
    final_violations = parse_erc(file_path)

    return {
        "fixes_applied": all_fixes,
        "iterations": iteration_count,
        "remaining_violations": len(final_violations),
        "unhandled_violations": [
            {"type": vtype, "count": count}
            for vtype, count in sorted(all_unhandled.items())
        ],
    }


def erc_auto_fix_root_cause(
    ir: SchematicIR,
    file_path: Path,
    max_iterations: int = 3,
    fix_classes: list[str] | None = None,
) -> dict[str, Any]:
    """Root cause mode: classify -> diagnose -> targeted fix -> document.

    Instead of blindly iterating repairs, this mode:
    1. Classifies all violations into fixable/pre-existing/benign/config_issue
    2. Diagnoses root causes for fixable violations only
    3. Applies targeted fixes using recommended repair actions
    4. Documents pre-existing violations with root cause explanations
    5. Suppresses benign violations from the detailed report (count only)
    6. Reports config issues for user action

    Single-pass by design (diagnosis replaces iteration).

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the schematic file (for ERC invocation).
        max_iterations: Kept for API consistency; root cause mode is single-pass.
        fix_classes: Only fix these violation classes. None = fixable only.

    Returns:
        Dict with mode, fixes_applied, iterations, remaining_violations,
        pre_existing_documented, benign_suppressed, config_issues, summary.
    """
    from kicad_agent.ops.violation_classifier import classify_violations
    from kicad_agent.ops.violation_diagnostic import diagnose_violations

    violations = parse_erc(file_path)
    if not violations:
        return _empty_root_cause_result()

    # Step 1: Classify all violations
    classified = classify_violations(violations, ir, file_path)
    fixable = classified["fixable"]
    pre_existing = classified["pre_existing"]
    benign = classified["benign"]
    config = classified["config_issues"]

    # Step 2: Diagnose fixable violations
    diagnoses = diagnose_violations(fixable, ir, file_path)

    # Step 3: Apply targeted fixes using existing repair functions
    fixes_applied: list[dict[str, Any]] = []
    for diagnosis in diagnoses.get("diagnoses", []):
        fix_options = diagnosis.get("fix_options", [])
        if not fix_options:
            continue

        rec_idx = diagnosis.get("recommended_fix_index", 0)
        recommended = fix_options[rec_idx]
        repair_name = _action_to_repair_name(recommended["action"])
        if repair_name is None:
            logger.debug(
                "No repair mapping for action '%s', skipping",
                recommended["action"],
            )
            continue

        try:
            func = _get_repair_function(repair_name)
            func(ir, file_path)
            fixes_applied.append({
                "type": diagnosis["violation_type"],
                "action": recommended["action"],
                "description": recommended["description"],
                "confidence": recommended["confidence"],
            })
            logger.info(
                "Root cause fix applied: %s for %s",
                recommended["action"], diagnosis["violation_type"],
            )
        except Exception as exc:
            logger.warning(
                "Root cause fix %s failed: %s", recommended["action"], exc,
            )

    # Step 4: Re-run ERC for final count
    final_violations = parse_erc(file_path)

    return {
        "mode": "root_cause",
        "fixes_applied": fixes_applied,
        "iterations": 1,  # Single-pass: diagnosis replaces iteration
        "remaining_violations": len(final_violations),
        "pre_existing_documented": [
            {
                "type": v["violation"]["type"],
                "root_cause": v["root_cause"],
                "details": v["details"],
                "confidence": v["confidence"],
            }
            for v in pre_existing
        ],
        "benign_suppressed": len(benign),
        "config_issues": [
            {"type": v["violation"]["type"], "details": v["details"]}
            for v in config
        ],
        "summary": classified["summary"],
    }
