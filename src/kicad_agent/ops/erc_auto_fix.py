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

# Repair functions authorized to add symbols.
# Issue #3: place_missing_units was adding 192 unauthorized components.
# Only add_power_flags is now authorized — it only adds PWR_FLAG symbols.
# place_missing_units must be audited before re-enabling.
_AUTHORIZED_SYMBOL_ADDITIONS = frozenset({
    "add_power_flags",       # adds PWR_FLAG power symbols only
})

# Maximum number of symbols a single repair may add. Even authorized
# repairs are capped to prevent runaway additions.
_MAX_SYMBOL_ADDITIONS_PER_REPAIR = 20


def _snapshot_ir_inventory(ir: SchematicIR) -> dict[str, int]:
    """Count schematic symbols and wires for scope-violation detection."""
    from kiutils.items.schitems import Connection
    sch = ir._parse_result.kiutils_obj
    symbol_count = len(sch.schematicSymbols)
    wire_count = sum(
        1 for item in sch.graphicalItems
        if isinstance(item, Connection) and getattr(item, "type", None) == "wire"
    )
    return {"symbols": symbol_count, "wires": wire_count}


# ---------------------------------------------------------------------------
# Violation type -> repair function mapping
# ---------------------------------------------------------------------------

# Maps ErcViolation.type strings to the repair function name in this module.
# These type strings come from kicad-cli ERC output as surfaced by parse_erc.
VIOLATION_REPAIR_MAP: dict[str, str] = {
    "pin_not_connected": "place_no_connects_from_erc",
    "power_pin_not_driven": "add_power_flags",
    "pin_to_pin": "fix_pin_type_mismatches",
    "label_multiple_wires": "add_junctions_at_labels",
    # Issue #3: place_missing_units removed from auto-fix. It created 192
    # unauthorized components. Re-enable only after audit with strict limits.
    # "missing_power_pin": "place_missing_units",
}

# Repair priority order. Shorts cause cascading errors and must be fixed first.
# Then pin type conflicts, power flags, and finally cosmetic fixes.
# Issue #3: place_missing_units removed from priority list.
# Phase 67: resolve_shorted_nets replaces separate break_wire_shorts + fix_shorted_nets
# calls with a single atomic operation (smart strategy: wire break then label fix).
REPAIR_PRIORITY: list[str] = [
    "resolve_shorted_nets",    # atomic short resolution (break + fix)
    "fix_pin_type_mismatches", # type conflicts
    "add_power_flags",         # power pin issues (maps from power_pin_not_driven)
    "place_no_connects_from_erc",  # unconnected pins / cosmetic (maps from pin_not_connected)
    "add_junctions_at_labels", # label at wire intersections (maps from label_multiple_wires)
    "snap_to_grid",            # off-grid / cosmetic
]


def _get_repair_function(repair_name: str) -> Any:
    """Import and return the repair function by name.

    Import paths follow the lazy-import pattern used throughout the executor.
    """
    if repair_name == "place_no_connects_from_erc":
        from kicad_agent.ops.repair_erc import place_no_connects_from_erc
        return place_no_connects_from_erc
    elif repair_name == "add_power_flags":
        from kicad_agent.ops.repair_erc import add_power_flags
        return add_power_flags
    elif repair_name == "fix_pin_type_mismatches":
        from kicad_agent.ops.repair_components import fix_pin_type_mismatches
        return fix_pin_type_mismatches
    elif repair_name == "place_missing_units":
        from kicad_agent.ops.repair_components import place_missing_units
        return place_missing_units
    elif repair_name == "break_wire_shorts":
        from kicad_agent.ops.repair_wires import break_wire_shorts
        return break_wire_shorts
    elif repair_name == "resolve_shorted_nets":
        from kicad_agent.ops.repair_nets import resolve_shorted_nets
        return resolve_shorted_nets
    elif repair_name == "snap_to_grid":
        from kicad_agent.ops.repair_wires import snap_to_grid
        return snap_to_grid
    elif repair_name == "add_junctions_at_labels":
        from kicad_agent.ops.repair_erc import add_junctions_at_labels
        return add_junctions_at_labels
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
        return "resolve_shorted_nets"
    if "off_grid" in vtype.lower():
        return "snap_to_grid"

    return None


# ---------------------------------------------------------------------------
# Root cause mode helpers
# ---------------------------------------------------------------------------

# Maps diagnosis action names to existing repair function names.
_ACTION_TO_REPAIR_MAP: dict[str, str] = {
    "place_no_connect": "place_no_connects_from_erc",
    "break_wire_shorts": "resolve_shorted_nets",
    "fix_shorted_nets": "resolve_shorted_nets",
    "resolve_shorted_nets": "resolve_shorted_nets",
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
    sheet_filter: str | None = "/",
    verify: bool = False,
) -> dict[str, Any]:
    """Run ERC, dispatch repairs by violation type, iterate until resolved.

    Supports two modes:
    - ``symptom`` (default): existing iteration-based repair. Groups violations
      by type and dispatches repair functions in priority order.
    - ``root_cause``: classify first, diagnose fixable violations, apply targeted
      fixes, document pre-existing issues, suppress benign noise. Single-pass.

    Phase 70: When verify=True, takes a net snapshot before each repair and
    diffs after. If a regression is detected, rolls back the IR and skips
    that repair.

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the schematic file (for ERC invocation).
        max_iterations: Maximum repair iterations (default 3, max 10 enforced by schema).
        mode: ``"symptom"`` for existing behavior, ``"root_cause"`` for classify-diagnose-fix.
        fix_classes: In root_cause mode, only fix these classes. None = fixable only.
        sheet_filter: Only fix violations from this sheet path.
        verify: If True, verify net topology after each repair and rollback on regression.

    Returns:
        Dict with:
            fixes_applied: List of {type, count, repair} dicts for each violation type fixed.
            iterations: Number of iterations actually run.
            remaining_violations: Count of violations after last iteration.
            unhandled_violations: List of {type, count} for unmapped violation types.
            verification_rollback: List of repairs that were rolled back (when verify=True).
    """
    if mode == "root_cause":
        return erc_auto_fix_root_cause(
            ir, file_path, max_iterations, fix_classes, sheet_filter
        )

    # --- Symptom mode: existing iteration-based repair ---
    all_fixes: list[dict[str, Any]] = []
    all_unhandled: dict[str, int] = {}
    verification_rollback: list[dict[str, Any]] = []
    iteration_count = 0
    previous_count = -1

    # Known limitation (Council M-03): The IR object is NOT re-parsed between
    # iterations. Repair functions mutate the IR in memory, so later iterations
    # operate on the same (mutated) IR. This is acceptable because parse_erc
    # re-reads the file from disk for fresh ERC results, and the early-stop
    # heuristic catches stagnation.

    for iteration in range(max_iterations):
        violations = parse_erc(file_path)

        # Bug B fix: filter to current sheet only. In hierarchical schematics,
        # ERC reports violations from all sheets but the IR only has data for
        # one sheet. Fixing cross-sheet violations causes no_connect_dangling
        # and missing-label regressions.
        if sheet_filter is not None:
            violations = [v for v in violations if v.sheet == sheet_filter]

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

                # Phase 70: Pre-repair checkpoint and snapshot when verify=True
                checkpoint = None
                snapshot_before = None
                if verify:
                    from kicad_agent.ops.repair_erc import _checkpoint_ir
                    from kicad_agent.ops.repair_nets import _take_net_snapshot
                    checkpoint = _checkpoint_ir(ir)
                    snapshot_before = _take_net_snapshot(ir)

                # Scope guard: snapshot inventory before repair (issue #3).
                # Always checkpoint for rollback regardless of verify flag.
                # If checkpoint fails (e.g. mock IR in tests), skip scope guard.
                scope_checkpoint = None
                inventory_before = None
                try:
                    from kicad_agent.ops.repair_erc import _checkpoint_ir as _ckpt
                    scope_checkpoint = _ckpt(ir)
                    inventory_before = _snapshot_ir_inventory(ir)
                except Exception:
                    pass

                # Call the repair function with (ir, file_path) and default args.
                # Council KR-04: auto-detect mode -- functions infer what to fix from IR state.
                func(ir, file_path)

                # Scope guard: detect unauthorized additions (issue #3).
                # No repair function should add wires. Only place_missing_units
                # and add_power_flags may add symbols.
                if scope_checkpoint is not None and inventory_before is not None:
                    inventory_after = _snapshot_ir_inventory(ir)
                    wire_delta = inventory_after["wires"] - inventory_before["wires"]
                    symbol_delta = inventory_after["symbols"] - inventory_before["symbols"]

                    # Diagnostic: always log inventory changes for forensics
                    if wire_delta != 0 or symbol_delta != 0:
                        logger.info(
                            "Repair %s inventory: symbols %d->%d (%+d), "
                            "wires %d->%d (%+d)",
                            repair_name,
                            inventory_before["symbols"], inventory_after["symbols"],
                            symbol_delta,
                            inventory_before["wires"], inventory_after["wires"],
                            wire_delta,
                        )

                    if wire_delta > 0:
                        logger.error(
                            "Scope violation: repair %s added %d wires (expected 0). "
                            "Rolling back. Before: %d wires, After: %d wires.",
                            repair_name, wire_delta,
                            inventory_before["wires"], inventory_after["wires"],
                        )
                        from kicad_agent.ops.repair_erc import _restore_ir
                        _restore_ir(ir, scope_checkpoint)
                        ir.schematic.to_file(str(file_path))
                        verification_rollback.append({
                            "repair": repair_name,
                            "reason": f"added {wire_delta} wires",
                            "inventory_before": inventory_before,
                            "inventory_after": inventory_after,
                        })
                        continue

                    if symbol_delta > 0 and repair_name not in _AUTHORIZED_SYMBOL_ADDITIONS:
                        logger.error(
                            "Scope violation: repair %s added %d symbols (expected 0). "
                            "Rolling back. Before: %d symbols, After: %d symbols.",
                            repair_name, symbol_delta,
                            inventory_before["symbols"], inventory_after["symbols"],
                        )
                        from kicad_agent.ops.repair_erc import _restore_ir
                        _restore_ir(ir, scope_checkpoint)
                        ir.schematic.to_file(str(file_path))
                        verification_rollback.append({
                            "repair": repair_name,
                            "reason": f"added {symbol_delta} unauthorized symbols",
                            "inventory_before": inventory_before,
                            "inventory_after": inventory_after,
                        })
                        continue

                    # Issue #3: Cap authorized symbol additions
                    if symbol_delta > _MAX_SYMBOL_ADDITIONS_PER_REPAIR:
                        logger.error(
                            "Scope violation: repair %s added %d symbols (max %d). "
                            "Rolling back. Before: %d symbols, After: %d symbols.",
                            repair_name, symbol_delta, _MAX_SYMBOL_ADDITIONS_PER_REPAIR,
                            inventory_before["symbols"], inventory_after["symbols"],
                        )
                        from kicad_agent.ops.repair_erc import _restore_ir
                        _restore_ir(ir, scope_checkpoint)
                        ir.schematic.to_file(str(file_path))
                        verification_rollback.append({
                            "repair": repair_name,
                            "reason": f"added {symbol_delta} symbols (exceeds cap of {_MAX_SYMBOL_ADDITIONS_PER_REPAIR})",
                            "inventory_before": inventory_before,
                            "inventory_after": inventory_after,
                        })
                        continue

                # Persist in-memory mutations to disk so parse_erc sees changes.
                ir.schematic.to_file(str(file_path))

                # Phase 70: Post-repair verification — rollback on regression
                if verify and snapshot_before is not None:
                    from kicad_agent.ops.repair_nets import (
                        _diff_net_snapshots,
                        _take_net_snapshot as _snap,
                    )
                    from kicad_agent.ops.repair_erc import _restore_ir
                    snapshot_after = _snap(ir)
                    diff = _diff_net_snapshots(snapshot_before, snapshot_after)
                    if not diff["clean"]:
                        logger.warning(
                            "Repair %s caused net regression (lost=%d, gained=%d), rolling back",
                            repair_name,
                            diff["lost_net_count"],
                            diff["gained_net_count"],
                        )
                        if checkpoint is not None:
                            _restore_ir(ir, checkpoint)
                            # Persist restored state to disk
                            ir.schematic.to_file(str(file_path))
                        verification_rollback.append({
                            "repair": repair_name,
                            "lost_nets": diff["lost_nets"],
                            "gained_nets": diff["gained_nets"],
                        })
                        continue

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
        "verification_rollback": verification_rollback,
    }


def erc_auto_fix_root_cause(
    ir: SchematicIR,
    file_path: Path,
    max_iterations: int = 3,
    fix_classes: list[str] | None = None,
    sheet_filter: str | None = "/",
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
        sheet_filter: Only fix violations from this sheet path.
            Defaults to "/" (root sheet only). Pass None for all sheets.

    Returns:
        Dict with mode, fixes_applied, iterations, remaining_violations,
        pre_existing_documented, benign_suppressed, config_issues, summary.
    """
    from kicad_agent.ops.violation_classifier import classify_violations
    from kicad_agent.ops.violation_diagnostic import diagnose_violations

    violations = parse_erc(file_path)

    # Bug B fix: filter to current sheet only in hierarchical schematics.
    if sheet_filter is not None:
        violations = [v for v in violations if v.sheet == sheet_filter]

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
            # Persist in-memory mutations to disk so parse_erc sees changes.
            ir.schematic.to_file(str(file_path))
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


# ---------------------------------------------------------------------------
# Hierarchical ERC auto-fix
# ---------------------------------------------------------------------------


def _discover_sub_sheets(
    file_path: Path,
    parent_path: str = "/",
) -> dict[str, Path]:
    """Walk hierarchical schematic and return {erc_sheet_path: file_path} mapping.

    Recursively reads HierarchicalSheet objects from each schematic file and
    builds a flat dictionary mapping ERC sheet paths (e.g. ``/Input Stage/``)
    to their corresponding file paths.

    Args:
        file_path: Path to a .kicad_sch file.
        parent_path: ERC sheet path for the parent (default "/" for root).

    Returns:
        Dict mapping ERC sheet path strings to Path objects.
    """
    from kiutils.schematic import Schematic as KiutilsSchematic

    result: dict[str, Path] = {}
    try:
        sch = KiutilsSchematic.from_file(str(file_path))
    except Exception:
        return result

    for sheet in sch.sheets:
        sheet_name = getattr(sheet, "sheetName", None)
        file_name_prop = getattr(sheet, "fileName", None)
        if sheet_name is None or file_name_prop is None:
            continue

        name = sheet_name.value if hasattr(sheet_name, "value") else str(sheet_name)
        fname = file_name_prop.value if hasattr(file_name_prop, "value") else str(file_name_prop)

        if not fname:
            continue

        child_path = file_path.parent / fname
        erc_path = f"{parent_path}{name}/"

        result[erc_path] = child_path

        # Recurse into child sheets
        if child_path.exists():
            result.update(_discover_sub_sheets(child_path, erc_path))

    return result


def _deregister_parse_result(parse_result: Any) -> None:
    """Remove a ParseResult from the IR registry to prevent id() collisions.

    The IR registry tracks ParseResult objects by id() to enforce one-IR-per-
    ParseResult. When processing multiple sheets in a hierarchy, Python may
    reuse memory addresses after garbage collection, causing false collisions.
    Call this after each sheet's IR is no longer needed.
    """
    from kicad_agent.ir.base import _ir_registry, _ir_registry_lock

    pr_id = id(parse_result)
    with _ir_registry_lock:
        _ir_registry.discard(pr_id)


def erc_auto_fix_hierarchical(
    root_path: Path,
    max_iterations: int = 3,
    mode: str = "symptom",
) -> dict[str, Any]:
    """Run erc_auto_fix across all sheets in a hierarchical schematic.

    Discovers all sub-sheets from the root schematic, runs ERC once to get
    all violations, then applies erc_auto_fix on each sheet that has violations.
    Each sheet's IR is created separately so positions match correctly.

    Args:
        root_path: Path to the root .kicad_sch file.
        max_iterations: Maximum repair iterations per sheet (default 3).
        mode: ``"symptom"`` or ``"root_cause"`` (passed to erc_auto_fix).

    Returns:
        Dict with:
            total_sheets: Number of sheets processed.
            sheets_with_fixes: Number of sheets that had fixable violations.
            per_sheet: Dict mapping sheet_path to erc_auto_fix result.
            total_remaining: Sum of remaining violations across all sheets.
    """
    from kicad_agent.parser.schematic_parser import parse_schematic

    # Step 1: Run ERC once on root (gets violations from all sheets)
    all_violations = parse_erc(root_path)

    # Step 2: Group violations by sheet
    violations_by_sheet: dict[str, int] = {}
    for v in all_violations:
        violations_by_sheet[v.sheet] = violations_by_sheet.get(v.sheet, 0) + 1

    # Step 3: Discover all sub-sheets
    sub_sheets = _discover_sub_sheets(root_path)

    # Build full mapping: root "/" + all sub-sheets
    sheet_file_map: dict[str, Path] = {"/": root_path}
    sheet_file_map.update(sub_sheets)

    # Step 4: Process each sheet that has violations
    per_sheet: dict[str, dict[str, Any]] = {}
    sheets_with_fixes = 0

    for sheet_path, sheet_file in sheet_file_map.items():
        if violations_by_sheet.get(sheet_path, 0) == 0:
            continue

        if not sheet_file.exists():
            logger.warning("Sheet file not found: %s (%s)", sheet_path, sheet_file)
            continue

        # Parse the sheet and create IR
        parse_result = None
        try:
            parse_result = parse_schematic(sheet_file)
            sheet_ir = SchematicIR(_parse_result=parse_result)
        except Exception as exc:
            logger.warning("Failed to parse sheet %s: %s", sheet_path, exc)
            # Deregister ParseResult to prevent id() collision on reuse
            if parse_result is not None:
                _deregister_parse_result(parse_result)
            continue

        # Run erc_auto_fix on this sheet.
        # Individual sub-sheet files report all violations as sheet="/",
        # so we use "/" as sheet_filter for sub-sheets (not the hierarchical path).
        effective_filter = "/" if sheet_path != "/" else "/"

        # Issue #3 forensics: snapshot inventory before per-sheet repair.
        # Measures symbol/wire counts before and after to catch unauthorized
        # additions that the per-repair scope guard might miss.
        sheet_inventory_before: dict[str, int] | None = None
        try:
            sheet_inventory_before = _snapshot_ir_inventory(sheet_ir)
        except Exception:
            pass

        try:
            result = erc_auto_fix(
                sheet_ir,
                sheet_file,
                max_iterations=max_iterations,
                mode=mode,
                sheet_filter=effective_filter,
            )

            # Issue #3 forensics: log per-sheet inventory delta.
            if sheet_inventory_before is not None:
                try:
                    sheet_inventory_after = _snapshot_ir_inventory(sheet_ir)
                    sym_delta = sheet_inventory_after["symbols"] - sheet_inventory_before["symbols"]
                    wire_delta = sheet_inventory_after["wires"] - sheet_inventory_before["wires"]
                    if sym_delta != 0 or wire_delta != 0:
                        logger.info(
                            "Sheet %s inventory delta: symbols %+d, wires %+d "
                            "(before: %d sym / %d wire, after: %d sym / %d wire)",
                            sheet_path, sym_delta, wire_delta,
                            sheet_inventory_before["symbols"],
                            sheet_inventory_before["wires"],
                            sheet_inventory_after["symbols"],
                            sheet_inventory_after["wires"],
                        )
                except Exception:
                    pass

            per_sheet[sheet_path] = result
            if result.get("fixes_applied"):
                sheets_with_fixes += 1
        except Exception as exc:
            logger.warning("erc_auto_fix failed on sheet %s: %s", sheet_path, exc)
            per_sheet[sheet_path] = {"error": str(exc)}
        finally:
            # Deregister to prevent id() collision when Python reuses memory
            _deregister_parse_result(parse_result)

    # Step 5: Re-run ERC for final total count
    final_violations = parse_erc(root_path)
    total_remaining = len(final_violations)

    return {
        "total_sheets": len(sheet_file_map),
        "sheets_with_violations": len(violations_by_sheet),
        "sheets_with_fixes": sheets_with_fixes,
        "per_sheet": per_sheet,
        "total_remaining": total_remaining,
    }
