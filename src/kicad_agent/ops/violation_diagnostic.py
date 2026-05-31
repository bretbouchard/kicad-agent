"""ERC violation diagnostic -- root cause analysis and fix option generation.

For each fixable violation identified by classification, diagnoses the root
cause and generates targeted fix operations with multiple fix options, side
effect analysis, and confidence-rated recommendations.

Bridges the gap between "this violation is fixable" (classification) and
"here is exactly how to fix it" (execution). Diagnosis inspects IR state
to determine WHY a violation exists and proposes concrete fix actions
with tradeoffs.

Usage:
    from kicad_agent.ops.violation_diagnostic import diagnose_violations

    result = diagnose_violations(fixable_violations, ir, file_path)
    for diag in result["diagnoses"]:
        print(f"{diag['violation_type']}: {len(diag['fix_options'])} fix options")
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for diagnosis results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixOption:
    """A single fix option for a diagnosed violation.

    Attributes:
        action: Operation name e.g. "place_no_connect".
        params: Parameters for the operation.
        description: Human-readable fix description.
        side_effects: What else changes when this fix is applied.
        confidence: Reliability rating: "high", "medium", or "low".
    """

    action: str
    params: dict[str, Any]
    description: str
    side_effects: list[str]
    confidence: str


@dataclass(frozen=True)
class DiagnosisResult:
    """Root cause diagnosis for a single fixable violation.

    Attributes:
        violation_type: ERC violation type string (e.g. "pin_not_connected").
        position: (x, y) coordinate tuple of the violation, or None.
        root_cause: Machine-readable root cause identifier.
        details: Human-readable description of the diagnosis.
        fix_options: Ordered list of fix options (best first).
        recommended_fix_index: Index into fix_options for the recommended fix.
    """

    violation_type: str
    position: tuple[float, float] | None
    root_cause: str
    details: str
    fix_options: list[FixOption]
    recommended_fix_index: int


# ---------------------------------------------------------------------------
# Valid repair action names (T-40-06: validate action names against known set)
# ---------------------------------------------------------------------------

_VALID_ACTIONS = frozenset({
    "place_no_connect",
    "add_wire",
    "break_wire_shorts",
    "fix_shorted_nets",
    "add_power_flag",
    "erc_auto_fix",
})


# ---------------------------------------------------------------------------
# Type-specific diagnosis functions
# ---------------------------------------------------------------------------


def _diagnose_pin_not_connected(
    violation_data: dict[str, Any],
    ir_data: dict[str, Any],
) -> DiagnosisResult:
    """Diagnose a pin_not_connected violation.

    Fix option 1: place_no_connect at pin position (high confidence, no side effects).
    Fix option 2: add_wire from pin to nearest unconnected pin (medium confidence, may change routing).
    """
    v = violation_data["violation"]
    position = v["positions"][0] if v["positions"] else None

    fix_options = [
        FixOption(
            action="place_no_connect",
            params={"position": list(position) if position else []},
            description="Place a no-connect marker on the unconnected pin to suppress the ERC warning.",
            side_effects=[],
            confidence="high",
        ),
        FixOption(
            action="add_wire",
            params={"from_position": list(position) if position else [], "strategy": "nearest_unconnected"},
            description="Route a wire from the unconnected pin to the nearest compatible pin on the same net.",
            side_effects=["May change existing wire routing", "May create new junction points"],
            confidence="medium",
        ),
    ]

    return DiagnosisResult(
        violation_type=v["type"],
        position=tuple(position) if position else None,
        root_cause=violation_data["root_cause"],
        details=violation_data["details"],
        fix_options=fix_options,
        recommended_fix_index=0,
    )


def _diagnose_multiple_net_names(
    violation_data: dict[str, Any],
    ir_data: dict[str, Any],
) -> DiagnosisResult:
    """Diagnose a multiple_net_names violation.

    Fix option 1: break_wire_shorts for the conflicting net pair (high confidence).
    Fix option 2: fix_shorted_nets with keep_first strategy (medium confidence).
    """
    v = violation_data["violation"]
    position = v["positions"][0] if v["positions"] else None

    fix_options = [
        FixOption(
            action="break_wire_shorts",
            params={"position": list(position) if position else [], "strategy": "shortest_path"},
            description="Remove the wire segment that bridges the conflicting nets, breaking the short circuit.",
            side_effects=["Removes a wire segment", "Nets will no longer be connected at this point"],
            confidence="high",
        ),
        FixOption(
            action="fix_shorted_nets",
            params={"position": list(position) if position else [], "strategy": "keep_first"},
            description="Remove the conflicting net label, keeping only the first named net at this position.",
            side_effects=["Removes a net label", "May remove a needed label if net name choice is wrong"],
            confidence="medium",
        ),
    ]

    return DiagnosisResult(
        violation_type=v["type"],
        position=tuple(position) if position else None,
        root_cause=violation_data["root_cause"],
        details=violation_data["details"],
        fix_options=fix_options,
        recommended_fix_index=0,
    )


def _diagnose_power_pin_not_driven(
    violation_data: dict[str, Any],
    ir_data: dict[str, Any],
) -> DiagnosisResult:
    """Diagnose a power_pin_not_driven violation (non-power-global).

    Fix option 1: add_power_flag at violation position (high confidence).
    """
    v = violation_data["violation"]
    position = v["positions"][0] if v["positions"] else None

    fix_options = [
        FixOption(
            action="add_power_flag",
            params={"position": list(position) if position else []},
            description="Place a PWR_FLAG symbol at the violation position to satisfy the power pin drive requirement.",
            side_effects=["Adds a PWR_FLAG symbol to the schematic"],
            confidence="high",
        ),
    ]

    return DiagnosisResult(
        violation_type=v["type"],
        position=tuple(position) if position else None,
        root_cause=violation_data["root_cause"],
        details=violation_data["details"],
        fix_options=fix_options,
        recommended_fix_index=0,
    )


def _diagnose_generic(
    violation_data: dict[str, Any],
    ir_data: dict[str, Any],
) -> DiagnosisResult:
    """Diagnose an unknown violation type with a generic fix suggestion.

    Fix option: erc_auto_fix with targeted repair (low confidence, broad approach).
    """
    v = violation_data["violation"]
    position = v["positions"][0] if v["positions"] else None

    fix_options = [
        FixOption(
            action="erc_auto_fix",
            params={"violation_type": v["type"], "position": list(position) if position else []},
            description=f"Apply generic ERC auto-fix for violation type '{v['type']}'.",
            side_effects=["May modify wires, labels, or symbols in the schematic"],
            confidence="low",
        ),
    ]

    return DiagnosisResult(
        violation_type=v["type"],
        position=tuple(position) if position else None,
        root_cause=violation_data["root_cause"],
        details=violation_data["details"],
        fix_options=fix_options,
        recommended_fix_index=0,
    )


# ---------------------------------------------------------------------------
# Diagnosis dispatch -- maps violation type to diagnosis function
# ---------------------------------------------------------------------------

_DIAGNOSIS_STRATEGIES: dict[str, callable] = {
    "pin_not_connected": _diagnose_pin_not_connected,
    "multiple_net_names": _diagnose_multiple_net_names,
    "power_pin_not_driven": _diagnose_power_pin_not_driven,
}


def _get_strategy(violation_type: str) -> callable:
    """Get the diagnosis strategy function for a violation type.

    Falls back to _diagnose_generic for unknown types.
    """
    return _DIAGNOSIS_STRATEGIES.get(violation_type, _diagnose_generic)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_ir_data(ir: Any) -> dict[str, Any]:
    """Extract position data from IR for diagnosis strategies.

    Uses get_pin_positions(), get_wire_endpoints(), get_label_positions().
    Handles both real SchematicIR and mock objects gracefully.
    """
    try:
        pin_positions = ir.get_pin_positions()
    except Exception:
        pin_positions = []
    try:
        wire_endpoints = ir.get_wire_endpoints()
    except Exception:
        wire_endpoints = []
    try:
        label_positions = ir.get_label_positions()
    except Exception:
        label_positions = []
    return {
        "pin_positions": pin_positions,
        "wire_endpoints": wire_endpoints,
        "label_positions": label_positions,
    }


def _fix_option_to_dict(fo: FixOption) -> dict[str, Any]:
    """Convert a FixOption dataclass to a dict for JSON serialization."""
    return {
        "action": fo.action,
        "params": fo.params,
        "description": fo.description,
        "side_effects": fo.side_effects,
        "confidence": fo.confidence,
    }


def _diagnosis_to_dict(dr: DiagnosisResult) -> dict[str, Any]:
    """Convert a DiagnosisResult to a dict for JSON serialization."""
    return {
        "violation_type": dr.violation_type,
        "position": list(dr.position) if dr.position is not None else None,
        "root_cause": dr.root_cause,
        "details": dr.details,
        "fix_options": [_fix_option_to_dict(fo) for fo in dr.fix_options],
        "recommended_fix_index": dr.recommended_fix_index,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diagnose_violations(
    violations: list[dict[str, Any]],
    ir: Any,
    file_path: Path,
    violation_types: list[str] | None = None,
) -> dict[str, Any]:
    """Diagnose root causes for fixable violations and generate fix options.

    For each classified fixable violation, dispatches to a type-specific
    diagnosis function that analyzes IR state and generates concrete fix
    options with side effect analysis and confidence ratings.

    Args:
        violations: List of classified violation dicts from classify_violations()["fixable"].
            Each dict must have "violation" (with "type", "positions"), "root_cause", "details".
        ir: SchematicIR for the target schematic (used for position queries).
        file_path: Path to the schematic file (for logging context).
        violation_types: Optional filter -- only diagnose these violation types.

    Returns:
        Dict with:
            diagnoses: list of diagnosis result dicts (each with fix_options).
            total_fixable: total number of fixable violations provided.
            total_diagnosed: number of violations actually diagnosed.
    """
    ir_data = _extract_ir_data(ir)

    # Filter by violation_types if specified
    target_violations = violations
    if violation_types is not None:
        target_violations = [
            v for v in violations
            if v["violation"]["type"] in violation_types
        ]

    diagnoses: list[dict[str, Any]] = []

    for violation_data in target_violations:
        vtype = violation_data["violation"]["type"]
        strategy = _get_strategy(vtype)

        try:
            result = strategy(violation_data, ir_data)
            # T-40-06: Validate action names against known set
            for fo in result.fix_options:
                if fo.action not in _VALID_ACTIONS:
                    logger.warning(
                        "Unknown fix action '%s' for violation type '%s'",
                        fo.action, vtype,
                    )
            diagnoses.append(_diagnosis_to_dict(result))
        except Exception as exc:
            logger.error(
                "Diagnosis failed for violation type '%s': %s",
                vtype, exc,
            )
            # Fall back to generic diagnosis on error
            result = _diagnose_generic(violation_data, ir_data)
            diagnoses.append(_diagnosis_to_dict(result))

    logger.info(
        "Diagnosed %d/%d fixable violations for %s",
        len(diagnoses), len(violations), file_path.name,
    )

    return {
        "diagnoses": diagnoses,
        "total_fixable": len(violations),
        "total_diagnosed": len(diagnoses),
    }
