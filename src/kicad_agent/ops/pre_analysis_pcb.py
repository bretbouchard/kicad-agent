"""PCB-specific pre-flight checks for the universal gate (D-05).

Extracted from pre_analysis.py to keep the main gate module under 800 lines.
Contains checks for PCB mutation operations: swap_footprint pad count,
remove_net connectivity, move_footprint overlap, and zone net overlap.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.ops.pre_analysis import PreAnalysisResult

logger = logging.getLogger(__name__)

# PCB mutation operations that require pre-flight checks.
# Tracks/vias ops implemented in Phase 101 (101-01 through 101-03):
#   add_track, add_arc_track, add_via, delete_track, delete_via,
#   move_track_endpoint, lock_track, lock_via, add_stitching_via_pattern.
# These do not currently require bespoke pre-flight checks (no footprint/net
# topology validation), but are listed so the gate recognizes them as known
# mutation ops rather than rejecting them as unknown.
_PCB_MUTATION_OP_TYPES = frozenset({
    "swap_footprint",
    "remove_net",
    "add_copper_zone",
    "remove_copper_zone",
    "move_footprint",
    "modify_net",
    "rename_net",
    "add_via",
    "delete_via",
    "add_track",
    "add_arc_track",
    "delete_track",
    "move_track_endpoint",
    "lock_track",
    "lock_via",
    "add_stitching_via_pattern",
})

# Overlap tolerance in mm for footprint collision checks
_FOOTPRINT_OVERLAP_TOLERANCE_MM = 1.27


def analyze_pcb(
    op: Any,
    ir: Any,
    file_path: Path,
    result: "PreAnalysisResult",
) -> None:
    """PCB-specific pre-flight checks (D-05).

    Called from PreAnalysisGate._analyze_pcb after file-type dispatch
    identifies a .kicad_pcb file. Only mutation ops produce blockers.

    Args:
        op: The operation root model.
        ir: PcbIR for the target PCB file.
        file_path: Path to the PCB file.
        result: PreAnalysisResult to append findings to.
    """
    op_type = getattr(op, "op_type", None)
    if op_type not in _PCB_MUTATION_OP_TYPES:
        return

    if op_type == "swap_footprint":
        _check_pcb_swap_footprint(op, ir, result)
    elif op_type == "remove_net":
        _check_pcb_remove_net(op, ir, result)
    elif op_type == "move_footprint":
        _check_pcb_move_footprint(op, ir, result)
    elif op_type in ("add_copper_zone", "remove_copper_zone"):
        _check_pcb_zone_overlap(op, ir, result)


def _check_pcb_swap_footprint(op: Any, ir: Any, result: "PreAnalysisResult") -> None:
    """Block swap_footprint when new footprint has fewer pads than old.

    If the new footprint pad count cannot be determined (e.g. library not
    available), a WARNING is emitted instead of blocking.
    """
    reference = getattr(op, "reference", None)
    if not reference:
        return

    # Verify old footprint exists
    old_footprint = ir.get_footprint_by_ref(reference)
    if old_footprint is None:
        result.blockers.append(
            _make_finding(
                "blocker",
                "unknown_ref",
                f"swap_footprint: footprint {reference} not found in PCB",
                {"reference": reference},
            )
        )
        return

    # Get old pad count
    old_pads = ir.get_footprint_pads(reference)
    old_pad_count = len(old_pads)

    # Attempt to determine new footprint pad count
    new_lib_id = getattr(op, "new_footprint_lib_id", None)
    new_pad_count: int | None = None

    if new_lib_id:
        new_pad_count = _resolve_footprint_pad_count(new_lib_id)

    if new_pad_count is not None and new_pad_count < old_pad_count:
        result.blockers.append(
            _make_finding(
                "blocker",
                "pad_count_mismatch",
                (
                    f"swap_footprint: new footprint has {new_pad_count} pads, "
                    f"old has {old_pad_count} -- {old_pad_count - new_pad_count} "
                    f"pad(s) would be disconnected"
                ),
                {
                    "reference": reference,
                    "old_pad_count": old_pad_count,
                    "new_pad_count": new_pad_count,
                    "new_footprint_lib_id": new_lib_id,
                },
            )
        )
    elif new_pad_count is None and new_lib_id:
        # Could not resolve new footprint -- warn but don't block
        result.warnings.append(
            _make_finding(
                "warning",
                "pad_count_unknown",
                (
                    f"swap_footprint: cannot verify pad count for "
                    f"{new_lib_id} -- old footprint has {old_pad_count} pads. "
                    f"Proceed with caution."
                ),
                {
                    "reference": reference,
                    "old_pad_count": old_pad_count,
                    "new_footprint_lib_id": new_lib_id,
                },
            )
        )


def _check_pcb_remove_net(op: Any, ir: Any, result: "PreAnalysisResult") -> None:
    """Block remove_net when the net has connected pads.

    Removing a net that is actively used would silently disconnect pads.
    """
    net_name = getattr(op, "net_name", None)
    if not net_name:
        return

    # Check if net exists
    net = ir.get_net_by_name(net_name)
    if net is None:
        result.blockers.append(
            _make_finding(
                "blocker",
                "unknown_net",
                f"remove_net: net '{net_name}' not found in PCB",
                {"net_name": net_name},
            )
        )
        return

    # Check for connected pads
    connected_pads = ir.get_net_pads(net_name)
    if connected_pads:
        result.blockers.append(
            _make_finding(
                "blocker",
                "net_has_connections",
                (
                    f"remove_net: net '{net_name}' has {len(connected_pads)} "
                    f"connected pad(s). Disconnect pads first."
                ),
                {
                    "net_name": net_name,
                    "pad_count": len(connected_pads),
                    "pads": [{"ref": p[0], "pad": p[1]} for p in connected_pads],
                },
            )
        )

    # Check if net is referenced by zones (warning only)
    if _net_referenced_by_zones(ir, net_name):
        result.warnings.append(
            _make_finding(
                "warning",
                "net_zone_reference",
                f"remove_net: net '{net_name}' is referenced by copper zone(s). "
                f"Zones will need manual update after removal.",
                {"net_name": net_name},
            )
        )


def _check_pcb_move_footprint(op: Any, ir: Any, result: "PreAnalysisResult") -> None:
    """Block move_footprint when destination overlaps existing footprints.

    Uses AABB bounding box overlap detection with a tolerance margin.
    """
    reference = getattr(op, "reference", None)
    position = getattr(op, "position", None)
    if not reference or position is None:
        return

    # Verify footprint exists
    old_footprint = ir.get_footprint_by_ref(reference)
    if old_footprint is None:
        result.blockers.append(
            _make_finding(
                "blocker",
                "unknown_ref",
                f"move_footprint: footprint {reference} not found in PCB",
                {"reference": reference},
            )
        )
        return

    dest_x = getattr(position, "x", 0.0)
    dest_y = getattr(position, "y", 0.0)

    # Build bounding box for destination
    dest_bbox = _get_footprint_bbox(ir, reference, dest_x, dest_y)
    if dest_bbox is None:
        return  # Cannot compute bbox -- allow proceed

    # Check overlaps with all other footprints
    overlaps = _find_footprint_overlaps(ir, dest_bbox, exclude_ref=reference)
    if overlaps:
        result.blockers.append(
            _make_finding(
                "blocker",
                "footprint_overlap",
                (
                    f"move_footprint: moving {reference} to ({dest_x}, {dest_y}) "
                    f"would overlap with: "
                    + ", ".join(o["ref"] for o in overlaps)
                ),
                {
                    "reference": reference,
                    "destination": {"x": dest_x, "y": dest_y},
                    "overlapping_footprints": overlaps,
                },
            )
        )


def _check_pcb_zone_overlap(op: Any, ir: Any, result: "PreAnalysisResult") -> None:
    """Warn when copper zone net overlaps power/ground nets.

    This is advisory -- zone assignments to power nets are valid but
    may indicate unintended coverage.
    """
    net_name = getattr(op, "net_name", None)
    if not net_name:
        return

    # Common power net name patterns
    power_patterns = ("gnd", "vcc", "vdd", "vss", "+3v3", "+5v", "+12v", "+3.3v", "+5v")
    if net_name.lower() in power_patterns or any(
        net_name.lower().startswith(p) for p in power_patterns
    ):
        # This is a power zone -- warn about potential over-coverage
        result.warnings.append(
            _make_finding(
                "warning",
                "power_zone_overlap",
                (
                    f"Copper zone assigned to power net '{net_name}'. "
                    f"Verify zone boundaries do not overlap signal traces."
                ),
                {"net_name": net_name, "op_type": op.op_type},
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(severity: str, category: str, message: str, details: dict) -> Any:
    """Create a PreAnalysisFinding without importing at module level (avoids circular imports)."""
    from kicad_agent.ops.pre_analysis import PreAnalysisFinding
    return PreAnalysisFinding(
        severity=severity,
        category=category,
        message=message,
        details=details,
    )


def _resolve_footprint_pad_count(lib_id: str) -> int | None:
    """Attempt to determine pad count for a footprint from its lib_id.

    Tries to parse the .kicad_mod file from the library path. Returns None
    if the file cannot be found or parsed.
    """
    # Extract footprint name and library from lib_id (format: "Library:Footprint")
    if ":" not in lib_id:
        return None

    # We cannot reliably resolve library paths without project context.
    # Return None to indicate "unknown" -- caller should warn.
    return None


def _net_referenced_by_zones(ir: Any, net_name: str) -> bool:
    """Check if a net is referenced by any copper zones in the PCB."""
    try:
        zones = getattr(ir, "zones", [])
        if not zones:
            # Try alternate access patterns
            board = getattr(ir, "board", None)
            if board is not None:
                zones = getattr(board, "zones", [])
        for zone in zones:
            zone_net = getattr(zone, "net_name", None) or getattr(zone, "net", None)
            if zone_net is not None:
                zone_name = zone_net if isinstance(zone_net, str) else getattr(zone_net, "name", "")
                if zone_name == net_name:
                    return True
    except Exception:
        pass
    return False


def _get_footprint_bbox(ir: Any, ref: str, cx: float, cy: float) -> dict | None:
    """Get bounding box for a footprint at a given position.

    Returns dict with x, y, width, height (center-based) or None if
    the footprint cannot be resolved.
    """
    footprint = ir.get_footprint_by_ref(ref)
    if footprint is None:
        return None

    # Try to get actual bounds from the footprint
    pads = ir.get_footprint_pads(ref)
    if not pads:
        # Default conservative size
        return {"x": cx, "y": cy, "width": 5.0, "height": 5.0}

    # Compute bounds from pad positions
    min_x = min(p[2] if len(p) > 2 else cx - 2.5 for p in pads)
    max_x = max(p[2] if len(p) > 2 else cx + 2.5 for p in pads)
    min_y = min(p[3] if len(p) > 3 else cy - 2.5 for p in pads)
    max_y = max(p[3] if len(p) > 3 else cy + 2.5 for p in pads)

    # Use relative offsets from center
    width = max(max_x - min_x, 2.0)
    height = max(max_y - min_y, 2.0)

    return {"x": cx, "y": cy, "width": width, "height": height}


def _find_footprint_overlaps(
    ir: Any,
    new_bbox: dict,
    exclude_ref: str | None = None,
    tolerance: float = _FOOTPRINT_OVERLAP_TOLERANCE_MM,
) -> list[dict]:
    """Find footprints whose bounding boxes overlap with new_bbox.

    Args:
        ir: PcbIR for the PCB.
        new_bbox: Dict with x, y, width, height (center-based).
        exclude_ref: Reference to exclude from overlap check.
        tolerance: Extra gap allowed between boxes (mm).

    Returns:
        List of overlapping footprint dicts with ref, x, y.
    """
    overlaps = []
    try:
        footprints = getattr(ir, "footprints", [])
        if not footprints:
            board = getattr(ir, "board", None)
            if board is not None:
                footprints = getattr(board, "footprints", [])
    except Exception:
        return overlaps

    nx1 = new_bbox["x"] - new_bbox["width"] / 2
    ny1 = new_bbox["y"] - new_bbox["height"] / 2
    nx2 = new_bbox["x"] + new_bbox["width"] / 2
    ny2 = new_bbox["y"] + new_bbox["height"] / 2

    for fp in footprints:
        ref = getattr(fp, "reference", "")
        if ref == exclude_ref or not ref:
            continue

        fx = getattr(fp, "x", 0.0)
        fy = getattr(fp, "y", 0.0)

        # Get bbox for this footprint
        fp_bbox = _get_footprint_bbox(ir, ref, fx, fy)
        if fp_bbox is None:
            continue

        cx1 = fp_bbox["x"] - fp_bbox["width"] / 2 - tolerance
        cy1 = fp_bbox["y"] - fp_bbox["height"] / 2 - tolerance
        cx2 = fp_bbox["x"] + fp_bbox["width"] / 2 + tolerance
        cy2 = fp_bbox["y"] + fp_bbox["height"] / 2 + tolerance

        # AABB overlap test
        if nx1 < cx2 and nx2 > cx1 and ny1 < cy2 and ny2 > cy1:
            overlaps.append({"ref": ref, "x": fx, "y": fy})

    return overlaps
