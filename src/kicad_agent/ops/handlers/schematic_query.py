"""Schematic query handlers -- read-only operations that inspect schematic files.

Handlers receive (op, SchematicIR, file_path) and return a result dict.
No Transaction wrapping, no serialization, no file writes.
"""

import dataclasses
import logging
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)

_SCHEMATIC_QUERY_HANDLERS: dict[str, Callable] = {}


def register_schematic_query(op_type: str) -> Callable:
    """Decorator to register a read-only schematic query operation handler."""
    def decorator(fn: Callable) -> Callable:
        _SCHEMATIC_QUERY_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_schematic_query("validate_refs")
def _handle_validate_refs(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    duplicates = ir.validate_reference_uniqueness()
    return {"duplicates": duplicates, "valid": len(duplicates) == 0}


@register_schematic_query("cross_ref_check")
def _handle_cross_ref_check(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    unresolved = ir.cross_reference_check()
    return {"unresolved": [{"ref": r, "lib_id": l} for r, l in unresolved]}


@register_schematic_query("validate_footprint")
def _handle_sch_validate_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.handlers.schematic import _validate_footprint_impl
    return _validate_footprint_impl(op.footprint_lib_id, file_path)


@register_schematic_query("verify_pin_map")
def _handle_verify_pin_map(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.verify_pin_map(reference=op.reference, footprint_lib_id=op.footprint_lib_id)


@register_schematic_query("validate_power_nets")
def _handle_validate_power_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.validation_gates import validate_power_nets
    return validate_power_nets(ir, file_path, check_hierarchical=op.check_hierarchical)


@register_schematic_query("validate_schematic")
def _handle_validate_schematic(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.validation_gates import validate_schematic_completeness
    return validate_schematic_completeness(
        file_path,
        check_symbol_resolution=op.check_symbol_resolution,
        check_format=op.check_format,
        check_power_nets=op.check_power_nets,
        check_annotation=op.check_annotation,
    )


@register_schematic_query("parse_erc")
def _handle_parse_erc(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.erc_parser import parse_erc
    violations = parse_erc(file_path)
    return {"violations": [dataclasses.asdict(v) for v in violations]}


@register_schematic_query("extract_violation_positions")
def _handle_extract_violation_positions(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.erc_parser import extract_violation_positions
    positions = extract_violation_positions(file_path, op.violation_type)
    return {"positions": [dataclasses.asdict(p) for p in positions], "count": len(positions)}


@register_schematic_query("validate_hlabels")
def _handle_validate_hlabels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.hlabel_guard import validate_hlabels
    expected = set(op.expected_labels) if op.expected_labels else None
    result = validate_hlabels(ir, expected_labels=expected)
    return dataclasses.asdict(result)


@register_schematic_query("navigate_hierarchy")
def _handle_navigate_hierarchy(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import navigate_hierarchy
    return navigate_hierarchy(op, ir, file_path)


@register_schematic_query("classify_violations")
def _handle_classify_violations(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.violation_classifier import classify_violations
    from kicad_agent.ops.erc_parser import parse_erc
    violations = parse_erc(file_path)
    return classify_violations(violations, ir, file_path)


@register_schematic_query("diagnose_violations")
def _handle_diagnose_violations(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.violation_diagnostic import diagnose_violations
    from kicad_agent.ops.violation_classifier import classify_violations
    from kicad_agent.ops.erc_parser import parse_erc
    violations = parse_erc(file_path)
    classified = classify_violations(violations, ir, file_path)
    fixable = classified["fixable"]
    if op.violation_types is not None:
        fixable = [v for v in fixable if v["violation"]["type"] in op.violation_types]
    return diagnose_violations(fixable, ir, file_path)


@register_schematic_query("extract_nets")
def _handle_extract_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.net_extractor import extract_nets
    return extract_nets(
        sch_path=file_path,
        include_positions=op.include_positions,
        netlist_path=op.netlist_path,
    )


@register_schematic_query("detect_net_conflicts")
def _handle_detect_net_conflicts(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.conflict_detector import detect_net_conflicts
    return detect_net_conflicts(
        sch_path=file_path,
        check_case_variants=op.check_case_variants,
        check_mixed_labels=op.check_mixed_labels,
        check_unlabeled_junctions=op.check_unlabeled_junctions,
    )


@register_schematic_query("suggest_net_names")
def _handle_suggest_net_names(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.net_namer import suggest_net_names
    return suggest_net_names(
        sch_path=file_path,
        netlist_path=op.netlist_path,
        naming_convention=op.naming_convention,
    )


@register_schematic_query("resolve_pin_positions")
def _handle_resolve_pin_positions(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.pin_resolver import PinResolver
    resolver = PinResolver(file_path)
    if op.ref:
        result = resolver.resolve(op.ref)
        if result is None:
            return {"ref": op.ref, "pins": {}}
        return {"ref": op.ref, "pins": result.get("pins", {})}
    else:
        return resolver.resolve_all()


@register_schematic_query("detect_routing_collisions")
def _handle_detect_routing_collisions(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.collision_detector import CollisionDetector
    detector = CollisionDetector(file_path)
    zones = detector.detect_routing_collisions(tolerance=op.collision_tolerance)
    return {"collision_zones": zones, "count": len(zones)}


@register_schematic_query("detect_pin_overlaps")
def _handle_detect_pin_overlaps(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.collision_detector import CollisionDetector
    detector = CollisionDetector(file_path)
    overlaps = detector.detect_pin_overlaps(tolerance=op.tolerance)
    return {"overlaps": overlaps, "count": len(overlaps)}


@register_schematic_query("infer_connectivity")
def _handle_infer_connectivity(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.net_inference import infer_nets
    return infer_nets(
        sch_path=file_path,
        pin_map=getattr(op, "pin_map", "auto"),
        confidence_threshold=getattr(op, "confidence_threshold", "medium"),
    )
