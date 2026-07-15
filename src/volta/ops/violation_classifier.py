"""ERC violation classifier -- rule-based classification into actionable categories.

Classifies ErcViolation instances into four categories:
- FIXABLE: can be automatically repaired (e.g. multiple_net_names, unconnected pins)
- PRE_EXISTING: caused by library/hierarchy config, not fixable by file editing
- BENIGN: expected by design, not real errors (e.g. unused units, cosmetic duplicates)
- CONFIG_ISSUE: external configuration needed (e.g. missing library)

Uses IR data (pin positions, net names, wire endpoints) to distinguish fixable
from pre-existing violations based on connectivity context.

Usage:
    from volta.ops.violation_classifier import classify_violations

    result = classify_violations(violations, ir, file_path)
    for cv in result["fixable"]:
        print(f"Fixable: {cv['root_cause']} ({cv['confidence']})")
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from volta.ops.erc_parser import ErcViolation

logger = logging.getLogger(__name__)


class ViolationCategory(str, Enum):
    """Classification categories for ERC violations."""

    FIXABLE = "FIXABLE"
    PRE_EXISTING = "PRE_EXISTING"
    BENIGN = "BENIGN"
    CONFIG_ISSUE = "CONFIG_ISSUE"


# ---------------------------------------------------------------------------
# Classification rules -- ordered list, first match wins
# ---------------------------------------------------------------------------

# Each rule is a (match_fn, category, root_cause, confidence) tuple.
# match_fn signature: (violation, ir_positions) -> bool

RuleTuple = tuple[
    callable,            # match function
    ViolationCategory,   # category
    str,                 # root_cause
    str,                 # confidence: "high", "medium", "low"
]


def _is_power_global(violation: ErcViolation, _ir_data: dict) -> bool:
    """power_pin_not_driven with '(power global)' in description."""
    return (
        violation.type == "power_pin_not_driven"
        and "(power global)" in violation.description
    )


def _is_orphaned_power_symbol(violation: ErcViolation, ir_data: dict) -> bool:
    """pin_not_connected on a #PWR symbol with no wire/label connection."""
    if violation.type != "pin_not_connected":
        return False
    # Check if any pin position near this violation is on a #PWR symbol
    pin_positions = ir_data.get("pin_positions", [])
    wire_endpoints = ir_data.get("wire_endpoints", [])
    label_positions = ir_data.get("label_positions", [])
    for pin in pin_positions:
        ref = pin.get("ref", "")
        pin_pos = pin.get("position")
        if not ref.startswith("#PWR") or pin_pos is None:
            continue
        # Check if violation position matches this pin
        for vp in violation.positions:
            if _positions_close(vp, pin_pos):
                # Check if no wire or label connects to this position
                if not _has_wire_or_label_at(pin_pos, wire_endpoints, label_positions):
                    return True
    return False


def _is_hierarchical_signal(violation: ErcViolation, _ir_data: dict) -> bool:
    """pin_not_driven connected only via global labels from another sheet."""
    return (
        violation.type == "pin_not_driven"
        and "global" in violation.description.lower()
    )


def _is_same_local_global_label(violation: ErcViolation, _ir_data: dict) -> bool:
    """same_local_global_label -> cosmetic duplicate."""
    return violation.type == "same_local_global_label"


def _is_missing_unit(violation: ErcViolation, _ir_data: dict) -> bool:
    """missing_unit -> unused unit by design."""
    return violation.type == "missing_unit"


def _is_lib_symbol_issues(violation: ErcViolation, _ir_data: dict) -> bool:
    """lib_symbol_issues -> missing library."""
    return violation.type == "lib_symbol_issues"


def _is_switch_diode_wire_dangling_fp(
    violation: ErcViolation, ir_data: dict
) -> bool:
    """wire_dangling on wires between switch and diode pins (KiCad 10 false positive).

    KiCad 10 ERC reports wire_dangling on properly-connected wires between
    switch pin2 and diode pin1 (cathode) in button matrix topology. These are
    real electrical connections that KiCad 10 fails to recognize.

    Requires both a switch symbol pin and a diode symbol pin near the violation
    position. Detection uses ref→lib_id map: 'Switch'/'Button' for switches,
    'Diode' for diodes.
    """
    if violation.type != "wire_dangling":
        return False

    pin_positions = ir_data.get("pin_positions", [])
    ref_to_lib_id = ir_data.get("ref_to_lib_id", {})
    has_switch_pin = False
    has_diode_pin = False

    for pin in pin_positions:
        pin_pos = (pin.get("x", 0), pin.get("y", 0))
        for vp in violation.positions:
            if not _positions_close(vp, pin_pos):
                continue
            ref = pin.get("reference", "")
            lib_id = ref_to_lib_id.get(ref, "").lower()
            if any(kw in lib_id for kw in ("switch", "button")):
                has_switch_pin = True
            if "diode" in lib_id:
                has_diode_pin = True

    return has_switch_pin and has_diode_pin


def _is_pin_to_pin_unspecified(violation: ErcViolation, _ir_data: dict) -> bool:
    """pin_to_pin with 'Unspecified' or 'unspecified' in description."""
    return (
        violation.type == "pin_to_pin"
        and ("unspecified" in violation.description.lower())
    )


def _is_multiple_net_names(violation: ErcViolation, _ir_data: dict) -> bool:
    """multiple_net_names -> net name conflict (fixable)."""
    return violation.type == "multiple_net_names"


def _is_pin_not_connected_default(violation: ErcViolation, ir_data: dict) -> bool:
    """pin_not_connected (non-power) -> can place no-connect marker."""
    if violation.type != "pin_not_connected":
        return False
    # Not on a #PWR symbol (those are caught by the earlier orphaned_power_symbol rule)
    pin_positions = ir_data.get("pin_positions", [])
    for pin in pin_positions:
        ref = pin.get("ref", "")
        pin_pos = pin.get("position")
        if ref.startswith("#PWR") and pin_pos is not None:
            for vp in violation.positions:
                if _positions_close(vp, pin_pos):
                    return False  # This is a #PWR pin, skip
    return True


def _is_power_pin_not_driven_default(violation: ErcViolation, _ir_data: dict) -> bool:
    """power_pin_not_driven without '(power global)' -> missing power symbol."""
    return violation.type == "power_pin_not_driven"


# Ordered rules: first match wins
_CLASSIFICATION_RULES: list[RuleTuple] = [
    # Pre-existing (library/hierarchy)
    (_is_power_global, ViolationCategory.PRE_EXISTING, "library_pin_type_mismatch", "high"),
    (_is_orphaned_power_symbol, ViolationCategory.PRE_EXISTING, "orphaned_power_symbol", "high"),
    (_is_hierarchical_signal, ViolationCategory.PRE_EXISTING, "hierarchical_signal", "high"),
    (_is_pin_to_pin_unspecified, ViolationCategory.PRE_EXISTING, "pin_type_in_library", "high"),
    # Benign
    (_is_same_local_global_label, ViolationCategory.BENIGN, "cosmetic_duplicate", "high"),
    (_is_missing_unit, ViolationCategory.BENIGN, "unused_unit_by_design", "high"),
    (_is_switch_diode_wire_dangling_fp, ViolationCategory.BENIGN, "kiCad10_wire_dangling_fp", "medium"),
    # Config issues
    (_is_lib_symbol_issues, ViolationCategory.CONFIG_ISSUE, "missing_library", "high"),
    # Fixable (specific)
    (_is_multiple_net_names, ViolationCategory.FIXABLE, "net_name_conflict", "high"),
    (_is_pin_not_connected_default, ViolationCategory.FIXABLE, "unconnected_pin", "high"),
    (_is_power_pin_not_driven_default, ViolationCategory.FIXABLE, "missing_power_symbol", "high"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_POSITION_TOLERANCE = 0.01  # mm


def _positions_close(
    a: tuple[float, float],
    b: tuple[float, float] | list[float],
) -> bool:
    """Check if two positions are within tolerance."""
    if isinstance(b, (list, tuple)) and len(b) >= 2:
        return abs(a[0] - b[0]) < _POSITION_TOLERANCE and abs(a[1] - b[1]) < _POSITION_TOLERANCE
    return False


def _has_wire_or_label_at(
    position: tuple[float, float],
    wire_endpoints: list[dict],
    label_positions: list[dict],
) -> bool:
    """Check if any wire endpoint or label is at the given position."""
    for we in wire_endpoints:
        we_pos = we.get("position")
        if we_pos is not None and _positions_close(position, we_pos):
            return True
    for lp in label_positions:
        lp_pos = lp.get("position")
        if lp_pos is not None and _positions_close(position, lp_pos):
            return True
    return False


def _extract_ir_data(ir: Any) -> dict[str, Any]:
    """Extract position data from IR for classification rules.

    Uses get_pin_positions(), get_wire_endpoints(), get_label_positions(),
    get_component_lib_ids().
    Handles both real SchematicIR and mock objects gracefully.
    """
    try:
        pin_positions = ir.get_pin_positions()
    except (AttributeError, TypeError, ValueError):
        pin_positions = []
    try:
        wire_endpoints = ir.get_wire_endpoints()
    except (AttributeError, TypeError, ValueError):
        wire_endpoints = []
    try:
        label_positions = ir.get_label_positions()
    except (AttributeError, TypeError, ValueError):
        label_positions = []
    try:
        lib_ids = ir.get_component_lib_ids()
        ref_to_lib_id = {ref: lib_id for ref, lib_id in lib_ids}
    except (AttributeError, TypeError, ValueError):
        ref_to_lib_id = {}
    return {
        "pin_positions": pin_positions,
        "wire_endpoints": wire_endpoints,
        "label_positions": label_positions,
        "ref_to_lib_id": ref_to_lib_id,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_violations(
    violations: list[ErcViolation],
    ir: Any,
    file_path: Path,
) -> dict[str, Any]:
    """Classify ERC violations into actionable categories.

    Applies rule-based classification to each violation, using IR data (pin
    positions, wire endpoints, label positions) to determine connectivity
    context. First matching rule wins.

    Args:
        violations: List of ErcViolation instances from parse_erc().
        ir: SchematicIR for the target schematic (used for position queries).
        file_path: Path to the schematic file (for logging context).

    Returns:
        Dict with:
            fixable: list of classified violation dicts.
            pre_existing: list of classified violation dicts.
            benign: list of classified violation dicts.
            config_issues: list of classified violation dicts.
            summary: dict with total, fixable, pre_existing, benign, config counts.
    """
    ir_data = _extract_ir_data(ir)

    fixable: list[dict] = []
    pre_existing: list[dict] = []
    benign: list[dict] = []
    config_issues: list[dict] = []

    for violation in violations:
        classified = _classify_one(violation, ir_data)
        category = classified["category"]

        if category == ViolationCategory.FIXABLE:
            fixable.append(classified)
        elif category == ViolationCategory.PRE_EXISTING:
            pre_existing.append(classified)
        elif category == ViolationCategory.BENIGN:
            benign.append(classified)
        elif category == ViolationCategory.CONFIG_ISSUE:
            config_issues.append(classified)

    summary = {
        "total": len(violations),
        "fixable": len(fixable),
        "pre_existing": len(pre_existing),
        "benign": len(benign),
        "config": len(config_issues),
    }

    logger.info(
        "Classified %d violations for %s: %d fixable, %d pre-existing, %d benign, %d config",
        summary["total"], file_path.name,
        summary["fixable"], summary["pre_existing"],
        summary["benign"], summary["config"],
    )

    return {
        "fixable": fixable,
        "pre_existing": pre_existing,
        "benign": benign,
        "config_issues": config_issues,
        "summary": summary,
    }


def _classify_one(
    violation: ErcViolation,
    ir_data: dict[str, Any],
) -> dict[str, Any]:
    """Classify a single violation using the rule list.

    Args:
        violation: ErcViolation to classify.
        ir_data: Pre-extracted IR position data.

    Returns:
        Dict with category, confidence, root_cause, details, and violation data.
    """
    for match_fn, category, root_cause, confidence in _CLASSIFICATION_RULES:
        if match_fn(violation, ir_data):
            return _build_classified(violation, category, confidence, root_cause)

    # Default: unknown fixable
    return _build_classified(
        violation,
        ViolationCategory.FIXABLE,
        "low",
        "unknown",
    )


def _build_classified(
    violation: ErcViolation,
    category: ViolationCategory,
    confidence: str,
    root_cause: str,
) -> dict[str, Any]:
    """Build a classified violation dict from components."""
    return {
        "category": category.value,
        "confidence": confidence,
        "root_cause": root_cause,
        "details": violation.description,
        "violation": {
            "sheet": violation.sheet,
            "type": violation.type,
            "severity": violation.severity,
            "description": violation.description,
            "positions": violation.positions,
        },
    }
