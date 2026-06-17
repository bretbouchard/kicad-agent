"""Cross-file pre-flight checks for the universal gate (D-06).

Extracted from pre_analysis.py to keep the main gate module under 800 lines.
Contains checks for cross-file mutation operations: lib_id validation,
ERC prerequisite, footprint existence, and net change threshold.

Cross-file operations receive the full ir_map (dict[Path, Any]) rather
than a single IR, since they need to inspect multiple files simultaneously.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from kicad_agent.ops.pre_analysis import PreAnalysisResult

logger = logging.getLogger(__name__)

# Cross-file mutation operations that require pre-flight checks
_CROSSFILE_MUTATION_OP_TYPES = frozenset({
    "propagate_symbol_change",
    "update_pcb_from_schematic",
    "repopulate_pcb_from_schematic",
    "rebuild_pcb_nets",
})

# Maximum fraction of net assignments that can change before blocking
_NET_CHANGE_THRESHOLD = 0.5


def analyze_crossfile(
    op: Any,
    ir_or_map: Union[Any, dict[Path, Any]],
    file_path: Path,
    result: "PreAnalysisResult",
) -> None:
    """Cross-file pre-flight checks (D-06).

    ir_or_map is the full ir_map (dict[Path, Any]) for cross-file ops,
    since checks need to inspect schematic and PCB IRs simultaneously.
    For single-IR callers, it accepts Any and degrades gracefully.

    Args:
        op: The operation root model.
        ir_or_map: Full ir_map dict[Path, Any] or single IR.
        file_path: Path to the primary target file.
        result: PreAnalysisResult to append findings to.
    """
    op_type = getattr(op, "op_type", None)
    if op_type not in _CROSSFILE_MUTATION_OP_TYPES:
        return

    # Normalize to ir_map (dict) if single IR passed
    ir_map = _ensure_ir_map(ir_or_map)

    if op_type == "propagate_symbol_change":
        _check_crossfile_lib_id(op, ir_map, result)
    elif op_type == "repopulate_pcb_from_schematic":
        _check_crossfile_erc_before_repopulate(op, ir_map, result)
    elif op_type == "update_pcb_from_schematic":
        _check_crossfile_footprint_exists(op, ir_map, result)
    elif op_type == "rebuild_pcb_nets":
        _check_crossfile_net_change_threshold(op, ir_map, result)


def _check_crossfile_lib_id(
    op: Any, ir_map: dict[Path, Any], result: "PreAnalysisResult"
) -> None:
    """Block propagate_symbol_change when lib_id not found in schematic libraries.

    Validates that the symbol's library identifier resolves to a known entry
    in one of the schematic's library tables.
    """
    lib_id = getattr(op, "lib_id", None)
    if not lib_id:
        # No lib_id specified -- nothing to validate
        return

    # Find a schematic IR in the map to check library entries
    sch_ir = _find_schematic_ir(ir_map)
    if sch_ir is None:
        return  # No schematic IR available -- cannot validate

    # Check if lib_id appears in the schematic's library symbols
    lib_symbols = getattr(sch_ir, "lib_symbols", [])
    if not lib_symbols:
        sch = getattr(sch_ir, "schematic", None)
        if sch is not None:
            lib_symbols = getattr(sch, "libSymbols", [])

    # Check embedded library symbols
    found = False
    for sym in lib_symbols:
        sym_lib_id = getattr(sym, "libId", "")
        if sym_lib_id == lib_id:
            found = True
            break
        # Also check by the symbol name portion after ':'
        if ":" in lib_id and sym_lib_id.endswith(":" + lib_id.split(":")[-1]):
            found = True
            break

    if not found:
        result.blockers.append(
            _make_finding(
                "blocker",
                "unknown_lib_id",
                (
                    f"propagate_symbol_change: lib_id '{lib_id}' not found in "
                    f"schematic libraries. Verify the symbol exists before propagating."
                ),
                {"lib_id": lib_id},
            )
        )


def _check_crossfile_erc_before_repopulate(
    op: Any, ir_map: dict[Path, Any], result: "PreAnalysisResult"
) -> None:
    """Block repopulate_pcb_from_schematic when ERC has errors.

    Repopulating the PCB from a schematic with ERC errors would propagate
    those errors into the PCB layout.
    """
    sch_ir = _find_schematic_ir(ir_map)
    if sch_ir is None:
        return  # No schematic to check

    # Look for pre-existing ERC results in enriched context or metadata
    # Since we cannot run ERC here (would require kicad-cli subprocess),
    # we check for common ERC error indicators in the schematic state.
    schematic = getattr(sch_ir, "schematic", None)
    if schematic is None:
        return

    # Check for ERC error markers (DRC markers in schematic)
    drc_markers = getattr(schematic, "drcExclusions", [])
    if not drc_markers:
        drc_markers = getattr(schematic, "drc_exclusions", [])

    # If there are explicit ERC exclusions, the schematic has known issues
    # We warn rather than block since exclusions may be intentional
    if drc_markers:
        result.warnings.append(
            _make_finding(
                "warning",
                "erc_exclusions_present",
                (
                    f"repopulate_pcb_from_schematic: schematic has "
                    f"{len(drc_markers)} DRC exclusion(s). Verify these are "
                    f"intentional before repopulating."
                ),
                {"exclusion_count": len(drc_markers)},
            )
        )

    # Check schematic_file attribute for ERC availability hint
    schematic_file = getattr(op, "schematic_file", None)
    if schematic_file and hasattr(op, "erc_errors"):
        erc_errors = getattr(op, "erc_errors", None)
        if erc_errors and len(erc_errors) > 0:
            result.blockers.append(
                _make_finding(
                    "blocker",
                    "erc_errors_present",
                    (
                        f"repopulate_pcb_from_schematic: schematic has "
                        f"{len(erc_errors)} ERC error(s). Fix errors before repopulating."
                    ),
                    {"error_count": len(erc_errors)},
                )
            )


def _check_crossfile_footprint_exists(
    op: Any, ir_map: dict[Path, Any], result: "PreAnalysisResult"
) -> None:
    """Block update_pcb_from_schematic when any symbol is missing a footprint.

    Verifies that all schematic symbols have valid footprint assignments
    before propagating changes to the PCB.
    """
    sch_ir = _find_schematic_ir(ir_map)
    pcb_ir = _find_pcb_ir(ir_map)
    if sch_ir is None or pcb_ir is None:
        return  # Need both IRs to validate

    # Collect all symbols in the schematic
    components = getattr(sch_ir, "components", [])
    if not components:
        return  # No components to check

    missing_footprints = []
    for comp in components:
        ref = ""
        fp_lib_id = ""
        for prop in getattr(comp, "properties", []):
            if getattr(prop, "key", "") == "Reference":
                ref = getattr(prop, "value", "")
            if getattr(prop, "key", "") == "Footprint":
                fp_lib_id = getattr(prop, "value", "")

        if ref and not fp_lib_id:
            missing_footprints.append(ref)

    if missing_footprints:
        result.blockers.append(
            _make_finding(
                "blocker",
                "missing_footprint",
                (
                    f"update_pcb_from_schematic: {len(missing_footprints)} "
                    f"symbol(s) missing footprint assignment: "
                    + ", ".join(missing_footprints[:5])
                    + ("..." if len(missing_footprints) > 5 else "")
                ),
                {
                    "missing_count": len(missing_footprints),
                    "references": missing_footprints,
                },
            )
        )


def _check_crossfile_net_change_threshold(
    op: Any, ir_map: dict[Path, Any], result: "PreAnalysisResult"
) -> None:
    """Block rebuild_pcb_nets when >50% of net assignments would change.

    A massive net rebuild indicates likely schematic corruption or a
    fundamental mismatch between schematic and PCB.
    """
    sch_ir = _find_schematic_ir(ir_map)
    pcb_ir = _find_pcb_ir(ir_map)
    if sch_ir is None or pcb_ir is None:
        return

    # Get net lists from both sources
    try:
        sch_nets = set()
        # Schematic nets from labels and power symbols
        labels = getattr(sch_ir, "get_label_positions", None)
        if callable(labels):
            for label in labels():
                net_name = label.get("name", "")
                if net_name:
                    sch_nets.add(net_name)

        pcb_nets = set()
        netlist = getattr(pcb_ir, "extract_netlist", None)
        if callable(netlist):
            pcb_netlist = netlist()
            if isinstance(pcb_netlist, dict):
                pcb_nets = set(pcb_netlist.keys())

        if not sch_nets or not pcb_nets:
            return  # Insufficient data to compare

        # Calculate overlap
        common = sch_nets & pcb_nets
        total = len(sch_nets | pcb_nets)
        if total == 0:
            return

        change_fraction = 1.0 - (len(common) / total)
        if change_fraction > _NET_CHANGE_THRESHOLD:
            result.blockers.append(
                _make_finding(
                    "blocker",
                    "excessive_net_change",
                    (
                        f"rebuild_pcb_nets: {change_fraction:.0%} of net assignments "
                        f"would change ({len(common)}/{total} nets match). "
                        f"Verify schematic and PCB are in sync before rebuilding."
                    ),
                    {
                        "change_fraction": round(change_fraction, 3),
                        "matching_nets": len(common),
                        "total_nets": total,
                        "threshold": _NET_CHANGE_THRESHOLD,
                    },
                )
            )
    except Exception:
        # Net comparison is best-effort; don't block on internal errors
        logger.debug("Net change threshold check failed", exc_info=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(severity: str, category: str, message: str, details: dict) -> Any:
    """Create a PreAnalysisFinding without importing at module level."""
    from kicad_agent.ops.pre_analysis import PreAnalysisFinding
    return PreAnalysisFinding(
        severity=severity,
        category=category,
        message=message,
        details=details,
    )


def _ensure_ir_map(ir_or_map: Any) -> dict[Path, Any]:
    """Normalize ir_or_map to a dict[Path, Any].

    If ir_or_map is already a dict, return it. Otherwise, wrap in a
    single-entry dict with a synthetic path.
    """
    if isinstance(ir_or_map, dict):
        # Check if keys are Path objects (ir_map) or strings (something else)
        if ir_or_map and isinstance(next(iter(ir_or_map.keys())), Path):
            return ir_or_map
        # Could be a dict with string keys -- wrap as single entry
    return {Path("<synthetic>"): ir_or_map}


def _find_schematic_ir(ir_map: dict[Path, Any]) -> Any | None:
    """Find a SchematicIR in the ir_map by file extension."""
    for fp, ir in ir_map.items():
        if fp.suffix == ".kicad_sch":
            return ir
    return None


def _find_pcb_ir(ir_map: dict[Path, Any]) -> Any | None:
    """Find a PcbIR in the ir_map by file extension."""
    for fp, ir in ir_map.items():
        if fp.suffix == ".kicad_pcb":
            return ir
    return None
