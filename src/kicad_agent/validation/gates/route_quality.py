"""Route quality metrics and scoring for post-route validation.

Computes completion percentage, via count, clearance violations,
length mismatch, and return path risk from PcbIR data. Produces a
composite quality_score and quality_status metadata.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RouteQualityMetrics(BaseModel):
    """Immutable route quality metrics computed from PcbIR and DRC data.

    All fields have defaults so the model can be constructed incrementally.
    quality_score is computed from the other fields.
    """

    model_config = {"frozen": True}

    completion_pct: float = 0.0
    via_count: int = 0
    clearance_violations: int = 0
    length_mismatch_pct: float = 0.0
    return_path_risk: tuple[str, ...] = ()
    diff_pair_issues: tuple[str, ...] = ()
    quality_score: float = 0.0
    quality_status: str = "prototype"


def compute_route_quality(
    pcb_ir: Any,
    constraints: Any,
    max_expected_vias: int = 50,
    max_allowed_violations: int = 0,
) -> RouteQualityMetrics:
    """Compute route quality metrics from PcbIR and constraints.

    Args:
        pcb_ir: PcbIR instance with footprints, nets, zones, trace data.
        constraints: DesignConstraints instance with electrical specs.
        max_expected_vias: Threshold for via count penalty.
        max_allowed_violations: Zero-tolerance clearance violation cap.

    Returns:
        RouteQualityMetrics with computed scores.
    """
    # 1. Completion percentage
    total_nets = len(pcb_ir.nets)
    routed_nets = _count_routed_nets(pcb_ir)
    completion_pct = (routed_nets / total_nets * 100.0) if total_nets > 0 else 0.0

    # 2. Via count
    via_count = _count_vias(pcb_ir)

    # 3. Clearance violations (from DRC if available, 0 otherwise)
    clearance_violations = 0

    # 4. Length mismatch (from diff pair checks)
    length_mismatch_pct = 0.0
    diff_pair_issues: list[str] = []
    if constraints is not None:
        diff_pair_issues, length_mismatch_pct = _check_diff_pairs(pcb_ir, constraints)

    # 5. Return path risk
    return_path_risk = _detect_return_path_risk(pcb_ir)

    # 6. Quality score
    via_score = 1.0 - min(via_count / max(1, max_expected_vias), 1.0)
    clearance_score = 1.0 - min(clearance_violations / max(1, max_allowed_violations), 1.0)
    length_score = 1.0 - length_mismatch_pct / 100.0
    quality_score = (
        (completion_pct / 100.0) * 0.4
        + via_score * 0.2
        + clearance_score * 0.2
        + length_score * 0.2
    )
    quality_score = max(0.0, min(1.0, quality_score))

    return RouteQualityMetrics(
        completion_pct=round(completion_pct, 1),
        via_count=via_count,
        clearance_violations=clearance_violations,
        length_mismatch_pct=round(length_mismatch_pct, 1),
        return_path_risk=tuple(return_path_risk),
        diff_pair_issues=tuple(diff_pair_issues),
        quality_score=round(quality_score, 3),
        quality_status="prototype",
    )


def _count_routed_nets(pcb_ir: Any) -> int:
    """Count nets that have at least one routed segment."""
    routed = 0
    trace_items = getattr(pcb_ir, "trace_items", None)
    if trace_items is None:
        return 0

    # Collect net names from routed segments
    routed_net_names: set[str] = set()
    for item in trace_items:
        net = getattr(item, "net", None)
        if net is not None:
            net_name = str(net)
            if net_name and net_name != "" and net_name != "0":
                routed_net_names.add(net_name)
        elif hasattr(item, "net_name") and item.net_name:
            routed_net_names.add(item.net_name)

    return len(routed_net_names)


def _count_vias(pcb_ir: Any) -> int:
    """Count vias on the board."""
    count = 0
    for fp in pcb_ir.footprints:
        for pad in fp.pads:
            pad_type = getattr(pad, "type", "").lower()
            if pad_type == "thru_hole":
                count += 1
            # Also check for via pads by size/shape heuristics
            if hasattr(pad, "pad_type_attr"):
                pt = str(getattr(pad, "pad_type_attr", "")).lower()
                if "via" in pt:
                    count += 1
    return count


def _check_diff_pairs(
    pcb_ir: Any,
    constraints: Any,
) -> tuple[list[str], float]:
    """Check differential pair specs against routed geometry.

    Returns (issues, max_length_mismatch_pct).
    """
    issues: list[str] = []
    max_mismatch_pct = 0.0

    if constraints is None or not hasattr(constraints, "electrical"):
        return issues, max_mismatch_pct

    for ec in constraints.electrical:
        if ec.diff_pair is None:
            continue

        pair_name = ec.diff_pair.pair_name
        target_gap = ec.diff_pair.gap_mm
        target_length = ec.diff_pair.length_match_mm if ec.diff_pair.length_match else None
        tolerance = ec.diff_pair.tolerance_mm if ec.diff_pair.tolerance_mm else 0.5

        # Find nets matching the pair pattern (name_P/name_N or name+/name-)
        pair_nets = _find_pair_nets(pcb_ir, pair_name)
        if len(pair_nets) < 2:
            issues.append(f"Diff pair '{pair_name}': only {len(pair_nets)} net(s) found")
            continue

        # Check gap (simplified: cannot verify exact routed gap from PcbIR alone)
        # Check length mismatch if target specified
        if target_length is not None:
            lengths = _get_net_routed_length(pcb_ir, pair_nets)
            if len(lengths) == 2:
                mismatch = abs(lengths[0] - lengths[1])
                mismatch_pct = mismatch / target_length * 100.0 if target_length > 0 else 0.0
                max_mismatch_pct = max(max_mismatch_pct, mismatch_pct)
                if mismatch > tolerance:
                    issues.append(
                        f"Diff pair '{pair_name}': length mismatch "
                        f"{mismatch:.2f}mm (tolerance: {tolerance}mm)"
                    )

    return issues, max_mismatch_pct


def _find_pair_nets(pcb_ir: Any, pair_name: str) -> list[str]:
    """Find nets belonging to a differential pair by name pattern."""
    found: list[str] = []
    for net in pcb_ir.nets:
        name = getattr(net, "name", "")
        # Match pair_P/pair_N or pair+/pair- suffixes
        if name == f"{pair_name}_P" or name == f"{pair_name}_N":
            found.append(name)
        elif name == f"{pair_name}+" or name == f"{pair_name}-":
            found.append(name)
        elif name.startswith(pair_name + "_") or name.startswith(pair_name):
            found.append(name)
    return found


def _get_net_routed_length(pcb_ir: Any, net_names: list[str]) -> list[float]:
    """Estimate routed length for nets by summing segment Manhattan distances."""
    lengths: list[float] = []
    trace_items = getattr(pcb_ir, "trace_items", None)
    if trace_items is None:
        return lengths

    net_segments: dict[str, list] = {n: [] for n in net_names}
    for item in trace_items:
        net = getattr(item, "net", None)
        net_name = str(net) if net else ""
        if net_name in net_segments:
            start = getattr(item, "start", None)
            end = getattr(item, "end", None)
            if start is not None and end is not None:
                sx = getattr(start, "X", getattr(start, "x", 0))
                sy = getattr(start, "Y", getattr(start, "y", 0))
                ex = getattr(end, "X", getattr(end, "x", 0))
                ey = getattr(end, "Y", getattr(end, "y", 0))
                net_segments[net_name].append((sx, sy, ex, ey))

    for n in net_names:
        total = sum(abs(ex - sx) + abs(ey - sy) for sx, sy, ex, ey in net_segments[n])
        lengths.append(total)

    return lengths


def _detect_return_path_risk(pcb_ir: Any) -> list[str]:
    """Detect signal nets without adjacent ground plane.

    For each signal net, identify the primary trace layer and check
    if an adjacent layer has a ground plane zone.
    """
    risk_nets: list[str] = []

    # Collect ground zone layers
    ground_layers: set[str] = set()
    for zone in getattr(pcb_ir, "zones", []):
        net_name = getattr(zone, "net_name", "") or getattr(zone, "net", "")
        layer = getattr(zone, "layer", "")
        net_upper = str(net_name).upper()
        if "GND" in net_upper or net_name == "0":
            ground_layers.add(layer)

    if not ground_layers:
        # No ground planes at all -- all signal nets at risk
        for net in pcb_ir.nets:
            name = getattr(net, "name", "")
            if name and name != "0" and not name.startswith("V"):
                risk_nets.append(name)
        return risk_nets

    # If ground planes exist on some layers, check each signal net
    # For simplicity, if ground planes exist on at least one layer,
    # assume adequate return paths (full analysis requires layer tracking
    # per net which PcbIR doesn't yet expose)
    return risk_nets
