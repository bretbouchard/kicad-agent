"""Internal vendor DRC evaluator — geometric checks against ManufacturerProfile limits.

Phase 206, DRC-01: runs DRC against a specific vendor's manufacturing limits as a
pre-flight gate.

CRITICAL PIVOT (RESEARCH RQ1): ``kicad-cli pcb drc`` has no ``--custom-rules`` flag
in KiCad 10 (verified empirically). This module implements Option C: it reads board
geometry from a ``NativeBoard`` (parsed via ``NativeParser.parse_pcb``) and compares
each dimension against the ``ManufacturerProfile`` numeric limits in pure Python.
It does NOT call kicad-cli with vendor rules.

The bundled ``.kicad_dru`` files ship for GUI use, documentation, and as the source
of truth for the numeric values, but the automated ``drc_vendor`` gate is this evaluator.

Threat model scenario 2 (malformed board crashes evaluator): every geometry access
uses ``getattr(obj, field, default)`` with safe defaults, and dimension extraction is
wrapped in try/except per-feature. A single malformed track/via/pad does NOT abort the
whole evaluation. The evaluator NEVER re-raises — it collects what it can and returns
a ``VendorDrcResult`` (possibly with an ``error_message`` if board access fails entirely).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from volta.dfm.profiles import ManufacturerProfile
from volta.validation.erc_drc import Severity, Violation


@dataclass(frozen=True)
class VendorDrcResult:
    """Structured result from a vendor-specific DRC check.

    Mirrors the ``DrcResult`` structure (``validation/erc_drc.py:91``) but for
    vendor-manufacturing-limit violations. Reuses the existing ``Violation``
    frozen dataclass (does not define a new violation type).

    Attributes:
        vendor: Vendor key the profile was loaded under (e.g. "pcbway").
        passed: True iff there are zero ERROR-severity violations. Warnings do not fail.
        violations: Tuple of ``Violation`` instances for any feature below limits.
        profile_name: Display name of the ManufacturerProfile used.
        checks_run: Tuple of check names that were evaluated.
        error_message: Set if board access failed entirely (evaluator never re-raises).
    """

    vendor: str
    passed: bool
    violations: tuple[Violation, ...] = ()
    profile_name: str = ""
    checks_run: tuple[str, ...] = ()
    error_message: Optional[str] = None

    @property
    def errors(self) -> tuple[Violation, ...]:
        """Violations with severity=error."""
        return tuple(v for v in self.violations if v.severity == Severity.ERROR)


# Tolerance for floating-point comparisons in the clearance check (mm). Two
# segments whose gap is within this epsilon of the limit are treated as equal.
_EPS = 1e-9


def _pos_xy(pos: Any) -> tuple[float, float]:
    """Extract (x, y) from a position object (NamedTuple with .X/.Y or a tuple).

    Handles both ``_NativePosition`` (has ``.X``/``.Y``) and plain tuples/lists.
    Returns (0.0, 0.0) if pos is None or unparseable.
    """
    if pos is None:
        return (0.0, 0.0)
    # _NativePosition NamedTuple exposes .X/.Y attributes.
    x = getattr(pos, "X", None)
    y = getattr(pos, "Y", None)
    if x is not None and y is not None:
        try:
            return (float(x), float(y))
        except (TypeError, ValueError):
            pass
    # Fallback: index into a tuple/list.
    try:
        return (float(pos[0]), float(pos[1]))
    except (TypeError, ValueError, IndexError):
        return (0.0, 0.0)


def run_vendor_drc(board: Any, profile: ManufacturerProfile) -> VendorDrcResult:
    """Run vendor-specific DRC checks against manufacturing limits.

    Walks the ``NativeBoard`` geometry and compares each dimension against the
    ``ManufacturerProfile`` numeric limits. Emits ``Violation`` instances for any
    feature below limits.

    The handler (``ops/handlers/query.py:_handle_drc_vendor``) re-parses the PCB
    via ``NativeParser.parse_pcb(file_path)`` to get a ``NativeBoard`` because
    ``execute_query`` builds ``PcbIR`` via the kiutils path where ``_native_board``
    is None (same dual-path issue as Phase 205's ``read_board_metadata`` handler).

    Args:
        board: A ``NativeBoard`` (from ``NativeParser.parse_pcb``) with segments,
            vias, and footprints. Duck-typed via getattr so test doubles work.
        profile: The ``ManufacturerProfile`` carrying the vendor limits.

    Returns:
        ``VendorDrcResult`` with violations for any feature below the profile limits.
        ``passed`` is True iff there are zero ERROR-severity violations.
    """
    violations: list[Violation] = []
    checks_run: list[str] = []

    # ---- Collect geometry defensively (threat model scenario 2) ----
    segments = list(getattr(board, "segments", ()) or ())
    vias = list(getattr(board, "vias", ()) or ())
    footprints = list(getattr(board, "footprints", ()) or ())

    # ---- Check 1: track width ----
    try:
        track_violations = _check_track_width(segments, profile)
        if track_violations:
            violations.extend(track_violations)
        checks_run.append("track_width")
    except Exception:  # noqa: BLE001 — never let one check abort the rest
        pass

    # ---- Check 2: drill size (vias + thru-hole pads) ----
    try:
        drill_violations = _check_drill_size(vias, footprints, profile)
        if drill_violations:
            violations.extend(drill_violations)
        checks_run.append("drill_size")
    except Exception:  # noqa: BLE001
        pass

    # ---- Check 3: annular ring (vias + thru-hole pads) ----
    try:
        annular_violations = _check_annular_ring(vias, footprints, profile)
        if annular_violations:
            violations.extend(annular_violations)
        checks_run.append("annular_ring")
    except Exception:  # noqa: BLE001
        pass

    # ---- Check 4: via diameter ----
    try:
        via_diam_violations = _check_via_diameter(vias, profile)
        if via_diam_violations:
            violations.extend(via_diam_violations)
        checks_run.append("via_diameter")
    except Exception:  # noqa: BLE001
        pass

    # ---- Check 5: clearance (pairwise track-to-track on same layer) ----
    try:
        clearance_violations = _check_clearance(segments, profile)
        if clearance_violations:
            violations.extend(clearance_violations)
        checks_run.append("clearance")
    except Exception:  # noqa: BLE001
        pass

    passed = len([v for v in violations if v.severity == Severity.ERROR]) == 0
    return VendorDrcResult(
        vendor=profile.name,
        passed=passed,
        violations=tuple(violations),
        profile_name=profile.name,
        checks_run=tuple(checks_run),
    )


def _check_track_width(
    segments: list, profile: ManufacturerProfile
) -> list[Violation]:
    """Check all segment widths against profile.min_trace_width_mm."""
    limit = profile.min_trace_width_mm
    out: list[Violation] = []
    for seg in segments:
        try:
            raw_width = getattr(seg, "width", None)
            width = float(raw_width) if raw_width is not None else 0.2
        except (TypeError, ValueError):
            continue
        if width < limit - _EPS:
            layer = getattr(seg, "layer", "") or ""
            net_name = getattr(seg, "net_name", "") or ""
            out.append(Violation(
                description=(
                    f"Track width {width}mm below {profile.name} minimum "
                    f"{limit}mm"
                ),
                severity=Severity.ERROR,
                type="vendor_trace_width",
                items=({
                    "net": net_name,
                    "layer": layer,
                    "actual_mm": width,
                    "required_mm": limit,
                },),
            ))
    return out


def _check_drill_size(
    vias: list, footprints: list, profile: ManufacturerProfile
) -> list[Violation]:
    """Check all via drills and thru-hole pad drills against profile.min_drill_mm."""
    limit = profile.min_drill_mm
    out: list[Violation] = []

    for via in vias:
        try:
            drill = float(getattr(via, "drill", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if 0 < drill < limit - _EPS:
            net_name = getattr(via, "net_name", "") or ""
            out.append(Violation(
                description=(
                    f"Via drill {drill}mm below {profile.name} minimum "
                    f"{limit}mm"
                ),
                severity=Severity.ERROR,
                type="vendor_drill_size",
                items=({
                    "net": net_name,
                    "actual_mm": drill,
                    "required_mm": limit,
                    "feature": "via",
                },),
            ))

    for fp in footprints:
        pads = list(getattr(fp, "pads", ()) or ())
        for pad in pads:
            pad_type = getattr(pad, "pad_type", "") or ""
            if pad_type != "thru_hole":
                continue
            try:
                drill = float(getattr(pad, "drill", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if 0 < drill < limit - _EPS:
                number = getattr(pad, "number", "") or ""
                out.append(Violation(
                    description=(
                        f"Pad drill {drill}mm below {profile.name} minimum "
                        f"{limit}mm"
                    ),
                    severity=Severity.ERROR,
                    type="vendor_drill_size",
                    items=({
                        "pad": number,
                        "actual_mm": drill,
                        "required_mm": limit,
                        "feature": "pad",
                    },),
                ))
    return out


def _check_annular_ring(
    vias: list, footprints: list, profile: ManufacturerProfile
) -> list[Violation]:
    """Check annular ring on vias and thru-hole pads against profile.min_annular_ring_mm.

    Annular ring = (diameter - drill) / 2.
    """
    limit = profile.min_annular_ring_mm
    out: list[Violation] = []

    for via in vias:
        try:
            drill = float(getattr(via, "drill", 0.0) or 0.0)
            # NativeVia stores the KiCad (size D) token in .diameter
            diameter = float(getattr(via, "diameter", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if drill <= 0 or diameter <= 0:
            continue
        annular = (diameter - drill) / 2.0
        if annular < limit - _EPS:
            net_name = getattr(via, "net_name", "") or ""
            out.append(Violation(
                description=(
                    f"Annular ring {annular:.4f}mm below {profile.name} minimum "
                    f"{limit}mm"
                ),
                severity=Severity.ERROR,
                type="vendor_annular_ring",
                items=({
                    "net": net_name,
                    "actual_mm": annular,
                    "required_mm": limit,
                    "diameter_mm": diameter,
                    "drill_mm": drill,
                    "feature": "via",
                },),
            ))

    for fp in footprints:
        pads = list(getattr(fp, "pads", ()) or ())
        for pad in pads:
            pad_type = getattr(pad, "pad_type", "") or ""
            if pad_type != "thru_hole":
                continue
            try:
                drill = float(getattr(pad, "drill", 0.0) or 0.0)
                size = getattr(pad, "size", (0.0, 0.0)) or (0.0, 0.0)
                diameter = float(max(size))
            except (TypeError, ValueError):
                continue
            if drill <= 0 or diameter <= 0:
                continue
            annular = (diameter - drill) / 2.0
            if annular < limit - _EPS:
                number = getattr(pad, "number", "") or ""
                out.append(Violation(
                    description=(
                        f"Pad annular ring {annular:.4f}mm below {profile.name} "
                        f"minimum {limit}mm"
                    ),
                    severity=Severity.ERROR,
                    type="vendor_annular_ring",
                    items=({
                        "pad": number,
                        "actual_mm": annular,
                        "required_mm": limit,
                        "diameter_mm": diameter,
                        "drill_mm": drill,
                        "feature": "pad",
                    },),
                ))
    return out


def _check_via_diameter(
    vias: list, profile: ManufacturerProfile
) -> list[Violation]:
    """Check all via diameters against profile.min_via_diameter_mm."""
    limit = profile.min_via_diameter_mm
    out: list[Violation] = []
    for via in vias:
        try:
            diameter = float(getattr(via, "diameter", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if diameter <= 0:
            continue
        if diameter < limit - _EPS:
            net_name = getattr(via, "net_name", "") or ""
            out.append(Violation(
                description=(
                    f"Via diameter {diameter}mm below {profile.name} minimum "
                    f"{limit}mm"
                ),
                severity=Severity.ERROR,
                type="vendor_via_diameter",
                items=({
                    "net": net_name,
                    "actual_mm": diameter,
                    "required_mm": limit,
                },),
            ))
    return out


def _check_clearance(
    segments: list, profile: ManufacturerProfile
) -> list[Violation]:
    """Check pairwise track-to-track clearance on the same layer.

    O(n^2) pairwise distance with bounding-box pre-filtering per layer (CONTEXT.md
    line 119). Two segments violate if the gap between them is less than
    ``profile.min_clearance_mm``. The clearance corridor uses width/2 on both
    tracks: a violation occurs when the centerline-to-centerline distance is less
    than ``min_clearance + width_a/2 + width_b/2``.

    Only track-to-track checks on the same layer are performed for v1 (the
    highest-signal, lowest-cost check). Pad-to-track and pad-to-pad clearance can
    be added later.
    """
    limit = profile.min_clearance_mm
    if limit <= 0 or len(segments) < 2:
        return []

    # Bucket segments by layer so we only compare same-layer pairs.
    by_layer: dict[str, list[tuple[float, float, float, float, float, str]]] = {}
    for seg in segments:
        try:
            layer = getattr(seg, "layer", "") or ""
            width = float(getattr(seg, "width", 0.0) or 0.0)
            sx, sy = _pos_xy(getattr(seg, "start", None))
            ex, ey = _pos_xy(getattr(seg, "end", None))
            net_name = getattr(seg, "net_name", "") or ""
        except (TypeError, ValueError):
            continue
        by_layer.setdefault(layer, []).append((sx, sy, ex, ey, width, net_name))

    out: list[Violation] = []
    for layer, segs in by_layer.items():
        n = len(segs)
        for i in range(n):
            sx1, sy1, ex1, ey1, w1, net1 = segs[i]
            min_x1 = min(sx1, ex1) - w1 / 2 - limit
            max_x1 = max(sx1, ex1) + w1 / 2 + limit
            min_y1 = min(sy1, ey1) - w1 / 2 - limit
            max_y1 = max(sy1, ey1) + w1 / 2 + limit
            for j in range(i + 1, n):
                sx2, sy2, ex2, ey2, w2, net2 = segs[j]
                # Skip same-net pairs — same-net copper is connected, not a clearance violation.
                if net1 and net2 and net1 == net2:
                    continue
                # Bounding-box pre-filter: skip if AABBs (expanded by limit) don't overlap.
                if (max(sx2, ex2) + w2 / 2 + limit < min_x1
                        or min(sx2, ex2) - w2 / 2 - limit > max_x1
                        or max(sy2, ey2) + w2 / 2 + limit < min_y1
                        or min(sy2, ey2) - w2 / 2 - limit > max_y1):
                    continue
                gap = _segment_gap(
                    (sx1, sy1, ex1, ey1), (sx2, sy2, ex2, ey2)
                )
                # Clearance corridor: subtract half-widths of both tracks.
                required = limit + w1 / 2 + w2 / 2
                if gap < required - _EPS:
                    out.append(Violation(
                        description=(
                            f"Track clearance {gap:.4f}mm below {profile.name} "
                            f"minimum {limit}mm on layer {layer}"
                        ),
                        severity=Severity.ERROR,
                        type="vendor_clearance",
                        items=({
                            "layer": layer,
                            "actual_gap_mm": gap,
                            "required_mm": limit,
                            "net_a": net1,
                            "net_b": net2,
                        },),
                    ))
    return out


def _segment_gap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Minimum distance between two line segments (each as x1,y1,x2,y2).

    Uses segment-to-segment distance. For collinear/overlapping segments the
    distance is zero.
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    # If the segments intersect, gap is 0.
    if _segments_intersect(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
        return 0.0

    # Otherwise the minimum distance is the smallest point-to-segment distance
    # among the 4 endpoint/segment combinations.
    d1 = _point_to_segment_dist(ax1, ay1, bx1, by1, bx2, by2)
    d2 = _point_to_segment_dist(ax2, ay2, bx1, by1, bx2, by2)
    d3 = _point_to_segment_dist(bx1, by1, ax1, ay1, ax2, ay2)
    d4 = _point_to_segment_dist(bx2, by2, ax1, ay1, ax2, ay2)
    return min(d1, d2, d3, d4)


def _point_to_segment_dist(
    px: float, py: float,
    x1: float, y1: float, x2: float, y2: float,
) -> float:
    """Minimum distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        # Segment is a point.
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _segments_intersect(
    ax1: float, ay1: float, ax2: float, ay2: float,
    bx1: float, by1: float, bx2: float, by2: float,
) -> bool:
    """Return True if segment A and segment B intersect (including touching)."""
    def _ccw(px1: float, py1: float, px2: float, py2: float, px3: float, py3: float) -> float:
        return (py3 - py1) * (px2 - px1) - (py2 - py1) * (px3 - px1)

    d1 = _ccw(bx1, by1, bx2, by2, ax1, ay1)
    d2 = _ccw(bx1, by1, bx2, by2, ax2, ay2)
    d3 = _ccw(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = _ccw(ax1, ay1, ax2, ay2, bx2, by2)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # Collinear / touching cases (treat touching as intersecting).
    def _on_segment(
        px: float, py: float,
        qx1: float, qy1: float, qx2: float, qy2: float,
    ) -> bool:
        return (min(qx1, qx2) - _EPS <= px <= max(qx1, qx2) + _EPS
                and min(qy1, qy2) - _EPS <= py <= max(qy1, qy2) + _EPS)

    if abs(d1) < _EPS and _on_segment(ax1, ay1, bx1, by1, bx2, by2):
        return True
    if abs(d2) < _EPS and _on_segment(ax2, ay2, bx1, by1, bx2, by2):
        return True
    if abs(d3) < _EPS and _on_segment(bx1, by1, ax1, ay1, ax2, ay2):
        return True
    if abs(d4) < _EPS and _on_segment(bx2, by2, ax1, ay1, ax2, ay2):
        return True
    return False


__all__ = ["VendorDrcResult", "run_vendor_drc"]
