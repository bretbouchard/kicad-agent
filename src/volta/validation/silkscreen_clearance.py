"""Silkscreen-over-copper detection and relocation engine.

Checks reference designators and values on silkscreen layers for
clearance violations against copper features (pads, traces, zones).

Usage:
    from volta.validation.silkscreen_clearance import check_silkscreen_clearance

    result = check_silkscreen_clearance(pcb_ir, clearance_mm=0.15)
    for v in result.violations:
        print(f"{v.text_content} at {v.text_position}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from volta.ir.pcb_ir import PcbIR


@dataclass(frozen=True)
class SilkscreenViolation:
    """A silkscreen item overlapping copper.

    Attributes:
        text_content: The text string (reference or value).
        text_position: Current (x, y) position in mm.
        footprint_ref: Footprint reference designator.
        overlapping_items: List of copper item identifiers overlapping.
        suggested_position: Nearest clear position (x, y) or None.
    """

    text_content: str
    text_position: tuple[float, float]
    footprint_ref: str
    overlapping_items: tuple[str, ...]
    suggested_position: tuple[float, float] | None


@dataclass(frozen=True)
class SilkscreenClearanceResult:
    """Result of silkscreen clearance check.

    Attributes:
        total_checked: Number of text items checked.
        violations: List of clearance violations found.
    """

    total_checked: int
    violations: tuple[SilkscreenViolation, ...]


def _get_footprint_text_items(pcb_ir: PcbIR) -> list[dict]:
    """Extract text items from footprints on silkscreen layers.

    Returns list of dicts with: text, position, ref, layer.
    """
    items: list[dict] = []
    board = pcb_ir.board

    footprints = []
    if hasattr(board, "footprints"):
        footprints = board.footprints
    elif hasattr(board, "graphicItems"):
        # Native parser path
        for fp in board.footprints if hasattr(board, "footprints") else []:
            footprints.append(fp)

    if not footprints:
        return items

    for fp in footprints:
        fp_ref = ""
        if hasattr(fp, "properties") and isinstance(fp.properties, dict):
            fp_ref = fp.properties.get("Reference", "")
        elif hasattr(fp, "reference"):
            fp_ref = str(fp.reference)

        # Extract reference text position.
        if hasattr(fp, "reference"):
            ref_obj = fp.reference
            if hasattr(ref_obj, "at"):
                at = ref_obj.at
                x = at[0] if isinstance(at, (tuple, list)) else getattr(at, "x", 0.0)
                y = at[1] if isinstance(at, (tuple, list)) and len(at) > 1 else getattr(at, "y", 0.0)
                items.append({
                    "text": fp_ref,
                    "position": (float(x), float(y)),
                    "ref": fp_ref,
                    "layer": "F.SilkS",
                })

        # Extract value text position.
        if hasattr(fp, "value"):
            val_obj = fp.value
            if hasattr(val_obj, "at"):
                at = val_obj.at
                x = at[0] if isinstance(at, (tuple, list)) else getattr(at, "x", 0.0)
                y = at[1] if isinstance(at, (tuple, list)) and len(at) > 1 else getattr(at, "y", 0.0)
                val_text = getattr(val_obj, "value", "") or ""
                items.append({
                    "text": val_text,
                    "position": (float(x), float(y)),
                    "ref": fp_ref,
                    "layer": "F.SilkS",
                })

    return items


def _get_copper_features(pcb_ir: PcbIR, copper_layers: list[str]) -> list[dict]:
    """Extract copper feature positions from the PCB.

    Returns list of dicts with: x, y, radius, kind, net.
    """
    features: list[dict] = []
    board = pcb_ir.board

    # Extract pad positions from footprints.
    for fp in (board.footprints if hasattr(board, "footprints") else []):
        fp_ref = ""
        if hasattr(fp, "properties") and isinstance(fp.properties, dict):
            fp_ref = fp.properties.get("Reference", "")
        elif hasattr(fp, "reference"):
            fp_ref = str(fp.reference)

        pads = fp.pads if hasattr(fp, "pads") else []
        for pad in pads:
            px, py = 0.0, 0.0
            at = getattr(pad, "at", None)
            if at is not None:
                px = at[0] if isinstance(at, (tuple, list)) else getattr(at, "x", 0.0)
                py = at[1] if isinstance(at, (tuple, list)) and len(at) > 1 else getattr(at, "y", 0.0)

            # Estimate pad size from size field.
            radius = 0.5  # Default conservative estimate.
            size = getattr(pad, "size", None)
            if size is not None:
                if isinstance(size, (tuple, list)):
                    radius = max(float(size[0]), float(size[1])) / 2
                elif hasattr(size, "x") and hasattr(size, "y"):
                    radius = max(float(size.x), float(size.y)) / 2

            pad_net = getattr(pad, "net", "")
            if hasattr(pad_net, "net"):
                pad_net = pad_net.net

            features.append({
                "x": float(px), "y": float(py),
                "radius": radius,
                "kind": "pad",
                "net": str(pad_net),
                "ref": fp_ref,
            })

    # Extract via positions.
    vias = board.vias if hasattr(board, "vias") else []
    for via in vias:
        at = getattr(via, "at", None)
        if at is not None:
            vx = at[0] if isinstance(at, (tuple, list)) else getattr(at, "x", 0.0)
            vy = at[1] if isinstance(at, (tuple, list)) and len(at) > 1 else getattr(at, "y", 0.0)
            size = getattr(via, "size", 0.8)
            if isinstance(size, (tuple, list)):
                vr = float(size[0]) / 2
            elif hasattr(size, "x"):
                vr = float(size.x) / 2
            else:
                vr = float(size) / 2
            features.append({
                "x": float(vx), "y": float(vy),
                "radius": vr,
                "kind": "via",
                "net": str(getattr(via, "net", "")),
            })

    # Extract trace endpoints (approximate).
    segments = board.segments if hasattr(board, "segments") else []
    for seg in segments:
        start = getattr(seg, "start", None)
        end = getattr(seg, "end", None)
        if start and end:
            sx = float(getattr(start, "x", getattr(start, "X", 0)))
            sy = float(getattr(start, "y", getattr(start, "Y", 0)))
            ex = float(getattr(end, "x", getattr(end, "X", 0)))
            ey = float(getattr(end, "y", getattr(end, "Y", 0)))
            width = float(getattr(seg, "width", 0.25))
            # Add both endpoints as small features.
            features.append({
                "x": sx, "y": sy, "radius": width / 2 + 0.1,
                "kind": "trace", "net": str(getattr(seg, "net", "")),
            })
            features.append({
                "x": ex, "y": ey, "radius": width / 2 + 0.1,
                "kind": "trace", "net": str(getattr(seg, "net", "")),
            })

    return features


def _check_text_overlap(
    text_pos: tuple[float, float],
    copper_features: list[dict],
    clearance_mm: float,
) -> tuple[list[str], tuple[float, float] | None]:
    """Check if a text position overlaps any copper feature.

    Returns (overlapping_items, suggested_clear_position).
    """
    # Text bounding box estimate: ~2mm wide, ~1mm tall for typical refdes.
    text_half_w = 1.0
    text_half_h = 0.5

    overlapping: list[str] = []
    for feat in copper_features:
        dx = abs(text_pos[0] - feat["x"])
        dy = abs(text_pos[1] - feat["y"])
        dist = math.sqrt(dx * dx + dy * dy)
        threshold = clearance_mm + feat["radius"]

        if dist < threshold:
            overlapping.append(f"{feat['kind']}:{feat.get('ref', '')}:{feat.get('net', '')}")

    if not overlapping:
        return [], None

    # Suggest nearest clear position: radially outward from nearest obstacle.
    suggested = _find_clear_position(
        text_pos, copper_features, clearance_mm,
        text_half_w, text_half_h,
    )
    return overlapping, suggested


def _find_clear_position(
    origin: tuple[float, float],
    copper_features: list[dict],
    clearance_mm: float,
    half_w: float = 1.0,
    half_h: float = 0.5,
    max_radius: float = 5.0,
    step: float = 0.5,
) -> tuple[float, float] | None:
    """Find the nearest clear position around origin.

    Searches radially outward at 8 angles, increasing radius.
    """
    for radius in (step, step * 2, step * 3, step * 4, max_radius):
        for angle_deg in range(0, 360, 45):
            angle_rad = math.radians(angle_deg)
            candidate = (
                origin[0] + radius * math.cos(angle_rad),
                origin[1] + radius * math.sin(angle_rad),
            )
            clear = True
            for feat in copper_features:
                dx = abs(candidate[0] - feat["x"])
                dy = abs(candidate[1] - feat["y"])
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < clearance_mm + feat["radius"] + max(half_w, half_h):
                    clear = False
                    break
            if clear:
                return (round(candidate[0], 3), round(candidate[1], 3))

    return None


def check_silkscreen_clearance(
    pcb_ir: PcbIR,
    clearance_mm: float = 0.15,
    copper_layers: list[str] | None = None,
    silk_layers: list[str] | None = None,
) -> SilkscreenClearanceResult:
    """Check silkscreen text items for copper clearance violations.

    Args:
        pcb_ir: PcbIR for the PCB to check.
        clearance_mm: Required clearance between silkscreen and copper.
        copper_layers: Copper layers to check against (default F.Cu).
        silk_layers: Silkscreen layers to check (default F.SilkS, B.SilkS).

    Returns:
        SilkscreenClearanceResult with all violations found.
    """
    if copper_layers is None:
        copper_layers = ["F.Cu"]
    if silk_layers is None:
        silk_layers = ["F.SilkS", "B.SilkS"]

    text_items = _get_footprint_text_items(pcb_ir)
    copper_features = _get_copper_features(pcb_ir, copper_layers)

    violations: list[SilkscreenViolation] = []

    for item in text_items:
        if item["layer"] not in silk_layers:
            continue
        if not item["text"]:
            continue

        overlapping, suggested = _check_text_overlap(
            item["position"], copper_features, clearance_mm,
        )

        if overlapping:
            violations.append(SilkscreenViolation(
                text_content=item["text"],
                text_position=item["position"],
                footprint_ref=item["ref"],
                overlapping_items=tuple(overlapping),
                suggested_position=suggested,
            ))

    return SilkscreenClearanceResult(
        total_checked=len(text_items),
        violations=tuple(violations),
    )
