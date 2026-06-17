"""Expanded schematic pre-flight checks (D-07).

Extracted from pre_analysis.py to keep the main gate module under 800 lines.
Contains additional schematic mutation checks: swap_symbol pin compatibility,
regenerate_wiring force requirement, label wire references, wire endpoint
validation, and overlap checks for duplicate/array operations.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.ops.pre_analysis import PreAnalysisResult

logger = logging.getLogger(__name__)


def analyze_schematic_expanded(
    op: Any,
    ir: Any,
    result: "PreAnalysisResult",
) -> None:
    """Run expanded schematic checks (D-07).

    Called from PreAnalysisGate.analyze() after the existing schematic
    analysis for specific op_types that need additional validation.

    Args:
        op: The operation root model.
        ir: SchematicIR for the target schematic file.
        result: PreAnalysisResult to append findings to.
    """
    op_type = getattr(op, "op_type", None)

    if op_type == "swap_symbol":
        _check_swap_symbol_pin_count(op, ir, result)
    elif op_type == "regenerate_wiring":
        _check_regenerate_wiring_force(op, result)
    elif op_type == "remove_labels":
        _check_labels_wire_refs(op, ir, result)
    elif op_type == "add_wire":
        _check_wire_endpoints(op, ir, result)
    elif op_type in ("duplicate_component", "array_replicate"):
        _check_overlap_for_duplicate(op, ir, result)


def _check_swap_symbol_pin_count(
    op: Any, ir: Any, result: "PreAnalysisResult"
) -> None:
    """Block swap_symbol when new symbol pin count differs >20% from old."""
    reference = getattr(op, "reference", None)
    new_lib_id = getattr(op, "new_symbol_lib_id", None)
    if not reference:
        return

    component = ir.get_component_by_ref(reference)
    if component is None:
        return  # unknown_ref already caught by _check_ref_resolution

    old_pin_count = _count_symbol_pins(ir, reference)
    if old_pin_count == 0:
        return  # Cannot determine -- skip check

    new_pin_count = _count_lib_symbol_pins(ir, new_lib_id)

    if new_pin_count is not None and new_pin_count > 0 and old_pin_count > 0:
        ratio = abs(new_pin_count - old_pin_count) / old_pin_count
        if ratio > 0.20:
            result.blockers.append(_make_finding(
                "blocker",
                "pin_count_mismatch",
                (
                    f"swap_symbol: new symbol has {new_pin_count} pins, "
                    f"old has {old_pin_count} ({ratio:.0%} difference > 20% threshold). "
                    f"Verify pin compatibility before swapping."
                ),
                {
                    "reference": reference,
                    "old_pin_count": old_pin_count,
                    "new_pin_count": new_pin_count,
                    "difference_ratio": round(ratio, 3),
                },
            ))


def _check_regenerate_wiring_force(
    op: Any, result: "PreAnalysisResult"
) -> None:
    """Block regenerate_wiring unless force is True."""
    force = getattr(op, "force", False)
    if not force:
        result.blockers.append(_make_finding(
            "blocker",
            "force_required",
            (
                "regenerate_wiring requires force=True to proceed. "
                "This operation strips all existing wires and labels."
            ),
            {"op_type": "regenerate_wiring"},
        ))


def _check_labels_wire_refs(
    op: Any, ir: Any, result: "PreAnalysisResult"
) -> None:
    """Block remove_labels when any label is referenced by wires."""
    labels = getattr(op, "labels", [])
    if not labels:
        return

    label_names: set[str] = set()
    for lbl in labels:
        name = lbl if isinstance(lbl, str) else getattr(lbl, "name", "")
        if name:
            label_names.add(name)

    if not label_names:
        return

    wire_endpoints = ir.get_wire_endpoints()
    referenced_labels: list[str] = []

    for we in wire_endpoints:
        net_name = getattr(we, "net", None)
        if net_name and net_name in label_names:
            referenced_labels.append(net_name)

    if referenced_labels:
        unique_refs = list(set(referenced_labels))
        result.blockers.append(_make_finding(
            "blocker",
            "label_wire_reference",
            (
                f"remove_labels: {len(unique_refs)} label(s) are referenced by "
                f"wires: {', '.join(unique_refs)}. Remove wires first."
            ),
            {
                "referenced_labels": unique_refs,
                "label_count": len(unique_refs),
            },
        ))


def _check_wire_endpoints(
    op: Any, ir: Any, result: "PreAnalysisResult"
) -> None:
    """Warn when add_wire endpoints don't land on known pins or wire endpoints."""
    pin_positions = ir.get_pin_positions()
    wire_endpoints = ir.get_wire_endpoints()

    known_points: set[tuple[float, float]] = set()
    for pin in pin_positions:
        known_points.add((round(pin["x"], 2), round(pin["y"], 2)))
    for we in wire_endpoints:
        known_points.add((
            round(getattr(we, "start_x", 0.0), 2),
            round(getattr(we, "start_y", 0.0), 2),
        ))
        known_points.add((
            round(getattr(we, "end_x", 0.0), 2),
            round(getattr(we, "end_y", 0.0), 2),
        ))

    points_to_check: list[tuple[str, float, float]] = []
    start_x = getattr(op, "start_x", None)
    start_y = getattr(op, "start_y", None)
    end_x = getattr(op, "end_x", None)
    end_y = getattr(op, "end_y", None)
    if start_x is not None and start_y is not None:
        points_to_check.append(("start", start_x, start_y))
    if end_x is not None and end_y is not None:
        points_to_check.append(("end", end_x, end_y))

    floating = []
    for label, px, py in points_to_check:
        if (round(px, 2), round(py, 2)) not in known_points:
            floating.append(f"{label} ({px}, {py})")

    if floating:
        result.warnings.append(_make_finding(
            "warning",
            "floating_wire_endpoint",
            (
                f"add_wire: endpoint(s) not on known pins or wire ends: "
                + ", ".join(floating)
            ),
            {"floating_endpoints": floating},
        ))


def _check_overlap_for_duplicate(
    op: Any, ir: Any, result: "PreAnalysisResult"
) -> None:
    """Block duplicate_component/array_replicate when duplicates overlap existing."""
    from kicad_agent.ops.pre_analysis import (
        PreAnalysisGate,
        _estimated_bbox,
    )

    reference = getattr(op, "reference", None)
    position = getattr(op, "position", None)
    if not reference or position is None:
        return

    dest_x = getattr(position, "x", 0.0)
    dest_y = getattr(position, "y", 0.0)

    existing_positions = PreAnalysisGate._get_component_bounding_boxes(ir)
    lib_id = ""
    source_comp = ir.get_component_by_ref(reference)
    if source_comp is not None:
        lib_id = getattr(source_comp, "libId", "")

    new_bbox = _estimated_bbox(dest_x, dest_y, lib_id, 0.0)
    overlaps = PreAnalysisGate._find_overlaps(new_bbox, existing_positions)
    if overlaps:
        result.blockers.append(_make_finding(
            "blocker",
            "component_overlap",
            message=(
                f"{op.op_type}: duplicating {reference} to ({dest_x}, {dest_y}) "
                f"would overlap with: "
                + ", ".join(f"{o['ref']} at ({o['x']}, {o['y']})" for o in overlaps)
            ),
            details={
                "reference": reference,
                "destination": {"x": dest_x, "y": dest_y},
                "overlapping_components": overlaps,
            },
        ))


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


def _count_symbol_pins(ir: Any, reference: str) -> int:
    """Count the pins of a placed symbol via pin_positions."""
    pin_positions = ir.get_pin_positions()
    return sum(1 for p in pin_positions if p.get("reference") == reference)


def _count_lib_symbol_pins(ir: Any, lib_id: str | None) -> int | None:
    """Count pins for a library symbol by lib_id."""
    if lib_id is None:
        return None

    sch = getattr(ir, "schematic", None)
    if sch is None:
        return None

    lib_symbols = getattr(sch, "libSymbols", [])
    for sym in lib_symbols:
        sym_lib_id = getattr(sym, "libId", "")
        if sym_lib_id == lib_id:
            pin_count = 0
            for unit in getattr(sym, "units", []):
                pins = getattr(unit, "pins", [])
                pin_count += len(pins)
            if pin_count == 0:
                pins = getattr(sym, "pins", [])
                pin_count = len(pins)
            return pin_count if pin_count > 0 else None

    return None
